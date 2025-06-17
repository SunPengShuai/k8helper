# K8Helper

K8Helper是一个基于AI的Kubernetes集群管理助手，它使用自然语言交互来简化Kubernetes操作，通过结合腾讯云混元大模型和OpenAI接口，实现智能化的集群管理和操作。

## 功能特点

- **自然语言交互**：使用自然语言描述Kubernetes操作，无需记忆复杂命令
- **智能命令识别**：自动将自然语言转换为适当的kubectl命令
- **任务取消功能**：支持实时取消正在执行的任务，提供中断按钮和任务状态管理
- **智能重试机制**：当命令执行失败时，AI会自动分析错误并生成修复命令
- **美观的结果展示**：以表格、分段和格式化的方式展示命令输出结果
- **支持多种查询类型**：Pod状态、服务列表、部署详情等
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
pip3 install -r requirements.txt
```

3. 配置应用：
编辑 `config.yml` 文件，设置您的API密钥：

```yaml
# 基础应用配置
app:
  name: "k8helper"
  version: "2.1.0"
  debug: false

# API服务配置
api:
  host: "0.0.0.0"
  port: 8080
  reload: true

# Kubernetes配置
kubernetes:
  config_path: "~/.kube/config"
  namespace: "default"

# LLM配置 - 获取API Key: https://console.cloud.tencent.com/hunyuan/api-key
llm:
  hunyuan:
    api_key: "your_hunyuan_api_key"
  openai:
    api_key: "your_openai_api_key"

# 日志配置
logging:
  level: "INFO"
  log_dir: "logs"
  file_name: "k8helper.log"
```

### 运行服务

#### 方式一：使用启动脚本（推荐）
```bash
# 启动应用
./start.sh

# 或指定端口
./start.sh 8081
```

#### 方式二：直接运行
```bash
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
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

打开浏览器访问 http://localhost:8080，在输入框中使用自然语言输入您的Kubernetes查询。

**新功能亮点**：
- **任务取消**：点击"⏹️ 中断"按钮可以随时取消正在执行的任务
- **实时状态**：显示任务执行状态和进度
- **智能重试**：失败的命令会自动分析错误并重试

#### API调用示例

1. 基础查询（支持任务取消）：
```bash
# 发起查询（会返回task_id）
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看所有Pod状态", "task_id": "12345"}'

# 取消任务
curl -X POST http://localhost:8080/api/v1/cancel \
  -H "Content-Type: application/json" \
  -d '{"task_id": "12345"}'

# 查看任务状态
curl http://localhost:8080/api/v1/tasks/status
```

2. 查看特定命名空间的服务：
```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看kube-system命名空间中的服务"}'
```

3. 查看特定Pod详情：
```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看kube-system命名空间下名为coredns的Pod的详细信息"}'
```

## 新功能亮点

### 任务管理和取消功能

- **实时取消**：支持在任务执行过程中随时取消
- **任务状态跟踪**：实时显示任务执行状态
- **优雅中断**：确保任务安全停止，不会留下残留进程
- **状态管理**：自动清理完成的任务，避免内存泄漏

### 智能重试机制

- **错误分析**：AI自动分析命令失败原因
- **修复建议**：生成针对性的修复命令
- **多步骤修复**：支持复杂的修复流程
- **重试历史**：记录所有重试尝试和结果

### 配置简化

- **移除冗余配置**：不再需要腾讯云基础服务配置
- **只需API Key**：只需要混元大模型的API密钥即可使用
- **自动检测**：启动脚本自动检测配置完整性

## 项目结构

```
k8helper/
├── src/
│   ├── api/            # API路由和请求处理
│   │   └── routes.py   # 主要API端点（包含任务管理）
│   ├── core/           # 核心业务逻辑
│   │   ├── llm_client.py    # LLM客户端
│   │   └── k8s_client.py    # Kubernetes客户端
│   ├── utils/          # 工具类
│   │   ├── config.py   # 配置管理
│   │   └── logger.py   # 日志工具
│   └── tests/          # 测试用例
├── chart/              # Helm chart定义
├── static/             # 静态资源文件
│   ├── css/           # 样式文件
│   ├── js/            # JavaScript文件（包含任务取消逻辑）
│   └── index.html     # 主页面
├── Dockerfile          # Docker构建文件
├── requirements.txt    # 项目依赖
├── start.sh           # 启动脚本
└── README.md           # 项目文档
```

## 开发指南

### 本地开发

1. **环境设置**：
```bash
# 克隆项目
git clone https://github.com/yourusername/k8helper.git
cd k8helper

# 安装依赖
pip3 install -r requirements.txt
```

2. **配置文件**：
```bash
# 编辑配置文件，添加您的API密钥
vim config.yml
```

3. **运行测试**：
```bash
python3 -m pytest src/tests/
```

4. **启动开发服务器**：
```bash
./start.sh 8080
```

### 构建Docker镜像

```bash
docker build -t k8helper .
```

### 使用Helm部署

```bash
cd k8helper
helm install k8helper ./chart \
  --set hunyuan.apiKey="your_api_key" \
  --set-file kubeconfig=~/.kube/config
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

## 故障排除

### 常见问题

1. **配置文件错误**：
   - 确保 `config.yml` 文件存在且格式正确
   - 检查混元API密钥是否正确设置
   - 验证API密钥有效性：https://console.cloud.tencent.com/hunyuan/api-key

2. **依赖问题**：
   ```bash
   # 重新安装依赖
   pip3 install -r requirements.txt
   
   # 或安装核心依赖
   pip3 install fastapi uvicorn openai tencentcloud-sdk-python-hunyuan pyyaml kubernetes
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
   - 测试kubectl命令：`kubectl get nodes`

5. **任务取消问题**：
   - 如果任务无法取消，检查任务ID是否正确
   - 查看任务状态：`curl http://localhost:8080/api/v1/tasks/status`
   - 清理僵尸任务：`curl -X POST http://localhost:8080/api/v1/tasks/cleanup`

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

# 查看任务相关日志
grep "task_id" logs/k8helper.log
```

### API测试

测试核心功能：
```bash
# 测试基本查询
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看集群节点状态"}'

# 测试任务管理
curl http://localhost:8080/api/v1/tasks/status
```

## 快速启动脚本

项目提供了便捷的脚本，用于简化环境设置和应用启动流程：

### 应用启动

使用`start.sh`脚本（完整版，包含环境检查和自动修复）：

```bash
# 赋予执行权限
chmod +x start.sh

# 使用默认端口(8080)启动
./start.sh

# 指定端口启动
./start.sh 8081
```

这个脚本会自动处理：
- 检查Python环境和依赖
- 验证配置文件完整性
- 检查混元API密钥
- 处理端口冲突
- 终止已存在的实例
- 启动应用服务

### 虚拟环境设置（可选）

如果需要使用虚拟环境，可以使用`setup_venv.sh`脚本：

```bash
# 赋予执行权限
chmod +x setup_venv.sh

# 运行脚本
./setup_venv.sh
```

### 开发流程示例

```bash
# 1. 首次设置
git clone https://github.com/yourusername/k8helper.git
cd k8helper
vim config.yml  # 配置API密钥

# 2. 启动应用
./start.sh

# 3. 测试API
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "查看所有Pod状态"}'
```

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
        - name: kubeconfig
          mountPath: /root/.kube/config
          subPath: config
        env:
        - name: HUNYUAN_API_KEY
          valueFrom:
            secretKeyRef:
              name: k8helper-secrets
              key: hunyuan-api-key
      volumes:
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