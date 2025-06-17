#!/bin/bash

# 设置颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# 获取参数
PORT=${1:-8080}

# 输出信息函数
info() { echo -e "${BLUE}[信息]${NC} $1"; }
success() { echo -e "${GREEN}[成功]${NC} $1"; }
warn() { echo -e "${YELLOW}[警告]${NC} $1"; }
error() { echo -e "${RED}[错误]${NC} $1"; }

# 设置工作目录
cd "$(dirname "$0")"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    warn "未检测到虚拟环境，请先运行 ./setup_venv.sh"
    read -p "是否现在运行虚拟环境设置脚本? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ./setup_venv.sh
    else
        exit 1
    fi
fi

# 激活虚拟环境
info "正在激活虚拟环境..."
source venv/bin/activate

# 检查端口
port_check=$(lsof -i:$PORT | grep LISTEN)
if [ -n "$port_check" ]; then
    warn "端口 $PORT 已被占用"
    for alt_port in {8081..8090}; do
        port_alt_check=$(lsof -i:$alt_port | grep LISTEN)
        if [ -z "$port_alt_check" ]; then
            PORT=$alt_port
            info "已自动切换至可用端口 $PORT"
            break
        fi
    done
fi

# 检查配置文件
if [ ! -f "config.yml" ]; then
    error "找不到配置文件：config.yml"
    info "请确保config.yml文件存在并包含正确的配置"
    exit 1
else
    success "检测到config.yml配置文件"
fi

# 检查并提醒旧的.env文件
if [ -f ".env" ]; then
    warn "检测到旧的.env文件，配置已迁移到config.yml"
    info "应用将使用config.yml中的配置，.env文件将被忽略"
fi

# 终止已有的应用进程
pkill -f "uvicorn src.main:app" 2>/dev/null || true
sleep 1

# 启动应用
info "启动K8Helper，访问地址: http://localhost:$PORT"
info "配置文件：config.yml"
info "按 Ctrl+C 终止应用"
echo ""

python -m uvicorn src.main:app --reload --host 0.0.0.0 --port $PORT 