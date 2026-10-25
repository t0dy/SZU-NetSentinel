"""
局域网活跃资产与网关放行状态审计工具 (LAN Asset & Gateway Audit Tool)
===================================================================

【技术背景与架构原理】：
在现代网络访问控制（Captive Portal / NAC）架构中：
1. 普通客户端处于数据平面（Data Plane），无法直接跨越安全边界读取网关内核的“放行白名单表”
   （如 iptables ipset、RADIUS Session Table）。这些属于管理平面（Management Plane）机密数据。
2. 合法网络运维人员获取“当前网关放行用户”的正规途径包括：
   - 方式一：调用认证系统的管理接口（如 RADIUS Accounting 账单审计、深澜/锐捷 OpenAPI，需 Admin Token）
   - 方式二：局域网二层资产探测（通过标准 ARP 协议探测当前子网内的活跃在线主机并排查非法/冲突设备）
   - 方式三：交换机端口绑定表查询（通过 SNMP 读取 DHCP Snooping / 802.1X 会话绑定表）

本脚本用于局域网管理员进行合法的本地网段资产清点、网关可达性核验与未受控设备排查。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import ipaddress
import socket
import struct
import sys
import time
from dataclasses import dataclass


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


@dataclass
class HostRecord:
    ip: str
    mac: str
    is_gateway: bool
    latency_ms: float


def get_default_gateway() -> tuple[str | None, int | None]:
    """通过 Windows 原生 IP 转发路由表获取默认网关 IP 与网卡索引。"""
    if sys.platform != "win32":
        return None, None
    try:
        row = MIB_IPFORWARDROW()
        res = ctypes.windll.iphlpapi.GetBestRoute(ctypes.c_ulong(0), 0, ctypes.byref(row))
        if res == 0 and row.dwForwardNextHop != 0:
            gw_ip = socket.inet_ntoa(struct.pack("I", row.dwForwardNextHop))
            return gw_ip, int(row.dwForwardIfIndex)
    except Exception:
        pass
    return None, None


def send_arp_probe(target_ip: str) -> tuple[str | None, float]:
    """使用 Windows 内核 SendARP 发送标准链路层 ARP 探针探测目标主机是否存在。"""
    if sys.platform != "win32":
        return None, 0.0

    started = time.perf_counter()
    try:
        dest_ip = socket.inet_aton(target_ip)
        dest_ulong = ctypes.c_ulong(struct.unpack("I", dest_ip)[0])
        mac_buf = (ctypes.c_byte * 6)()
        mac_len = ctypes.c_ulong(6)
        res = ctypes.windll.iphlpapi.SendARP(
            dest_ulong, 0, ctypes.byref(mac_buf), ctypes.byref(mac_len)
        )
        elapsed = (time.perf_counter() - started) * 1000.0
        if res == 0:
            mac_str = "-".join(f"{b & 0xff:02X}" for b in mac_buf)
            return mac_str, round(elapsed, 2)
    except Exception:
        pass
    return None, 0.0


def scan_subnet(subnet_str: str, max_threads: int = 50) -> list[HostRecord]:
    """并发扫描目标子网内的活跃资产。"""
    try:
        net = ipaddress.ip_network(subnet_str, strict=False)
    except ValueError as exc:
        print(f"[-] 无效的子网格式: {exc}")
        return []

    # 限制单次扫描的主机数量，防止过度消耗网络带宽（默认限制为 256 主机）
    hosts = list(net.hosts())
    if len(hosts) > 512:
        print(f"[!] 目标网段过大（{len(hosts)} 个主机），为保障网络稳定，仅取前 256 个地址进行审计。")
        hosts = hosts[:256]

    gw_ip, _ = get_default_gateway()
    results: list[HostRecord] = []

    print(f"[*] 正在审计网段 {net} 中的活跃资产（并发线程: {max_threads}）...")
    started = time.time()

    def probe_worker(ip_obj: ipaddress.IPv4Address) -> HostRecord | None:
        ip_str = str(ip_obj)
        mac, latency = send_arp_probe(ip_str)
        if mac:
            return HostRecord(
                ip=ip_str,
                mac=mac,
                is_gateway=(ip_str == gw_ip),
                latency_ms=latency,
            )
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = {executor.submit(probe_worker, host): host for host in hosts}
        for future in concurrent.futures.as_completed(futures):
            record = future.result()
            if record:
                results.append(record)

    results.sort(key=lambda r: socket.inet_aton(r.ip))
    duration = round(time.time() - started, 2)
    print(f"[+] 审计完成！耗时 {duration} 秒，发现 {len(results)} 台活跃设备。")
    return results


def print_audit_report(records: list[HostRecord], gw_ip: str | None) -> None:
    """输出排版清晰的审计分析报告。"""
    print("\n" + "=" * 70)
    print(f"{'IP 地址':<18} {'MAC 物理地址':<22} {'延迟':<10} {'角色/备注'}")
    print("-" * 70)

    for r in records:
        role = "【默认网关】" if r.is_gateway else "局域网终端"
        print(f"{r.ip:<18} {r.mac:<22} {r.latency_ms:>6.2f} ms  {role}")

    print("=" * 70)
    print("\n【网络安全审计与防御提示】：")
    print("1. 为什么普通主机无法直接查看网关内部认证表？")
    print("   网关放行白名单保存在认证服务器内核（如 iptables ipset / RADIUS Session），")
    print("   数据平面普通主机无法跨权限读取。合法运维查询请登录认证管理控制台。")
    print("2. 如何防止未认证设备冒用活跃 MAC 逃逸？")
    print("   交换机应开启 DHCP Snooping 与 IP Source Guard (IPSG)，在物理端口硬件级")
    print("   绑定 IP-MAC-Port，严防伪造 MAC 绕过认证。")
    print("3. 防范同网段中间人嗅探：")
    print("   客户端应开启网关静态 ARP 绑定（Static ARP），交换机应启用 Dynamic ARP Inspection (DAI)。\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="局域网活跃资产排查与网关状态审计工具"
    )
    gw_ip, _ = get_default_gateway()
    default_subnet = ""
    if gw_ip:
        parts = gw_ip.split(".")
        default_subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"

    parser.add_argument(
        "--subnet",
        default=default_subnet or "172.30.48.0/24",
        help="目标扫描网段 (默认推导为本机所在 /24 网段)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=30,
        help="并发探测线程数 (默认: 30)",
    )

    args = parser.parse_args()

    if sys.platform != "win32":
        print("[-] 本工具依赖 Windows 原生网络栈 API。")
        return

    records = scan_subnet(args.subnet, max_threads=args.threads)
    print_audit_report(records, gw_ip)


if __name__ == "__main__":
    main()
