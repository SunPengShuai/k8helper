from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import json
import re
import threading
import shlex
import yaml
import os
from ..core.k8s_client import KubernetesClient
from ..core.llm_client import SuperKubectlAgent
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 全局变量，用于存储投票数据，使用线程锁确保并发安全
vote_data = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
vote_lock = threading.Lock()
vote_users = set()  # 记录已投票用户

# 安全配置管理
class SecurityConfig:
    """动态安全配置管理"""
    def __init__(self):
        self.super_admin_mode = False
        self.custom_dangerous_commands = set()
        self.custom_safe_commands = set()
        self.custom_safe_create_resources = set()
        self.custom_safe_apply_resources = set()
        self.custom_safe_scale_resources = set()
        self.lock = threading.Lock()
    
    def enable_super_admin_mode(self):
        """启用超级管理员模式"""
        with self.lock:
            self.super_admin_mode = True
    
    def disable_super_admin_mode(self):
        """禁用超级管理员模式"""
        with self.lock:
            self.super_admin_mode = False
    
    def is_super_admin_enabled(self):
        """检查是否启用超级管理员模式"""
        with self.lock:
            return self.super_admin_mode
    
    def add_dangerous_command(self, command: str):
        """添加危险命令"""
        with self.lock:
            self.custom_dangerous_commands.add(command.lower())
    
    def remove_dangerous_command(self, command: str):
        """移除危险命令"""
        with self.lock:
            self.custom_dangerous_commands.discard(command.lower())
    
    def add_safe_resource(self, resource_type: str, operation: str):
        """添加安全资源"""
        with self.lock:
            if operation == 'create':
                self.custom_safe_create_resources.add(resource_type.lower())
            elif operation == 'apply':
                self.custom_safe_apply_resources.add(resource_type.lower())
            elif operation == 'scale':
                self.custom_safe_scale_resources.add(resource_type.lower())
    
    def remove_safe_resource(self, resource_type: str, operation: str):
        """移除安全资源"""
        with self.lock:
            if operation == 'create':
                self.custom_safe_create_resources.discard(resource_type.lower())
            elif operation == 'apply':
                self.custom_safe_apply_resources.discard(resource_type.lower())
            elif operation == 'scale':
                self.custom_safe_scale_resources.discard(resource_type.lower())
    
    def get_config(self):
        """获取当前配置"""
        with self.lock:
            return {
                "super_admin_mode": self.super_admin_mode,
                "custom_dangerous_commands": list(self.custom_dangerous_commands),
                "custom_safe_create_resources": list(self.custom_safe_create_resources),
                "custom_safe_apply_resources": list(self.custom_safe_apply_resources),
                "custom_safe_scale_resources": list(self.custom_safe_scale_resources)
            }

# 全局安全配置实例
security_config = SecurityConfig()

class SecurityConfigRequest(BaseModel):
    super_admin_mode: Optional[bool] = None
    dangerous_commands: Optional[List[str]] = None
    safe_create_resources: Optional[List[str]] = None
    safe_apply_resources: Optional[List[str]] = None
    safe_scale_resources: Optional[List[str]] = None

class QueryRequest(BaseModel):
    query: str
    context: Optional[Dict[str, Any]] = None

class ToolResponse(BaseModel):
    tool_name: str
    parameters: Dict[str, Any]

class VoteRequest(BaseModel):
    user_id: str
    option: str

