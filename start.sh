#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # 无颜色

# 定义端口
DEFAULT_PORT=8080
PORT=${1:-$DEFAULT_PORT}

# 函数：打印带颜色的信息
print_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

print_error() {
    echo -e "${RED}[错误]${NC} $1"
}

# 确保工作目录正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 欢迎信息
echo "=================================================="
echo "        K8Helper - Kubernetes助手启动脚本           "
echo "=================================================="
echo ""

# 检查是否有其他uvicorn进程正在运行
uvicorn_pid=$(pgrep -f "uvicorn src.main:app")
if [ -n "$uvicorn_pid" ]; then
    print_warning "检测到已有uvicorn进程正在运行（PID: $uvicorn_pid）"
    read -p "是否终止已有进程并继续? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "正在终止uvicorn进程..."
        pkill -f "uvicorn src.main:app" || true
        sleep 2
    else
        print_info "退出脚本，保留已有进程"
        exit 0
    fi
fi

# 检查端口是否被占用
port_check=$(lsof -i:$PORT | grep LISTEN)
if [ -n "$port_check" ]; then
    print_warning "端口 $PORT 已被占用"
    read -p "是否尝试使用其他可用端口? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for alt_port in {8081..8090}; do
            port_alt_check=$(lsof -i:$alt_port | grep LISTEN)
            if [ -z "$port_alt_check" ]; then
                PORT=$alt_port
                print_info "已切换至可用端口 $PORT"
                break
            fi
        done
    else
        print_error "退出脚本，请手动释放端口 $PORT 后重试"
        exit 1
    fi
fi

# 激活虚拟环境
print_info "激活虚拟环境..."
if [ ! -d "venv" ]; then
    print_info "虚拟环境不存在，正在创建..."
    python3 -m venv venv
fi

source venv/bin/activate
if [ $? -ne 0 ]; then
    print_error "虚拟环境激活失败！"
    exit 1
fi
print_success "虚拟环境激活成功"

# 安装依赖
print_info "安装项目依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    print_warning "有些依赖安装失败，尝试安装必要的依赖..."
    pip install fastapi uvicorn openai python-dotenv tencentcloud-sdk-python-hunyuan pyyaml
    if [ $? -ne 0 ]; then
        print_error "依赖安装失败！请检查网络连接或手动安装依赖。"
        exit 1
    fi
fi
print_success "依赖安装完成"

# 检查配置文件
echo ""
print_info "检查配置文件..."

if [ -f "config.yml" ]; then
    print_success "检测到config.yml配置文件"
    
    # 检查配置文件中的关键配置
    if grep -q "secret_id:" config.yml && grep -q "secret_key:" config.yml; then
        print_success "配置文件包含必要的API密钥配置"
    else
        print_warning "配置文件中缺少API密钥配置，请检查config.yml文件"
    fi
else
    print_error "未找到config.yml配置文件！"
    print_info "请确保config.yml文件存在并包含正确的配置"
    exit 1
fi

# 检查并清理旧的.env文件（如果存在）
if [ -f ".env" ]; then
    print_warning "检测到旧的.env文件，配置已迁移到config.yml"
    read -p "是否删除旧的.env文件? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm .env
        print_success "已删除旧的.env文件"
    else
        print_info "保留.env文件，但应用将使用config.yml配置"
    fi
fi

# 启动应用
echo ""
print_info "启动K8Helper应用，端口：$PORT"
print_info "配置文件：config.yml"
print_info "按Ctrl+C终止应用..."
echo ""

python -m uvicorn src.main:app --reload --host 0.0.0.0 --port $PORT 