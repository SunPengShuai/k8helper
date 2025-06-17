# K8Helper

K8Helper是一个基于AI的Kubernetes集群管理助手，它使用自然语言交互来简化Kubernetes操作，通过结合腾讯云混元大模型和OpenAI接口，实现智能化的集群管理和操作。

## 功能特点

- **自然语言交互**：使用自然语言描述Kubernetes操作，无需记忆复杂命令
- **智能命令识别**：自动将自然语言转换为适当的kubectl命令
- **安全管理系统**：超级管理员模式、Shell命令安全控制、自定义安全策略
- **系统配置管理**：AI模型配置、重试策略、性能参数调优
- **美观的结果展示**：以表格、分段和格式化的方式展示命令输出结果
- **多功能界面**：AI助手、Shell命令、安全设置、系统配置四大功能模块
- **Web界面和API双接口**：同时提供API调用和Web界面两种使用方式

## 快速开始

### 环境要求

- Python 3.9+
- Kubernetes集群访问权限
- 腾讯云混元大模型或OpenAI API密钥

### 安装

1. 克隆仓库：
```bash
git clone https://github.com/yourusername/k8helper.git
cd k8helper
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置应用：
编辑 `config.yml` 文件，设置您的API密钥和其他配置：

```yaml
# 腾讯云配置
tencent:
  secret_id: "your_tencent_secret_id"
  secret_key: "your_tencent_secret_key"
  region: "ap-guangzhou"

# LLM配置
llm:
  hunyuan:
    api_key: "your_hunyuan_api_key"
    secret_key: "your_hunyuan_secret_key"
  openai:
    api_key: "your_openai_api_key"

# API服务配置
api:
  host: "0.0.0.0"
  port: 8080
  reload: true
```

### 运行服务

#### 方式一：使用启动脚本（推荐）
```bash
# 首次运行，设置虚拟环境
./setup_venv.sh

# 启动应用
./start.sh

# 或指定端口
./start.sh 8081
```

#### 方式二：直接运行
```bash
cd k8helper
python -m uvicorn src.main:app --host 0.0.0.0 --port 8080
```

### 使用Docker运行

1. 构建镜像：
```bash
docker build -t k8helper .
```

2. 运行容器：
```bash
docker run -p 8080:8080 \
  -v ~/.kube/config:/root/.kube/config:ro \
  -v $(pwd)/config.yml:/app/config.yml:ro \
  k8helper
```

### 使用示例

#### Web界面使用

打开浏览器访问 http://localhost:8080，您将看到四个主要功能模块：

1. **🤖 AI助手**：使用自然语言查询Kubernetes资源
2. **💻 Shell命令**：执行高级Shell命令和管道操作
3. **🔒 安全设置**：管理超级管理员模式和安全策略
4. **⚙️ 系统配置**：配置AI模型、重试策略、性能参数等

#### API调用示例

1. 基础查询：
```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "如何查看Kubernetes集群中所有Pod的状态？"}'
```

2. 复杂查询：
```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看kube-system命名空间中CPU使用率最高的Pod"}'
```

3. Shell命令执行：
```bash
curl -X POST http://localhost:8080/api/v1/shell \
  -H "Content-Type: application/json" \
  -d '{"command": "kubectl get pods --all-namespaces | grep -v Running"}'
```

4. 安全配置管理：
```bash
# 获取当前安全配置
curl http://localhost:8080/api/v1/security/config

# 启用超级管理员模式
curl -X POST http://localhost:8080/api/v1/security/super-admin/enable
```

## 项目结构

```
k8helper/
├── src/
│   ├── api/            # API路由和请求处理
│   ├── core/           # 核心业务逻辑
│   ├── utils/          # 工具类
│   └── tests/          # 测试用例
├── static/             # 静态资源文件
│   ├── css/           # 样式文件
│   │   ├── style.css          # 主样式文件
│   │   └── setting_style.css  # 系统配置页面样式
│   ├── js/            # JavaScript文件
│   └── index.html     # 主页面
├── chart/              # Helm chart定义
├── config.yml          # 统一配置文件
├── Dockerfile          # Docker构建文件
├── requirements.txt    # 项目依赖
├── start.sh           # 启动脚本
├── run.sh             # 简化启动脚本
├── setup_venv.sh      # 虚拟环境设置脚本
└── README.md          # 项目文档
```

## 高级功能

### 智能重试机制
当命令执行失败时，AI会自动分析错误原因并生成修复命令：
- 自动识别权限问题、资源不存在等常见错误
- 生成针对性的修复建议
- 支持多步骤修复流程

### 复杂Shell命令支持
支持管道、命令替换等高级Shell语法：
```bash
# 批量删除失败的Pod
kubectl get pods --all-namespaces --field-selector=status.phase=Failed -o name | xargs kubectl delete