class KubectlExecutor:
    """安全的Kubectl命令执行器 - 支持复杂shell语法"""
    
    # 定义绝对危险的命令列表
    DANGEROUS_COMMANDS = [
        'delete', 'remove', 'rm', 'destroy', 'kill', 'terminate',
        'patch', 'replace', 'edit'
    ]
    
    # 定义只读安全命令
    SAFE_COMMANDS = [
        'get', 'describe', 'logs', 'top', 'version', 'cluster-info',
        'api-resources', 'api-versions', 'config', 'explain'
    ]
    
    # 定义相对安全的创建操作（允许的资源类型）
    SAFE_CREATE_RESOURCES = [
        'namespace', 'ns', 'configmap', 'cm', 'secret', 'pod', 'pods',
        'deployment', 'deploy', 'service', 'svc', 'job', 'cronjob'
    ]
    
    # 定义相对安全的扩缩容操作
    SAFE_SCALE_RESOURCES = [
        'deployment', 'deploy', 'replicaset', 'rs', 'statefulset', 'sts'
    ]
    
    # 定义相对安全的apply操作（允许的资源类型）
    SAFE_APPLY_RESOURCES = [
        'namespace', 'ns', 'configmap', 'cm', 'secret', 'pod', 'pods',
        'deployment', 'deploy', 'service', 'svc', 'job', 'cronjob'
    ]
    
    @classmethod
    def _detect_shell_syntax(cls, command: str) -> Dict[str, Any]:
        """
        检测命令中的shell语法
        
        Args:
            command: 原始命令（可能包含或不包含kubectl前缀）
            
        Returns:
            Dict: 检测结果，包含语法类型和解析信息
        """
        command = command.strip()
        
        # 检测heredoc语法
        if '<<' in command:
            # 匹配 kubectl apply -f - <<EOF ... EOF 格式
            heredoc_pattern = r'kubectl\s+apply\s+-f\s+-\s+<<(\w+)\s+(.*?)\s+\1'
            match = re.search(heredoc_pattern, command, re.DOTALL)
            if match:
                delimiter = match.group(1)
                yaml_content = match.group(2).strip()
                return {
                    "type": "heredoc",
                    "kubectl_command": "apply -f -",
                    "yaml_content": yaml_content,
                    "delimiter": delimiter
                }
        
        # 检测管道语法
        if '|' in command and 'kubectl' in command:
            # 匹配 echo "yaml" | kubectl apply -f - 格式
            pipe_pattern = r'echo\s+["\']([^"\']*)["\']?\s*\|\s*kubectl\s+(.+)'
            match = re.search(pipe_pattern, command, re.DOTALL)
            if match:
                yaml_content = match.group(1)
                kubectl_command = match.group(2)
                return {
                    "type": "pipe",
                    "kubectl_command": kubectl_command,
                    "yaml_content": yaml_content
                }
        
        # 检测多行YAML内容
        if 'apiVersion:' in command and 'kind:' in command:
            # 提取kubectl命令和YAML内容
            lines = command.split('\n')
            kubectl_line = None
            yaml_lines = []
            
            for line in lines:
                if line.strip().startswith('kubectl'):
                    kubectl_line = line.strip()
                elif line.strip() and ('apiVersion:' in line or 'kind:' in line or 'metadata:' in line or 'spec:' in line or line.startswith('  ') or line.startswith('-')):
                    yaml_lines.append(line)
            
            if kubectl_line and yaml_lines:
                kubectl_command = kubectl_line.replace('kubectl ', '')
                yaml_content = '\n'.join(yaml_lines)
                return {
                    "type": "multiline_yaml",
                    "kubectl_command": kubectl_command,
                    "yaml_content": yaml_content
                }
        
        # 普通kubectl命令（带kubectl前缀）
        if command.startswith('kubectl '):
            return {
                "type": "simple",
                "kubectl_command": command.replace('kubectl ', '')
            }
        
        # 普通kubectl子命令（不带kubectl前缀）- 这是AI生成的常见格式
        # 检查是否是有效的kubectl子命令
        command_parts = command.split()
        if command_parts:
            first_word = command_parts[0].lower()
            # 检查是否是已知的kubectl子命令
            known_kubectl_commands = [
                'get', 'describe', 'logs', 'top', 'version', 'cluster-info',
                'api-resources', 'api-versions', 'config', 'explain',
                'create', 'apply', 'delete', 'patch', 'replace', 'edit',
                'scale', 'rollout', 'expose', 'run', 'exec', 'port-forward',
                'proxy', 'cp', 'auth', 'diff', 'kustomize'
            ]
            
            if first_word in known_kubectl_commands:
                return {
                    "type": "simple",
                    "kubectl_command": command
                }
        
        return {
            "type": "unknown",
            "original_command": command
        }
    
    @classmethod
    def is_safe_command(cls, command: str) -> tuple[bool, str]:
        """
        检查命令是否安全（支持复杂shell语法）
        
        Args:
            command: kubectl命令或shell命令
            
        Returns:
            tuple: (是否安全, 警告信息)
        """
        # 超级管理员模式下允许所有命令
        if security_config.is_super_admin_enabled():
            return True, "超级管理员模式：允许所有命令"
        
        # 解析shell语法
        syntax_info = cls._detect_shell_syntax(command)
        
        if syntax_info["type"] == "unknown":
            return False, f"无法解析的命令格式: {command[:100]}..."
        
        # 获取实际的kubectl命令
        kubectl_command = syntax_info.get("kubectl_command", "")
        if not kubectl_command:
            return False, "未找到有效的kubectl命令"
        
        # 对kubectl命令进行安全检查
        command_lower = kubectl_command.lower().strip()
        command_parts = command_lower.split()
        first_word = command_parts[0] if command_parts else ""
        
        # 检查用户自定义的危险命令
        config = security_config.get_config()
        all_dangerous_commands = set(cls.DANGEROUS_COMMANDS) | set(config["custom_dangerous_commands"])
        
        # 检查是否是只读安全命令
        if first_word in cls.SAFE_COMMANDS:
            return True, ""
        
        # 特殊处理create命令
        if first_word == 'create':
            if len(command_parts) >= 2:
                resource_type = command_parts[1]
                # 合并默认和用户自定义的安全资源
                all_safe_create_resources = set(cls.SAFE_CREATE_RESOURCES) | set(config["custom_safe_create_resources"])
                if resource_type in all_safe_create_resources:
                    return True, ""
                else:
                    return False, f"不允许创建资源类型 '{resource_type}'，仅允许创建: {', '.join(sorted(all_safe_create_resources))}"
            else:
                return False, "create命令缺少资源类型参数"
        
        # 特殊处理scale命令
        if first_word == 'scale':
            if len(command_parts) >= 2:
                resource_type = command_parts[1].split('/')[0]  # 处理 deployment/name 格式
                # 合并默认和用户自定义的安全资源
                all_safe_scale_resources = set(cls.SAFE_SCALE_RESOURCES) | set(config["custom_safe_scale_resources"])
                if resource_type in all_safe_scale_resources:
                    return True, ""
                else:
                    return False, f"不允许扩缩容资源类型 '{resource_type}'，仅允许扩缩容: {', '.join(sorted(all_safe_scale_resources))}"
            else:
                return False, "scale命令缺少资源类型参数"
        
        # 特殊处理apply命令
        if first_word == 'apply':
            # 对于apply -f -（从stdin读取），需要检查YAML内容
            if '-f' in command_parts and '-' in command_parts:
                yaml_content = syntax_info.get("yaml_content", "")
                if yaml_content:
                    # 解析YAML内容，检查资源类型
                    try:
                        import yaml
                        yaml_docs = list(yaml.safe_load_all(yaml_content))
                        all_safe_apply_resources = set(cls.SAFE_APPLY_RESOURCES) | set(config["custom_safe_apply_resources"])
                        
                        for doc in yaml_docs:
                            if doc and isinstance(doc, dict):
                                kind = doc.get('kind', '').lower()
                                if kind not in all_safe_apply_resources:
                                    return False, f"不允许apply资源类型 '{kind}'，仅允许apply: {', '.join(sorted(all_safe_apply_resources))}"
                        
                        return True, ""
                    except Exception as e:
                        return False, f"YAML内容解析失败: {str(e)}"
                else:
                    return False, "apply -f - 命令缺少YAML内容"
            
            # 检查是否指定了资源类型
            resource_found = False
            all_safe_apply_resources = set(cls.SAFE_APPLY_RESOURCES) | set(config["custom_safe_apply_resources"])
            for part in command_parts[1:]:
                if part.startswith('-'):
                    continue
                # 检查是否是安全的资源类型
                resource_type = part.split('/')[0] if '/' in part else part
                if resource_type in all_safe_apply_resources:
                    resource_found = True
                    break
            
            if resource_found:
                return True, ""
            else:
                return False, f"apply命令未指定安全的资源类型，仅允许apply: {', '.join(sorted(all_safe_apply_resources))}"
        
        # 检查是否是绝对危险命令
        for dangerous in all_dangerous_commands:
            if dangerous in command_lower:
                return False, f"检测到危险操作 '{dangerous}'，为了安全已阻止执行"
        
        # 未知命令，谨慎处理
        return False, f"未知命令 '{first_word}'，为了安全已阻止执行。允许的命令类型: {', '.join(cls.SAFE_COMMANDS + ['create', 'scale', 'apply'])}"
    
    @classmethod
    async def execute_kubectl(cls, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        安全执行kubectl命令（支持复杂shell语法）
        
        Args:
            command: kubectl命令或shell命令
            timeout: 超时时间（秒）
            
        Returns:
            Dict: 执行结果
        """
        try:
            # 安全检查
            is_safe, warning = cls.is_safe_command(command)
            if not is_safe:
                return {
                    "success": False,
                    "error": warning,
                    "output": "",
                    "command": command
                }
            
            # 解析shell语法
            syntax_info = cls._detect_shell_syntax(command)
            
            if syntax_info["type"] == "simple":
                # 简单kubectl命令
                return await cls._execute_simple_kubectl(syntax_info["kubectl_command"], timeout)
            
            elif syntax_info["type"] in ["heredoc", "pipe", "multiline_yaml"]:
                # 复杂shell语法，需要通过临时文件或stdin处理
                return await cls._execute_complex_kubectl(syntax_info, timeout)
            
            else:
                return {
                    "success": False,
                    "error": f"不支持的命令格式: {syntax_info['type']}",
                    "output": "",
                    "command": command
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"命令执行超时（{timeout}秒）",
                "output": "",
                "command": command
            }
        except Exception as e:
            logger.error(f"执行kubectl命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": "",
                "command": command
            }
    
    @classmethod
    async def _execute_simple_kubectl(cls, kubectl_command: str, timeout: int) -> Dict[str, Any]:
        """执行简单的kubectl命令"""
        full_command = f"kubectl {kubectl_command}"
        
        # 使用shlex安全解析命令
        try:
            cmd_args = shlex.split(full_command)
        except ValueError as e:
            return {
                "success": False,
                "error": f"命令格式错误: {str(e)}",
                "output": "",
                "command": full_command
            }
        
        # 执行命令
        logger.info(f"执行kubectl命令: {full_command}")
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/data/workspace"
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "output": result.stdout,
                "error": result.stderr if result.stderr else "",
                "command": full_command,
                "return_code": result.returncode
            }
        else:
            return {
                "success": False,
                "output": result.stdout,
                "error": result.stderr or "命令执行失败",
                "command": full_command,
                "return_code": result.returncode
            }
    
    @classmethod
    async def _execute_complex_kubectl(cls, syntax_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行复杂的kubectl命令（包含YAML内容）"""
        kubectl_command = syntax_info["kubectl_command"]
        yaml_content = syntax_info.get("yaml_content", "")
        
        if not yaml_content:
            return {
                "success": False,
                "error": "缺少YAML内容",
                "output": "",
                "command": f"kubectl {kubectl_command}"
            }
        
        try:
            # 创建临时文件存储YAML内容
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                temp_file.write(yaml_content)
                temp_file_path = temp_file.name
            
            try:
                # 构建kubectl命令，使用临时文件
                if kubectl_command.endswith('-f -'):
                    # 将 -f - 替换为 -f temp_file_path
                    kubectl_command = kubectl_command.replace('-f -', f'-f {temp_file_path}')
                elif '-f -' in kubectl_command:
                    kubectl_command = kubectl_command.replace('-f -', f'-f {temp_file_path}')
                else:
                    # 如果没有-f参数，添加它
                    kubectl_command = f"{kubectl_command} -f {temp_file_path}"
                
                full_command = f"kubectl {kubectl_command}"
                
                # 使用shlex安全解析命令
                cmd_args = shlex.split(full_command)
                
                # 执行命令
                logger.info(f"执行复杂kubectl命令: {full_command}")
                logger.info(f"YAML内容: {yaml_content[:200]}...")
                
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd="/data/workspace"
                )
                
                if result.returncode == 0:
                    return {
                        "success": True,
                        "output": result.stdout,
                        "error": result.stderr if result.stderr else "",
                        "command": full_command,
                        "return_code": result.returncode,
                        "yaml_content": yaml_content
                    }
                else:
                    return {
                        "success": False,
                        "output": result.stdout,
                        "error": result.stderr or "命令执行失败",
                        "command": full_command,
                        "return_code": result.returncode,
                        "yaml_content": yaml_content
                    }
                    
            finally:
                # 清理临时文件
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"执行复杂kubectl命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": "",
                "command": f"kubectl {kubectl_command}",
                "yaml_content": yaml_content
            }

