# K8Helper

K8Helper是一个基于AI的Kubernetes集群管理助手，它使用自然语言交互来简化Kubernetes操作，通过结合腾讯云混元大模型和OpenAI接口，实现智能化的集群管理和操作。

## 功能特点

- 自然语言交互：使用自然语言描述Kubernetes操作，无需记忆复杂命令
- 智能命令识别：自动将自然语言转换为适当的kubectl命令
- 美观的结果展示：以表格、分段和格式化的方式展示命令输出结果
- 支持多种查询类型：Pod状态、服务列表、部署详情等
- Web界面和API双接口：同时提供API调用和Web界面两种使用方式

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

3. 配置环境变量：
```bash
export TENCENT_SECRET_ID="your_secret_id"
export TENCENT_SECRET_KEY="your_secret_key"
```

### 运行服务

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
  -e TENCENT_SECRET_ID=your_secret_id \
  -e TENCENT_SECRET_KEY=your_secret_key \
  -v ~/.kube/config:/root/.kube/config:ro \
  k8helper
```

### 使用示例

#### Web界面使用

打开浏览器访问 http://localhost:8080，在输入框中使用自然语言输入您的Kubernetes查询。

#### API调用示例

1. 查看所有Pod状态：
```bash
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "如何查看Kubernetes集群中所有Pod的状态？"}'
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

## 项目结构

```
k8helper/
├── src/
│   ├── api/            # API路由和请求处理
│   ├── core/           # 核心业务逻辑
│   ├── utils/          # 工具类
│   └── tests/          # 测试用例
├── chart/              # Helm chart定义
├── static/             # 静态资源文件
├── Dockerfile          # Docker构建文件
├── requirements.txt    # 项目依赖
└── README.md           # 项目文档
```

## 开发指南

### 运行测试

```bash
python -m pytest src/tests/
```

### 构建Docker镜像

```bash
docker build -t k8helper .
```

### 使用Helm部署

```bash
cd k8helper
helm install k8helper ./chart \
  --set secrets.tencentSecretId=your_secret_id \
  --set secrets.tencentSecretKey=your_secret_key
```

## 实现原理

K8Helper采用MCP (Model-Controller-Plugin) 架构：

- A端（MCPserver）：应用服务器，能访问Kubernetes环境并执行kubectl命令，但无分析能力
- B端（MCPclient）：远程大模型服务，如腾讯云混元或OpenAI，具有分析能力但无法直接操作Kubernetes

工作流程：
1. 用户向A端提交自然语言查询（如"该集群有多少Pod？"）
2. A端将用户问题和可用工具列表传给B端
3. B端理解问题并返回需要执行的具体kubectl命令
4. A端执行命令并将结果格式化展示给用户

这种架构结合了大模型的理解能力和本地执行环境的操作能力，实现了智能化的Kubernetes管理。

## 扩展教程

### 常见问题解决

#### 依赖问题

如果遇到`ModuleNotFoundError: No module named 'tencentcloud.hunyuan'`错误，需要安装腾讯云混元大模型SDK：

```bash
pip install tencentcloud-sdk-python-hunyuan
```

如果使用OpenAI兼容接口，请确保已安装openai包：

```bash
pip install openai
```

#### 环境变量配置

1. 设置临时环境变量：

```bash
export TENCENT_SECRET_ID="your_secret_id"
export TENCENT_SECRET_KEY="your_secret_key"
```

2. 或创建.env文件（推荐）：

```bash
# 在项目根目录创建.env文件
echo "TENCENT_SECRET_ID=your_secret_id" > .env
echo "TENCENT_SECRET_KEY=your_secret_key" >> .env
```

#### 端口冲突

如果默认端口(8080)被占用，可以更改端口：

```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8081
```

或者查找并关闭占用端口的进程：

```bash
# 查找占用8080端口的进程
lsof -i :8080
# 终止进程
kill -9 <PID>
```

### 修改LLM模型配置

K8Helper默认使用腾讯云混元大模型，但也支持配置为使用OpenAI或其他兼容接口的模型：

1. 在`src/core/llm_client.py`中更新模型配置：

