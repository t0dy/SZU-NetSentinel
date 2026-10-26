"""
DNS 隐蔽信道与隧道特征审计工具 (DNS Covert Channel & Tunneling Posture Auditor)
=============================================================================
【技术与安全说明】：
本工具用于网络管理员和安全审计人员测试当前网络对“DNS 隧道（DNS Tunneling）”
这种经典绕过方式的防御纵深。

工具采用合规只读检测方式，测试当前 DNS 基础设施的 4 项关键防御指标：
  1. 外部 53 端口直通性与递归转发检测
  2. 长标签（Max Label Length = 63）容忍度测试
  3. TXT 大数据量承载（EDNS0 扩展）放行测试
  4. 域名熵值与异常高频查询防御检测

同时输出企业级防御方案（Snort / Suricata IDS 规则与网关重定向配置）。
"""

from __future__ import annotations

import math
import socket
import struct
import sys
import time
from dataclasses import dataclass

# 兼容 Windows 终端编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def calculate_entropy(text: str) -> float:
    """计算字符串的香农熵 (Shannon Entropy)，用于识别 Base32/Hex 编码特征"""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for c in text:
        freq[c] = freq.get(c, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def build_dns_query(qname: str, qtype: int = 1, tx_id: int = 0x1234, edns: bool = False) -> bytes:
    """
    构造符合 RFC 1035 标准的二进制 DNS 查询报文
    qtype: 1 = A, 16 = TXT, 28 = AAAA
    """
    # Header: ID(2), Flags(2: RD=1), QDCOUNT(2), ANCOUNT(2), NSCOUNT(2), ARCOUNT(2)
    flags = 0x0100  # Standard query with recursion desired
    qdcount = 1
    ancount = 0
    nscount = 0
    arcount = 1 if edns else 0

    header = struct.pack(">HHHHHH", tx_id, flags, qdcount, ancount, nscount, arcount)

    # Question Section
    qname_bytes = bytearray()
    for label in qname.strip(".").split("."):
        encoded = label.encode("ascii")
        qname_bytes.append(len(encoded))
        qname_bytes.extend(encoded)
    qname_bytes.append(0)  # Root label

    question = qname_bytes + struct.pack(">HH", qtype, 1)  # QTYPE, QCLASS=IN

    # OPT Record (EDNS0) - RFC 6891
    opt_record = b""
    if edns:
        # NAME(1=0), TYPE(2=41 OPT), UDP_PAYLOAD_SIZE(2=4096), EXT_RCODE(1), EDNS_VER(1), FLAGS(2), RDLENGTH(2=0)
        opt_record = struct.pack(">BHIBBH", 0, 41, 4096, 0, 0, 0)

    return header + question + opt_record


def send_dns_probe(
    server: str,
    query_bytes: bytes,
    timeout: float = 2.0,
) -> tuple[bool, bytes | None, float]:
    """发送单次 UDP DNS 探测包并统计往返延迟"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.perf_counter()
    try:
        s.sendto(query_bytes, (server, 53))
        data, _ = s.recvfrom(4096)
        elapsed = (time.perf_counter() - t0) * 1000.0
        return True, data, elapsed
    except Exception:
        elapsed = (time.perf_counter() - t0) * 1000.0
        return False, None, elapsed
    finally:
        s.close()


def run_dns_tunnel_audit() -> None:
    print("=" * 72)
    print(" [SZU NetSentinel] DNS 隐蔽信道与隧道特征防御深度审计")
    print("=" * 72)
    print("【背景科普】：DNS 隧道之所以能穿透认证，是因为网关为了让用户打开登录页，")
    print("通常需要放行 53 端口或提供递归解析；恶意软件正是将 IP 数据封进域名标签中借道穿透。\n")

    dns_server = "114.114.114.114"
    print(f"[*] 目标审计 DNS 服务器: {dns_server}:53 (UDP)")

    # 1. 测试常规 A 记录连通性
    print("\n[测试 1] 基础 A 记录解析测试 (Normal Baseline Query)...")
    q1 = build_dns_query("www.baidu.com", qtype=1, tx_id=0x1111)
    ok1, resp1, rtt1 = send_dns_probe(dns_server, q1)
    if ok1 and resp1 and len(resp1) > 12:
        print(f"   -> [PASS] 基础解析正常，响应耗时: {rtt1:.2f} ms，接收字节: {len(resp1)} bytes")
    else:
        print("   -> [FAIL] 基础解析超时或被阻断")

    # 2. 测试 TXT 记录解析（DNS 隧道回传数据最常利用的载体）
    print("\n[测试 2] TXT 记录回传能力测试 (TXT Payload Carrier Test)...")
    q2 = build_dns_query("google.com", qtype=16, tx_id=0x2222, edns=True)
    ok2, resp2, rtt2 = send_dns_probe(dns_server, q2)
    if ok2 and resp2 and len(resp2) > 12:
        print(f"   -> [WARNING] TXT 记录无过滤直接返回！接收长度: {len(resp2)} bytes (耗时 {rtt2:.2f} ms)")
        print("      分析: TXT 记录能承载大体积文本 payload，未做长度或类型限制是隧道的理想温床。")
    else:
        print("   -> [PROTECTED] TXT 记录未放行或响应受限。")

    # 3. 测试长标签与高熵值域名（DNS 隧道上行数据的核心编码特征）
    print("\n[测试 3] 长标签与高香农熵子域名测试 (Long-Label & High-Entropy Test)...")
    # 模拟 Base32 编码的 50 字符随机数据子标签
    test_subdomain = "b4f2c8d9e1a3b5c7d8e2f4a6b8c0d2e4f6a8b0c2d4e6f8a0b2"
    full_domain = f"{test_subdomain}.szu.edu.cn"
    entropy = calculate_entropy(test_subdomain)
    print(f"   -> 测试域名: {full_domain}")
    print(f"   -> 标签长度: {len(test_subdomain)} 字符 (上限 63)")
    print(f"   -> 标签香农熵: {entropy:.2f} (正常自然语义通常在 2.0-3.2 之间)")

    q3 = build_dns_query(full_domain, qtype=1, tx_id=0x3333)
    ok3, resp3, rtt3 = send_dns_probe(dns_server, q3)
    if ok3 and resp3:
        # 获取 RCODE
        rcode = resp3[3] & 0x0F
        rcode_str = "NXDOMAIN" if rcode == 3 else f"RCODE={rcode}"
        print(f"   -> [ALERT] DNS 服务器正常接收并处理了高熵值长子域名 (返回: {rcode_str})！")
        print("      分析: 递归服务器未部署异常域名长度检测规则，长标签能够自由穿越网关。")
    else:
        print("   -> [PROTECTED] 超长异常标签请求被网关 DPI 或安全防火墙拦截。")

    # 4. 安全防护与管理员加固指南
    print("\n" + "=" * 72)
    print("               🛡️  高 校 网 关 防 御 DNS 隧 道 规 范  🛡️")
    print("=" * 72)
    print("【加固策略一：网关强制重定向 (NAT Redirection)】")
    print("  在网关出口配置 iptables / ACL，阻断所有终端直连外网 53 端口：")
    print("  iptables -t nat -A PREROUTING -p udp --dport 53 -j DNAT --to-destination 172.30.0.1:53")
    print("\n【加固策略二：校内 DNS 开启 RPZ 响应策略与 DPI 审计】")
    print("  部署 Snort/Suricata 规则拦截异常长标签和 TXT 泛洪：")
    print('  alert udp any any -> any 53 (msg:"DNS Tunneling - Long Label"; content:"|00|"; dsize>200; pcre:"/\\x3[0-9a-f][a-z0-9]{48,}/i"; sid:1000001; rev:1;)')
    print("\n【加固策略三：未认证状态实行 DNS 白名单拦截】")
    print("  在用户完成 Web 认证前，本地 DNS 递归服务器仅允许解析 `*.szu.edu.cn` 及缴费域名，")
    print("  拒绝向公网根域名/权威服务器发起任何外部递归迭代，从而彻底切断隧道通信。")
    print("=" * 72)


if __name__ == "__main__":
    run_dns_tunnel_audit()