class OutputFormatter:
    """智能输出格式化器"""
    
    @classmethod
    def format_output(cls, command: str, output: str, output_format: str = "auto") -> Dict[str, Any]:
        """
        格式化kubectl命令输出
        
        Args:
            command: 执行的命令
            output: 命令输出
            output_format: 输出格式 (table/text/auto)
            
        Returns:
            Dict: 格式化后的结果
        """
        if not output.strip():
            return {
                "type": "text",
                "content": "命令执行成功，但没有输出内容",
                "command": command
            }
        
        # 自动检测格式
        if output_format == "auto":
            output_format = cls._detect_format(command, output)
        
        if output_format == "table":
            return cls._format_as_table(command, output)
        else:
            return cls._format_as_text(command, output)
    
    @classmethod
    def _detect_format(cls, command: str, output: str) -> str:
        """自动检测最佳输出格式"""
        command_lower = command.lower()
        
        # 表格格式适用的命令
        table_commands = ['get', 'top']
        if any(cmd in command_lower for cmd in table_commands):
            # 检查输出是否像表格
            lines = output.strip().split('\n')
            if len(lines) >= 2:
                # 检查是否有表头
                first_line = lines[0]
                if any(header in first_line.upper() for header in ['NAME', 'READY', 'STATUS', 'AGE', 'NAMESPACE']):
                    return "table"
        
        return "text"
    
    @classmethod
    def _format_as_table(cls, command: str, output: str) -> Dict[str, Any]:
        """格式化为表格"""
        lines = output.strip().split('\n')
        if len(lines) < 2:
            return cls._format_as_text(command, output)
        
        try:
            # 解析表头
            header_line = lines[0]
            headers = re.split(r'\s{2,}', header_line.strip())
            
            # 解析数据行
            data_rows = []
            for line in lines[1:]:
                if line.strip():
                    # 使用正则表达式分割，保持与表头对齐
                    row_data = re.split(r'\s{2,}', line.strip())
                    # 确保行数据长度与表头匹配
                    while len(row_data) < len(headers):
                        row_data.append("")
                    data_rows.append(row_data[:len(headers)])
            
            return {
                "type": "table",
                "command": command,
                "headers": headers,
                "data": data_rows,
                "total_rows": len(data_rows)
            }
            
        except Exception as e:
            logger.warning(f"表格解析失败: {str(e)}, 回退到文本格式")
            return cls._format_as_text(command, output)
    
    @classmethod
    def _format_as_text(cls, command: str, output: str) -> Dict[str, Any]:
        """格式化为文本"""
        # 检查是否是YAML或JSON格式
        content_type = "text"
        try:
            # 尝试解析为JSON
            json.loads(output)
            content_type = "json"
        except:
            try:
                # 尝试解析为YAML
                yaml.safe_load(output)
                if output.strip().startswith(('apiVersion:', 'kind:', 'metadata:')):
                    content_type = "yaml"
            except:
                pass
        
        return {
            "type": "text",
            "content_type": content_type,
            "command": command,
            "content": output,
            "line_count": len(output.split('\n'))
        }

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}

