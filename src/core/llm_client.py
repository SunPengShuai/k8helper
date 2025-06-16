from typing import Dict, Any
import json
import os
import re
import traceback
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)

# 尝试导入 OpenAI 客户端，如果失败则提供一个备用实现
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    logger.warning("未找到OpenAI包，将使用内部模拟实现")
    HAS_OPENAI = False
    
    # 创建一个模拟的OpenAI类，避免导入错误
    class OpenAI:
        def __init__(self, **kwargs):
            self.api_key = kwargs.get("api_key")
            self.base_url = kwargs.get("base_url")
            self.chat = type('obj', (object,), {
                'completions': type('obj', (object,), {
                    'create': lambda **kwargs: None
                })
            })

class SuperKubectlAgent:
    """超强Kubectl AI Agent - 能够理解和执行任意kubectl命令"""
    
    def __init__(self):
        try:
            # 获取混元配置
            self.hunyuan_config = Config.get_hunyuan_config()
            self.api_key = self.hunyuan_config["api_key"]
            self.secret_key = self.hunyuan_config["secret_key"]
        except Exception as e:
            logger.warning(f"初始化混元配置失败: {str(e)}，将使用测试密钥")
            self.api_key = "test_api_key"
            self.secret_key = "test_secret_key"
        
        # 定义kubectl命令类别和常用操作
        self.kubectl_categories = {
            "资源查看": [
                "get pods", "get deployments", "get services", "get nodes", 
                "get namespaces", "get configmaps", "get secrets", "get ingress",
                "get pv", "get pvc", "get events", "get all"
            ],
            "资源详情": [
                "describe pod", "describe deployment", "describe service", 
                "describe node", "describe namespace", "describe ingress"
            ],
            "日志查看": [
                "logs", "logs -f", "logs --tail=100", "logs --since=1h"
            ],
            "资源操作": [
                "apply -f", "delete", "create", "edit", "patch", "scale"
            ],
            "集群管理": [
                "cluster-info", "top nodes", "top pods", "version", "api-resources"
            ],
            "调试工具": [
                "exec -it", "port-forward", "proxy", "cp"
            ]
        }
        
        # 初始化 OpenAI 客户端（如果可用）
        if HAS_OPENAI:
            try:
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url="https://api.hunyuan.cloud.tencent.com/v1"
                )
            except Exception as e:
                logger.error(f"初始化OpenAI客户端失败: {str(e)}")
                self.client = None
        else:
            self.client = None
            logger.warning("OpenAI客户端未初始化，LLM功能将不可用")

    async def analyze_query(self, query: str, context: Dict[str, Any] = None) -> Dict:
        """
        分析用户查询并生成kubectl命令和输出格式建议
        
        Args:
            query: 用户查询
            context: 上下文信息
            
        Returns:
            Dict: 包含命令、参数和格式化建议的分析结果
        """
        try:
            # 检查客户端是否可用
            if not HAS_OPENAI or not self.client:
                logger.warning("LLM客户端不可用，返回手动响应")
                return {
                    "success": True,
                    "tool_name": "kubectl_command",
                    "parameters": {
                        "command": "kubectl get pods --all-namespaces -o wide",
                        "output_format": "table"
                    },
                    "analysis": "LLM服务不可用，返回默认命令"
                }
                
            # 构造系统提示词
            system_prompt = f"""你是一个Kubernetes专家AI助手。你需要分析用户的查询，并返回结构化的JSON响应。

你的任务是：
1. 理解用户的Kubernetes相关问题
2. 生成合适的kubectl命令（可以包含shell语法）
3. 建议最佳的输出格式（table表格 或 text文本）
4. 提供简要的分析说明

可用的kubectl命令类别：
{json.dumps(self.kubectl_categories, ensure_ascii=False, indent=2)}

输出格式选择：
- "table": 适合列表数据，如pods、services、deployments等
- "text": 适合详细信息，如describe、logs、配置文件等

重要规则：
1. **准确识别用户意图**：如果用户明确说"删除"、"移除"等，必须生成删除命令，不要改成查看命令
2. **支持shell语法**：可以使用管道（|）、xargs、grep等shell命令来实现复杂操作
3. 对于批量操作，优先使用shell语法组合命令，如：`get ns -o name | grep '^namespace/a' | xargs kubectl delete`
4. 每个命令都应该是可执行的，不要只给建议
5. **删除操作特殊处理**：对于删除操作，自动添加验证步骤来确认删除结果

返回的JSON必须严格按照以下格式：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "实际的kubectl命令（不包含kubectl前缀，可以包含shell语法）",
        "output_format": "table 或 text",
        "namespace": "可选，如果命令涉及特定命名空间",
        "explanation": "命令的简要说明",
        "steps": ["可选，如果是多步操作，列出所有步骤"]
    }},
    "analysis": "对用户问题的分析和解决方案"
}}

示例1 - 简单查询：
用户问："查看所有Pod的状态"
返回：
{{
    "tool_name": "kubectl_command", 
    "parameters": {{
        "command": "kubectl get pods --all-namespaces -o wide",
        "output_format": "table",
        "explanation": "获取所有命名空间中Pod的详细状态信息"
    }},
    "analysis": "用户想查看集群中所有Pod的运行状态，使用get pods命令并显示详细信息"
}}

示例2 - 批量删除操作（使用shell语法）：
用户问："依次删除所有a开头的namespace"
返回：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "kubectl get namespace -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete namespace",
        "output_format": "text",
        "explanation": "批量删除所有以'a'开头的命名空间",
        "steps": [
            "kubectl get namespace -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete namespace",
            "kubectl get namespace | grep '^a'"
        ]
    }},
    "analysis": "用户需要批量删除所有以'a'开头的命名空间，使用shell管道命令获取符合条件的命名空间并批量删除，最后验证删除结果。"
}}

示例3 - 复杂操作（分步执行）：
用户问："创建一个名为test的namespace并在其中创建一个nginx pod"
返回：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "kubectl create namespace test",
        "output_format": "text",
        "explanation": "第一步：创建名为test的命名空间",
        "steps": [
            "kubectl create namespace test",
            "kubectl create deployment nginx-deployment --image=nginx:latest --namespace=test"
        ]
    }},
    "analysis": "用户需要执行两步操作：1) 创建命名空间 2) 在该命名空间中创建nginx部署。建议分步执行以确保每步都成功。"
}}

重要提醒：
- 只返回JSON，不要包含任何其他文字
- 命令中必须包含"kubectl"前缀
- **准确识别删除意图**：如果用户说"删除"、"移除"等，必须生成删除命令
- **支持shell语法**：可以使用管道、grep、xargs等来实现复杂操作
- 如果是危险操作，在explanation中给出警告
- 删除操作自动添加验证步骤"""
            
            # 构造请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"用户查询: {query}"}
            ]
            
            # 发送请求
            completion = self.client.chat.completions.create(
                model="hunyuan-turbos-latest",
                messages=messages,
                extra_body={
                    "enable_enhancement": True
                }
            )
            
            logger.info(f"混元API原始响应: {completion.model_dump_json()}")
            
            # 解析响应
            try:
                content = completion.choices[0].message.content.strip()
                
                # 尝试从内容中提取JSON结构
                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group(1)
                        analysis = json.loads(extracted_json)
                        return {
                            "success": True,
                            "tool_name": analysis.get("tool_name", "kubectl_command"),
                            "parameters": analysis.get("parameters", {}),
                            "analysis": analysis.get("analysis", "")
                        }
                    except Exception as e:
                        logger.warning(f"解析JSON块失败: {str(e)}")
                
                # 尝试直接解析为JSON对象
                try:
                    analysis = json.loads(content)
                    return {
                        "success": True,
                        "tool_name": analysis.get("tool_name", "kubectl_command"),
                        "parameters": analysis.get("parameters", {}),
                        "analysis": analysis.get("analysis", "")
                    }
                except Exception as e:
                    logger.warning(f"直接解析JSON失败: {str(e)}")
                    
                    # 智能解析fallback - 尝试从文本中提取kubectl命令
                    kubectl_patterns = [
                        r'kubectl\s+(.+?)(?:\n|$)',
                        r'`kubectl\s+(.+?)`',
                        r'"kubectl\s+(.+?)"',
                        r'命令[：:]\s*kubectl\s+(.+?)(?:\n|$)',
                        r'执行[：:]\s*kubectl\s+(.+?)(?:\n|$)'
                    ]
                    
                    for pattern in kubectl_patterns:
                        match = re.search(pattern, content, re.IGNORECASE)
                        if match:
                            command = match.group(1).strip()
                            # 判断输出格式
                            output_format = "table" if any(cmd in command.lower() for cmd in ["get", "list"]) else "text"
                            
                            return {
                                "success": True,
                                "tool_name": "kubectl_command",
                                "parameters": {
                                    "command": command,
                                    "output_format": output_format,
                                    "explanation": f"从AI响应中提取的kubectl命令: {command}"
                                },
                                "analysis": content[:200] + "..." if len(content) > 200 else content
                            }
                    
                    # 最后的fallback - 基于关键词推测命令
                    return self._generate_fallback_command(query, content)
                    
            except Exception as e:
                logger.error(f"解析响应失败: {str(e)}, 原始内容: {content}")
                return self._generate_fallback_command(query, str(e))
                
        except Exception as e:
            logger.error(f"分析查询失败: {str(e)}\n{traceback.format_exc()}")
            return self._generate_fallback_command(query, str(e))
    
    def _generate_fallback_command(self, query: str, error_info: str = "") -> Dict:
        """
        基于查询关键词生成fallback命令
        
        Args:
            query: 用户查询
            error_info: 错误信息
            
        Returns:
            Dict: fallback命令响应
        """
        query_lower = query.lower()
        
        # 首先检查是否是删除操作
        delete_keywords = ["删除", "移除", "清除", "delete", "remove", "清理"]
        is_delete_operation = any(keyword in query_lower for keyword in delete_keywords)
        
        if is_delete_operation:
            # 删除操作的特殊处理
            if "namespace" in query_lower or "命名空间" in query_lower:
                if "a开头" in query_lower or "a开始" in query_lower:
                    # 删除a开头的namespace
                    return {
                        "success": True,
                        "tool_name": "kubectl_command",
                        "parameters": {
                            "command": "kubectl get namespace -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete namespace",
                            "output_format": "text",
                            "explanation": "批量删除所有以'a'开头的命名空间",
                            "steps": [
                                "kubectl get namespace -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete namespace",
                                "kubectl get namespace | grep '^a'"
                            ]
                        },
                        "analysis": "用户需要批量删除所有以'a'开头的命名空间，使用shell管道命令获取符合条件的命名空间并批量删除，最后验证删除结果"
                    }
                else:
                    return {
                        "success": True,
                        "tool_name": "kubectl_command",
                        "parameters": {
                            "command": "kubectl delete namespace",
                            "output_format": "text",
                            "explanation": "删除命名空间（需要指定具体的命名空间名称）"
                        },
                        "analysis": "用户想要删除命名空间，但需要指定具体的命名空间名称"
                    }
            elif "pod" in query_lower:
                return {
                    "success": True,
                    "tool_name": "kubectl_command",
                    "parameters": {
                        "command": "kubectl delete pod --all --all-namespaces",
                        "output_format": "text",
                        "explanation": "删除所有Pod"
                    },
                    "analysis": "用户想要删除Pod"
                }
            else:
                return {
                    "success": True,
                    "tool_name": "kubectl_command",
                    "parameters": {
                        "command": "kubectl get all --all-namespaces",
                        "output_format": "table",
                        "explanation": "先查看所有资源，然后确定要删除的具体资源"
                    },
                    "analysis": "用户想要删除资源，但需要先确定具体要删除什么"
                }
        
        # 非删除操作的关键词映射
        keyword_commands = {
            "pod": "kubectl get pods --all-namespaces -o wide",
            "deployment": "kubectl get deployments --all-namespaces",
            "service": "kubectl get services --all-namespaces",
            "node": "kubectl get nodes -o wide", 
            "namespace": "kubectl get namespace",
            "命名空间": "kubectl get namespace",
            "日志": "kubectl logs",
            "log": "kubectl logs",
            "describe": "kubectl describe",
            "详情": "kubectl describe",
            "状态": "kubectl get pods --all-namespaces",
            "集群": "kubectl cluster-info",
            "版本": "kubectl version",
            "事件": "kubectl get events --all-namespaces",
            "配置": "kubectl get configmaps --all-namespaces"
        }
        
        # 查找匹配的关键词
        for keyword, command in keyword_commands.items():
            if keyword in query_lower:
                output_format = "table" if command.startswith("kubectl") else "text"
                return {
                    "success": True,
                    "tool_name": "kubectl_command",
                    "parameters": {
                        "command": command,
                        "output_format": output_format,
                        "explanation": f"基于关键词'{keyword}'生成的命令"
                    },
                    "analysis": f"根据查询中的关键词'{keyword}'推测用户想要执行的操作"
                }
        
        # 默认命令
        return {
            "success": True,
            "tool_name": "kubectl_command",
            "parameters": {
                "command": "kubectl get pods --all-namespaces",
                "output_format": "table",
                "explanation": "默认命令：查看所有Pod状态"
            },
            "analysis": f"无法准确解析查询，返回默认命令。错误信息: {error_info[:100]}"
        }

    async def generate_smart_reply(self, query: str, command: str, output: str, formatted_result: Dict[str, Any]) -> str:
        """
        基于用户查询和命令执行结果生成智能回复
        
        Args:
            query: 用户原始查询
            command: 执行的kubectl命令
            output: 命令原始输出
            formatted_result: 格式化后的结果
            
        Returns:
            str: 智能回复内容
        """
        try:
            # 检查客户端是否可用
            if not HAS_OPENAI or not self.client:
                logger.warning("LLM客户端不可用，返回基础统计")
                return self._generate_basic_stats(query, output, formatted_result)
            
            # 构造智能回复的系统提示词
            system_prompt = """你是一个Kubernetes专家AI助手。用户提出了一个问题，系统执行了相应的kubectl命令（可能包含重试）并获得了结果。

你的任务是：
1. 分析用户的原始问题
2. 理解kubectl命令的执行结果
3. 针对用户的具体问题给出直接、准确的回答
4. 如果有重试过程，要特别说明重试的情况和最终结果
5. 提供有用的统计信息和洞察

回复要求：
- 直接回答用户的问题
- 提供具体的数字统计
- 如果有异常情况，要指出来
- 如果有重试过程，要说明重试的原因和结果
- 语言要简洁明了，专业但易懂
- 不要重复显示原始数据，专注于分析和回答

重试信息处理：
- 如果命令经过重试才成功，要说明这一点
- 解释为什么需要重试以及AI是如何修复问题的
- 强调最终的成功结果

删除操作特殊处理：
- 如果是删除操作，要特别关注删除的结果
- 如果删除目标不存在（NotFound错误），应该说明这实际上意味着删除操作达到了预期效果
- 区分"删除成功"和"删除目标已经不存在"两种情况
- 对于删除操作，要明确说明最终的状态

示例：
用户问："删除nginx命名空间"
如果返回"namespace not found"，你应该回答："✅ 删除操作达到预期效果。nginx命名空间不存在，说明删除目标已经不存在，删除操作的目的已经达到。"

用户问："创建一个namespace"
如果第一次失败但重试成功，你应该回答："✅ 成功创建了命名空间。虽然初次尝试遇到了一些问题，但AI自动分析错误并调整了命令，最终成功完成了创建操作。"
"""
            
            # 准备上下文信息
            context_info = f"""
用户问题: {query}
执行命令: {command}
命令输出: {output[:2000]}...  # 限制长度避免token过多
格式化结果类型: {formatted_result.get('type', 'unknown')}
"""
            
            if formatted_result.get('type') == 'table':
                context_info += f"""
表格数据行数: {formatted_result.get('total_rows', 0)}
表格列数: {len(formatted_result.get('headers', []))}
表头: {', '.join(formatted_result.get('headers', []))}
"""
            
            # 构造请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context_info}
            ]
            
            # 发送请求
            completion = self.client.chat.completions.create(
                model="hunyuan-turbos-latest",
                messages=messages,
                extra_body={
                    "enable_enhancement": True
                }
            )
            
            smart_reply = completion.choices[0].message.content.strip()
            logger.info(f"生成智能回复: {smart_reply[:100]}...")
            
            return smart_reply
            
        except Exception as e:
            logger.error(f"生成智能回复失败: {str(e)}")
            return self._generate_basic_stats(query, output, formatted_result)
    
    def _generate_basic_stats(self, query: str, output: str, formatted_result: Dict[str, Any]) -> str:
        """
        生成基础统计信息作为fallback
        
        Args:
            query: 用户查询
            output: 命令输出
            formatted_result: 格式化结果
            
        Returns:
            str: 基础统计回复
        """
        try:
            query_lower = query.lower()
            
            if formatted_result.get('type') == 'table':
                total_rows = formatted_result.get('total_rows', 0)
                headers = formatted_result.get('headers', [])
                
                if 'pod' in query_lower and '多少' in query_lower:
                    return f"根据查询结果，集群中总共有 {total_rows} 个Pod。"
                elif 'node' in query_lower or '节点' in query_lower:
                    return f"集群中总共有 {total_rows} 个节点。"
                elif 'service' in query_lower or '服务' in query_lower:
                    return f"集群中总共有 {total_rows} 个服务。"
                elif 'deployment' in query_lower:
                    return f"集群中总共有 {total_rows} 个Deployment。"
                else:
                    return f"查询结果包含 {total_rows} 条记录，共 {len(headers)} 个字段。"
            
            elif formatted_result.get('type') == 'text':
                line_count = formatted_result.get('line_count', 0)
                if 'describe' in query_lower:
                    return f"已获取详细信息，包含 {line_count} 行详细配置和状态信息。"
                elif 'log' in query_lower or '日志' in query_lower:
                    return f"已获取日志信息，共 {line_count} 行日志记录。"
                else:
                    return f"命令执行成功，返回了 {line_count} 行信息。"
            
            else:
                return "命令执行成功，请查看上方的详细结果。"
                
        except Exception as e:
            logger.error(f"生成基础统计失败: {str(e)}")
            return "命令执行成功，请查看详细结果。"

    async def analyze_error_and_retry(self, original_query: str, failed_command: str, error_message: str, step_number: int, execution_history: list) -> Dict:
        """
        分析命令执行错误并生成重试命令
        
        Args:
            original_query: 用户原始查询
            failed_command: 失败的命令
            error_message: 错误信息
            step_number: 步骤编号
            execution_history: 执行历史
            
        Returns:
            Dict: 重试分析结果
        """
        try:
            # 检查客户端是否可用
            if not HAS_OPENAI or not self.client:
                logger.warning("LLM客户端不可用，使用基础重试建议")
                return self._generate_basic_retry_suggestion(failed_command, error_message)
            
            # 构造错误分析的系统提示词
            system_prompt = """你是一个Kubernetes专家AI助手，专门负责分析kubectl命令执行错误并提供修复建议。

你的任务是：
1. 分析kubectl命令执行失败的原因
2. 根据错误信息判断是否可以通过修改命令来修复
3. 如果可以修复，生成一个新的kubectl命令（可以包含shell语法）
4. 提供修复的原因说明

常见错误类型和修复策略：
1. 资源已存在错误 (AlreadyExists) - 可以改用get命令查看或使用--dry-run
2. 权限不足错误 (Forbidden) - 检查RBAC权限，可能需要不同的命名空间
3. 资源不存在错误 (NotFound) - 检查资源名称、命名空间是否正确，可能需要先创建依赖资源
4. 语法错误 (Invalid) - 修正命令参数格式，可以使用shell语法来简化复杂操作
5. 网络连接错误 - 可能是临时问题，建议重试相同命令
6. 资源配额不足 - 可以尝试创建更小的资源或检查配额

**重要规则 - 删除操作特殊处理：**
- 如果原始命令是删除操作（delete），绝对不要改成查看操作（get、describe等）
- 删除操作失败时，应该：
  1. 如果是"资源不存在"错误，说明删除目标已经不存在，可以认为删除成功
  2. 如果是"命名空间不存在"错误，说明整个命名空间都不存在，删除目标自然也不存在
  3. 如果是权限问题，不要改变操作类型，而是标记为无法重试
  4. 如果是语法错误，修正语法但保持删除操作，可以使用shell语法来简化
- 删除操作的重试命令必须仍然是删除操作，不能改成其他操作类型

其他重要规则：
- 只返回JSON，不要包含任何其他文字
- **支持shell语法**：可以使用管道（|）、xargs、grep等来实现复杂操作
- 优先使用可执行的命令，不要只给建议
- 如果是权限问题，不要建议提升权限，而是建议使用允许的操作
- 对于复杂的批量操作，优先使用shell语法组合命令

返回的JSON必须严格按照以下格式：
{
    "success": true/false,
    "can_retry": true/false,
    "retry_command": "修复后的命令",
    "retry_reason": "为什么这样修复的原因",
    "error_analysis": "对错误的详细分析",
    "confidence": "high/medium/low - 修复成功的信心程度"
}

如果无法修复，返回：
{
    "success": false,
    "can_retry": false,
    "error": "无法修复的原因",
    "error_analysis": "对错误的详细分析"
}

示例1 - 命名空间不存在（创建依赖）：
错误: "namespaces \"test\" not found"
失败命令: "kubectl create deployment nginx --image=nginx --namespace=test"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "kubectl create namespace test",
    "retry_reason": "需要先创建命名空间test，然后再创建deployment",
    "error_analysis": "命名空间test不存在，需要先创建",
    "confidence": "high"
}

示例2 - 资源已存在：
错误: "namespaces \"default\" already exists"
失败命令: "kubectl create namespace default"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "kubectl get namespace default",
    "retry_reason": "命名空间已存在，改为查看现有命名空间",
    "error_analysis": "命名空间default已经存在",
    "confidence": "high"
}

示例3 - 批量删除语法错误（使用shell语法修复）：
错误: "error: there is no need to specify a resource type as a separate argument when passing arguments in resource/name form"
失败命令: "kubectl get namespaces -o name | grep '^namespace/a' | xargs kubectl delete"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "kubectl get namespace -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete namespace",
    "retry_reason": "修复shell管道命令的语法错误，使用cut命令提取命名空间名称，避免资源类型重复指定",
    "error_analysis": "原命令在xargs传递参数时出现资源类型重复指定的问题，使用cut命令提取纯命名空间名称可以解决",
    "confidence": "high"
}"""
            
            # 准备错误分析上下文
            context_info = f"""
用户原始查询: {original_query}
失败的命令: {failed_command}
错误信息: {error_message}
步骤编号: {step_number}
执行历史: {json.dumps(execution_history, ensure_ascii=False, indent=2)}
"""
            
            # 构造请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context_info}
            ]
            
            # 发送请求
            completion = self.client.chat.completions.create(
                model="hunyuan-turbos-latest",
                messages=messages,
                extra_body={
                    "enable_enhancement": True
                }
            )
            
            logger.info(f"错误分析API响应: {completion.model_dump_json()}")
            
            # 解析响应
            try:
                content = completion.choices[0].message.content.strip()
                
                # 尝试从内容中提取JSON结构
                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group(1)
                        analysis = json.loads(extracted_json)
                        
                        return analysis
                    except Exception as e:
                        logger.warning(f"解析JSON块失败: {str(e)}")
                
                # 尝试直接解析为JSON对象
                try:
                    analysis = json.loads(content)
                    return analysis
                except Exception as e:
                    logger.warning(f"直接解析JSON失败: {str(e)}")
                    
                    # 如果解析失败，返回基础的重试建议
                    return self._generate_basic_retry_suggestion(failed_command, error_message)
                    
            except Exception as e:
                logger.error(f"解析错误分析响应失败: {str(e)}")
                return self._generate_basic_retry_suggestion(failed_command, error_message)
                
        except Exception as e:
            logger.error(f"错误分析失败: {str(e)}")
            return {
                "success": False,
                "error": f"错误分析失败: {str(e)}"
            }
    
    def _generate_basic_retry_suggestion(self, failed_command: str, error_message: str) -> Dict:
        """
        生成基础的重试建议（fallback方法）
        
        Args:
            failed_command: 失败的命令
            error_message: 错误信息
            
        Returns:
            Dict: 基础重试建议
        """
        error_lower = error_message.lower()
        command_lower = failed_command.lower()
        
        # 特殊处理删除操作
        if 'delete' in command_lower:
            # 删除操作遇到"资源不存在"错误，应该认为删除成功
            if 'not found' in error_lower or 'notfound' in error_lower:
                return {
                    "success": False,
                    "can_retry": False,
                    "error": "删除目标不存在，删除操作的目的已经达到",
                    "error_analysis": "要删除的资源不存在，说明删除目标已经不存在，删除操作实际上已经成功"
                }
            
            # 删除操作遇到语法错误，尝试修复语法但保持删除操作
            if 'setting \'all\' parameter but found a non empty selector' in error_message:
                # 修复 --all 和 --selector 冲突的问题
                if '--all' in failed_command and '--selector' in failed_command:
                    retry_command = failed_command.replace('--all', '').strip()
                    # 清理多余的空格
                    retry_command = ' '.join(retry_command.split())
                    return {
                        "success": True,
                        "can_retry": True,
                        "retry_command": retry_command,
                        "retry_reason": "删除命令不能同时使用--all和--selector参数，移除--all参数",
                        "error_analysis": "kubectl delete命令语法错误，--all和--selector不能同时使用",
                        "confidence": "high"
                    }
            
            # 删除操作遇到权限错误，不改变操作类型
            if 'forbidden' in error_lower or 'unauthorized' in error_lower:
                return {
                    "success": False,
                    "can_retry": False,
                    "error": "权限不足，无法执行删除操作",
                    "error_analysis": "当前用户没有执行删除操作的权限"
                }
        
        # 非删除操作的处理逻辑
        
        # 资源已存在错误
        if 'already exists' in error_lower or 'alreadyexists' in error_lower:
            if 'create' in command_lower:
                # 将create改为get来查看现有资源
                retry_command = failed_command.replace('create', 'get', 1)
                return {
                    "success": True,
                    "can_retry": True,
                    "retry_command": retry_command,
                    "retry_reason": "资源已存在，改为查看现有资源",
                    "error_analysis": "尝试创建的资源已经存在",
                    "confidence": "high"
                }
        
        # 命名空间不存在错误 - 重要修复
        if 'not found' in error_lower and 'namespace' in error_lower:
            # 从错误信息中提取命名空间名称
            import re
            namespace_match = re.search(r'namespaces?\s+["\']([^"\']+)["\']?\s+not found', error_message, re.IGNORECASE)
            if namespace_match:
                namespace_name = namespace_match.group(1)
                return {
                    "success": True,
                    "can_retry": True,
                    "retry_command": f"kubectl create namespace {namespace_name}",
                    "retry_reason": f"需要先创建命名空间 {namespace_name}",
                    "error_analysis": f"命名空间 {namespace_name} 不存在，需要先创建",
                    "confidence": "high"
                }
        
        # 其他资源不存在错误
        if 'not found' in error_lower or 'notfound' in error_lower:
            return {
                "success": False,
                "can_retry": False,
                "error": "资源不存在，需要检查资源名称或先创建依赖资源",
                "error_analysis": "指定的资源不存在"
            }
        
        # 权限错误
        if 'forbidden' in error_lower or 'unauthorized' in error_lower:
            return {
                "success": False,
                "can_retry": False,
                "error": "权限不足，无法执行此操作",
                "error_analysis": "当前用户没有执行此操作的权限"
            }
        
        # 网络或临时错误
        if any(keyword in error_lower for keyword in ['timeout', 'connection', 'network', 'temporary']):
            return {
                "success": True,
                "can_retry": True,
                "retry_command": failed_command,  # 重试相同命令
                "retry_reason": "可能是临时网络问题，重试相同命令",
                "error_analysis": "检测到网络或临时性错误",
                "confidence": "medium"
            }
        
        # 默认情况：无法确定如何修复
        return {
            "success": False,
            "can_retry": False,
            "error": "无法自动修复此错误",
            "error_analysis": f"未知错误类型: {error_message[:100]}"
        }
    
    async def generate_smart_reply_with_retry_info(self, query: str, command: str, output: str, formatted_result: Dict[str, Any]) -> str:
        """
        基于用户查询和命令执行结果生成包含重试信息的智能回复
        
        Args:
            query: 用户原始查询
            command: 执行的kubectl命令
            output: 命令原始输出
            formatted_result: 格式化后的结果（包含重试信息）
            
        Returns:
            str: 智能回复内容
        """
        try:
            # 检查客户端是否可用
            if not HAS_OPENAI or not self.client:
                logger.warning("LLM客户端不可用，返回基础统计")
                return self._generate_basic_stats_with_retry(query, output, formatted_result)
            
            # 构造智能回复的系统提示词
            system_prompt = """你是一个Kubernetes专家AI助手。用户提出了一个问题，系统执行了相应的kubectl命令（可能包含重试）并获得了结果。

你的任务是：
1. 分析用户的原始问题
2. 理解kubectl命令的执行结果
3. 针对用户的具体问题给出直接、准确的回答
4. 如果有重试过程，要特别说明重试的情况和最终结果
5. 提供有用的统计信息和洞察

回复要求：
- 直接回答用户的问题
- 提供具体的数字统计
- 如果有异常情况，要指出来
- 如果有重试过程，要说明重试的原因和结果
- 语言要简洁明了，专业但易懂
- 不要重复显示原始数据，专注于分析和回答

重试信息处理：
- 如果命令经过重试才成功，要说明这一点
- 解释为什么需要重试以及AI是如何修复问题的
- 强调最终的成功结果

删除操作特殊处理：
- 如果是删除操作，要特别关注删除的结果
- 如果删除目标不存在（NotFound错误），应该说明这实际上意味着删除操作达到了预期效果
- 区分"删除成功"和"删除目标已经不存在"两种情况
- 对于删除操作，要明确说明最终的状态

示例：
用户问："删除nginx命名空间"
如果返回"namespace not found"，你应该回答："✅ 删除操作达到预期效果。nginx命名空间不存在，说明删除目标已经不存在，删除操作的目的已经达到。"

用户问："创建一个namespace"
如果第一次失败但重试成功，你应该回答："✅ 成功创建了命名空间。虽然初次尝试遇到了一些问题，但AI自动分析错误并调整了命令，最终成功完成了创建操作。"
"""
            
            # 准备上下文信息
            steps = formatted_result.get("steps", [])
            retry_info = ""
            
            if steps:
                total_retries = sum(step.get("retry_count", 0) for step in steps)
                if total_retries > 0:
                    retry_info = f"执行过程中进行了 {total_retries} 次智能重试。"
            
            context_info = f"""
用户问题: {query}
执行命令: {command}
命令输出: {output[:2000]}...  # 限制长度避免token过多
格式化结果类型: {formatted_result.get('type', 'unknown')}
重试信息: {retry_info}
"""
            
            if formatted_result.get('type') == 'multi_step':
                context_info += f"""
总步骤数: {formatted_result.get('total_steps', 0)}
成功步骤数: {len([s for s in steps if s.get('success', False)])}
失败步骤数: {len([s for s in steps if not s.get('success', True)])}
"""
            
            # 构造请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context_info}
            ]
            
            # 发送请求
            completion = self.client.chat.completions.create(
                model="hunyuan-turbos-latest",
                messages=messages,
                extra_body={
                    "enable_enhancement": True
                }
            )
            
            smart_reply = completion.choices[0].message.content.strip()
            logger.info(f"生成带重试信息的智能回复: {smart_reply[:100]}...")
            
            return smart_reply
            
        except Exception as e:
            logger.error(f"生成带重试信息的智能回复失败: {str(e)}")
            return self._generate_basic_stats_with_retry(query, output, formatted_result)
    
    def _generate_basic_stats_with_retry(self, query: str, output: str, formatted_result: Dict[str, Any]) -> str:
        """
        生成包含重试信息的基础统计信息作为fallback
        
        Args:
            query: 用户查询
            output: 命令输出
            formatted_result: 格式化结果
            
        Returns:
            str: 基础统计回复
        """
        try:
            query_lower = query.lower()
            
            # 计算重试信息
            retry_info = ""
            if formatted_result.get('type') == 'multi_step':
                steps = formatted_result.get("steps", [])
                total_retries = sum(step.get("retry_count", 0) for step in steps)
                if total_retries > 0:
                    retry_info = f"（经过 {total_retries} 次智能重试）"
            
            if formatted_result.get('type') == 'table':
                total_rows = formatted_result.get('total_rows', 0)
                headers = formatted_result.get('headers', [])
                
                if 'pod' in query_lower and '多少' in query_lower:
                    return f"根据查询结果，集群中总共有 {total_rows} 个Pod{retry_info}。"
                elif 'node' in query_lower or '节点' in query_lower:
                    return f"集群中总共有 {total_rows} 个节点{retry_info}。"
                elif 'service' in query_lower or '服务' in query_lower:
                    return f"集群中总共有 {total_rows} 个服务{retry_info}。"
                elif 'deployment' in query_lower:
                    return f"集群中总共有 {total_rows} 个Deployment{retry_info}。"
                else:
                    return f"查询结果包含 {total_rows} 条记录，共 {len(headers)} 个字段{retry_info}。"
            
            elif formatted_result.get('type') == 'text':
                line_count = formatted_result.get('line_count', 0)
                if 'describe' in query_lower:
                    return f"已获取详细信息，包含 {line_count} 行详细配置和状态信息{retry_info}。"
                elif 'log' in query_lower or '日志' in query_lower:
                    return f"已获取日志信息，共 {line_count} 行日志记录{retry_info}。"
                else:
                    return f"命令执行成功，返回了 {line_count} 行信息{retry_info}。"
            
            elif formatted_result.get('type') == 'multi_step':
                steps = formatted_result.get("steps", [])
                success_count = len([s for s in steps if s.get('success', False)])
                total_count = len(steps)
                
                if success_count == total_count:
                    return f"✅ 成功完成所有 {total_count} 个步骤{retry_info}。"
                else:
                    return f"⚠️ 完成了 {total_count} 个步骤中的 {success_count} 个{retry_info}。"
            
            else:
                return f"命令执行成功{retry_info}，请查看详细结果。"
                
        except Exception as e:
            logger.error(f"生成带重试信息的基础统计失败: {str(e)}")
            return "命令执行完成，请查看详细结果。"

# 保持向后兼容
HunyuanClient = SuperKubectlAgent 