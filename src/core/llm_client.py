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
                        "command": "get pods --all-namespaces",
                        "output_format": "table"
                    },
                    "analysis": "LLM服务不可用，返回默认命令"
                }
                
            # 构造系统提示词
            system_prompt = f"""你是一个Kubernetes专家AI助手。你需要分析用户的查询，并返回结构化的JSON响应。

你的任务是：
1. 理解用户的Kubernetes相关问题
2. 生成合适的完整命令（包括kubectl前缀，也可以是纯shell命令）
3. 建议最佳的输出格式（table表格 或 text文本）
4. 提供简要的分析说明

可用的kubectl命令类别：
{json.dumps(self.kubectl_categories, ensure_ascii=False, indent=2)}

输出格式选择：
- "table": 适合列表数据，如pods、services、deployments等
- "text": 适合详细信息，如describe、logs、配置文件等

重要规则：
1. **准确识别用户意图**：如果用户明确说"删除"、"移除"等，必须生成删除命令，不要改成查看命令
2. **生成完整命令**：必须包含完整的命令前缀（如kubectl、ls、cat等），不要省略
3. **支持shell语法**：可以使用管道（|）、xargs、grep等shell命令来实现复杂操作
4. 对于批量操作，优先使用shell语法组合命令，如：`kubectl get ns -o name | grep '^namespace/a' | xargs kubectl delete`
5. 每个命令都应该是可执行的，不要只给建议
6. **删除操作特殊处理**：对于删除操作，自动添加验证步骤来确认删除结果

返回的JSON必须严格按照以下格式：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "完整的命令（包含kubectl前缀或其他命令前缀，可以包含shell语法）",
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
    "analysis": "用户想查看集群中所有Pod的运行状态，使用kubectl get pods命令并显示详细信息"
}}

示例2 - 批量删除操作（使用shell语法）：
用户问："依次删除所有a开头的namespace"
返回：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "kubectl get ns -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete ns",
        "output_format": "text",
        "explanation": "批量删除所有以'a'开头的命名空间",
        "steps": [
            "kubectl get ns -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete ns",
            "kubectl get ns | grep '^a'"
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

示例4 - 纯shell命令：
用户问："查看当前目录下的所有文件"
返回：
{{
    "tool_name": "kubectl_command",
    "parameters": {{
        "command": "ls -la",
        "output_format": "text",
        "explanation": "列出当前目录下的所有文件和详细信息"
    }},
    "analysis": "用户需要查看文件系统信息，使用ls命令显示详细的文件列表"
}}

重要提醒：
- 只返回JSON，不要包含任何其他文字
- **必须包含完整的命令前缀**（kubectl、ls、cat等）
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
                            command = f"kubectl {match.group(1).strip()}"  # 确保包含kubectl前缀
                            # 判断输出格式
                            output_format = "table" if any(cmd in command.lower() for cmd in ["get", "list"]) else "text"
                            
                            return {
                                "success": True,
                                "tool_name": "kubectl_command",
                                "parameters": {
                                    "command": command,
                                    "output_format": output_format,
                                    "explanation": f"从AI响应中提取的完整命令: {command}"
                                },
                                "analysis": content[:200] + "..." if len(content) > 200 else content
                            }
                    
                    # 尝试提取其他shell命令
                    shell_patterns = [
                        r'`([^`]+)`',
                        r'"([^"]+)"',
                        r'命令[：:]\s*([^\n]+)',
                        r'执行[：:]\s*([^\n]+)'
                    ]
                    
                    for pattern in shell_patterns:
                        match = re.search(pattern, content)
                        if match:
                            command = match.group(1).strip()
                            # 确保命令看起来合理
                            if len(command.split()) >= 1 and not command.startswith('http'):
                                output_format = "table" if any(cmd in command.lower() for cmd in ["get", "list", "ls"]) else "text"
                                
                                return {
                                    "success": True,
                                    "tool_name": "kubectl_command",
                                    "parameters": {
                                        "command": command,
                                        "output_format": output_format,
                                        "explanation": f"从AI响应中提取的完整命令: {command}"
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
                            "command": "kubectl get ns -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete ns",
                            "output_format": "text",
                            "explanation": "批量删除所有以'a'开头的命名空间",
                            "steps": [
                                "kubectl get ns -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete ns",
                                "kubectl get ns | grep '^a'"
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
            "namespace": "kubectl get namespaces",
            "命名空间": "kubectl get namespaces",
            "日志": "kubectl logs",
            "log": "kubectl logs",
            "describe": "kubectl describe",
            "详情": "kubectl describe",
            "状态": "kubectl get pods --all-namespaces",
            "集群": "kubectl cluster-info",
            "版本": "kubectl version",
            "事件": "kubectl get events --all-namespaces",
            "配置": "kubectl get configmaps --all-namespaces",
            "文件": "ls -la",
            "目录": "ls -la",
            "当前目录": "pwd",
            "磁盘": "df -h",
            "内存": "free -h",
            "进程": "ps aux"
        }
        
        # 查找匹配的关键词
        for keyword, command in keyword_commands.items():
            if keyword in query_lower:
                output_format = "table" if command.startswith("get") else "text"
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
                "command": "get pods --all-namespaces",
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
- retry_command中不要包含"kubectl"前缀
- **支持shell语法**：可以使用管道（|）、xargs、grep等来实现复杂操作
- 优先使用可执行的命令，不要只给建议
- 如果是权限问题，不要建议提升权限，而是建议使用允许的操作
- 对于复杂的批量操作，优先使用shell语法组合命令

返回的JSON必须严格按照以下格式：
{
    "success": true/false,
    "can_retry": true/false,
    "retry_command": "修复后的完整命令（包含kubectl前缀或其他命令前缀，可以包含shell语法）",
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
失败命令: "create deployment nginx --image=nginx --namespace=test"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "create namespace test",
    "retry_reason": "需要先创建命名空间test，然后再创建deployment",
    "error_analysis": "命名空间test不存在，需要先创建",
    "confidence": "high"
}

示例2 - 资源已存在：
错误: "namespaces \"default\" already exists"
失败命令: "create namespace default"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "get namespace default",
    "retry_reason": "命名空间已存在，改为查看现有命名空间",
    "error_analysis": "命名空间default已经存在",
    "confidence": "high"
}

示例3 - 批量删除语法错误（使用shell语法修复）：
错误: "error: there is no need to specify a resource type as a separate argument when passing arguments in resource/name form"
失败命令: "get namespaces -o name | grep '^namespace/a' | xargs kubectl delete"
正确返回:
{
    "success": true,
    "can_retry": true,
    "retry_command": "kubectl get ns -o name | grep '^namespace/a' | cut -d'/' -f2 | xargs kubectl delete ns",
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
                    # 确保包含完整前缀
                    if not retry_command.startswith('kubectl'):
                        retry_command = f"kubectl {retry_command}"
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
                # 确保包含完整前缀
                if not retry_command.startswith('kubectl'):
                    retry_command = f"kubectl {retry_command}"
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
            # 确保包含完整前缀
            retry_command = failed_command
            if not retry_command.startswith(('kubectl', 'ls', 'cat', 'echo', 'ps', 'df', 'free')):
                retry_command = f"kubectl {retry_command}"
            return {
                "success": True,
                "can_retry": True,
                "retry_command": retry_command,
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

    async def analyze_shell_query(self, query: str, context: Dict[str, Any] = None) -> Dict:
        """
        分析用户的自然语言查询并生成Shell命令
        
        Args:
            query: 用户查询
            context: 上下文信息
            
        Returns:
            Dict: 包含生成的Shell命令和分析结果
        """
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                # 检查客户端是否可用
                if not HAS_OPENAI or not self.client:
                    logger.warning("LLM客户端不可用，返回手动响应")
                    return self._generate_fallback_shell_command(query)
                    
                # 构造专门的Shell命令生成提示词
                system_prompt = f"""你是一个Linux Shell专家AI助手。你必须严格按照要求返回纯JSON格式的响应，且JSON中需要包含可直接执行的 Shell 命令字段。

