from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SZUNetSentinel"
LEGACY_VALUE_NAMES = ("SZUNetworkGuardian",)

LINUX_SERVICE_NAME = "szu-sentinel.service"
LINUX_DESKTOP_NAME = "szu-sentinel.desktop"


def _linux_service_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / LINUX_SERVICE_NAME


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / LINUX_DESKTOP_NAME


def _startup_command_list() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--autostart"]
    python = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = python.with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else python
    else:
        executable = python
    main_file = Path(__file__).resolve().parents[1] / "main.py"
    return [str(executable), str(main_file), "--autostart"]


def _startup_command() -> str:
    parts = _startup_command_list()
    return subprocess.list2cmdline(parts)


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return _linux_service_path().exists() or _linux_desktop_path().exists()

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_READ,
        ) as key:
            for name in (VALUE_NAME, *LEGACY_VALUE_NAMES):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return True
                except FileNotFoundError:
                    continue
            return False
    except FileNotFoundError:
        return False


def _set_linux_autostart(enabled: bool) -> None:
    svc_path = _linux_service_path()
    desktop_path = _linux_desktop_path()
    cmd_parts = _startup_command_list()
    exec_str = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)

    if enabled:
        # 1. 创建 systemd user service
        svc_path.parent.mkdir(parents=True, exist_ok=True)
        service_content = f"""[Unit]
Description=SZU NetSentinel - Shenzhen University Campus Network Guardian
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_str}
Restart=always
RestartSec=10
TimeoutStopSec=5

[Install]
WantedBy=default.target
"""
        svc_path.write_text(service_content, encoding="utf-8")

        # 2. 创建 XDG autostart desktop entry
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        desktop_content = f"""[Desktop Entry]
Type=Application
Name=SZU NetSentinel
Comment=Shenzhen University Campus Network Auto-Connector
Exec={exec_str}
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
"""
        desktop_path.write_text(desktop_content, encoding="utf-8")

        if shutil.which("systemctl"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "daemon-reload"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                subprocess.run(
                    ["systemctl", "--user", "enable", LINUX_SERVICE_NAME],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                pass
    else:
        if shutil.which("systemctl"):
            try:
                subprocess.run(
                    ["systemctl", "--user", "disable", LINUX_SERVICE_NAME],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except Exception:
                pass
        try:
            if svc_path.exists():
                svc_path.unlink()
        except OSError:
            pass
        try:
            if desktop_path.exists():
                desktop_path.unlink()
        except OSError:
            pass


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        _set_linux_autostart(enabled)
        return

    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_SZ,
                _startup_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        for legacy_name in LEGACY_VALUE_NAMES:
            try:
                winreg.DeleteValue(key, legacy_name)
            except FileNotFoundError:
                pass


def sync_autostart_path() -> bool:
    """If autostart is already enabled, update its command to point to current location."""
    if sys.platform != "win32":
        if is_autostart_enabled():
            _set_linux_autostart(True)
            return True
        return False

    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            current_target = _startup_command()
            was_enabled = False
            for legacy_name in LEGACY_VALUE_NAMES:
                try:
                    val, _ = winreg.QueryValueEx(key, legacy_name)
                    if val:
                        was_enabled = True
                    winreg.DeleteValue(key, legacy_name)
                except FileNotFoundError:
                    pass

            try:
                value, _ = winreg.QueryValueEx(key, VALUE_NAME)
                if value:
                    was_enabled = True
            except FileNotFoundError:
                value = None

            if was_enabled and value != current_target:
                winreg.SetValueEx(
                    key,
                    VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    current_target,
                )
                return True
    except FileNotFoundError:
        pass
    return False
