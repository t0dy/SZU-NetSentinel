from __future__ import annotations

import getpass
import os
import signal
import sys
import time
from datetime import datetime

from .local_log import LocalLog
from .models import AppConfig, ZONE_AUTO, ZONE_DORMITORY, ZONE_OFFICE
from .monitor import MonitorController, MonitorEvent
from .network import NetworkClient
from .startup import is_autostart_enabled, set_autostart
from .storage import ConfigStore


class TerminalColor:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def _colorize(text: str, color: str) -> str:
    # Windows 10/11 supports ANSI escape codes in terminal
    if sys.stdout.isatty():
        return f"{color}{text}{TerminalColor.RESET}"
    return text


def print_banner() -> None:
    from . import __version__
    banner = f"""
===========================================================
  [+] SZU NetSentinel (深大校园网智能哨兵) v{__version__}
  轻量、安静地守护你的校园网连接 · Linux & Windows 双平台
===========================================================
"""
    print(_colorize(banner.strip(), TerminalColor.CYAN))
    print()


def show_status(store: ConfigStore) -> int:
    print_banner()
    config = store.load()
    print(_colorize("[*] 正在检测当前校园网环境与连通性...", TerminalColor.BLUE))
    client = NetworkClient()
    client._configure_direct(config.direct_mode)
    
    zone = client.detect_zone(config)
    zone_names = {
        ZONE_AUTO: "自动识别",
        ZONE_OFFICE: "教学办公区 (深澜 SRun)",
        ZONE_DORMITORY: "宿舍区 (锐捷 ePortal)",
    }
    print(f"  • 当前配置账号: {config.username or _colorize('(未设置)', TerminalColor.YELLOW)}")
    print(f"  • 检测到网络区域: {_colorize(zone_names.get(zone, zone), TerminalColor.BOLD)}")
    
    if client.direct_route:
        print(f"  • 物理直连网卡 IP: {_colorize(client.direct_route.source_ip, TerminalColor.GREEN)}")
        print(f"  • 直连 DNS 服务器: {', '.join(client.direct_route.dns_servers[:3])}")
    else:
        print(f"  • 直连网卡: 未捕获到物理直连网卡 (采用默认系统路由)")

    print(f"  • 开机自启服务: {'已开启' if is_autostart_enabled() else '未开启'}")
    print()

    print(_colorize("[*] 正在执行外网连通性探测...", TerminalColor.BLUE))
    res = client.check_connection()
    if res.connected:
        lat_str = f"{res.latency_ms}ms" if res.latency_ms is not None else "<10ms"
        print(_colorize(f"  [OK] 网络在线！外网通信正常，延迟: {lat_str}", TerminalColor.GREEN))
        return 0
    else:
        print(_colorize("  [OFFLINE] 当前处于离线或未认证状态。", TerminalColor.RED))
        return 1


def login_once(store: ConfigStore) -> int:
    print_banner()
    config = store.load()
    if not config.username or not config.password:
        print(_colorize("[错误] 未配置校园网账号或密码，请先运行 `python main.py --config` 进行配置。", TerminalColor.RED))
        return 1

    print(_colorize(f"[*] 正在为账号 {config.username} 发起校园网登录认证...", TerminalColor.BLUE))
    client = NetworkClient()
    client._configure_direct(config.direct_mode)
    try:
        msg = client.send_login(config, progress_callback=lambda p: print(f"  [*] {p}"))
        print(_colorize(f"  [OK] 登录成功: {msg}", TerminalColor.GREEN))
        return 0
    except Exception as exc:
        print(_colorize(f"  [FAIL] 登录失败: {exc}", TerminalColor.RED))
        return 1