```python
# 使用OpenAI API
self.client = OpenAI(
    api_key="your_openai_api_key",
    base_url="https://api.openai.com/v1"  # OpenAI官方接口
)

# 修改请求模型名称
completion = self.client.chat.completions.create(
    model="gpt-3.5-turbo",  # 替换为你需要的模型
    messages=messages
)
```

### 健康检查和调试

使用健康检查API来验证服务是否正常运行：

```bash
curl http://localhost:8080/api/v1/health
```

正常返回：`{"status":"healthy"}`

### 性能优化建议

1. 设置API超时和重试机制：

```python
# 在llm_client.py中设置
self.client = OpenAI(
    api_key=self.secret_key,
    base_url="https://api.hunyuan.cloud.tencent.com/v1",
    timeout=30.0,  # 设置30秒超时
    max_retries=3  # 设置最大重试次数
)
```

2. 启用结果缓存，对相同查询避免重复调用LLM：

```python
# 在routes.py中实现简单缓存
query_cache = {}

@router.post("/query")
async def process_query(request: QueryRequest):
    # 检查缓存
    cache_key = request.query
    if cache_key in query_cache:
        return query_cache[cache_key]
        
    # 处理请求逻辑...
    
    # 存入缓存
    query_cache[cache_key] = response
    return response
```

### 部署最佳实践

对于生产环境，建议：

1. 使用Kubernetes进行部署，确保高可用：
   - 部署多个副本
   - 配置资源限制和请求
   - 使用ConfigMap和Secret管理配置

2. 设置监控和日志：
   - 使用Prometheus监控API性能
   - 配置structured logging便于日志分析

3. 安全建议：
   - 使用HTTPS保护API通信
   - 实现API认证机制
   - 定期更新依赖包以修复安全漏洞
   
### 快速启动脚本

项目提供了几个便捷的脚本，用于简化环境设置和应用启动流程：

#### 虚拟环境设置

使用`setup_venv.sh`脚本快速创建和配置Python虚拟环境：

```bash
# 赋予执行权限
chmod +x setup_venv.sh

# 运行脚本
./setup_venv.sh
```

此脚本会自动：
- 创建Python虚拟环境
- 安装所有必要的依赖
- 创建默认的.env文件（如果不存在）

#### 应用启动

有两种方式可以启动应用：

1. 使用`start.sh`脚本（完整版，包含环境检查）：

```bash
# 赋予执行权限
chmod +x start.sh

# 使用默认端口(8080)启动
./start.sh

# 指定端口启动
./start.sh 8081
```

2. 使用`run.sh`脚本（简化版，假设环境已设置）：

```bash
# 赋予执行权限
chmod +x run.sh

# 使用默认端口启动
./run.sh

# 指定端口和环境变量文件
./run.sh 8081 custom.env
```

这些脚本会自动处理：
- 检查和激活虚拟环境
- 设置必要的环境变量
- 处理端口冲突
- 终止已存在的实例
- 启动应用服务

#### 开发流程示例

```bash
# 1. 初次设置（只需运行一次）
./setup_venv.sh

# 2. 日常开发启动
./run.sh

# 3. 测试API
curl -X POST http://localhost:8080/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "如何查看所有Pod的状态？"}'
```

## 工具能力扩展指南

K8Helper的核心功能是将自然语言转换为Kubernetes命令。如果您想扩展系统的能力，可以通过以下步骤添加新的工具和命令：

### 添加新的kubectl命令工具

1. 在`src/core/llm_client.py`文件中扩展`available_tools`列表：

```python
# 在HunyuanClient类的__init__方法中找到available_tools列表
self.available_tools = [
    # 现有工具...
    
    # 添加新工具示例
    {
        "name": "kubectl_get_configmaps",
        "description": "获取ConfigMap资源列表",
        "parameters": {
            "namespace": "可选，指定要查询的命名空间，不指定则查询所有命名空间",
            "output_format": "可选，输出格式，如wide、json、yaml等"
        }
    }
]
```

2. 在`src/api/routes.py`文件中的`execute_tool`函数中添加对应的处理逻辑：

```python
async def execute_tool(tool_name: str, parameters: Dict[str, Any]) -> str:
    """执行工具命令"""
    try:
        # 现有工具处理逻辑...
        
        # 添加新工具处理逻辑
        elif tool_name == "kubectl_get_configmaps":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "configmaps"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("--all-namespaces")
            if output_format:
                cmd.extend(["-o", output_format])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
```

