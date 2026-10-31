#!/usr/bin/env bash
# ==============================================================================
# SZU NetSentinel Linux 一键安装与守护服务部署脚本
# ==============================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}====================================================${NC}"
echo -e "${GREEN}  SZU NetSentinel (深大校园网智能哨兵) - Linux 安装向导${NC}"
echo -e "${CYAN}====================================================${NC}"

# 1. 检查 Python 3 环境
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}[错误] 未检测到 python3，请先安装 Python 3.8+ (如 sudo apt install python3 python3-pip)${NC}"
    exit 1
fi

PYTHON_BIN="$(command -v python3)"
PY_VER="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo -e "${BLUE}[*] 检测到 Python 解释器:${NC} $PYTHON_BIN (v$PY_VER)"

# 2. 安装 requests 依赖
echo -e "${BLUE}[*] 正在检查/安装必要运行依赖 (requests)...${NC}"
$PYTHON_BIN -m pip install --quiet --upgrade requests

# 3. 部署脚本至 ~/.local/bin/szu-sentinel
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_PATH/szu_sentinel_linux.py" ]; then
    cp "$SCRIPT_PATH/szu_sentinel_linux.py" "$INSTALL_DIR/szu-sentinel"
else
    # 包装 main.py
    cat << 'EOF' > "$INSTALL_DIR/szu-sentinel"
#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$DIR/szu_pkg:$PYTHONPATH"
exec python3 -m szu_sentinel "$@"
EOF
fi

chmod +x "$INSTALL_DIR/szu-sentinel"
echo -e "${GREEN}[OK] 客户端已成功安装至:${NC} $INSTALL_DIR/szu-sentinel"

# 4. 检测 PATH 是否包含 ~/.local/bin
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo -e "${YELLOW}[提示] 请将 ~/.local/bin 加入你的 PATH (可在 ~/.bashrc 或 ~/.zshrc 中追加: export PATH=\"\$HOME/.local/bin:\$PATH\")${NC}"
fi

# 5. 提示或执行配置向导
echo ""
echo -e "${CYAN}----------------------------------------------------${NC}"
echo -e "${GREEN}现在启动校园网交互配置向导...${NC}"
"$INSTALL_DIR/szu-sentinel" --config

# 6. 配置 systemd user 守护服务
echo ""
echo -e "${BLUE}[*] 正在配置 systemd 开机自启与后台保活守护服务...${NC}"
"$INSTALL_DIR/szu-sentinel" --install-service

echo ""
echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}  安装部署完成！常用命令速查:${NC}"
echo -e "${CYAN}  • 状态检测:${NC}    szu-sentinel --status"
echo -e "${CYAN}  • 手动登录:${NC}    szu-sentinel --login"
echo -e "${CYAN}  • 终端守护:${NC}    szu-sentinel --daemon"
echo -e "${CYAN}  • 重新配置:${NC}    szu-sentinel --config"
echo -e "${CYAN}  • 启动服务:${NC}    systemctl --user start szu-sentinel"
echo -e "${CYAN}  • 查看服务日志:${NC} journalctl --user -u szu-sentinel -f"
echo -e "${GREEN}====================================================${NC}"