@router.post("/query")
async def process_query(request: QueryRequest):
    """
    处理用户查询 - 超强AI Agent版本（支持分步执行和智能重试）
    
    Args:
        request: 查询请求
        
    Returns:
        Dict: 处理结果，包含AI分析、命令执行结果和格式化输出
    """
    try:
        # 初始化AI Agent
        ai_agent = SuperKubectlAgent()
        
        # AI分析查询
        analysis = await ai_agent.analyze_query(request.query, request.context)
        if not analysis["success"]:
            raise HTTPException(status_code=400, detail=analysis.get("error", "AI分析失败"))
        
        # 获取分析结果
        tool_name = analysis.get("tool_name", "kubectl_command")
        parameters = analysis.get("parameters", {})
        ai_analysis = analysis.get("analysis", "")
        
        # 执行kubectl命令
        if tool_name == "kubectl_command":
            command = parameters.get("command", "get pods")
            output_format = parameters.get("output_format", "auto")
            steps = parameters.get("steps", [])
            
            # 检查是否是分步执行
            if steps and len(steps) > 1:
                # 分步执行多个命令（支持智能重试）
                step_results = []
                all_success = True
                combined_output = ""
                retry_enabled = True  # 启用重试机制
                max_retries = 2  # 每个步骤最多重试2次
                
                for i, step_command in enumerate(steps):
                    logger.info(f"执行第 {i+1} 步命令: {step_command}")
                    
                    # 执行单步命令（带重试）
                    step_success = False
                    retry_count = 0
                    current_command = step_command
                    step_execution_history = []
                    
                    while not step_success and retry_count <= max_retries:
                        # 执行命令
                        exec_result = await KubectlExecutor.execute_kubectl(current_command)
                        step_execution_history.append({
                            "attempt": retry_count + 1,
                            "command": current_command,
                            "result": exec_result
                        })
                        
                        if exec_result["success"]:
                            step_success = True
                            # 格式化成功结果
                            formatted_result = OutputFormatter.format_output(
                                exec_result["command"], 
                                exec_result["output"], 
                                output_format
                            )
                        else:
                            # 命令失败，尝试智能重试
                            if retry_enabled and retry_count < max_retries:
                                logger.warning(f"步骤 {i+1} 第 {retry_count + 1} 次尝试失败: {exec_result['error']}")
                                
                                try:
                                    # 让AI分析错误并生成修复命令
                                    retry_analysis = await ai_agent.analyze_error_and_retry(
                                        original_query=request.query,
                                        failed_command=current_command,
                                        error_message=exec_result["error"],
                                        step_number=i + 1,
                                        execution_history=step_execution_history
                                    )
                                    
                                    if retry_analysis.get("success") and retry_analysis.get("retry_command"):
                                        current_command = retry_analysis["retry_command"]
                                        logger.info(f"AI建议重试命令: {current_command}")
                                        logger.info(f"重试原因: {retry_analysis.get('retry_reason', '未知')}")
                                        retry_count += 1
                                        continue
                                    else:
                                        logger.warning(f"AI无法生成重试命令: {retry_analysis.get('error', '未知错误')}")
                                        break
                                        
                                except Exception as e:
                                    logger.error(f"智能重试分析失败: {str(e)}")
                                    break
                            else:
                                # 不重试或已达到最大重试次数
                                break
                    
                    # 记录步骤结果
                    if step_success:
                        step_results.append({
                            "step": i + 1,
                            "command": current_command,
                            "execution_result": exec_result,
                            "formatted_result": formatted_result,
                            "success": True,
                            "retry_count": retry_count,
                            "execution_history": step_execution_history
                        })
                        combined_output += f"步骤 {i+1}: {exec_result['output']}\n"
                    else:
                        # 步骤最终失败
                        all_success = False
                        formatted_result = {
                            "type": "error",
                            "command": current_command,
                            "error": exec_result["error"],
                            "content": exec_result.get("output", "")
                        }
                        
                        step_results.append({
                            "step": i + 1,
                            "command": current_command,
                            "execution_result": exec_result,
                            "formatted_result": formatted_result,
                            "success": False,
                            "retry_count": retry_count,
                            "execution_history": step_execution_history
                        })
                        
                        combined_output += f"步骤 {i+1} 失败: {exec_result['error']}\n"
                        
                        # 如果某步失败，询问是否继续
                        if i < len(steps) - 1:
                            logger.warning(f"步骤 {i+1} 最终失败，停止后续步骤执行")
                            break
                
                # 生成分步执行的智能回复
                try:
                    smart_reply = await ai_agent.generate_smart_reply_with_retry_info(
                        request.query,
                        f"分步执行: {' -> '.join(steps)}",
                        combined_output,
                        {"type": "multi_step", "steps": step_results, "total_steps": len(steps)}
                    )
                except Exception as e:
                    logger.warning(f"生成分步智能回复失败: {str(e)}")
                    retry_info = ""
                    total_retries = sum(step.get("retry_count", 0) for step in step_results)
                    if total_retries > 0:
                        retry_info = f"（包含 {total_retries} 次智能重试）"
                    
                    if all_success:
                        smart_reply = f"✅ 成功完成 {len(step_results)} 个步骤的操作{retry_info}。"
                    else:
                        failed_steps = [r for r in step_results if not r["success"]]
                        smart_reply = f"⚠️ 完成了 {len(step_results)} 个步骤，其中 {len(failed_steps)} 个失败{retry_info}。"
                
                # 构造分步执行响应
                response = {
                    "success": all_success,
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "ai_analysis": ai_analysis,
                    "execution_type": "multi_step_with_retry",
                    "step_results": step_results,
                    "total_steps": len(steps),
                    "completed_steps": len(step_results),
                    "smart_reply": smart_reply,
                    "combined_output": combined_output,
                    "retry_enabled": retry_enabled,
                    "max_retries": max_retries
                }
                
            else:
                # 单步执行（也支持重试）
                retry_enabled = True
                max_retries = 2
                retry_count = 0
                current_command = command
                execution_history = []
                exec_success = False
                
                while not exec_success and retry_count <= max_retries:
                    exec_result = await KubectlExecutor.execute_kubectl(current_command)
                    execution_history.append({
                        "attempt": retry_count + 1,
                        "command": current_command,
                        "result": exec_result
                    })
                    
                    if exec_result["success"]:
                        exec_success = True
                    else:
                        # 单步命令失败，尝试智能重试
                        if retry_enabled and retry_count < max_retries:
                            logger.warning(f"单步命令第 {retry_count + 1} 次尝试失败: {exec_result['error']}")
                            
                            try:
                                # 让AI分析错误并生成修复命令
                                retry_analysis = await ai_agent.analyze_error_and_retry(
                                    original_query=request.query,
                                    failed_command=current_command,
                                    error_message=exec_result["error"],
                                    step_number=1,
                                    execution_history=execution_history
                                )
                                
                                if retry_analysis.get("success") and retry_analysis.get("retry_command"):
                                    current_command = retry_analysis["retry_command"]
                                    logger.info(f"AI建议重试命令: {current_command}")
                                    logger.info(f"重试原因: {retry_analysis.get('retry_reason', '未知')}")
                                    retry_count += 1
                                    continue
                                else:
                                    logger.warning(f"AI无法生成重试命令: {retry_analysis.get('error', '未知错误')}")
                                    break
                                    
                            except Exception as e:
                                logger.error(f"智能重试分析失败: {str(e)}")
                                break
                        else:
                            break
        
        # 格式化输出
                if exec_success:
                    formatted_result = OutputFormatter.format_output(
                        exec_result["command"], 
                        exec_result["output"], 
                        output_format
                    )
                    
                    # 生成智能回复
                    try:
                        smart_reply = await ai_agent.generate_smart_reply(
                            request.query,
                            exec_result["command"],
                            exec_result["output"],
                            formatted_result
                        )
                        
                        # 如果有重试，添加重试信息
                        if retry_count > 0:
                            smart_reply += f"\n\n💡 注意：此命令经过 {retry_count} 次智能重试后成功执行。"
                            
                    except Exception as e:
                        logger.warning(f"生成智能回复失败: {str(e)}")
                        retry_info = f"（经过 {retry_count} 次重试）" if retry_count > 0 else ""
                        smart_reply = f"命令执行成功{retry_info}，请查看详细结果。"
                    
                else:
                    formatted_result = {
                        "type": "error",
                        "command": current_command,
                        "error": exec_result["error"],
                        "content": exec_result.get("output", "")
                    }
                    retry_info = f"（已重试 {retry_count} 次）" if retry_count > 0 else ""
                    smart_reply = f"❌ 执行失败{retry_info}: {exec_result['error']}"
                
                    # 构造单步执行响应
                response = {
                        "success": exec_success,
                        "tool_name": tool_name,
                        "parameters": parameters,
                        "ai_analysis": ai_analysis,
                        "execution_type": "single_step_with_retry",
                        "execution_result": exec_result,
                        "formatted_result": formatted_result,
                        "smart_reply": smart_reply,
                        "command_executed": exec_result["command"],
                        "retry_count": retry_count,
                        "execution_history": execution_history,
                        "retry_enabled": retry_enabled,
                        "max_retries": max_retries
                    }
            
        else:
            # 处理其他工具（保持向后兼容）
            result = await execute_legacy_tool(tool_name, parameters)
            formatted_result = format_legacy_output(tool_name, result, parameters)
            
            # 为传统工具也生成智能回复
            try:
                smart_reply = await ai_agent.generate_smart_reply(
                    request.query,
                    f"legacy_{tool_name}",
                    result,
                    formatted_result
                )
            except Exception as e:
                logger.warning(f"生成传统工具智能回复失败: {str(e)}")
                smart_reply = "操作完成，请查看详细结果。"
            
            response = {
                "success": True,
                "tool_name": tool_name,
                "parameters": parameters,
                "ai_analysis": ai_analysis,
                "execution_type": "legacy",
                "result": result,
                "formatted_result": formatted_result,
                "smart_reply": smart_reply
            }
        
        return response
        
    except Exception as e:
        logger.error(f"处理查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理查询失败: {str(e)}")