def configure_interactive(store: ConfigStore) -> None:
    print_banner()
    config = store.load()
    print(_colorize("=== 校园网配置交互向导 ===", TerminalColor.BOLD))
    print("直接按回车可保留括号内的当前默认值。\n")

    current_user = config.username or ""
    user_prompt = f"校园网学号/工号 [{current_user}]: " if current_user else "校园网学号/工号: "
    new_user = input(user_prompt).strip()
    if new_user:
        username = new_user
    else:
        username = current_user

    has_pwd = bool(config.password)
    pwd_prompt = "统一身份认证密码 (已保存，回车保持不变): " if has_pwd else "统一身份认证密码: "
    new_pwd = getpass.getpass(pwd_prompt).strip()
    if new_pwd:
        password = new_pwd
    else:
        password = config.password

    print("\n网络区域选项:")
    print("  1. 自动识别 (推荐，全校自适应)")
    print("  2. 教学办公区 / 实验楼 / 图书馆 (SRun 协议)")
    print("  3. 宿舍区 (ePortal 协议)")
    zone_choice = input(f"请选择网络区域 (1-3) [当前: {config.zone}]: ").strip()
    if zone_choice == "1":
        zone = ZONE_AUTO
    elif zone_choice == "2":
        zone = ZONE_OFFICE
    elif zone_choice == "3":
        zone = ZONE_DORMITORY
    else:
        zone = config.zone

    interval_input = input(f"掉线检测间隔 (分钟) [{config.interval_minutes}]: ").strip()
    try:
        interval = int(interval_input) if interval_input else config.interval_minutes
        if interval < 1 or interval > 60:
            interval = 5
    except ValueError:
        interval = 5

    direct_input = input(f"启用物理网卡直连防代理干扰 (y/n) [{'y' if config.direct_mode else 'n'}]: ").strip().lower()
    if direct_input in ("y", "yes"):
        direct_mode = True
    elif direct_input in ("n", "no"):
        direct_mode = False
    else:
        direct_mode = config.direct_mode

    new_config = AppConfig(
        username=username,
        password=password,
        zone=zone,
        interval_minutes=interval,
        direct_mode=direct_mode,
        autostart=config.autostart,
    )
    store.save(new_config)
    print(_colorize("\n[OK] 配置保存成功！凭据已安全加密存储于:", TerminalColor.GREEN))
    print(f"    {store.path}\n")


def run_daemon(store: ConfigStore) -> None:
    print_banner()
    config = store.load()
    if not config.username or not config.password:
        print(_colorize("[警告] 尚未配置校园网账号或密码！", TerminalColor.YELLOW))
        print("请运行 `python main.py --config` 进行设置。\n")

    local_log = LocalLog()
    state_colors = {
        "checking": TerminalColor.BLUE,
        "online": TerminalColor.GREEN,
        "reconnecting": TerminalColor.YELLOW,
        "offline": TerminalColor.RED,
        "stopped": TerminalColor.GRAY,
    }

    def on_event(event: MonitorEvent) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = state_colors.get(event.state, TerminalColor.RESET)
        tag = f"[{event.state.upper():<7}]"
        tag_colored = _colorize(tag, color)
        
        detail = event.message
        if event.latency_ms is not None:
            detail += f" ({event.latency_ms}ms)"
        if event.extra_info:
            detail += f" - {event.extra_info}"

        print(f"[{now_str}] {tag_colored} {detail}")
        sys.stdout.flush()
        local_log.write(f"[{event.state.upper()}] {detail}", level=event.level)

    monitor = MonitorController(event_callback=on_event)
    print(_colorize(f"[*] 启动后台网络守护 (检测间隔: {config.interval_minutes} 分钟)...", TerminalColor.CYAN))
    print(_colorize("[*] 按 Ctrl+C 退出守护。", TerminalColor.GRAY))
    print()

    monitor.start(config)

    def signal_handler(signum, frame):
        print(_colorize("\n[*] 正在停止守护并退出...", TerminalColor.YELLOW))
        monitor.stop()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)
    except Exception:
        pass

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()
        print(_colorize("[*] 守护已停止。", TerminalColor.GRAY))