3. 为新命令添加格式化输出支持（可选）：

在`format_output`函数中添加相应的格式化逻辑，使输出更美观：

```python
def format_output(tool_name: str, output: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """格式化输出结果"""
    try:
        # 现有格式化逻辑...
        
        # 为新工具添加格式化逻辑
        elif tool_name == "kubectl_get_configmaps":
            return format_table_output(output, tool_name, parameters)
    except Exception as e:
        logger.error(f"格式化输出失败: {str(e)}")
        return {"type": "text", "content": output}
```

### 添加复杂的非kubectl命令工具

如果您需要添加更复杂的功能（如日志分析、资源监控等），建议以下步骤：

1. 在`src/core`目录下创建新的模块文件，例如`resource_monitor.py`：

```python
from typing import Dict, Any
import subprocess
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ResourceMonitor:
    """资源监控工具类"""
    
    @staticmethod
    def get_node_resource_usage() -> Dict[str, Any]:
        """获取节点资源使用情况"""
        try:
            # 实现逻辑
            cmd = ["kubectl", "top", "nodes"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # 处理输出
            if result.returncode != 0:
                return {"success": False, "error": result.stderr}
                
            # 解析输出
            lines = result.stdout.strip().split('\n')
            headers = lines[0].strip().split()
            data = []
            
            for i in range(1, len(lines)):
                values = lines[i].strip().split()
                node_data = {}
                for j in range(min(len(headers), len(values))):
                    node_data[headers[j]] = values[j]
                data.append(node_data)
                
            return {
                "success": True,
                "data": data
            }
        except Exception as e:
            logger.error(f"获取节点资源使用情况失败: {str(e)}")
            return {"success": False, "error": str(e)}
```

2. 更新`llm_client.py`中的工具列表，添加新工具：

```python
{
    "name": "resource_monitor",
    "description": "获取集群资源使用情况，包括节点CPU和内存使用率",
    "parameters": {}
}
```

3. 在`routes.py`中添加对应的处理逻辑：

```python
from ..core.resource_monitor import ResourceMonitor

# 在execute_tool函数中添加
elif tool_name == "resource_monitor":
    monitor = ResourceMonitor()
    result = monitor.get_node_resource_usage()
    if result["success"]:
        return json.dumps(result["data"], ensure_ascii=False, indent=2)
    else:
        return f"获取资源使用情况失败: {result['error']}"
```

### 配置系统提示词

如需调整系统的理解能力或响应风格，可以修改`llm_client.py`中的系统提示词：

```python
system_prompt = """你是一个Kubernetes集群管理助手。你需要分析用户的查询，并返回结构化的JSON，包含工具名称和参数。
严格从提供的工具列表中选择一个最合适的工具，不要使用未定义的工具。
...
"""
```

### 集成新的LLM模型

如果您想使用不同的AI模型，可以在`llm_client.py`中添加新的模型适配：

```python
class AzureOpenAIClient(HunyuanClient):
    """Azure OpenAI模型客户端"""
    
    def __init__(self):
        super().__init__()
        self.client = OpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            base_url=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version="2023-05-15"
        )
        
    async def analyze_query(self, query: str, context: Dict[str, Any] = None) -> Dict:
        # 实现Azure OpenAI的请求逻辑
        # ...
```

然后在`routes.py`中根据配置选择使用哪个客户端：

```python
# 根据配置选择LLM客户端
llm_client_type = Config.LLM_CLIENT_TYPE
if llm_client_type == "azure":
    llm_client = AzureOpenAIClient()
elif llm_client_type == "openai":
    llm_client = OpenAIClient()
else:
    llm_client = HunyuanClient()  # 默认使用腾讯云混元
```

### 开发建议

1. 遵循模块化设计原则：新功能应该独立封装在单独的模块中
2. 保持兼容性：确保添加的功能不影响现有功能
3. 完善错误处理：对所有可能的错误情况进行处理
4. 添加测试用例：为新功能添加单元测试和集成测试
5. 更新文档：在添加新功能后更新文档和注释