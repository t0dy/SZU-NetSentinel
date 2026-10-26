# 局域网放行状态与活跃资产审计指南

本文档与配套的 Python 工具保存在 `network_audit/` 目录下，专门解答与实现：
**“网关如何管理放行用户列表，在当前网络下如何通过 Python 获取与审计局域网状态。”**

---

## 一、网络架构解析：普通主机能否直接读取网关放行列表？

### 1. 管理平面与数据平面的安全隔离
在正规的校园网与企业网架构中：
* **网关放行表**属于**管理平面（Management Plane）**机密数据，由网关内核防火墙（如 Linux `ipset`、`iptables`、BRAS 硬件流表）以及 RADIUS 认证计费数据库维护。
* **接入设备（包括你的电脑）**处于**数据平面（Data Plane）**。受网关访问控制策略限制，未授权的终端只能向网关发起 DNS、重定向 HTTP 或登录请求，**网关绝对不会向普通终端开放无需鉴权的“全局已放行白名单查询接口”**。

> [!IMPORTANT]
> 如果某个网关允许任意局域网设备免鉴权读取全局放行用户的 IP 与 MAC，则该网关存在**未授权信息泄露高危漏洞**，攻击者可据此实施身份冒用。

---

## 二、合法管理员：如何通过 Python 获取网关放行用户？

对于合法的网络管理员或运维团队，通过代码获取“当前网关放行在线用户”有以下标准途径：

### 方式一：调用认证计费系统管理端 OpenAPI（推荐）
深澜（SRun 4000/3000）、锐捷（RG-SAM/ePortal）等系统均向管理员提供经过鉴权的 RESTful API。

**Python 示例（管理员视角）**：
```python
import requests

ADMIN_API_URL = "https://net.szu.edu.cn:8001/api/v1/online_users"
ADMIN_TOKEN = "your_secure_admin_bearer_token"

def get_whitelisted_users():
    headers = {
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.get(ADMIN_API_URL, headers=headers, timeout=5)
    data = response.json()
    
    # 解析网关放行的会话
    for user in data.get("list", []):
        print(f"账号: {user['username']} | IP: {user['user_ip']} | MAC: {user['mac']} | 放行状态: 已放行")

if __name__ == "__main__":
    get_whitelisted_users()
```

### 方式二：通过 SNMP 协议读取网关/核心交换机会话 MIB
网络管理员可通过 SNMP 轮询（OID 节点：`IF-MIB`、`dot11` 或厂商私有 MIB）批量拉取当前通过 802.1X 或 Web 认证的在线列表。

---

## 三、普通终端：如何用 Python 审计本地局域网活跃资产？

虽然普通终端无法跨权限直接读取网关内部数据库，但在同一局域网（二层广播域）内，可以通过标准网络协议审计本网段内的**活跃主机与网关物理地址**。

我们在本文件夹编写了完整的原生 Python 审计脚本：[`scanner.py`](file:///e:/szu_network/network_audit/scanner.py)。

### 1. 核心技术原理
* 使用 Windows 内核 `SendARP` 原生 API，直接向局域网 IP 发送标准 ARP 请求。
* **高安全性与合规性**：不依赖任何黑客抓包驱动（无需 WinPcap/Npcap），纯原生 Windows 底层调用，执行速度极快（秒级完成 `/24` 网段扫描）。
* **自动识别默认网关**：基于内核 `GetBestRoute` 路由表自动比对默认网关 IP 与实际物理 MAC，辅助排查局域网 ARP 欺骗攻击。

### 2. 使用方法
在命令行中运行：
```powershell
cd e:\szu_network\network_audit

# 自动推导本机所在网段并执行审计
python scanner.py

# 或指定特定网段与线程数
python scanner.py --subnet 172.30.48.0/24 --threads 50
```

### 3. 运行输出样例
```text
[*] 正在审计网段 172.30.48.0/24 中的活跃资产（并发线程: 30）...
[+] 审计完成！耗时 0.42 秒，发现 12 台活跃设备。

======================================================================
IP 地址             MAC 物理地址           延迟       角色/备注
----------------------------------------------------------------------
172.30.48.1        70-F9-6D-70-34-8F        0.18 ms  【默认网关】
172.30.48.15       34-48-ED-12-34-56        1.12 ms  局域网终端
172.30.48.110      A0-36-BC-11-22-33        0.05 ms  局域网终端 (本机)
======================================================================
```

---

## 四、安全加固与防御准则

1. **防范未认证设备逃逸**：
   * 网关与接入层交换机必须开启 **DHCP Snooping + IP Source Guard (IPSG)**。
   * 当交换机在硬件端口上绑定了合法分配的 `IP-MAC-Port` 三元组时，任何未认证主机即使冒用合法 MAC 发包，也会在接入交换机底层物理端口直接被硬件丢弃。
2. **防范局域网中间人与嗅探**：
   * 客户端建议开启网关静态 ARP 绑定（在 `SZU-NetSentinel` 主界面点击【一键安全加固】即可一键生效），使恶意伪造的 ARP 应答包在 Windows 内核直接失效。

---

## 五、校园网逃逸隐患与防御纵深实测工具：`audit_posture.py`

在 `network_audit/` 目录下新增了只读防御姿态实测工具：[`audit_posture.py`](file:///e:/szu_network/network_audit/audit_posture.py)。

### 1. 运行方式
```powershell
python network_audit/audit_posture.py
```

### 2. 六维自动化探测能力
1. **二层交换机隔离与代理 ARP 审计**：探测交换机是否开启 Proxy-ARP / PVLAN。
2. **认证网关工作模式与凭证审计**：探测网关是二层强绑定还是三层纯 IP 放行（深大宿舍区 ePortal 接口测试）。
3. **DNS 53 端口出站策略审计**：测试外部公共 DNS 连通性，评估 DNS 隧道穿透隐患。
4. **IPv6 双栈免认证穿透审计**：测试 CERNET2 原生 IPv6 是否绕过 IPv4 计费系统。
5. **ICMP 协议外网放行审计**：测试外网 ICMP Ping 是否被网关过滤。
6. **HTTP 劫持与 Host 伪造审计**：测试 Captive Portal 重定向行为及放行白名单。

---

## 六、DNS 隐蔽信道与隧道特征审计工具：`dns_tunnel_audit.py`

在 `network_audit/` 目录下新增了专门测试 DNS 隐蔽信道穿透特征与防御能力的工具：[`dns_tunnel_audit.py`](file:///e:/szu_network/network_audit/dns_tunnel_audit.py)。

### 1. 为什么 DNS 隧道能够绕过传统认证？
Captive Portal 为了让未登录用户能解析到登录网页，通常必须放行 UDP 53 端口。DNS 隧道（如历史上的 Iodine、dnscat2）正是利用了这一放行窗口，将 TCP/IP 数据切片编码（如 Base32/Base64）后嵌入到子域名字段中（例如 `data123.tunnel.attacker.com`），借助 DNS 递归查询一路传递到外网自建权威服务器，从而实现穿透。

### 2. 运行方式
```powershell
python network_audit/dns_tunnel_audit.py
```

### 3. 工具测试项
* **A 记录基础解析测试**：基线连通性与往返延迟。
* **TXT 大载荷回传测试**：测试网关是否放行大文本 TXT 记录（隧道下行载体）。
* **长标签与高香农熵审计**：构造极限长度（50+ 字符）高信息熵子域名，测试本地网关与 DNS 是否具备特征识别与拦截能力。
* **防御加固输出**：提供企业级 Snort/Suricata 检测规则与 iptables 强制拦截配置。
