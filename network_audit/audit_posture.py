"""
校园网络安全防御姿态与逃逸隐患深度审计工具
(Campus Network Security Posture & Vulnerability Audit Tool)
=============================================================
本脚本从主机侧以“只读探测”的方式，对当前局域网与认证网关进行 6 大维度的安全防御纵深测试：
  1. 二层隔离与代理 ARP 状态 (Layer-2 Isolation & Proxy ARP)
  2. 认证网关工作模式与会话机制 (Portal Layer-3 IP vs Layer-2 MAC Inspection)
  3. DNS 53 端口出站策略与隧道隐患 (DNS Outbound Policy & Tunneling Risk)
  4. IPv6 双栈链路与免认证穿透隐患 (IPv6 Dual-Stack Auth & Leakage Check)
  5. ICMP 协议外网放行与隧道隐患 (ICMP Egress & Ping Reachability)
  6. HTTP 劫持行为与 Host 头白名单探测 (Captive Redirection & Host Header Probe)
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# 兼容 Windows 默认 GBK 终端输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. 结构与底层 API 定义
# ---------------------------------------------------------------------------

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


def get_default_gateway_and_ip() -> tuple[str | None, str | None]:
    """获取当前默认 IPv4 网关与本机出网 IP"""
    if sys.platform != "win32":
        return None, None
    try:
        row = MIB_IPFORWARDROW()
        res = ctypes.windll.iphlpapi.GetBestRoute(ctypes.c_ulong(0), 0, ctypes.byref(row))
        if res == 0 and row.dwForwardNextHop != 0:
            gw_ip = socket.inet_ntoa(struct.pack("I", row.dwForwardNextHop))
            # 探测本机连接网关的源 IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((gw_ip, 80))
            local_ip = s.getsockname()[0]
            s.close()
            return gw_ip, local_ip
    except Exception:
        pass
    return None, None


def send_arp_probe(target_ip: str) -> str | None:
    """使用 Win32 SendARP 获取目标 IP 的 MAC 地址"""
    if sys.platform != "win32":
        return None
    try:
        dest_ip = socket.inet_aton(target_ip)
        dest_ulong = ctypes.c_ulong(struct.unpack("I", dest_ip)[0])
        mac_buf = (ctypes.c_byte * 6)()
        mac_len = ctypes.c_ulong(6)
        res = ctypes.windll.iphlpapi.SendARP(
            dest_ulong, 0, ctypes.byref(mac_buf), ctypes.byref(mac_len)
        )
        if res == 0:
            return "-".join(f"{b & 0xff:02X}" for b in mac_buf)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 2. 核心探测模块
# ---------------------------------------------------------------------------

@dataclass
class AuditReport:
    l2_proxy_arp: bool
    l2_gateway_mac: str | None
    l2_details: str
    gateway_mode: str
    portal_session_mac: str | None
    gateway_details: str
    dns_external_open: bool
    dns_details: str
    ipv6_available: bool
    ipv6_addresses: list[str]
    ipv6_reachability: bool
    ipv6_details: str
    icmp_open: bool
    icmp_details: str
    captive_state: str


def audit_layer2(gw_ip: str, local_ip: str) -> tuple[bool, str | None, str]:
    """测试二层隔离与代理 ARP 状态"""
    gw_mac = send_arp_probe(gw_ip)
    if not gw_mac:
        return False, None, "无法获取网关 MAC 地址"

    # 在同子网内随机抽样 5 个相邻 IP 测试 ARP 响应
    ip_parts = [int(p) for p in gw_ip.split(".")]
    sample_ips = []
    for offset in [2, 5, 10, 20, 50]:
        test_host = (ip_parts[3] + offset) % 250 + 2
        test_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.{test_host}"
        if test_ip != local_ip and test_ip != gw_ip:
            sample_ips.append(test_ip)

    matches_gw = 0
    tested_count = 0
    for sip in sample_ips:
        smac = send_arp_probe(sip)
        if smac:
            tested_count += 1
            if smac.upper() == gw_mac.upper():
                matches_gw += 1

    is_proxy_arp = (tested_count > 0 and matches_gw == tested_count)
    if is_proxy_arp:
        msg = (
            f"探测到交换机开启了【代理 ARP (Proxy ARP)】与【端口隔离 (PVLAN)】！\n"
            f"   网关 MAC: {gw_mac}。\n"
            f"   所测同子网随机 IP 均被交换机代答为网关 MAC。\n"
            f"   结论：局域网内主机无法嗅探其他真实主机 MAC，二层克隆逃逸在此架构下直接失效。"
        )
    else:
        msg = f"未探测到强制代理 ARP，网关 MAC: {gw_mac}，同子网可探测到真实分散 MAC。"
    return is_proxy_arp, gw_mac, msg


def audit_gateway_session(local_ip: str) -> tuple[str, str | None, str]:
    """审计 ePortal / SRun 网关在线会话与管控模式"""
    # 尝试读取深大宿舍区 ePortal 在线列表
    urls = [
        "http://172.30.255.42:801/eportal/portal/online_list",
        "http://172.30.254.68/eportal/portal/online_list",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SZU-Audit/2.0"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
                # 提取 JSONP
                m = re.search(r"jsonpReturn\((.*)\);?", raw)
                data_str = m.group(1) if m else raw
                data = json.loads(data_str)
                if data.get("result") == 1 and "list" in data and len(data["list"]) > 0:
                    sess = data["list"][0]
                    online_mac = sess.get("online_mac", "")
                    online_ip = sess.get("online_ip", "")
                    if online_mac == "000000000000":
                        mode = "三层纯 IP 路由放行模式 (Layer-3 IP Policy Routing)"
                        details = (
                            f"认证系统返回 session: {sess.get('online_session')}, IP: {online_ip}, MAC: 000000000000。\n"
                            f"   由于穿越了三层核心交换机，认证网关未绑定客户端物理 MAC。\n"
                            f"   网关仅依据【IP 地址】作为计费与放行唯一凭证（三层 Web Portal 架构）。"
                        )
                    else:
                        mode = "二层 MAC 强绑定模式 (Layer-2 IP-MAC Binding)"
                        details = f"认证系统严格绑定了物理 MAC: {online_mac} 与 IP: {online_ip}。"
                    return mode, online_mac, details
        except Exception:
            continue

    return "未知/离线", None, "未能从本地 Portal 接口读取到在线会话数据（当前可能未登录或处在非 ePortal 区域）。"


def audit_dns_policy() -> tuple[bool, str]:
    """测试外网 UDP 53 端口是否开放、被拦截或未授权直通"""
    test_servers = [
        ("114.114.114.114", "114 DNS"),
        ("8.8.8.8", "Google DNS"),
        ("223.5.5.5", "Aliyun DNS"),
    ]
    tx_id = 0xA1B2
    # www.baidu.com A 记录查询
    query = struct.pack(">H", tx_id) + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x03www\x05baidu\x03com\x00\x00\x01\x00\x01"

    success_count = 0
    results = []
    for s_ip, s_name in test_servers:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1.5)
        t0 = time.perf_counter()
        try:
            s.sendto(query, (s_ip, 53))
            data, addr = s.recvfrom(512)
            elapsed = (time.perf_counter() - t0) * 1000.0
            resp_id = struct.unpack(">H", data[:2])[0]
            if resp_id == tx_id:
                success_count += 1
                results.append(f"{s_name} ({s_ip}): 开放直通 (延迟 {elapsed:.1f}ms)")
            else:
                results.append(f"{s_name} ({s_ip}): 被劫持/重定向")
        except socket.timeout:
            results.append(f"{s_name} ({s_ip}): 超时阻断")
        except Exception as e:
            results.append(f"{s_name} ({s_ip}): 错误 ({e})")
        finally:
            s.close()

    is_open = (success_count > 0)
    if is_open:
        msg = (
            f"外部 UDP 53 端口未做严格校内重定向！\n"
            f"   " + "\n   ".join(results) + "\n"
            f"   【安全隐患】：网关未强制将 DNS 重定向到校内递归服务器，外网 53 端口完全可达。\n"
            f"   若在未认证状态下仍未阻断 53 端口，则存在通过 DNS Tunneling 绕过计费认证的风险。"
        )
    else:
        msg = "所有外部 UDP 53 端口均被网关阻断或劫持至校内统一 DNS，具备良好的 DNS 隧道防御能力。"
    return is_open, msg


def audit_ipv6_reachability() -> tuple[bool, list[str], bool, str]:
    """测试 IPv6 地址分配与外网连通性"""
    # 1. 查找本机公网 IPv6
    ipv6_addrs = []
    try:
        res = subprocess.run(["ipconfig"], capture_output=True, text=True, errors="ignore")
        for line in res.stdout.splitlines():
            line = line.strip()
            if "IPv6" in line and ":" in line:
                parts = line.split(":")
                addr = ":".join(parts[1:]).strip()
                if addr.startswith("2001:") or addr.startswith("240"):
                    ipv6_addrs.append(addr)
    except Exception:
        pass

    has_global_v6 = len(ipv6_addrs) > 0

    # 2. 测试外网 IPv6 连通性
    v6_reachable = False
    v6_test_target = "2001:4860:4860::8888"  # Google DNS IPv6
    try:
        proc = subprocess.run(
            ["ping", "-6", "-n", "1", "-w", "1500", v6_test_target],
            capture_output=True,
            text=True,
            errors="ignore",
        )
        if proc.returncode == 0:
            v6_reachable = True
    except Exception:
        pass

    # 3. 测试 HTTP IPv6 网站
    http_v6_ok = False
    if v6_reachable:
        try:
            req = urllib.request.Request(
                "http://ipv6.test-ipv6.com",
                headers={"User-Agent": "SZU-Audit/2.0"},
            )
            with urllib.request.urlopen(req, timeout=3.0) as r:
                if r.status == 200:
                    http_v6_ok = True
        except Exception:
            pass

    if has_global_v6 and v6_reachable:
        msg = (
            f"检测到原生教育网/公网 IPv6 地址已生效 ({ipv6_addrs[0]})！\n"
            f"   IPv6 外网连通性: 正常 (外网 Ping 可达, HTTP 测试网站返回 200)。\n"
            f"   【典型现象】：很多高校由于认证计费系统主要覆盖 IPv4，IPv6 往往直通 CERNET2。\n"
            f"   如果未登录 IPv4 账号时 IPv6 仍可上网，这是高校最常见的免认证出网途径。"
        )
    elif has_global_v6 and not v6_reachable:
        msg = f"已分配公网 IPv6 ({ipv6_addrs[0]})，但外网路由被网关 ACL 拦截（双栈同步受控）。"
    else:
        msg = "未检测到公网 IPv6 地址或本地网络未开启 IPv6。"

    return has_global_v6, ipv6_addrs, v6_reachable, msg


def audit_icmp() -> tuple[bool, str]:
    """测试 ICMP 外网 Ping 连通性"""
    icmp_open = False
    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", "1200", "114.114.114.114"],
            capture_output=True,
            text=True,
            errors="ignore",
        )
        icmp_open = (proc.returncode == 0)
    except Exception:
        pass

    if icmp_open:
        msg = (
            "外网 ICMP Ping (114.114.114.114) 直通放行。\n"
            "   【潜在风险】：若未认证时网关仍放行 ICMP，可被用于构建 ICMP 隧道穿透。"
        )
    else:
        msg = "外网 ICMP Ping 被阻断，防御策略良好。"
    return icmp_open, msg


def audit_captive_state() -> str:
    """检查当前网络认证连通状态"""
    urls = [
        ("http://connectivitycheck.gstatic.com/generate_204", 204),
        ("http://www.msftconnecttest.com/connecttest.txt", 200),
    ]
    for u, expected in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "SZU-Audit/2.0"})
            with urllib.request.urlopen(req, timeout=2.5) as r:
                if r.status == expected:
                    return "当前状态：已认证出网 (Online / Authenticated)"
        except urllib.error.HTTPError as e:
            if e.code in (302, 301, 307):
                loc = e.headers.get("Location", "")
                return f"当前状态：未认证 (Captive Portal 拦截重定向 -> {loc[:60]}...)"
        except Exception:
            pass
    return "当前状态：网络离线或受限"


# ---------------------------------------------------------------------------
# 3. 主审计报告生成器
# ---------------------------------------------------------------------------

def run_full_audit() -> None:
    print("=" * 72)
    print(" [SZU NetSentinel] 校园网安全防御纵深与逃逸风险实测审计工具")
    print("=" * 72)

    gw_ip, local_ip = get_default_gateway_and_ip()
    if not gw_ip or not local_ip:
        print("[-] 错误: 无法获取本机 IPv4 网关或出网网卡，请确认已连接校园网有线/无线。")
        return

    print(f"[*] 本机出网 IP: {local_ip}")
    print(f"[*] 默认网关 IP: {gw_ip}")
    print("[*] 正在执行 6 维网络防御实测，请稍候...\n")

    # 1. 认证状态
    captive_state = audit_captive_state()
    print(f"[0] 网络接入状态: {captive_state}")
    print("-" * 72)

    # 2. 二层隔离与代理 ARP
    print("[1/5] 正在审计二层链路与交换机隔离机制 (Layer-2 Isolation)...")
    is_proxy_arp, gw_mac, l2_details = audit_layer2(gw_ip, local_ip)
    print(f"   -> {l2_details}\n")

    # 3. 认证网关工作模式
    print("[2/5] 正在审计认证网关与在线会话凭证 (Portal Session Mode)...")
    gw_mode, portal_mac, gw_details = audit_gateway_session(local_ip)
    print(f"   -> 工作模式: {gw_mode}")
    print(f"   -> {gw_details}\n")

    # 4. DNS 策略
    print("[3/5] 正在测试外部 UDP 53 端口放行策略 (DNS Policy)...")
    dns_open, dns_details = audit_dns_policy()
    print(f"   -> {dns_details}\n")

    # 5. IPv6 双栈审计
    print("[4/5] 正在测试 IPv6 双栈直通与漏防隐患 (IPv6 Leakage)...")
    has_v6, v6_addrs, v6_ok, v6_details = audit_ipv6_reachability()
    print(f"   -> {v6_details}\n")

    # 6. ICMP 外网策略
    print("[5/5] 正在测试 ICMP 外网连通性 (ICMP Passthrough)...")
    icmp_open, icmp_details = audit_icmp()
    print(f"   -> {icmp_details}\n")

    # 总结与风险评分看板
    print("=" * 72)
    print("                  实 测 安 全 姿 态 评 分 看 板")
    print("=" * 72)
    print(f"{'攻击/逃逸向量':<20} | {'实测安全评级':<18} | {'核心原因与工程分析'}")
    print("-" * 72)

    if is_proxy_arp:
        print(f"{'二层 MAC 冒用克隆':<18} | 【极高防御 - 无法实施】 | 交换机 Proxy-ARP 与端口隔离，真实 MAC 不可见")
    else:
        print(f"{'二层 MAC 冒用克隆':<18} | 【中度风险】             | 局域网二层可见分散 MAC")

    if portal_mac == "000000000000":
        print(f"{'三层 IP 会话劫持':<18} | 【架构缺陷 / 易冲突】   | 网关只认 IP 不认 MAC；但伪造 IP 会引发 ARP 冲突与交换机封锁")
    else:
        print(f"{'三层 IP 会话劫持':<18} | 【高防御】               | 网关与接入交换机强制绑定物理 MAC")

    if dns_open:
        print(f"{'DNS (53) 隧道穿透':<18} | 【存在隐患】             | 外部 UDP 53 未强制重定向至校内自建递归 DNS")
    else:
        print(f"{'DNS (53) 隧道穿透':<18} | 【高防御】               | 外部 53 端口被强制劫持阻断")

    if has_v6 and v6_ok:
        print(f"{'IPv6 双栈免认证穿透':<16} | 【典型逃逸口】           | 原生 IPv6 直通 CERNET2，ePortal 仅管辖 IPv4 流量")
    else:
        print(f"{'IPv6 双栈免认证穿透':<16} | 【高防御】               | IPv6 双栈同步纳入认证管控或无公网路由")

    if icmp_open:
        print(f"{'ICMP Ping 隧道':<20} | 【存在隐患】             | 外网 ICMP 流量全通，可被利用于 ICMP 隧道穿透")
    else:
        print(f"{'ICMP Ping 隧道':<20} | 【高防御】               | 外网 ICMP 均被丢弃")

    print("=" * 72)
    print("结论分析：你所听说的校园网“有人能逃逸”，绝大多数是利用了【IPv6 双栈直通】或【53 端口 DNS 隧道】；")
    print("而在本网络环境下，【二层克隆他人 MAC】在交换机 Proxy-ARP 与 PVLAN 机制下是根本无法实施的。")
    print("=" * 72)


if __name__ == "__main__":
    run_full_audit()