# 查找资源使用率最高的节点
kubectl top nodes | sort -k3 -nr | head -5
```

### 安全策略管理
- **超级管理员模式**：控制危险操作的执行权限
- **命令白名单/黑名单**：自定义允许和禁止的命令
- **资源操作限制**：限制可以创建、删除的资源类型

### 系统配置管理
- **AI模型切换**：支持腾讯云混元和OpenAI模型
- **重试策略配置**：自定义最大重试次数和延迟时间
- **性能参数调优**：超时设置、输出限制、结果缓存

## 开发指南

### 本地开发

1. **环境设置**：
```bash
# 设置虚拟环境
./setup_venv.sh

# 激活虚拟环境
source venv/bin/activate
```

2. **运行测试**：
```bash
python -m pytest src/tests/
```

3. **启动开发服务器**：
```bash
./start.sh 8080
```

### 功能扩展

要添加新的kubectl命令支持，请参考 `src/core/llm_client.py` 中的工具定义，并在 `src/api/routes.py` 中添加相应的处理逻辑。

### 构建Docker镜像

```bash
docker build -t k8helper .
```

### 使用Helm部署

```bash
cd k8helper
helm install k8helper ./chart \
  --set-file config=config.yml
```

## 配置说明

### 配置文件结构

`config.yml` 文件包含以下主要配置节：

- **app**: 应用基础配置（名称、版本、调试模式）
- **api**: API服务配置（主机、端口、CORS设置）
- **kubernetes**: Kubernetes连接配置
- **tencent**: 腾讯云服务配置
- **llm**: 大语言模型配置（混元、OpenAI）
- **logging**: 日志配置
- **security**: 安全策略配置
- **services**: Kubernetes API服务配置
- **tools**: MCP工具配置

### 环境变量支持

配置文件支持环境变量替换，格式为 `${ENV_VAR_NAME}`：

```yaml
tencent:
  secret_id: "${TENCENT_SECRET_ID}"
  secret_key: "${TENCENT_SECRET_KEY}"
```

## 故障排除

### 常见问题

1. **配置文件错误**：
   - 确保 `config.yml` 文件存在且格式正确
   - 检查API密钥是否正确设置

2. **依赖问题**：
   ```bash
   # 重新安装依赖
   pip install -r requirements.txt
   
   # 或安装核心依赖
   pip install fastapi uvicorn openai tencentcloud-sdk-python-hunyuan pyyaml
   ```

3. **端口冲突**：
   ```bash
   # 查找占用端口的进程
   lsof -i :8080
   
   # 使用其他端口启动
   ./start.sh 8081
   ```

4. **Kubernetes连接问题**：
   - 确保 `~/.kube/config` 文件存在且有效
   - 检查集群连接权限

### 健康检查

使用健康检查API验证服务状态：
```bash
curl http://localhost:8080/health
```

### 日志调试

查看应用日志：
```bash
# 查看实时日志
tail -f logs/k8helper.log

# 查看错误日志
grep ERROR logs/k8helper.log
```

## 实现原理

K8Helper采用MCP (Model-Controller-Plugin) 架构：

- **A端（MCPserver）**：应用服务器，能访问Kubernetes环境并执行kubectl命令，但无分析能力
- **B端（MCPclient）**：远程大模型服务，如腾讯云混元或OpenAI，具有分析能力但无法直接操作Kubernetes

工作流程：
1. 用户向A端提交自然语言查询（如"该集群有多少Pod？"）
2. A端将用户问题和可用工具列表传给B端
3. B端理解问题并返回需要执行的具体kubectl命令
4. A端执行命令并将结果格式化展示给用户

这种架构结合了大模型的理解能力和本地执行环境的操作能力，实现了智能化的Kubernetes管理。

## 部署最佳实践

### 生产环境建议

1. **安全配置**：
   - 使用HTTPS保护API通信
   - 实现API认证机制
   - 定期更新依赖包

2. **高可用部署**：
   - 部署多个副本
   - 配置资源限制和请求
   - 使用ConfigMap和Secret管理配置

3. **监控和日志**：
   - 使用Prometheus监控API性能
   - 配置structured logging
   - 设置告警规则

### Kubernetes部署示例

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8helper
spec:
  replicas: 2
  selector:
    matchLabels:
      app: k8helper
  template:
    metadata:
      labels:
        app: k8helper
    spec:
      containers:
      - name: k8helper
        image: k8helper:latest
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: config
          mountPath: /app/config.yml
          subPath: config.yml
        - name: kubeconfig
          mountPath: /root/.kube/config
          subPath: config
      volumes:
      - name: config
        configMap:
          name: k8helper-config
      - name: kubeconfig
        secret:
          secretName: kubeconfig
```

## 支持与反馈

如果您在使用过程中遇到问题或有改进建议，请通过以下方式联系我们：

- 提交Issue：[GitHub Issues](https://github.com/yourusername/k8helper/issues)
- 功能请求：[GitHub Discussions](https://github.com/yourusername/k8helper/discussions)
- 邮件支持：support@k8helper.com

## 许可证

本项目采用MIT许可证，详情请参阅 [LICENSE](LICENSE) 文件。