@router.post("/vote")
async def vote(request: VoteRequest):
    """
    处理用户投票请求
    
    Args:
        request: 包含user_id和option的投票请求
        
    Returns:
        Dict: 投票结果
    """
    # 定义默认成功返回结构
    success_response = {"code": 200, "message": "投票成功", "data": {}}
    
    try:
        # 确保请求参数有效
        if not request or not hasattr(request, 'user_id') or not hasattr(request, 'option'):
            return {"code": 400, "message": "无效的请求参数", "data": {}}
            
        user_id = request.user_id
        if not user_id:
            return {"code": 400, "message": "用户ID不能为空", "data": {}}
            
        option = request.option.upper() if request.option else ""  # 转为大写以统一处理
        if not option:
            return {"code": 400, "message": "投票选项不能为空", "data": {}}
        
        # 验证选项是否有效
        if option not in vote_data:
            return {"code": 400, "message": f"无效的投票选项: {option}，有效选项为 A/B/C/D/E", "data": {}}
        
        # 使用线程锁确保并发安全
        try:
            with vote_lock:
                # 记录投票
                vote_data[option] += 1
                vote_users.add(user_id)
                
                # 返回当前投票情况
                result = vote_data.copy()
            
            # 投票成功
            return {"code": 200, "message": "投票成功", "data": {"votes": result}}
        except Exception as e:
            # 锁操作失败，记录错误
            logger.error(f"投票锁操作失败: {str(e)}")
            # 返回成功以防止重试风暴，因为可能实际上已经投票成功
            return success_response
            
    except ValueError as e:
        # 处理值错误
        logger.error(f"投票值错误: {str(e)}")
        return {"code": 400, "message": f"投票请求格式错误: {str(e)}", "data": {}}
        
    except Exception as e:
        # 记录详细的错误信息到日志，但对外返回简洁的错误
        logger.error(f"投票处理失败: {str(e)}")
        # 由于可能已经投票成功或失败不明确，返回成功以避免用户重试
        return success_response

