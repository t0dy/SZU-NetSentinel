#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SZU NetSentinel (深大校园网智能哨兵) - Linux 专版 / Standalone CLI Edition
======================================================================
轻量、安静、全自动的深圳大学校园网掉线检测与保活守护工具（专为 Linux 服务器与桌面打造）。
无须桌面 GUI 与额外系统组件，单文件即开即用，仅需 Python 3.8+ 及 requests 库。

项目地址: https://github.com/t0dy/SZU-NetSentinel
许可协议: MIT License
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import hashlib
import hmac
import ipaddress
import json
import math
import os
import platform
import random
import secrets
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlsplit, urlunsplit

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3 import PoolManager
except ImportError:
    print("[错误] 未安装 requests 库，请先执行: pip install requests")
    sys.exit(1)

__version__ = "2.6.0"

# ==============================================================================
# 1. 常量定义与网段规则
# ==============================================================================
ZONE_AUTO = "auto"
ZONE_OFFICE = "office"
ZONE_DORMITORY = "dormitory"

FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
PREFERRED_CAMPUS_NETWORK = ipaddress.ip_network("172.16.0.0/12")
DIRECT_DNS_SERVERS = (
    "192.168.247.6",
    "223.5.5.5",
    "119.29.29.29",
    "114.114.114.114",
)

SRUN_INIT_URL = "https://net.szu.edu.cn"
SRUN_CHALLENGE_URL = "https://net.szu.edu.cn/cgi-bin/get_challenge"
SRUN_PORTAL_URL = "https://net.szu.edu.cn/cgi-bin/srun_portal"
SRUN_RAD_USER_INFO_URL = "https://net.szu.edu.cn/cgi-bin/rad_user_info"

DORMITORY_LOGIN_URL = "http://172.30.255.42:801/eportal/?c=ACSetting&a=Login"
DORMITORY_LOGOUT_URL = "http://172.30.255.42:801/eportal/?c=ACSetting&a=Logout"

MICROSOFT_CHECK_URL = "http://www.msftconnecttest.com/connecttest.txt"
MICROSOFT_CHECK_TEXT = "Microsoft Connect Test"
CLOUDFLARE_204_URL = "http://cp.cloudflare.com/generate_204"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 NetSentinel/2.6"
    ),
    "Accept": "*/*",
}

from szu_sentinel.models import AppConfig, ZONE_AUTO, ZONE_DORMITORY, ZONE_OFFICE
from szu_sentinel.network import NetworkClient
from szu_sentinel.storage import ConfigStore
from szu_sentinel.monitor import MonitorController, MonitorEvent
from szu_sentinel.local_log import LocalLog
from szu_sentinel.startup import set_autostart, is_autostart_enabled


# ==============================================================================
# 3. 控制台 ANSI 彩色与终端展示
# ==============================================================================
class TermColor:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"


