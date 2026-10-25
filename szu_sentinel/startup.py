from __future__ import annotations

import subprocess
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SZUNetSentinel"
LEGACY_VALUE_NAMES = ("SZUNetworkGuardian",)


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        parts = [sys.executable, "--autostart"]
    else:
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        executable = pythonw if pythonw.exists() else python
        main_file = Path(__file__).resolve().parents[1] / "main.py"
        parts = [str(executable), str(main_file), "--autostart"]
    return subprocess.list2cmdline(parts)


def is_autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
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


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        if enabled:
            raise OSError("开机自启仅支持 Windows")
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