**绝对禁止的行为：**
1. 不要返回任何解释文字、说明或注释
2. 不要使用markdown格式（如```json```）
3. 不要添加任何前缀或后缀文字
4. 不要返回除JSON对象以外的任何内容

**你只能返回一个有效的JSON对象，示例格式：**
{{
    "success": true,
    "task_analysis": "对整个任务的简要分析",
    "total_steps": 步骤总数,
    "current_step": 1,
    "steps": [
        {{
            "step_number": 1,
            "command": "具体的shell命令",
            "purpose": "这一步的目的",
            "expected_result": "预期的执行结果",
            "verification": "如何验证这一步是否成功"
        }}
    ],
    "execution_strategy": "sequential",
    "can_execute": true
}}

**命令生成规则：**
1. 对于文件创建，使用cat命令和heredoc语法：cat > filename << 'EOF'
2. 对于C++文件，生成完整的可编译代码
3. 对于编译需求，添加g++编译步骤
4. 每个步骤只包含一个具体的shell命令
5. 命令必须是可直接执行的

**示例输入：** "创建一个名为test的文件夹并在其中创建hello.cpp文件"
**你必须返回的格式：**
{{
    "success": true,
    "task_analysis": "创建目录test，在其中创建C++文件hello.cpp",
    "total_steps": 3,
    "current_step": 1,
    "steps": [
        {{
            "step_number": 1,
            "command": "mkdir -p test",
            "purpose": "创建目录test",
            "expected_result": "成功创建目录test",
            "verification": "目录test存在"
        }},
        {{
            "step_number": 2,
            "command": "cat > test/hello.cpp << 'EOF'\\n#include <iostream>\\nint main() {{\\n    std::cout << \\"Hello World!\\" << std::endl;\\n    return 0;\\n}}\\nEOF",
            "purpose": "创建C++文件hello.cpp",
            "expected_result": "文件test/hello.cpp被创建",
            "verification": "文件存在且包含C++代码"
        }},
        {{
            "step_number": 3,
            "command": "ls -la test/",
            "purpose": "验证文件创建结果",
            "expected_result": "显示test目录中的hello.cpp文件",
            "verification": "能看到创建的文件"
        }}
    ],
    "execution_strategy": "sequential",
    "can_execute": true
}}

