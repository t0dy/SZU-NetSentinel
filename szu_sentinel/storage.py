from __future__ import annotations

import base64
import ctypes
import hashlib
import hmac
import json
import os
import platform
import secrets
import sys
from pathlib import Path

from .models import AppConfig, ZONE_AUTO


APP_DIRECTORY = "SZUNetSentinel"
LEGACY_APP_DIRECTORY = "SZUNetworkGuardian"
LINUX_APP_DIRECTORY = "szu-sentinel"


if sys.platform == "win32":
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data, max(1, len(data)))
        blob = DATA_BLOB(
            len(data),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
        )
        return blob, buffer


def _get_linux_machine_id() -> str:
    for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            if os.path.exists(candidate):
                with open(candidate, "r", encoding="ascii") as fp:
                    val = fp.read().strip()
                    if val:
                        return val
        except Exception:
            pass
    return platform.node() or "szu-linux-node"


def _derive_linux_key(salt: bytes) -> bytes:
    machine_id = _get_linux_machine_id()
    uid = getattr(os, "getuid", lambda: 1000)()
    seed = f"{machine_id}:{uid}:szu-sentinel".encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", seed, salt, 60000)


def _linux_protect_secret(secret: str) -> str:
    raw = secret.encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    key = _derive_linux_key(salt)

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, raw, None)
        mode = b"A"
    except ImportError:
        blocks = []
        for i in range((len(raw) + 31) // 32):
            blocks.append(hmac.new(key, nonce + i.to_bytes(4, "big"), "sha256").digest())
        keystream = b"".join(blocks)[:len(raw)]
        ct = bytes(a ^ b for a, b in zip(raw, keystream))
        tag = hmac.new(key, b"TAG:" + nonce + ct, "sha256").digest()[:16]
        ciphertext = ct + tag
        mode = b"H"

    blob = b"LNX1" + mode + salt + nonce + ciphertext
    return base64.b64encode(blob).decode("ascii")


def _linux_unprotect_secret(encoded: str) -> str:
    try:
        blob = base64.b64decode(encoded)
    except Exception:
        return ""
    if not blob.startswith(b"LNX1") or len(blob) < 33:
        return ""
    mode = blob[4:5]
    salt = blob[5:21]
    nonce = blob[21:33]
    ciphertext = blob[33:]
    key = _derive_linux_key(salt)

    try:
        if mode == b"A":
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(key)
            raw = aesgcm.decrypt(nonce, ciphertext, None)
            return raw.decode("utf-8")
        elif mode == b"H":
            if len(ciphertext) < 16:
                return ""
            ct = ciphertext[:-16]
            tag = ciphertext[-16:]
            expected_tag = hmac.new(key, b"TAG:" + nonce + ct, "sha256").digest()[:16]
            if not hmac.compare_digest(tag, expected_tag):
                return ""
            blocks = []
            for i in range((len(ct) + 31) // 32):
                blocks.append(hmac.new(key, nonce + i.to_bytes(4, "big"), "sha256").digest())
            keystream = b"".join(blocks)[:len(ct)]
            raw = bytes(a ^ b for a, b in zip(ct, keystream))
            return raw.decode("utf-8")
    except Exception:
        return ""
    return ""


def protect_secret(secret: str) -> str:
    if not secret:
        return ""
    if sys.platform != "win32":
        return _linux_protect_secret(secret)

    raw = secret.encode("utf-8")
    input_blob, input_buffer = _blob_from_bytes(raw)
    output_blob = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    description = "SZU NetSentinel"

    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    finally:
        kernel32.LocalFree(output_blob.pbData)


def unprotect_secret(encoded: str) -> str:
    if not encoded:
        return ""
    try:
        peek = base64.b64decode(encoded[:16])
        if peek.startswith(b"LNX1"):
            return _linux_unprotect_secret(encoded)
    except Exception:
        pass

    if sys.platform != "win32":
        dec = _linux_unprotect_secret(encoded)
        return dec if dec else encoded

    try:
        protected = base64.b64decode(encoded)
        input_blob, input_buffer = _blob_from_bytes(protected)
        output_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        )
        _ = input_buffer
        if not ok:
            raise ctypes.WinError()
        try:
            raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
            return raw.decode("utf-8")
        finally:
            kernel32.LocalFree(output_blob.pbData)
    except Exception:
        dec = _linux_unprotect_secret(encoded)
        return dec if dec else encoded


def default_config_path() -> Path:
    override = os.environ.get("SZU_SENTINEL_DATA_DIR") or os.environ.get("SZU_GUARDIAN_DATA_DIR")
    if override:
        return Path(override) / "config.json"

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            target = Path(base) / APP_DIRECTORY / "config.json"
            if not target.exists():
                legacy = Path(base) / LEGACY_APP_DIRECTORY / "config.json"
                if legacy.exists():
                    try:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        import shutil
                        shutil.copy2(legacy, target)
                    except Exception:
                        pass
            return target
        return Path.home() / f".{APP_DIRECTORY}" / "config.json"

    # Linux / macOS (XDG standard)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        target = Path(xdg) / LINUX_APP_DIRECTORY / "config.json"
    else:
        target = Path.home() / ".config" / LINUX_APP_DIRECTORY / "config.json"

    if not target.exists():
        legacy = Path.home() / f".{APP_DIRECTORY}" / "config.json"
        if legacy.exists():
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                import shutil
                shutil.copy2(legacy, target)
            except Exception:
                pass
    return target


class ConfigStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_config_path()

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            password = unprotect_secret(str(payload.get("password_dpapi", "")))
            schema_version = int(payload.get("schema_version", 1))
            zone = str(payload.get("zone", ZONE_AUTO))
            if schema_version < 2:
                zone = ZONE_AUTO
            return AppConfig(
                username=str(payload.get("username", "")),
                password=password,
                zone=zone,
                interval_minutes=int(payload.get("interval_minutes", 5)),
                autostart=bool(payload.get("autostart", False)),
                start_on_launch=bool(payload.get("start_on_launch", True)),
                direct_mode=bool(payload.get("direct_mode", True)),
                arp_guard=bool(payload.get("arp_guard", True)),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            try:
                os.chmod(self.path.parent, 0o700)
            except Exception:
                pass

        payload = config.public_dict()
        payload["schema_version"] = 3
        payload["password_dpapi"] = protect_secret(config.password)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if sys.platform != "win32":
            try:
                os.chmod(temporary, 0o600)
            except Exception:
                pass
        temporary.replace(self.path)
        if sys.platform != "win32":
            try:
                os.chmod(self.path, 0o600)
            except Exception:
                pass
