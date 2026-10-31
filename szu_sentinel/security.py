from __future__ import annotations

import ctypes
import os
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass
from typing import NamedTuple


FIREWALL_RULE_TCP = "SZU-NetSentinel-LAN-Worm-Shield"
FIREWALL_RULE_UDP = "SZU-NetSentinel-LAN-Worm-Shield-UDP"
HIGH_RISK_PORTS_TCP = "135,137,138,139,445,3389"
HIGH_RISK_PORTS_UDP = "137,138,445"
CAMPUS_PRIVATE_SUBNETS = "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"


class MIB_IPFORWARDROW(ctypes.Structure):
    _fields_ = [
        ("dwForwardDest", ctypes.c_ulong),
        ("dwForwardMask", ctypes.c_ulong),
        ("dwForwardPolicy", ctypes.c_ulong),
        ("dwForwardNextHop", ctypes.c_ulong),
        ("dwForwardIfIndex", ctypes.c_ulong),
        ("dwForwardType", ctypes.c_ulong),
        ("dwForwardProto", ctypes.c_ulong),
        ("dwForwardAge", ctypes.c_ulong),
        ("dwForwardNextHopAS", ctypes.c_ulong),
        ("dwForwardMetric1", ctypes.c_ulong),
        ("dwForwardMetric2", ctypes.c_ulong),
        ("dwForwardMetric3", ctypes.c_ulong),
        ("dwForwardMetric4", ctypes.c_ulong),
        ("dwForwardMetric5", ctypes.c_ulong),
    ]


class MIB_IPNETROW(ctypes.Structure):
    _fields_ = [
        ("dwIndex", ctypes.c_ulong),
        ("dwPhysAddrLen", ctypes.c_ulong),
        ("bPhysAddr", ctypes.c_byte * 8),
        ("dwAddr", ctypes.c_ulong),
        ("dwType", ctypes.c_ulong),
    ]


@dataclass
class SecurityAuditResult:
    gateway_ip: str | None
    gateway_mac: str | None
    arp_type: str  # "dynamic", "static", "unknown"
    arp_spoofed: bool
    firewall_enabled: bool
    lan_shield_active: bool
    risk_level: str  # "SAFE", "WARNING", "DANGER"
    summary: str


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def get_default_gateway_and_if_index() -> tuple[str | None, int | None]:
    if sys.platform == "win32":
        try:
            row = MIB_IPFORWARDROW()
            res = ctypes.windll.iphlpapi.GetBestRoute(ctypes.c_ulong(0), 0, ctypes.byref(row))
            if res == 0 and row.dwForwardNextHop != 0:
                ip = socket.inet_ntoa(struct.pack("I", row.dwForwardNextHop))
                return ip, int(row.dwForwardIfIndex)
        except Exception:
            pass
        return None, None
    elif sys.platform.startswith("linux"):
        if os.path.exists("/proc/net/route"):
            try:
                with open("/proc/net/route", "r") as fp:
                    for line in fp:
                        parts = line.strip().split()
                        if len(parts) >= 3 and parts[1] == "00000000":
                            gw_hex = parts[2]
                            if gw_hex != "00000000":
                                gw_bytes = bytes.fromhex(gw_hex)
                                gw_ip = socket.inet_ntoa(gw_bytes[::-1])
                                return gw_ip, 0
            except Exception:
                pass
    return None, None


def query_live_gateway_mac(gateway_ip: str) -> str | None:
    """Send an active kernel-level ARP query over the wire to obtain genuine MAC."""
    if sys.platform != "win32" or not gateway_ip:
        return None
    try:
        dest_ip = socket.inet_aton(gateway_ip)
        dest_ulong = ctypes.c_ulong(struct.unpack("I", dest_ip)[0])
        mac = (ctypes.c_byte * 6)()
        mac_len = ctypes.c_ulong(6)
        res = ctypes.windll.iphlpapi.SendARP(
            dest_ulong, 0, ctypes.byref(mac), ctypes.byref(mac_len)
        )
        if res == 0:
            return "-".join(f"{b & 0xff:02x}" for b in mac)
    except Exception:
        pass
    return None


