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

# 检查并安装yq工具（用于处理YAML）
check_yq() {
    if ! command -v yq &> /dev/null; then
        print_info "安装yq工具用于处理YAML配置..."
        # 尝试使用不同的包管理器安装yq
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y yq
        elif command -v yum &> /dev/null; then
            sudo yum install -y yq
        elif command -v brew &> /dev/null; then
            brew install yq
        else
            print_warning "无法自动安装yq，将使用Python处理YAML"
            return 1
        fi
    fi
    return 0
}

# 从config.yml读取配置的Python脚本
read_config_value() {
    local key=$1
    python3 -c "
import yaml
import sys
try:
    with open('config.yml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    keys = '$key'.split('.')
    value = config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            print('')
            sys.exit(0)
    
    print(value if value is not None else '')
except Exception as e:
    print('')
" 2>/dev/null
}

# 确保工作目录正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 欢迎信息
echo "=================================================="
echo "        K8Helper - Kubernetes助手启动脚本           "
echo "=================================================="
echo ""

# 检查config.yml文件是否存在
if [ ! -f "config.yml" ]; then
    print_error "未找到config.yml配置文件！"
    print_info "请确保config.yml文件存在于项目根目录"
    exit 1
fi

print_success "找到config.yml配置文件"

# 从config.yml读取端口配置
CONFIG_PORT=$(read_config_value "api.port")
if [ -n "$CONFIG_PORT" ] && [ "$PORT" = "$DEFAULT_PORT" ]; then
    PORT=$CONFIG_PORT
    print_info "使用config.yml中配置的端口: $PORT"
fi

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
port_check=$(lsof -i:$PORT 2>/dev/null | grep LISTEN)
if [ -n "$port_check" ]; then
    print_warning "端口 $PORT 已被占用"
    read -p "是否尝试使用其他可用端口? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for alt_port in {8081..8090}; do
            port_alt_check=$(lsof -i:$alt_port 2>/dev/null | grep LISTEN)
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
    pip install fastapi uvicorn openai python-dotenv tencentcloud-sdk-python-hunyuan pyyaml kubernetes
    if [ $? -ne 0 ]; then
        print_error "依赖安装失败！请检查网络连接或手动安装依赖。"
        exit 1
    fi
fi
print_success "依赖安装完成"

# 验证配置文件
echo ""
print_info "验证配置文件..."

# 读取关键配置项
APP_NAME=$(read_config_value "app.name")
APP_VERSION=$(read_config_value "app.version")
HUNYUAN_API_KEY=$(read_config_value "llm.hunyuan.api_key")

print_info "应用名称: ${APP_NAME:-k8helper}"
print_info "应用版本: ${APP_VERSION:-unknown}"

# 检查关键配置
if [ -z "$HUNYUAN_API_KEY" ] || [ "$HUNYUAN_API_KEY" = "your_api_key" ] || [ "$HUNYUAN_API_KEY" = "test_key" ]; then
    print_warning "混元API Key未配置或使用默认值"
    print_info "请编辑config.yml文件中的llm.hunyuan.api_key配置"
    print_info "获取API Key: https://console.cloud.tencent.com/hunyuan/api-key"
fi

# 检查是否存在旧的.env文件
if [ -f ".env" ]; then
    print_warning "检测到旧的.env文件"
    print_info "项目现在使用config.yml配置文件，建议删除.env文件"
    read -p "是否删除旧的.env文件? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm .env
        print_success "已删除.env文件"
    fi
fi

# 设置环境变量（从config.yml读取）
print_info "从config.yml设置环境变量..."
export CONFIG_FILE="config.yml"

# 启动应用
echo ""
print_info "启动K8Helper应用，端口：$PORT"
print_info "配置文件：config.yml"
print_info "按Ctrl+C终止应用..."
echo ""

# 从config.yml读取host配置
CONFIG_HOST=$(read_config_value "api.host")
HOST=${CONFIG_HOST:-"0.0.0.0"}

# 从config.yml读取reload配置
CONFIG_RELOAD=$(read_config_value "api.reload")
if [ "$CONFIG_RELOAD" = "true" ]; then
    RELOAD_FLAG="--reload"
else
    RELOAD_FLAG=""
fi

python -m uvicorn src.main:app $RELOAD_FLAG --host $HOST --port $PORT 