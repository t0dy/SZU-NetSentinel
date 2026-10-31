from __future__ import annotations

import argparse
import ctypes
import os
import sys

from szu_sentinel.cli import (
    configure_interactive,
    login_once,
    run_daemon,
    show_status,
)
from szu_sentinel.startup import set_autostart
from szu_sentinel.storage import ConfigStore


def is_gui_available() -> bool:
    if sys.platform == "win32":
        return True
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SZU NetSentinel - 深圳大学校园网掉线检测与智能自动保活重连工具 (Linux & Windows)",
    )
    parser.add_argument(
        "-d",
        "--daemon",
        "--cli",
        dest="daemon",
        action="store_true",
        help="以无界面终端/后台守护进程模式运行（自动重连与保活）",
    )
    parser.add_argument(
        "-s",
        "--status",
        action="store_true",
        help="查询当前校园网连接状态、网卡物理IP与网关区域",
    )
    parser.add_argument(
        "-l",
        "--login",
        action="store_true",
        help="立即执行一次校园网登录认证",
    )
    parser.add_argument(
        "-c",
        "--config",
        action="store_true",
        help="启动交互式配置向导（设置学号、密码、网络区域与检测间隔）",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="安装并启用开机后台自动守护服务（Linux systemd 或 Windows 启动项）",
    )
    parser.add_argument(
        "--uninstall-service",
        action="store_true",
        help="卸载开机自动守护服务",
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="由系统开机启动项调用",
    )
    parser.add_argument(
        "--harden-lan",
        action="store_true",
        help="以管理员权限执行校园网局域网防病毒高危端口阻断与网关ARP加固",
    )
    parser.add_argument(
        "--unharden-lan",
        action="store_true",
        help="以管理员权限移除校园网安全防护规则",
    )
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = parse_args()
    store = ConfigStore()

    if args.harden_lan:
        from szu_sentinel.security import apply_security_hardening
        ok, msg = apply_security_hardening()
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, msg, "SZU NetSentinel 局域网安全防护加固", 0x40 if ok else 0x10)
        return 0 if ok else 1

    if args.unharden_lan:
        from szu_sentinel.security import remove_security_hardening
        ok, msg = remove_security_hardening()
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, msg, "SZU NetSentinel 局域网安全防护", 0x40 if ok else 0x10)
        return 0 if ok else 1

    if args.config:
        configure_interactive(store)
        return 0

    if args.status:
        return show_status(store)

    if args.login:
        return login_once(store)

    if args.install_service:
        set_autostart(True)
        print("[✓] 守护服务已安装并启用。")
        return 0

    if args.uninstall_service:
        set_autostart(False)
        print("[✓] 守护服务已卸载。")
        return 0

    # 守护进程或无图形界面环境
    if args.daemon or (args.autostart and not is_gui_available()):
        run_daemon(store)
        return 0

    if not is_gui_available():
        print("[*] 未检测到图形桌面环境 ($DISPLAY)，自动以终端守护模式启动。")
        run_daemon(store)
        return 0

    # 启动 GUI 模式
    enable_windows_dpi_awareness()
    if sys.platform == "win32":
        try:
            from szu_sentinel import __version__
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"SZU.NetSentinel.App.v{__version__}")
        except Exception:
            pass

    from szu_sentinel.ui import SentinelApp
    app = SentinelApp(store, launched_by_autostart=args.autostart)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