async def execute_tool(tool_name: str, parameters: Dict[str, Any]) -> str:
    """
    执行工具命令
    
    Args:
        tool_name: 工具名称
        parameters: 工具参数
        
    Returns:
        str: 执行结果
    """
    try:
        if tool_name == "kubectl_get_pods":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            label_selector = parameters.get("label_selector", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "pods"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("--all-namespaces")
            if output_format:
                cmd.extend(["-o", output_format])
            if label_selector:
                cmd.extend(["-l", label_selector])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_describe_pod":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            # 构建命令
            cmd = ["kubectl", "describe", "pod", pod_name, "-n", namespace]
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_logs":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            container = parameters.get("container", "")
            tail = parameters.get("tail", "")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            # 构建命令
            cmd = ["kubectl", "logs", pod_name, "-n", namespace]
            if container:
                cmd.extend(["-c", container])
            if tail:
                cmd.extend(["--tail", str(tail)])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_get_deployments":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "deployments"]
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
            
        elif tool_name == "kubectl_get_services":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "services"]
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
            
        elif tool_name == "kubectl_get_nodes":
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "nodes"]
            if output_format:
                cmd.extend(["-o", output_format])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_command":
            command = parameters.get("command", "")
            if not command:
                return "错误: 缺少命令"
                
            # 构建命令
            cmd = ["kubectl"] + command.split()
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "manual_response":
            text = parameters.get("text", "")
            return f"系统回复: {text}"
            
        else:
            return f"不支持的工具类型: {tool_name}"
            
    except Exception as e:
        logger.error(f"执行工具失败: {str(e)}")
        return f"执行工具出错: {str(e)}"