**重要提醒：只返回JSON对象，不要包含任何其他内容！**"""
                
                # 构造请求
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"用户查询: {query}"}
                ]
                
                # 如果有上下文，添加到消息中
                if context:
                    context_str = f"上下文信息: {json.dumps(context, ensure_ascii=False)}"
                    messages.append({"role": "user", "content": context_str})
                
                # 如果是重试，添加错误信息
                if attempt > 0:
                    retry_msg = f"""前一次尝试失败，请严格按照要求：
1. 只返回纯JSON对象，不要任何其他文字
2. 不要使用```json```标记
3. 不要添加解释或说明
4. 确保JSON格式完全正确
这是第{attempt + 1}次尝试，请务必返回有效的JSON格式。"""
                    messages.append({"role": "user", "content": retry_msg})
                
                # 调用LLM
                response = self.client.chat.completions.create(
                    model="hunyuan-lite",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
                
                # 解析响应
                content = response.choices[0].message.content.strip()
                logger.info(f"LLM Shell分析响应 (尝试 {attempt + 1}): {content[:200]}...")
                
                # 严格的JSON解析
                try:
                    # 首先尝试直接解析
                    result = json.loads(content)
                    
                    # 验证必要字段
                    if not isinstance(result, dict):
                        raise ValueError("响应不是有效的JSON对象")
                    
                    if not result.get("steps") or not isinstance(result["steps"], list):
                        raise ValueError("缺少steps字段或格式不正确")
                    
                    if not result.get("success"):
                        result["success"] = True
                    
                    # 转换为前端期望的格式
                    formatted_result = {
                        "success": result["success"],
                        "ai_analysis": result.get("task_analysis", "AI生成的分步执行计划"),
                        "execution_type": "step_by_step",
                        "total_steps": result.get("total_steps", len(result.get("steps", []))),
                        "current_step": result.get("current_step", 1),
                        "steps": result.get("steps", []),
                        "execution_strategy": result.get("execution_strategy", "sequential"),
                        "can_execute": result.get("can_execute", True),
                        "safety_check": {
                            "is_safe": True,
                            "warning": ""
                        },
                        "recommendations": [
                            "任务将分步执行，每步完成后会验证结果",
                            "如果某步失败，AI会根据错误信息调整后续步骤"
                        ]
                    }
                    
                    logger.info(f"成功解析JSON响应 (尝试 {attempt + 1})")
                    return formatted_result
                    
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON解析失败 (尝试 {attempt + 1}): {str(e)}")
                    
                    # 尝试清理响应内容
                    cleaned_content = content
                    
                    # 移除markdown代码块标记
                    cleaned_content = re.sub(r'```json\s*', '', cleaned_content)
                    cleaned_content = re.sub(r'```\s*$', '', cleaned_content)
                    cleaned_content = re.sub(r'```.*?\n', '', cleaned_content)
                    
                    # 移除前后的非JSON文本
                    json_start = cleaned_content.find('{')
                    json_end = cleaned_content.rfind('}')
                    
                    if json_start != -1 and json_end != -1 and json_end > json_start:
                        json_str = cleaned_content[json_start:json_end + 1]
                        try:
                            result = json.loads(json_str)
                            
                            # 验证并格式化
                            if isinstance(result, dict) and result.get("steps"):
                                formatted_result = {
                                    "success": result.get("success", True),
                                    "ai_analysis": result.get("task_analysis", "AI生成的分步执行计划"),
                                    "execution_type": "step_by_step",
                                    "total_steps": result.get("total_steps", len(result.get("steps", []))),
                                    "current_step": result.get("current_step", 1),
                                    "steps": result.get("steps", []),
                                    "execution_strategy": result.get("execution_strategy", "sequential"),
                                    "can_execute": result.get("can_execute", True),
                                    "safety_check": {"is_safe": True, "warning": ""},
                                    "recommendations": ["任务将分步执行"]
                                }
                                
                                logger.info(f"成功清理并解析JSON响应 (尝试 {attempt + 1})")
                                return formatted_result
                        except json.JSONDecodeError:
                            pass
                    
                    # 如果不是最后一次尝试，继续重试
                    if attempt < max_retries - 1:
                        logger.warning(f"尝试 {attempt + 1} 失败，准备重试...")
                        continue
                    else:
                        logger.error("所有尝试都失败，AI未返回有效JSON")
                        return {
                            "success": False,
                            "error": "AI未返回有效JSON结构，请重试或联系管理员",
                            "ai_analysis": f"JSON解析失败，共尝试{max_retries}次",
                            "can_execute": False
                        }
                
            except Exception as e:
                logger.error(f"Shell查询分析失败 (尝试 {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    continue
                else:
                    return {
                        "success": False,
                        "error": f"AI调用异常: {str(e)}",
                        "ai_analysis": str(e),
                        "can_execute": False
                    }
        
        # 理论上已在循环内返回，这里兜底
        return {
            "success": False,
            "error": "AI未能生成有效响应",
            "ai_analysis": "未知原因",
            "can_execute": False
        }

    def _generate_fallback_shell_command(self, query: str, error_info: str = "") -> Dict:
        """
        生成备用Shell命令响应（当LLM不可用时）
        
        Args:
            query: 用户查询
            error_info: 错误信息
            
        Returns:
            Dict: 备用响应
        """
        import re
        
        query_lower = query.lower()
        
        # 改进的关键词匹配和信息提取
        if ("创建" in query or "建立" in query) and ("目录" in query or "文件夹" in query):
            # 提取目录名 - 改进的正则表达式
            dir_patterns = [
                r'名为["\']?([A-Za-z0-9_\-]{2,})["\']?的.*(?:目录|文件夹)',
                r'(?:目录|文件夹)["\']?([A-Za-z0-9_\-]{2,})["\']?',
                r'创建.*["\']?([A-Za-z0-9_\-]{2,})["\']?.*(?:目录|文件夹)',
                r'一个["\']?([A-Za-z0-9_\-]{2,})["\']?(?:目录|文件夹)',
                r'叫["\']?([A-Za-z0-9_\-]{2,})["\']?的(?:目录|文件夹)'
            ]
            
            dir_name = "myproject"  # 默认目录名
            for pattern in dir_patterns:
                match = re.search(pattern, query)
                if match:
                    dir_name = match.group(1)
                    break
            
            # 检查是否需要创建文件
            if "文件" in query:
                # 提取文件名 - 改进的正则表达式
                file_patterns = [
                    r'名为["\']?([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?的.*文件',
                    r'文件["\']?([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?',
                    r'写入.*["\']?([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?',
                    r'创建.*["\']?([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?.*文件',
                    r'一个["\']?([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)["\']?文件'
                ]
                
                file_name = "main.cpp"  # 默认文件名
                for pattern in file_patterns:
                    match = re.search(pattern, query)
                    if match:
                        file_name = match.group(1)
                        break
                
                # 检查编程语言类型和游戏类型
                if "c++" in query_lower or "cpp" in query_lower:
                    if not file_name.endswith('.cpp'):
                        # 根据游戏类型确定文件名
                        if "石头剪刀布" in query or "剪刀石头布" in query:
                            file_name = "game.cpp"
                        else:
                            file_name = "main.cpp"
                    
                    # 根据游戏类型生成相应的C++代码
                    if "石头剪刀布" in query or "剪刀石头布" in query:
                        # 生成完整的石头剪刀布游戏代码
                        cpp_code = '''#include <iostream>
#include <ctime>
#include <cstdlib>
#include <string>

int main() {
    std::srand(std::time(0));
    int computer, user;
    std::string choice;

    std::cout << "=== 石头剪刀布游戏 ===" << std::endl;
    
    while (true) {
        std::cout << "请输入您的选择（石头/剪刀/布，输入q退出）：";
        std::cin >> choice;
        
        if (choice == "q" || choice == "Q") {
            std::cout << "谢谢游戏！再见！" << std::endl;
            break;
        }

        if (choice == "石头") {
            user = 1;
        } else if (choice == "剪刀") {
            user = 2;
        } else if (choice == "布") {
            user = 3;
        } else {
            std::cout << "无效的输入，请重新输入！" << std::endl;
            continue;
        }

        computer = std::rand() % 3 + 1;

        std::cout << "你选择了：" << choice << std::endl;
        std::cout << "电脑选择了：";
        if (computer == 1) {
            std::cout << "石头";
        } else if (computer == 2) {
            std::cout << "剪刀";
        } else {
            std::cout << "布";
        }
        std::cout << std::endl;

        if (user == computer) {
            std::cout << "平局！" << std::endl;
        } else if ((user == 1 && computer == 2) || (user == 2 && computer == 3) || (user == 3 && computer == 1)) {
            std::cout << "🎉 你赢了！" << std::endl;
        } else {
            std::cout << "💻 电脑赢了！" << std::endl;
        }
        
        std::cout << std::string(30, '-') << std::endl;
    }

    return 0;
}'''
                    else:
                        # 生成简单的Hello World程序
                        cpp_code = '''#include <iostream>

int main() {
    std::cout << "Hello, World!" << std::endl;
    return 0;
}'''
                    
                    # 检查是否需要编译
                    if "编译" in query or "二进制" in query or "可执行" in query:
                        # 确定可执行文件名
                        exe_name = "game" if "游戏" in query else "main"
                        
                        steps = [
                            {
                                "step_number": 1,
                                "command": f"mkdir -p {dir_name}",
                                "purpose": f"创建目录{dir_name}",
                                "expected_result": f"成功创建目录{dir_name}",
                                "verification": f"目录{dir_name}存在"
                            },
                            {
                                "step_number": 2,
                                "command": f"cat > {dir_name}/{file_name} << 'EOF'\\n{cpp_code}\\nEOF",
                                "purpose": f"创建C++文件{file_name}",
                                "expected_result": f"文件{dir_name}/{file_name}被创建并包含C++代码",
                                "verification": "文件存在且包含C++代码"
                            },
                            {
                                "step_number": 3,
                                "command": f"cd {dir_name} && g++ {file_name} -o {exe_name}",
                                "purpose": "编译C++文件为二进制可执行文件",
                                "expected_result": f"成功生成{exe_name}可执行文件",
                                "verification": f"{exe_name}文件存在且可执行"
                            },
                            {
                                "step_number": 4,
                                "command": f"ls -la {dir_name}/",
                                "purpose": "验证文件创建和编译结果",
                                "expected_result": f"显示{dir_name}目录中的{file_name}和{exe_name}文件",
                                "verification": "能看到源文件和编译后的可执行文件"
                            }
                        ]
                        
                        game_type = "石头剪刀布游戏" if "石头剪刀布" in query or "剪刀石头布" in query else "C++程序"
                        
                        return {
                            "success": True,
                            "ai_analysis": f"LLM服务不可用({error_info})，使用智能匹配：用户需要创建目录'{dir_name}'、{game_type}文件'{file_name}'并编译为二进制文件",
                            "execution_type": "step_by_step",
                            "total_steps": 4,
                            "current_step": 1,
                            "steps": steps,
                            "execution_strategy": "sequential",
                            "can_execute": True,
                            "safety_check": {"is_safe": True, "warning": ""},
                            "recommendations": [
                                f"任务将分步执行：创建目录 → 创建{game_type}文件 → 编译 → 验证",
                                f"编译完成后可以运行：cd {dir_name} && ./{exe_name}",
                                "如果编译失败，请确保系统已安装g++编译器"
                            ]
                        }
                    else:
                        # 只创建文件，不编译
                        steps = [
                            {
                                "step_number": 1,
                                "command": f"mkdir -p {dir_name}",
                                "purpose": f"创建目录{dir_name}",
                                "expected_result": f"成功创建目录{dir_name}",
                                "verification": f"目录{dir_name}存在"
                            },
                            {
                                "step_number": 2,
                                "command": f"cat > {dir_name}/{file_name} << 'EOF'\\n{cpp_code}\\nEOF",
                                "purpose": f"创建C++文件{file_name}",
                                "expected_result": f"文件{dir_name}/{file_name}被创建并包含C++代码",
                                "verification": "文件存在且包含C++代码"
                            },
                            {
                                "step_number": 3,
                                "command": f"ls -la {dir_name}/",
                                "purpose": "验证文件创建结果",
                                "expected_result": f"显示{dir_name}目录中的{file_name}文件",
                                "verification": "能看到创建的C++源文件"
                            }
                        ]
                        
                        game_type = "石头剪刀布游戏" if "石头剪刀布" in query or "剪刀石头布" in query else "C++程序"
                        
                        return {
                            "success": True,
                            "ai_analysis": f"LLM服务不可用({error_info})，使用智能匹配：用户需要创建目录'{dir_name}'和{game_type}文件'{file_name}'",
                            "execution_type": "step_by_step",
                            "total_steps": 3,
                            "current_step": 1,
                            "steps": steps,
                            "execution_strategy": "sequential",
                            "can_execute": True,
                            "safety_check": {"is_safe": True, "warning": ""},
                            "recommendations": [
                                f"任务将分步执行：创建目录 → 创建{game_type}文件 → 验证",
                                f"如需编译，可以运行：cd {dir_name} && g++ {file_name} -o game"
                            ]
                        }
                
                else:
                    # 非C++文件的处理
                    steps = [
                        {
                            "step_number": 1,
                            "command": f"mkdir -p {dir_name}",
                            "purpose": f"创建目录{dir_name}",
                            "expected_result": f"成功创建目录{dir_name}",
                            "verification": f"目录{dir_name}存在"
                        },
                        {
                            "step_number": 2,
                            "command": f"touch {dir_name}/{file_name}",
                            "purpose": f"创建文件{file_name}",
                            "expected_result": f"文件{dir_name}/{file_name}被创建",
                            "verification": "文件存在"
                        },
                        {
                            "step_number": 3,
                            "command": f"ls -la {dir_name}/",
                            "purpose": "验证文件创建结果",
                            "expected_result": f"显示{dir_name}目录中的{file_name}文件",
                            "verification": "能看到创建的文件"
                        }
                    ]
                    
                    return {
                        "success": True,
                        "ai_analysis": f"LLM服务不可用({error_info})，使用智能匹配：用户需要创建目录'{dir_name}'和文件'{file_name}'",
                        "execution_type": "step_by_step",
                        "total_steps": 3,
                        "current_step": 1,
                        "steps": steps,
                        "execution_strategy": "sequential",
                        "can_execute": True,
                        "safety_check": {"is_safe": True, "warning": ""},
                        "recommendations": [
                            "任务将分步执行：创建目录 → 创建文件 → 验证"
                        ]
                    }
            
            else:
                # 只创建目录
                steps = [
                    {
                        "step_number": 1,
                        "command": f"mkdir -p {dir_name}",
                        "purpose": f"创建目录{dir_name}",
                        "expected_result": f"成功创建目录{dir_name}",
                        "verification": f"目录{dir_name}存在"
                    },
                    {
                        "step_number": 2,
                        "command": f"ls -la {dir_name}/",
                        "purpose": "验证目录创建结果",
                        "expected_result": f"显示{dir_name}目录的内容",
                        "verification": "目录存在且可访问"
                    }
                ]
                
                return {
                    "success": True,
                    "ai_analysis": f"LLM服务不可用({error_info})，使用智能匹配：用户需要创建目录'{dir_name}'",
                    "execution_type": "step_by_step",
                    "total_steps": 2,
                    "current_step": 1,
                    "steps": steps,
                    "execution_strategy": "sequential",
                    "can_execute": True,
                    "safety_check": {"is_safe": True, "warning": ""},
                    "recommendations": [
                        "任务将分步执行：创建目录 → 验证"
                    ]
                }
        
        # 其他常见命令的处理
        common_commands = {
            "查看当前目录": ("pwd", "显示当前工作目录"),
            "列出文件": ("ls -la", "列出当前目录的所有文件和详细信息"),
            "查看磁盘空间": ("df -h", "显示磁盘使用情况"),
            "查看内存使用": ("free -h", "显示内存使用情况"),
            "查看系统信息": ("uname -a", "显示系统信息")
        }
        
        for desc, (cmd, explanation) in common_commands.items():
            if any(keyword in query_lower for keyword in desc.split()):
                return {
                    "success": True,
                    "ai_analysis": f"LLM服务不可用({error_info})，使用智能匹配：识别为{desc}操作",
                    "execution_type": "single_step",
                    "generated_command": cmd,
                    "command_explanation": explanation,
                    "steps": [{
                        "step_number": 1,
                        "command": cmd,
                        "purpose": explanation,
                        "expected_result": f"成功执行{desc}",
                        "verification": "命令正常输出结果"
                    }],
                    "safety_check": {"is_safe": True, "warning": ""},
                    "can_execute": True,
                    "recommendations": [f"这是一个安全的{desc}命令"]
                }
        
        # 默认响应 - 提供更有用的测试命令
        return {
            "success": True,
            "ai_analysis": f"LLM服务不可用({error_info})，无法准确解析查询: {query[:50]}...",
            "execution_type": "single_step",
            "generated_command": "echo 'AI服务暂时不可用，这是一个测试命令'",
            "command_explanation": "基础测试命令，用于验证系统功能",
            "steps": [{
                "step_number": 1,
                "command": "echo 'AI服务暂时不可用，这是一个测试命令'",
                "purpose": "测试系统基本功能",
                "expected_result": "输出测试信息",
                "verification": "显示测试消息"
            }],
            "safety_check": {"is_safe": True, "warning": ""},
            "can_execute": True,
            "recommendations": [
                "这是一个基础测试命令",
                "请检查LLM服务配置或稍后重试",
                "您也可以直接输入具体的shell命令"
            ]
        }

# 保持向后兼容
HunyuanClient = SuperKubectlAgent 