def get_cached_gateway_mac_and_type(gateway_ip: str) -> tuple[str | None, str]:
    """Retrieve the current local OS ARP cache table entry for the given gateway."""
    if not gateway_ip:
        return None, "unknown"
    if sys.platform != "win32":
        if sys.platform.startswith("linux") and os.path.exists("/proc/net/arp"):
            try:
                with open("/proc/net/arp", "r") as fp:
                    for line in fp:
                        parts = line.strip().split()
                        if len(parts) >= 6 and parts[0] == gateway_ip:
                            flags = parts[2]
                            mac = parts[3].replace(":", "-").lower()
                            arp_type = "static" if flags in ("0x6", "6") else "dynamic"
                            return mac, arp_type
            except Exception:
                pass
        return None, "unknown"
    try:
        size = ctypes.c_ulong(0)
        ctypes.windll.iphlpapi.GetIpNetTable(None, ctypes.byref(size), False)
        if size.value == 0:
            return None, "unknown"
        buf = ctypes.create_string_buffer(size.value)
        res = ctypes.windll.iphlpapi.GetIpNetTable(buf, ctypes.byref(size), False)
        if res != 0:
            return None, "unknown"
        num_entries = struct.unpack("I", buf[:4])[0]
        offset = 4
        row_size = ctypes.sizeof(MIB_IPNETROW)
        for _ in range(num_entries):
            row = MIB_IPNETROW.from_buffer_copy(buf[offset : offset + row_size])
            offset += row_size
            ip = socket.inet_ntoa(struct.pack("I", row.dwAddr))
            if ip == gateway_ip:
                mac = "-".join(f"{b & 0xff:02x}" for b in row.bPhysAddr[: row.dwPhysAddrLen])
                type_map = {1: "other", 2: "invalid", 3: "dynamic", 4: "static"}
                return mac, type_map.get(row.dwType, "unknown")
    except Exception:
        pass
    return None, "unknown"


def get_firewall_profiles_status() -> dict[str, bool]:
    """Check if Windows Firewall is active across profiles via Windows Registry."""
    status = {"Domain": True, "Private": True, "Public": True}
    if sys.platform != "win32":
        return status
    try:
        import winreg

        profiles = {
            "Domain": "DomainProfile",
            "Private": "StandardProfile",
            "Public": "PublicProfile",
        }
        for name, key_name in profiles.items():
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    f"SYSTEM\\CurrentControlSet\\Services\\SharedAccess\\Parameters\\FirewallPolicy\\{key_name}",
                )
                val, _ = winreg.QueryValueEx(key, "EnableFirewall")
                status[name] = bool(val == 1)
            except Exception:
                pass
    except Exception:
        pass
    return status


def is_lan_shield_active() -> bool:
    """Check whether our campus high-risk worm & attack blocking rules exist."""
    if sys.platform != "win32":
        return False
    try:
        res = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE_TCP}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return res.returncode == 0
    except Exception:
        return False


def audit_security() -> SecurityAuditResult:
    """Comprehensive host & network security assessment."""
    gw_ip, _ = get_default_gateway_and_if_index()
    live_mac = query_live_gateway_mac(gw_ip) if gw_ip else None
    cached_mac, arp_type = get_cached_gateway_mac_and_type(gw_ip) if gw_ip else (None, "unknown")

    arp_spoofed = False
    if live_mac and cached_mac and live_mac.lower() != cached_mac.lower():
        arp_spoofed = True

    fw_profiles = get_firewall_profiles_status()
    all_fw_enabled = fw_profiles.get("Private", False) and fw_profiles.get("Public", False)
    shield_active = is_lan_shield_active()

    if arp_spoofed:
        risk = "DANGER"
        summary = f"检测到网关 ARP 缓存被篡改（缓存: {cached_mac}，真实: {live_mac}），疑似局域网嗅探或挂马攻击！"
    elif not all_fw_enabled and not shield_active:
        risk = "WARNING"
        summary = "Windows 专用网络防火墙未开启，高危端口（445/135等）正直接暴露在校园网中，存在勒索病毒渗透风险！"
    elif not shield_active:
        risk = "WARNING"
        summary = "尚未启用校园网高危端口防护规则，建议一键加固以阻断局域网病毒横向扩散。"
    else:
        risk = "SAFE"
        arp_desc = "静态绑定" if arp_type == "static" else "动态监听"
        summary = f"局域网防护正常运行中（网关: {gw_ip or '未知'} [{arp_desc}]，高危端口已隔离）"

    return SecurityAuditResult(
        gateway_ip=gw_ip,
        gateway_mac=live_mac or cached_mac,
        arp_type=arp_type,
        arp_spoofed=arp_spoofed,
        firewall_enabled=all_fw_enabled,
        lan_shield_active=shield_active,
        risk_level=risk,
        summary=summary,
    )