def colorize(text: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{text}{TermColor.RESET}"
    return text


def print_banner() -> None:
    banner = f"""
===========================================================
  [+] SZU NetSentinel (深大校园网智能哨兵) v{__version__} [Linux]
  轻量、安静地守护你的校园网连接 · Linux 服务器与桌面专属
===========================================================
"""
    print(colorize(banner.strip(), TermColor.CYAN))
    print()


# ==============================================================================
# 4. Linux CLI 命令操作实现
# ==============================================================================
def cmd_status(store: ConfigStore) -> int:
    print_banner()
    config = store.load()
    print(colorize("[*] 正在检测当前网络环境与网关连通性...", TermColor.BLUE))
    client = NetworkClient()
    client._configure_direct(config.direct_mode)

    zone = client.detect_zone(config)
    zone_names = {
        ZONE_AUTO: "自动识别",
        ZONE_OFFICE: "教学办公区 / 实验楼 (深澜 SRun)",
        ZONE_DORMITORY: "宿舍区 (锐捷 ePortal)",
    }
    print(f"  • 当前配置账号: {config.username or colorize('(未设置)', TermColor.YELLOW)}")
    print(f"  • 检测到网络区域: {colorize(zone_names.get(zone, zone), TermColor.BOLD)}")

    if client.direct_route:
        print(f"  • 物理直连网卡 IP: {colorize(client.direct_route.source_ip, TermColor.GREEN)}")
        print(f"  • 直连 DNS 服务器: {', '.join(client.direct_route.dns_servers[:3])}")
    else:
        print(f"  • 直连网卡: 未捕获到物理网卡直连 (使用系统默认路由)")

    print(f"  • 开机自启服务: {'已开启' if is_autostart_enabled() else '未开启'}")
    print()

    print(colorize("[*] 正在探测外网连通性...", TermColor.BLUE))
    res = client.check_connection()
    if res.connected:
        lat_str = f"{res.latency_ms}ms" if res.latency_ms is not None else "<10ms"
        print(colorize(f"  [OK] 网络正常在线！外网畅通，网络延迟: {lat_str}", TermColor.GREEN))
        return 0
    else:
        print(colorize("  [OFFLINE] 当前处于离线或未认证状态。", TermColor.RED))
        return 1


def cmd_login(store: ConfigStore) -> int:
    print_banner()
    config = store.load()
    if not config.username or not config.password:
        print(colorize("[错误] 未配置校园网账号或密码，请先执行 `szu-sentinel --config` 进行设置。", TermColor.RED))
        return 1

    print(colorize(f"[*] 正在为账号 {config.username} 发起校园网认证...", TermColor.BLUE))
    client = NetworkClient()
    client._configure_direct(config.direct_mode)
    try:
        msg = client.send_login(config, progress_callback=lambda p: print(f"  [*] {p}"))
        print(colorize(f"  [OK] 认证成功: {msg}", TermColor.GREEN))
        return 0
    except Exception as exc:
        print(colorize(f"  [FAIL] 认证失败: {exc}", TermColor.RED))
        return 1


def cmd_config(store: ConfigStore) -> None:
    print_banner()
    config = store.load()
    print(colorize("=== 校园网配置向导 (Linux) ===", TermColor.BOLD))
    print("直接按回车可保留括号内的默认设置。\n")

    current_user = config.username or ""
    prompt_user = f"校园网学号/工号 [{current_user}]: " if current_user else "校园网学号/工号: "
    new_user = input(prompt_user).strip()
    username = new_user if new_user else current_user

    has_pwd = bool(config.password)
    prompt_pwd = "统一身份认证密码 (已保存，回车保持不变): " if has_pwd else "统一身份认证密码: "
    new_pwd = getpass.getpass(prompt_pwd).strip()
    password = new_pwd if new_pwd else config.password

    print("\n网络区域选项:")
    print("  1. 自动识别 (全校自适应，推荐)")
    print("  2. 教学办公区 / 实验楼 / 图书馆 (SRun 协议)")
    print("  3. 宿舍区 (ePortal 协议)")
    zone_choice = input(f"选择区域 (1-3) [当前: {config.zone}]: ").strip()
    if zone_choice == "1":
        zone = ZONE_AUTO
    elif zone_choice == "2":
        zone = ZONE_OFFICE
    elif zone_choice == "3":
        zone = ZONE_DORMITORY
    else:
        zone = config.zone

    interval_input = input(f"检测与保活间隔 (分钟) [{config.interval_minutes}]: ").strip()
    try:
        interval = int(interval_input) if interval_input else config.interval_minutes
        if interval < 1 or interval > 1440:
            interval = 5
    except ValueError:
        interval = 5

    direct_input = input(f"启用物理网卡直连防代理干扰 (y/n) [{'y' if config.direct_mode else 'n'}]: ").strip().lower()
    direct_mode = direct_input in ("y", "yes") if direct_input else config.direct_mode

    new_cfg = AppConfig(
        username=username,
        password=password,
        zone=zone,
        interval_minutes=interval,
        direct_mode=direct_mode,
        autostart=config.autostart,
    )
    store.save(new_cfg)
    print(colorize(f"\n[OK] 配置已加密保存至: {store.path}", TermColor.GREEN))
    print()


def cmd_daemon(store: ConfigStore) -> None:
    print_banner()
    config = store.load()
    if not config.username or not config.password:
        print(colorize("[警告] 尚未配置校园网账号或密码！", TermColor.YELLOW))
        print("请运行 `szu-sentinel --config` 进行设置。\n")

    local_log = LocalLog()
    state_colors = {
        "checking": TermColor.BLUE,
        "online": TermColor.GREEN,
        "reconnecting": TermColor.YELLOW,
        "offline": TermColor.RED,
        "stopped": TermColor.GRAY,
    }

    def on_event(event: MonitorEvent) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = state_colors.get(event.state, TermColor.RESET)
        tag = f"[{event.state.upper():<7}]"
        tag_colored = colorize(tag, color)

        detail = event.message
        if event.latency_ms is not None:
            detail += f" ({event.latency_ms}ms)"
        if event.extra_info:
            detail += f" - {event.extra_info}"

        print(f"[{now_str}] {tag_colored} {detail}")
        sys.stdout.flush()
        local_log.write(f"[{event.state.upper()}] {detail}", level=event.level)

    monitor = MonitorController(event_callback=on_event)
    print(colorize(f"[*] 启动后台网络保活守护 (心跳检测间隔: {config.interval_minutes} 分钟)...", TermColor.CYAN))
    print(colorize("[*] 按 Ctrl+C 可停止守护。\n", TermColor.GRAY))

    monitor.start(config)

    def signal_handler(signum, frame):
        print(colorize("\n[*] 正在停止守护并退出...", TermColor.YELLOW))
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
        print(colorize("[*] 守护已停止。", TermColor.GRAY))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="SZU NetSentinel (深大校园网智能哨兵) - Linux 专版 / CLI Edition",
    )
    parser.add_argument(
        "-d", "--daemon", "--cli",
        dest="daemon",
        action="store_true",
        help="以无界面后台守护进程模式运行（自动保活与掉线重连）",
    )
    parser.add_argument(
        "-s", "--status",
        action="store_true",
        help="查询当前校园网连通状态、网卡物理IP与网关区域",
    )
    parser.add_argument(
        "-l", "--login",
        action="store_true",
        help="立即执行一次校园网登录认证",
    )
    parser.add_argument(
        "-c", "--config",
        action="store_true",
        help="运行交互式配置向导（设置账号、密码与网络区域）",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="一键配置并启用 Linux systemd 用户级后台守护服务",
    )
    parser.add_argument(
        "--uninstall-service",
        action="store_true",
        help="卸载 Linux systemd 守护服务",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="由 systemd 服务或开机启动项调用",
    )

    args = parser.parse_args()
    store = ConfigStore()

    if args.config:
        cmd_config(store)
        return 0
    if args.status:
        return cmd_status(store)
    if args.login:
        return cmd_login(store)
    if args.install_service:
        set_autostart(True)
        print("[OK] systemd 用户级守护服务已配置并启用！")
        print("     服务名: szu-sentinel.service")
        print("     常用命令: systemctl --user status szu-sentinel")
        return 0
    if args.uninstall_service:
        set_autostart(False)
        print("[OK] systemd 用户级守护服务已卸载。")
        return 0

    # 默认或 --daemon
    cmd_daemon(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
