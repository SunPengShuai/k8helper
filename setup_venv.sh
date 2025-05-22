#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # 无颜色

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
echo "        K8Helper - 虚拟环境设置脚本                "
echo "=================================================="
echo ""

# 检查python3是否存在
if ! command -v python3 &> /dev/null; then
    print_error "未找到python3，请先安装Python 3"
    exit 1
fi

# 检查当前Python版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
print_info "检测到Python版本: $python_version"

# 创建虚拟环境
print_info "正在创建或更新虚拟环境..."
if [ -d "venv" ]; then
    print_warning "检测到已存在的虚拟环境"
    read -p "是否重新创建虚拟环境？这将删除已有环境 (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "删除已有虚拟环境..."
        rm -rf venv
        python3 -m venv venv
        print_success "虚拟环境已重新创建"
    else
        print_info "保留现有虚拟环境"
    fi
else
    python3 -m venv venv
    print_success "虚拟环境创建成功"
fi

# 激活虚拟环境
print_info "激活虚拟环境..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    print_error "虚拟环境激活失败！"
    exit 1
fi
print_success "虚拟环境激活成功"

# 升级pip
print_info "升级pip..."
pip install --upgrade pip
print_success "pip升级完成"

# 安装依赖
print_info "安装项目依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    print_warning "依赖安装过程中出现错误，尝试安装核心依赖..."
    pip install fastapi uvicorn kubernetes python-dotenv
    pip install tencentcloud-sdk-python-hunyuan
    pip install openai
    if [ $? -ne 0 ]; then
        print_error "核心依赖安装失败！请检查网络连接或手动安装依赖。"
    else
        print_success "核心依赖安装成功"
    fi
else
    print_success "所有依赖安装完成"
fi

# 创建.env文件（如果不存在）
if [ ! -f ".env" ]; then
    print_info "创建默认的.env文件..."
    cat > .env << EOF
TENCENT_SECRET_ID=your_secret_id
TENCENT_SECRET_KEY=your_secret_key
EOF
    print_success ".env文件创建成功，请在使用前更新实际的密钥"
else
    print_info "检测到已存在的.env文件，跳过创建"
fi

echo ""
print_success "虚拟环境设置完成！"
echo ""
print_info "使用方法："
echo "  1. 激活虚拟环境：source venv/bin/activate"
echo "  2. 运行应用：./start.sh [端口号]"
echo "  3. 退出虚拟环境：deactivate"
echo ""
print_info "或直接使用启动脚本："
echo "  ./start.sh [端口号]"
echo "" 