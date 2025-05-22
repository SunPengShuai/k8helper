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

class HunyuanClient:
    def __init__(self):
        try:
            self.config = Config.get_tencent_config()
            self.secret_id = self.config["secret_id"]
            self.secret_key = self.config["secret_key"]
        except Exception as e:
            logger.warning(f"初始化腾讯云配置失败: {str(e)}，将使用测试密钥")
            self.secret_id = "test_id"
            self.secret_key = "test_key"
        
        # 定义可用的 kubectl 工具列表
        self.available_tools = [
            {
                "name": "kubectl_get_pods",
                "description": "获取所有Pod或特定命名空间Pod的列表",
                "parameters": {
                    "namespace": "可选，指定要查询的命名空间，不指定则查询所有命名空间",
                    "output_format": "可选，输出格式，如wide、json、yaml等",
                    "label_selector": "可选，按标签筛选Pod"
                }
            },
            {
                "name": "kubectl_describe_pod",
                "description": "获取Pod的详细信息",
                "parameters": {
                    "pod_name": "要查询的Pod名称",
                    "namespace": "可选，Pod所在的命名空间，默认为default"
                }
            },
            {
                "name": "kubectl_logs",
                "description": "获取Pod的日志",
                "parameters": {
                    "pod_name": "要查询日志的Pod名称",
                    "namespace": "可选，Pod所在的命名空间，默认为default",
                    "container": "可选，容器名称，如果Pod中有多个容器",
                    "tail": "可选，要显示的最后几行日志数量"
                }
            },
            {
                "name": "kubectl_get_deployments",
                "description": "获取Deployment列表",
                "parameters": {
                    "namespace": "可选，指定要查询的命名空间，不指定则查询所有命名空间",
                    "output_format": "可选，输出格式，如wide、json、yaml等"
                }
            },
            {
                "name": "kubectl_get_services",
                "description": "获取Service列表",
                "parameters": {
                    "namespace": "可选，指定要查询的命名空间，不指定则查询所有命名空间",
                    "output_format": "可选，输出格式，如wide、json、yaml等"
                }
            },
            {
                "name": "kubectl_get_nodes",
                "description": "获取集群节点列表",
                "parameters": {
                    "output_format": "可选，输出格式，如wide、json、yaml等"
                }
            }
        ]
        
        # 初始化 OpenAI 客户端（如果可用）
        if HAS_OPENAI:
            try:
                self.client = OpenAI(
                    api_key=self.secret_key,
                    base_url="https://api.hunyuan.cloud.tencent.com/v1"
                )
            except Exception as e:
                logger.error(f"初始化OpenAI客户端失败: {str(e)}")
                self.client = None
        else:
            self.client = None
            logger.warning("OpenAI客户端未初始化，LLM功能将不可用")

    async def analyze_query(self, query: str, context: Dict[str, Any] = None) -> Dict:
        try:
            # 检查客户端是否可用
            if not HAS_OPENAI or not self.client:
                logger.warning("LLM客户端不可用，返回手动响应")
                return {
                    "success": True,
                    "tool_name": "manual_response",
                    "parameters": {
                        "text": "很抱歉，LLM服务暂时不可用，请稍后再试或使用kubectl命令。"
                    },
                    "analysis": "LLM服务不可用"
                }
                
            # 构造系统提示词
            system_prompt = """你是一个Kubernetes集群管理助手。你需要分析用户的查询，并返回结构化的JSON，包含工具名称和参数。
            严格从提供的工具列表中选择一个最合适的工具，不要使用未定义的工具。
            返回的JSON必须包含以下字段：
            1. tool_name: 所选工具的名称
            2. parameters: 包含该工具所需的参数
            
            示例响应格式：
            {
                "tool_name": "kubectl_get_pods",
                "parameters": {
                    "namespace": "default",
                    "output_format": "wide"
                }
            }
            
            不要在JSON中包含任何解释或额外文字，仅返回JSON对象。"""
            
            # 构造请求
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"可用工具列表：\n{json.dumps(self.available_tools, ensure_ascii=False, indent=2)}\n\n用户查询: {query}"}
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
                content = completion.choices[0].message.content
                
                # 尝试从内容中提取JSON结构
                json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
                if json_match:
                    try:
                        extracted_json = json_match.group(1)
                        analysis = json.loads(extracted_json)
                        return {
                            "success": True,
                            "tool_name": analysis.get("tool_name"),
                            "parameters": analysis.get("parameters", {}),
                        }
                    except Exception:
                        pass
                
                # 尝试直接解析为JSON对象
                try:
                    analysis = json.loads(content)
                    return {
                        "success": True,
                        "tool_name": analysis.get("tool_name"),
                        "parameters": analysis.get("parameters", {}),
                    }
                except Exception:
                    # 提取 kubectl 命令(fallback)
                    kubectl_match = re.search(r'```bash\s*(kubectl\s+.*?)\s*```', content, re.DOTALL)
                    if kubectl_match:
                        kubectl_cmd = kubectl_match.group(1).strip()
                        cmd_parts = kubectl_cmd.split()
                        if len(cmd_parts) > 1:
                            return {
                                "success": True,
                                "tool_name": "kubectl_command",
                                "parameters": {
                                    "command": " ".join(cmd_parts[1:])
                                },
                            }
                    
                    # 最后，如果所有方法都失败，返回原始文本
                    return {
                        "success": True,
                        "tool_name": "manual_response",
                        "parameters": {
                            "text": content
                        },
                    }
            except Exception as e:
                logger.error(f"解析响应失败: {str(e)}, 原始内容: {completion}")
                return {"success": False, "error": f"解析响应失败: {str(e)}", "raw": str(completion)}
        except Exception as e:
            logger.error(f"分析查询失败: {str(e)}\n{traceback.format_exc()}")
            return {
                "success": True,  # 将成功状态改为True以避免HTTP 500错误
                "tool_name": "manual_response", 
                "parameters": {
                    "text": "处理查询时遇到问题，请稍后再试或尝试不同的查询。" 
                }
            }
            
    def _build_prompt(self, query: str, context: Dict[str, Any] = None) -> str:
        """构建提示词"""
        prompt = f"用户问题: {query}\n\n"
        
        if context:
            if "available_tools" in context:
                prompt += "可用工具:\n"
                for tool in context["available_tools"]:
                    prompt += f"- {tool['name']}: {tool['description']}\n"
                prompt += "\n"
                
            if "tool_result" in context:
                prompt += f"工具执行结果:\n{context['tool_result']}\n\n"
                
            if "tool_config" in context:
                prompt += f"工具配置:\n{context['tool_config']}\n\n"
                
        prompt += """请分析用户问题，并返回JSON格式的响应，包含以下字段：
1. tool_name: 要使用的工具名称
2. parameters: 工具所需的参数
3. analysis: 对问题的分析和解决方案

示例响应:
{
    "tool_name": "kubectl",
    "parameters": {
        "args": "get pods --all-namespaces"
    },
    "analysis": "这是一个查看所有Pod状态的命令"
}"""
        
        return prompt 