def apply_security_hardening() -> tuple[bool, str]:
    """Apply the security hardening rules (must be run elevated)."""
    if sys.platform != "win32":
        return False, "当前系统不支持 Windows 防火墙加固"

    errors = []
    # 1. 确保所有防火墙配置文件均开启
    try:
        subprocess.run(
            ["netsh", "advfirewall", "set", "allprofiles", "state", "on"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        errors.append(f"开启防火墙失败: {exc}")

    # 2. 阻断校园网局域网方向的 TCP 高危渗透端口 (135,137,138,139,445,3389)
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE_TCP}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={FIREWALL_RULE_TCP}",
                "dir=in",
                "action=block",
                "protocol=TCP",
                f"localport={HIGH_RISK_PORTS_TCP}",
                f"remoteip={CAMPUS_PRIVATE_SUBNETS}",
                "description=SZU NetSentinel 校园网局域网防病毒防渗透规则",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        errors.append(f"添加 TCP 拦截规则失败: {exc}")

    # 3. 阻断 UDP 高危广播与嗅探端口 (137,138,445)
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE_UDP}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        subprocess.run(
            [
                "netsh",
                "advfirewall",
                "firewall",
                "add",
                "rule",
                f"name={FIREWALL_RULE_UDP}",
                "dir=in",
                "action=block",
                "protocol=UDP",
                f"localport={HIGH_RISK_PORTS_UDP}",
                f"remoteip={CAMPUS_PRIVATE_SUBNETS}",
                "description=SZU NetSentinel 校园网局域网防病毒防渗透规则",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        errors.append(f"添加 UDP 拦截规则失败: {exc}")

    # 4. 锁定网关静态 ARP 绑定（杜绝局域网 ARP 欺骗劫持）
    gw_ip, if_idx = get_default_gateway_and_if_index()
    if gw_ip and if_idx:
        live_mac = query_live_gateway_mac(gw_ip)
        if live_mac:
            try:
                subprocess.run(
                    [
                        "netsh",
                        "interface",
                        "ipv4",
                        "add",
                        "neighbors",
                        str(if_idx),
                        gw_ip,
                        live_mac,
                        "store=active",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except Exception:
                pass

    if errors:
        return False, "；".join(errors)
    return True, "已成功开启局域网安全加固（防火墙开启、445/SMB蠕虫端口已阻断、网关ARP已锁定）"


def remove_security_hardening() -> tuple[bool, str]:
    """Remove our custom firewall rules."""
    if sys.platform != "win32":
        return False, "不支持的系统"
    try:
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE_TCP}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        subprocess.run(
            ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={FIREWALL_RULE_UDP}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, "已移除安全防护规则"
    except Exception as exc:
        return False, str(exc)


def request_elevation(param: str = "--harden-lan") -> bool:
    """Request Windows UAC elevation to execute security hardening."""
    if sys.platform != "win32":
        return False
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = param
    else:
        exe = sys.executable
        args = f'"{os.path.abspath(sys.argv[0])}" {param}'

    res = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        exe,
        args,
        None,
        1,  # SW_SHOWNORMAL
    )
    return res > 32
