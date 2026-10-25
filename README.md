# 🛡️ SZU NetSentinel (深大网络守卫) v2.0.0

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows11&logoColor=white)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v2.0.0-orange.svg)](https://github.com/Georgeupup/szu-network-guardian/releases)

**SZU NetSentinel** 是一款专为深圳大学（SZU）师生打造的轻量级、全自动校园网掉线检测与保活守护工具。

具备**全校自适应智能区域识别**、**深澜 SRun 与宿舍 ePortal 双协议支持**、**物理网卡直连防代理干扰**、**30 秒轻量保活心跳**、**Windows DPAPI 硬件级密码加密**及**系统托盘静默运行**等特性，助你彻底告别断网、登录过期与频繁重连的烦恼。

---

## 🌟 核心功能特性

### 1. 🧠 全校自适应三级智能区域识别
无需手动切换区域！无论你在宿舍、教学楼、图书馆还是实验楼，程序通过**三级启发式引擎**在 0 毫秒内即时锁定网关：
- **Level 1（网关重定向捕获）**：检测外网探测时的 HTTP 302 重定向链条，捕获网关下发的指令。
- **Level 2（物理网卡 IP 网段指纹）**：秒级识别本机校园网真实的 IPv4 分配规则：
  - 宿舍区：`172.30.0.0/16` ➡️ 自动加载 **ePortal 协议**
  - 粤海 / 沧海教学办公区：`172.31.0.0/16` ➡️ 自动加载 **SRun 协议**
  - 丽湖校区：`172.28.0.0/16` ➡️ 自动加载 **SRun 协议**
- **Level 3（存活性双探针）**：分别探测 `172.30.255.42:801` ePortal 与 `net.szu.edu.cn` SRun 响应，双重容错。

### 2. ⚡ 30 秒轻量级保活心跳 (Keep-Alive Heartbeat)
- 定期向校园网网关发送低开销轻量心跳包，有效防止因长时间无流量导致网关将会话判定为空闲（Idle Timeout）而踢下线。
- 教学区深度核验 SRun 会话状态。即使百度等免流白名单可打开，一旦认证过期也会立即无感重连。

### 3. 🛡️ 物理网卡直连（完全隔离代理软件干扰）
- 自动适配 **Clash / Mihomo / V2Ray / Sing-box / Surge** 等各类代理软件。
- 自动识别并排除 `198.18.0.0/15` Fake-IP 虚拟网卡，强制绑定电脑真实的物理有线网卡或 `SZU_WLAN` 无线网卡发起 DNS 解析与登录。
- 具备**优雅降级机制（Graceful Fallback）**：即使特殊网络环境下直连 DNS 受限，也会自动无感切回标准网络会话，绝不影响连网。

### 4. 🔐 企业级安全防护 (Windows DPAPI)
- 绝不明文保存账号密码！密码通过 Windows 底层数据保护 API（`CryptProtectData`）进行加密，密钥与当前 Windows 用户凭据硬件级绑定，其他用户或拷贝文件均无法解密。
- 日志自动脱敏，绝不记录任何明文密码、加密密钥或完整 payload。

### 5. 🪟 极简后台运行与开机自启
- 现代化清晰图形界面，操作简单直接。
- 最小化或点击关闭窗口自动缩入 Windows 系统托盘静默守护，内存占用极低（~30MB）。
- 支持一键开启“开机自动启动”，写入当前用户注册表，无需 UAC 管理员提权。
- 本地日志按天自动归档，自动清理 7 天前旧日志，不堆积垃圾文件。

---

## 🚀 使用教程

### 方式一：下载单文件 EXE（最推荐，即开即用）

1. 从 [Releases 页面](https://github.com/Georgeupup/szu-network-guardian/releases) 下载最新版的 `SZU-NetSentinel-v2.0.0.exe`（或直接使用项目目录下的可执行文件）。
2. **建议操作**：将 EXE 文件放置在固定的文件夹中（例如 `D:\Software\SZUNetSentinel\`），不要直接在桌面临时文件夹或下载目录中开启开机自启。
3. 双击运行 `SZU-NetSentinel-v2.0.0.exe`。
4. **填写配置**：
   - **校园网账号**：输入你的深大学号（如 `2023xxxxxx`）。
   - **登录密码**：输入统一身份认证密码。
   - **网络区域**：保持默认的 **`自动识别（全校自适应，推荐）`** 即可。
   - **检测间隔**：推荐保持默认 **3 分钟**。
   - **检测和认证强制直连**：推荐保持**勾选**（使用代理也能正常重连）。
   - **开机自动启动**：根据个人习惯勾选。
5. 点击 **【开始守护】**，此时右侧日志将即时输出认证与网络连通结果。
6. 点击右上角关闭按钮或最小化，程序将自动缩至右下角系统托盘静默运行。

---

### 方式二：从源码运行（开发者 / Python 用户）

#### 1. 克隆代码与安装依赖
```powershell
git clone https://github.com/Georgeupup/szu-network-guardian.git
cd szu-network-guardian

# 安装基础运行依赖
python -m pip install -r requirements.txt
```

#### 2. 启动图形界面
```powershell
python main.py
```

#### 3. 执行单元测试
本项目包含 34 项完整的单元测试，覆盖加密运算、子网启发识别、网关探针与故障转移：
```powershell
python -m unittest discover -s tests -v
```

---

## 🛠️ 打包编译 Windows 单文件 EXE

如果你修改了源码并希望重新打包 EXE：

```powershell
# 执行内置打包脚本（会自动配置隔离环境、运行测试并生成 EXE）
powershell.exe -ExecutionPolicy Bypass -File .\build.ps1
```

或使用系统已安装的 PyInstaller 直接编译：
```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SZU-NetSentinel-v2.0.0" main.py
```
生成的单文件将存放在 `dist\SZU-NetSentinel-v2.0.0.exe`。

---

## 📂 配置与数据路径

程序的所有持久化数据均储存在当前用户的本地 AppData 目录中：

| 数据类型 | 路径 | 说明 |
| :--- | :--- | :--- |
| **配置文件** | `%LOCALAPPDATA%\SZUNetSentinel\config.json` | 包含账号、配置参数及 DPAPI 加密后的密码密文 |
| **运行日志** | `%LOCALAPPDATA%\SZUNetSentinel\logs\guardian-YYYY-MM-DD.log` | 每日分卷运行日志，保留最近 7 天 |
| **开机自启** | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | 注册表自启项 `SZUNetSentinel` |

> [!TIP]
> 如需彻底重置密码或配置，只需删除 `%LOCALAPPDATA%\SZUNetSentinel\config.json` 即可。

---

## 🏗️ 架构与模块划分

```text
szu_network/
├── szu_sentinel/              # 核心守护逻辑包
│   ├── direct_network.py     # 物理网卡绑定、DNS 解析与防代理 TUN 拦截
│   ├── network.py            # 三级智能区域识别、双探针联网复核、重连逻辑
│   ├── srun.py               # 深澜 SRun 协议核心（XEncode/XXTEA/HMAC-MD5/Base64）
│   ├── monitor.py            # 后台守护线程与保活心跳调度
│   ├── storage.py            # Windows DPAPI 加密凭据存储
│   ├── startup.py            # Windows 用户级注册表开机自启
│   ├── local_log.py          # 本地分卷日志记录与 7 天自动滚动清理
│   ├── tray.py               # Windows 系统托盘集成（pystray）
│   └── ui.py                 # Tkinter 现代化图形管理界面
├── tests/                    # 完整单元测试集（34 个测试）
├── build.ps1                 # Windows 自动化打包编译脚本
├── main.py                   # 启动入口（支持 GUI 与托盘）
└── requirements.txt          # 运行依赖清单
```

---

## ❓ 常见问题 (FAQ)

### Q1：为什么提示“检测到校园网直连”，它和普通连接有什么区别？
> 很多同学电脑上运行了 Clash、Mihomo、V2Ray 等工具，这些软件会开启虚拟网卡（TUN 模式）劫持全部流量。当校园网掉线时，代理软件常导致外网探测结果失真，或者登录请求被发送到代理服务器而导致连接失败。直连技术能绕过虚拟网卡，直接通过机身真实的无线/有线网卡跟深大认证服务器通信，确保重连 100% 可用。

### Q2：我带着电脑从宿舍去了图书馆/教学楼，需要手动去设置界面改区域吗？
> **完全不需要！** 只要网络区域选择的是默认的“自动识别”，程序在每次检测时都会重新识别当前所处网络的真实 IP 和网关特征。一从宿舍走到教学区，它就会无感平滑切换为 SRun 协议，无需任何人工干预。

### Q3：移动了 EXE 的存放位置后，开机自启失效了怎么办？
> Windows 的开机自启项记录的是勾选那一刻 EXE 所在的绝对路径。如果移动了文件位置，只需打开软件，取消勾选“开机自动启动”，然后重新勾选一次即可更新注册表路径。

---

## 📄 开源许可与致谢

- 本项目采用 [MIT License](LICENSE) 许可协议。
- 感谢 [ackness/szu-autoconnect](https://github.com/ackness/szu-autoconnect)、[Sleepstars/SZU-login](https://github.com/Sleepstars/SZU-login)、[vidar-team/srun-login](https://github.com/vidar-team/srun-login) 等开源项目的技术探索与参考。
- 更多归属与声明请阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
