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
    print_warning "未检测到python3，尝试自动安装Python 3.10..."

    install_success=false
    # 检测包管理器并安装
    if command -v apt-get &> /dev/null; then
        print_info "使用 apt 安装 Python 3.10"
        sudo apt-get update && sudo apt-get install -y python3.10 python3.10-venv python3.10-distutils && \
        sudo ln -sf $(which python3.10) /usr/bin/python3 && install_success=true
    elif command -v yum &> /dev/null; then
        print_info "使用 yum 安装 Python 3.10"
        sudo yum install -y python3.10 && \
        sudo ln -sf $(which python3.10) /usr/bin/python3 && install_success=true
    elif command -v dnf &> /dev/null; then
        print_info "使用 dnf 安装 Python 3.10"
        sudo dnf install -y python3.10 && \
        sudo ln -sf $(which python3.10) /usr/bin/python3 && install_success=true
    elif command -v brew &> /dev/null; then
        print_info "使用 brew 安装 Python 3.10"
        brew install python@3.10 && \
        ln -sf $(brew --prefix)/opt/python@3.10/bin/python3 /usr/local/bin/python3 && install_success=true
    else
        print_error "无法自动识别包管理器，请手动安装Python 3.10"
    fi

    if ! $install_success; then
        print_error "自动安装Python 3.10失败，请手动安装后重新运行脚本"
        exit 1
    fi

    print_success "Python 3.10 安装完成"
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
    pip install fastapi uvicorn kubernetes python-dotenv pyyaml
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

# 检查配置文件
if [ ! -f "config.yml" ]; then
    print_warning "未找到config.yml配置文件"
    print_info "请确保config.yml文件存在并包含正确的配置"
    print_info "配置文件应包含API密钥、服务端口等必要配置"
else
    print_success "检测到config.yml配置文件"
    
    # 检查配置文件中的关键配置
    if grep -q "secret_id:" config.yml && grep -q "secret_key:" config.yml; then
        print_success "配置文件包含必要的API密钥配置"
else
        print_warning "配置文件中可能缺少API密钥配置，请检查config.yml文件"
    fi
fi

# 检查并提醒旧的.env文件
if [ -f ".env" ]; then
    print_warning "检测到旧的.env文件，配置已迁移到config.yml"
    print_info "建议删除.env文件，应用将使用config.yml中的配置"
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
print_info "配置文件："
echo "  应用使用config.yml作为配置文件"
echo "  请确保其中包含正确的API密钥和其他配置"
echo "" 