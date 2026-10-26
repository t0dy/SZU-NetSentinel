from __future__ import annotations

import argparse
import ctypes
import sys

from szu_sentinel.storage import ConfigStore
from szu_sentinel.ui import SentinelApp


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
    parser = argparse.ArgumentParser(description="SZU NetSentinel - 深圳大学校园网断线监控与智能自动重连工具")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="由 Windows 开机启动项调用；窗口将最小化并自动开始监控",
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
    args = parse_args()
    if args.harden_lan:
        from szu_sentinel.security import apply_security_hardening
        ok, msg = apply_security_hardening()
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, msg, "SZU NetSentinel 局域网安全防护加固", 0x40 if ok else 0x10)
        return 0 if ok else 1

    if args.unharden_lan:
        from szu_sentinel.security import remove_security_hardening
        ok, msg = remove_security_hardening()
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(0, msg, "SZU NetSentinel 局域网安全防护", 0x40 if ok else 0x10)
        return 0 if ok else 1

    enable_windows_dpi_awareness()
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SZU.NetSentinel.App.v2.5")
        except Exception:
            pass
    app = SentinelApp(ConfigStore(), launched_by_autostart=args.autostart)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