def format_output(tool_name: str, output: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    格式化输出结果
    
    Args:
        tool_name: 工具名称
        output: 输出结果
        parameters: 工具参数
        
    Returns:
        Dict: 格式化后的结果
    """
    try:
        # 针对不同工具类型进行格式化处理
        if tool_name.startswith("kubectl_get"):
            # 格式化表格输出
            rows = output.strip().split('\n')
            if len(rows) <= 1:
                return {"type": "text", "content": output}
            
            # 提取表头和数据
            headers = re.split(r'\s+', rows[0].strip())
            data = []
            
            for i in range(1, len(rows)):
                # 将每行按空格分割并对齐到表头
                row_data = {}
                cols = re.split(r'\s+', rows[i].strip(), len(headers) - 1)
                
                # 可能的列数不够，做一个安全检查
                for j in range(min(len(headers), len(cols))):
                    row_data[headers[j]] = cols[j]
                
                data.append(row_data)
            
            return {
                "type": "table", 
                "headers": headers, 
                "data": data,
                "command": f"kubectl {' '.join(tool_name.split('_')[1:])}"
            }
            
        elif tool_name == "kubectl_describe_pod":
            # 提取关键信息，分块展示
            sections = {}
            current_section = "基本信息"
            sections[current_section] = []
            
            for line in output.split('\n'):
                line = line.rstrip()
                if not line:
                    continue
                    
                # 检测新的段落
                if line and line[0] != ' ' and ':' not in line:
                    current_section = line
                    sections[current_section] = []
                else:
                    sections[current_section].append(line)
            
            # 格式化输出
            return {
                "type": "describe",
                "sections": sections,
                "pod_name": parameters.get("pod_name", ""),
                "namespace": parameters.get("namespace", "default")
            }
            
        elif tool_name == "kubectl_logs":
            log_lines = output.split('\n')
            return {
                "type": "logs",
                "lines": log_lines,
                "pod_name": parameters.get("pod_name", ""),
                "namespace": parameters.get("namespace", "default")
            }
            
        else:
            # 默认文本输出
            return {"type": "text", "content": output}
            
    except Exception as e:
        logger.error(f"格式化输出失败: {str(e)}")
        return {"type": "text", "content": output, "error": str(e)} 

async def execute_legacy_tool(tool_name: str, parameters: Dict[str, Any]) -> str:
    """
    执行传统工具命令（向后兼容）
    
    Args:
        tool_name: 工具名称
        parameters: 工具参数
        
    Returns:
        str: 执行结果
    """
    try:
        if tool_name == "manual_response":
            return parameters.get("text", "手动响应")
            
        # 将传统工具调用转换为kubectl命令
        if tool_name == "kubectl_get_pods":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            label_selector = parameters.get("label_selector", "")
            
            # 构建命令
            command_parts = ["get", "pods"]
            if namespace:
                command_parts.extend(["-n", namespace])
            else:
                command_parts.append("--all-namespaces")
            if output_format:
                command_parts.extend(["-o", output_format])
            if label_selector:
                command_parts.extend(["-l", label_selector])
                
            command = " ".join(command_parts)
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        elif tool_name == "kubectl_describe_pod":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            command = f"describe pod {pod_name} -n {namespace}"
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        elif tool_name == "kubectl_logs":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            container = parameters.get("container", "")
            tail = parameters.get("tail", "")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            command_parts = ["logs", pod_name, "-n", namespace]
            if container:
                command_parts.extend(["-c", container])
            if tail:
                command_parts.extend(["--tail", str(tail)])
                
            command = " ".join(command_parts)
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        elif tool_name == "kubectl_get_deployments":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            command_parts = ["get", "deployments"]
            if namespace:
                command_parts.extend(["-n", namespace])
            else:
                command_parts.append("--all-namespaces")
            if output_format:
                command_parts.extend(["-o", output_format])
                
            command = " ".join(command_parts)
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        elif tool_name == "kubectl_get_services":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            command_parts = ["get", "services"]
            if namespace:
                command_parts.extend(["-n", namespace])
            else:
                command_parts.append("--all-namespaces")
            if output_format:
                command_parts.extend(["-o", output_format])
                
            command = " ".join(command_parts)
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        elif tool_name == "kubectl_get_nodes":
            output_format = parameters.get("output_format", "")
            
            command_parts = ["get", "nodes"]
            if output_format:
                command_parts.extend(["-o", output_format])
                
            command = " ".join(command_parts)
            exec_result = await KubectlExecutor.execute_kubectl(command)
            return exec_result["output"] if exec_result["success"] else exec_result["error"]
            
        else:
            return f"未知工具: {tool_name}"
            
    except Exception as e:
        logger.error(f"执行传统工具失败: {str(e)}")
        return f"执行失败: {str(e)}"

def format_legacy_output(tool_name: str, output: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    格式化传统工具输出（向后兼容）
    
    Args:
        tool_name: 工具名称
        output: 输出内容
        parameters: 参数
        
    Returns:
        Dict: 格式化结果
    """
    if tool_name == "manual_response":
        return {
            "type": "text",
            "content": output,
            "command": "手动响应"
        }
    
    # 对于kubectl相关工具，使用智能格式化
    return OutputFormatter.format_output(f"kubectl {tool_name}", output, "auto")

@router.get("/security/config")
async def get_security_config():
    """获取当前安全配置"""
    try:
        config = security_config.get_config()
        
        # 添加默认配置信息
        default_config = {
            "default_dangerous_commands": KubectlExecutor.DANGEROUS_COMMANDS,
            "default_safe_commands": KubectlExecutor.SAFE_COMMANDS,
            "default_safe_create_resources": KubectlExecutor.SAFE_CREATE_RESOURCES,
            "default_safe_apply_resources": KubectlExecutor.SAFE_APPLY_RESOURCES,
            "default_safe_scale_resources": KubectlExecutor.SAFE_SCALE_RESOURCES
        }
        
        return {
            "success": True,
            "current_config": config,
            "default_config": default_config
        }
    except Exception as e:
        logger.error(f"获取安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取安全配置失败: {str(e)}")

@router.post("/security/config")
async def update_security_config(request: SecurityConfigRequest):
    """更新安全配置"""
    try:
        # 更新超级管理员模式
        if request.super_admin_mode is not None:
            if request.super_admin_mode:
                security_config.enable_super_admin_mode()
            else:
                security_config.disable_super_admin_mode()
        
        # 更新危险命令列表
        if request.dangerous_commands is not None:
            # 清空现有自定义危险命令
            config = security_config.get_config()
            for cmd in config["custom_dangerous_commands"]:
                security_config.remove_dangerous_command(cmd)
            # 添加新的危险命令
            for cmd in request.dangerous_commands:
                security_config.add_dangerous_command(cmd)
        
        # 更新安全创建资源列表
        if request.safe_create_resources is not None:
            config = security_config.get_config()
            for resource in config["custom_safe_create_resources"]:
                security_config.remove_safe_resource(resource, 'create')
            for resource in request.safe_create_resources:
                security_config.add_safe_resource(resource, 'create')
        
        # 更新安全apply资源列表
        if request.safe_apply_resources is not None:
            config = security_config.get_config()
            for resource in config["custom_safe_apply_resources"]:
                security_config.remove_safe_resource(resource, 'apply')
            for resource in request.safe_apply_resources:
                security_config.add_safe_resource(resource, 'apply')
        
        # 更新安全scale资源列表
        if request.safe_scale_resources is not None:
            config = security_config.get_config()
            for resource in config["custom_safe_scale_resources"]:
                security_config.remove_safe_resource(resource, 'scale')
            for resource in request.safe_scale_resources:
                security_config.add_safe_resource(resource, 'scale')
        
        return {
            "success": True,
            "message": "安全配置更新成功",
            "current_config": security_config.get_config()
        }
        
    except Exception as e:
        logger.error(f"更新安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新安全配置失败: {str(e)}")

@router.post("/security/super-admin/enable")
async def enable_super_admin():
    """启用超级管理员模式"""
    try:
        security_config.enable_super_admin_mode()
        return {
            "success": True,
            "message": "超级管理员模式已启用",
            "super_admin_mode": True
        }
    except Exception as e:
        logger.error(f"启用超级管理员模式失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启用超级管理员模式失败: {str(e)}")

@router.post("/security/super-admin/disable")
async def disable_super_admin():
    """禁用超级管理员模式"""
    try:
        security_config.disable_super_admin_mode()
        return {
            "success": True,
            "message": "超级管理员模式已禁用",
            "super_admin_mode": False
        }
    except Exception as e:
        logger.error(f"禁用超级管理员模式失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"禁用超级管理员模式失败: {str(e)}")

@router.post("/security/reset")
async def reset_security_config():
    """重置安全配置到默认状态"""
    try:
        # 禁用超级管理员模式
        security_config.disable_super_admin_mode()
        
        # 清空所有自定义配置
        config = security_config.get_config()
        
        # 清空自定义危险命令
        for cmd in config["custom_dangerous_commands"]:
            security_config.remove_dangerous_command(cmd)
        
        # 清空自定义安全资源
        for resource in config["custom_safe_create_resources"]:
            security_config.remove_safe_resource(resource, 'create')
        for resource in config["custom_safe_apply_resources"]:
            security_config.remove_safe_resource(resource, 'apply')
        for resource in config["custom_safe_scale_resources"]:
            security_config.remove_safe_resource(resource, 'scale')
        
        return {
            "success": True,
            "message": "安全配置已重置到默认状态",
            "current_config": security_config.get_config()
        }
        
    except Exception as e:
        logger.error(f"重置安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重置安全配置失败: {str(e)}") 