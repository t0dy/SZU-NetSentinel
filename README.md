# 🛡️ SZU NetSentinel (深大网络守卫) v2.6.0

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-0078D4?logo=linux&logoColor=white)](https://github.com/t0dy/SZU-NetSentinel)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v2.6.0-orange.svg)](https://github.com/t0dy/SZU-NetSentinel/releases)

**SZU NetSentinel** 是一款专为深圳大学（SZU）师生打造的轻量级、全自动校园网掉线检测与保活守护工具（全面支持 **Windows 10/11** 与 **Linux 服务器/桌面**）。

具备**全校自适应智能区域识别**、**深澜 SRun 与宿舍 ePortal 双协议支持**、**物理网卡直连防代理干扰**、**30 秒轻量保活心跳**、**极低内存后台优化（1~8MB）**、**Windows DPAPI 硬件级密码加密**及**系统托盘静默运行**等特性，助你彻底告别断网、登录过期与频繁重连的烦恼。

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

### 4. 🔒 校园网局域网安全防护与防病毒侵入 (NEW)
在校园网（宿舍区 `172.30.*`、教学区 `172.31.*`）环境下，数万台电脑同处同一局域网广播域，普遍存在黑客与勒索蠕虫横向扫描渗透的风险。本项目集成专属安全引擎：
- **网关防 ARP 嗅探与劫持监测**：利用内核底层 `SendARP` 与系统 ARP 缓存比对，实时发现同网段中间人 ARP 投毒攻击；支持静态绑定默认网关（Static ARP），使黑客仿冒网关的嗅探包直接失效。
- **高危端口局域网暴露阻断**：一键阻断来自校园网的 `TCP 135, 137, 138, 139, 445, 3389` 及 `UDP 137, 138, 445` 入站连接，彻底切断 WannaCry、永恒之蓝等勒索病毒与 Trojan 矿机通过 SMB/RPC 在校园网内的横向传播。
- **Windows 防火墙状态自检**：检测专用/公用网络防火墙启闭状态，防止连入校园网后电脑沦为“不设防”状态。

### 5. 🔐 企业级凭据安全 (Windows DPAPI)
- 绝不明文保存账号密码！密码通过 Windows 底层数据保护 API（`CryptProtectData`）进行加密，密钥与当前 Windows 用户凭据硬件级绑定，其他用户或拷贝文件均无法解密。
- 日志自动脱敏，绝不记录任何明文密码、加密密钥或完整 payload。

### 6. 🪟 专属拟物网络盾牌图标与极致内存优化
- **标题栏与窗口原生盾牌图标**：彻底修复 Windows 标题栏左上角渲染 Tkinter 默认羽毛笔/毛笔图标的问题，基于 Win32 原生消息与多尺寸 ICO 资源，确保 16x16 标题栏、任务栏及 Alt-Tab 统一呈现专属深蓝网络盾牌。
- **后台常驻极度轻量（1MB ~ 8MB）**：引入 Windows `psapi.EmptyWorkingSet` 内存压缩技术，在启动后以及最小化至托盘时自动通知内核回收工作集，内存占用从以往的 50MB 骤降至 **1MB~8MB**，近乎“零开销”静默守护。
- **现代化卡片式图形界面**：高分辨率抗锯齿视觉勾选框（✔），告别让人困惑的打叉 ☒。
- **支持一键开启“开机自动启动”**：写入当前用户注册表，无需 UAC 管理员提权。
- **本地日志智能裁剪**：按天归档，自动清理 7 天前旧日志，UI 文本框自动保留最新记录，杜绝长时间运行内存泄露。

### 7. 🔄 代理与网络热切换自愈 + 高分屏大视野界面 (v2.6.0)
- **WinError 10049 异常免疫与动态网卡感知**：彻底解决 Clash / Mihomo 开关系统代理、TUN 模式切换或 DHCP 租期更新导致网卡 IP 变更时，底层套接字绑定旧 IP 崩溃并陷入死循环重连（`[WinError 10049]`）的痛点。底层 `DirectRoute` 具备动态生命周期校验（`is_valid()`），在发现网卡变动或错误时自动毫秒级刷新重绑。
- **强制阻断系统代理继承**：直连与探针会话显式注入 `proxies={"http": None, "https": None}`，彻底切断代理软件注册表及环境变量劫持，保证校园网登录通道绝对干净直达。
- **自适应高分屏 920px 大视野排版**：自适应窗口高度全面升级，界面启动即拥有超 300px 的完整独立日志窗口（首屏直接展示 12~15 行实时日志），彻底告别手动拉伸窗口。
- **操作栏与按钮防截断优化**：重构“保存设置”交互区域，彻底消除 Windows 缩放下的按钮文字截断（如“保存设”）；运行日志新增原生平滑滚动条与 `[清空]` 快捷按钮。

---

## 🚀 使用教程

### 方式一：Windows 单文件 EXE（即开即用，最推荐）

1. 从 [Releases 页面](https://github.com/t0dy/SZU-NetSentinel/releases) 下载最新版的 `SZU-NetSentinel-v2.6.0.exe`（或直接使用项目根目录下的可执行文件）。
2. **建议操作**：将 EXE 文件放置在固定的文件夹中（例如 `D:\Software\SZUNetSentinel\`），不要直接在桌面临时文件夹或下载目录中开启开机自启。
3. 双击运行 `SZU-NetSentinel-v2.6.0.exe`。
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

### 方式二：Linux 服务器与终端用户（专属 CLI / systemd 守护）

专为深大实验室 GPU 深度学习训练服务器、无显示器 Linux 工作站、寝室 NAS 及 Linux 桌面打造。支持一键部署为后台常驻守护服务，即使注销退出 SSH 也永不掉线。

#### 1. 一键自动安装与部署 (Ubuntu / Debian / CentOS / Arch)
```bash
# 执行一键安装脚本（自动安装依赖、部署命令与配置 systemd 守护）
curl -sSL https://raw.githubusercontent.com/t0dy/SZU-NetSentinel/main/install_linux.sh | bash
```

#### 2. 或手动单文件运行（极简便携，仅需 requests 库）
```bash
# 下载 Linux 专版独立脚本
wget https://raw.githubusercontent.com/t0dy/SZU-NetSentinel/main/szu_sentinel_linux.py -O szu-sentinel
chmod +x szu-sentinel

# 1. 运行交互向导配置账号与密码（密码经设备指纹密钥加密且权限设为 0600，杜绝明文泄露）
python3 szu-sentinel --config

# 2. 检查网络连通与区域识别状态
python3 szu-sentinel --status

# 3. 立即手动执行一次登录
python3 szu-sentinel --login

# 4. 启动终端保活守护（前台实时打印色彩日志，30 秒低开销轻量心跳防踢）
python3 szu-sentinel --daemon

# 5. 一键配置开机自动后台运行 (systemd user service)
python3 szu-sentinel --install-service
```

> [!TIP]
> **systemd 常用服务管理命令**：
> - 启动守护：`systemctl --user start szu-sentinel`
> - 停止守护：`systemctl --user stop szu-sentinel`
> - 查看运行状态：`systemctl --user status szu-sentinel`
> - 实时查看守护日志：`journalctl --user -u szu-sentinel -f`

---

### 方式三：从源码运行（跨平台开发者 / Python 用户）

#### 1. 克隆代码与安装依赖
```bash
git clone https://github.com/t0dy/SZU-NetSentinel.git
cd SZU-NetSentinel

# 安装基础运行依赖
python -m pip install -r requirements.txt
```

#### 2. 启动程序
* **在有图形界面的系统上（Windows / Linux X11/Wayland）**：
  ```bash
  python main.py
  ```
* **在无显示器或 SSH 远程服务器上**：
  `main.py` 会自动检测并以终端守护模式启动，或手动指定参数：
  ```bash
  python main.py --daemon
  ```

#### 3. 执行跨平台单元测试
本项目包含 **42 项**完整的跨平台单元测试，覆盖加密运算、子网启发识别、网关探针、Linux网卡解析、物理直连自愈与 systemd 服务生成：
```bash
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
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SZU-NetSentinel-v2.6.0" main.py
```
生成的单文件将存放在 `dist\SZU-NetSentinel-v2.6.0.exe`。

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
