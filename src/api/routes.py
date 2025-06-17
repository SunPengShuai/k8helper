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
from ..utils.config import Config

logger = get_logger(__name__)
router = APIRouter()

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
        # 新增：shell命令安全配置
        self.allow_shell_commands = False
        self.safe_shell_commands = set(['grep', 'awk', 'sed', 'cut', 'sort', 'uniq', 'head', 'tail', 'wc', 'tr', 'echo'])
        self.dangerous_shell_commands = set(['rm', 'rmdir', 'mv', 'cp', 'chmod', 'chown', 'sudo', 'su', 'kill', 'killall', 'pkill', 'reboot', 'shutdown', 'dd', 'fdisk', 'mkfs', 'mount', 'umount'])
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
    
    def enable_shell_commands(self):
        """启用shell命令支持"""
        with self.lock:
            self.allow_shell_commands = True
    
    def disable_shell_commands(self):
        """禁用shell命令支持"""
        with self.lock:
            self.allow_shell_commands = False
    
    def is_shell_commands_enabled(self):
        """检查是否启用shell命令支持"""
        with self.lock:
            return self.allow_shell_commands
    
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
                "allow_shell_commands": self.allow_shell_commands,
                "custom_dangerous_commands": list(self.custom_dangerous_commands),
                "custom_safe_create_resources": list(self.custom_safe_create_resources),
                "custom_safe_apply_resources": list(self.custom_safe_apply_resources),
                "custom_safe_scale_resources": list(self.custom_safe_scale_resources),
                "safe_shell_commands": list(self.safe_shell_commands),
                "dangerous_shell_commands": list(self.dangerous_shell_commands)
            }

# 全局安全配置实例
security_config = SecurityConfig()

class SecurityConfigRequest(BaseModel):
    super_admin_mode: Optional[bool] = None
    allow_shell_commands: Optional[bool] = None
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

class ShellCommandRequest(BaseModel):
    command: str
    timeout: Optional[int] = 30

class EnhancedKubectlExecutor:
    """增强版Kubectl命令执行器 - 支持shell命令组合"""
    
    @classmethod
    def _get_dangerous_commands(cls):
        """获取危险命令列表"""
        base_commands = set(Config.get_dangerous_commands())
        custom_commands = security_config.custom_dangerous_commands
        return base_commands.union(custom_commands)
    
    @classmethod
    def _get_safe_commands(cls):
        """获取安全命令列表"""
        base_commands = set(Config.get_safe_commands())
        custom_commands = security_config.custom_safe_commands
        return base_commands.union(custom_commands)
    
    @classmethod
    def _get_safe_create_resources(cls):
        """获取安全创建资源列表"""
        base_resources = set(Config.get_safe_create_resources())
        custom_resources = security_config.custom_safe_create_resources
        return base_resources.union(custom_resources)
    
    @classmethod
    def _get_safe_scale_resources(cls):
        """获取安全扩缩容资源列表"""
        base_resources = set(Config.get_safe_scale_resources())
        custom_resources = security_config.custom_safe_scale_resources
        return base_resources.union(custom_resources)
    
    @classmethod
    def _get_safe_apply_resources(cls):
        """获取安全应用资源列表"""
        base_resources = set(Config.get_safe_apply_resources())
        custom_resources = security_config.custom_safe_apply_resources
        return base_resources.union(custom_resources)
    
    @classmethod
    def _detect_command_type(cls, command: str) -> Dict[str, Any]:
        """
        检测命令类型和结构
        
        Args:
            command: 原始命令
            
        Returns:
            Dict: 检测结果，包含命令类型和解析信息
        """
        command = command.strip()
        
        # 检测命令替换语法 $(...)
        if '$' in command and ')' in command:
            return cls._parse_command_substitution(command)
        
        # 检测管道语法
        if '|' in command:
            return cls._parse_pipeline(command)
        
        # 检测heredoc语法
        if '<<' in command:
            return cls._parse_heredoc(command)
        
        # 检测逻辑操作符 && || ;
        if any(op in command for op in ['&&', '||', ';']):
            return cls._parse_logical_operators(command)
        
        # 检测重定向 > >> < 2>
        if any(op in command for op in ['>', '<', '2>']):
            return cls._parse_redirection(command)
        
        # 检测简单kubectl命令
        if command.startswith('kubectl '):
            return {
                "type": "simple_kubectl",
                "kubectl_command": command.replace('kubectl ', ''),
                "original_command": command
            }
        
        # 检测kubectl子命令（带kubectl前缀）
        command_parts = command.split()
        if command_parts:
            first_word = command_parts[0].lower()
            known_kubectl_commands = [
                'get', 'describe', 'logs', 'top', 'version', 'cluster-info',
                'api-resources', 'api-versions', 'config', 'explain',
                'create', 'apply', 'delete', 'patch', 'replace', 'edit',
                'scale', 'rollout', 'expose', 'run', 'exec', 'port-forward',
                'proxy', 'cp', 'auth', 'diff', 'kustomize'
            ]
            
            if first_word in known_kubectl_commands:
                return {
                    "type": "simple_kubectl",
                    "kubectl_command": command,
                    "original_command": f"kubectl {command}"
                }
        
        # 检测纯shell命令
        return {
            "type": "shell_command",
            "shell_command": command,
            "original_command": command
        }
    
    @classmethod
    def _parse_command_substitution(cls, command: str) -> Dict[str, Any]:
        """解析命令替换语法 $(...)"""
        # 匹配 $(...) 模式
        substitution_pattern = r'\$\(([^)]+)\)'
        matches = re.findall(substitution_pattern, command)
        
        if not matches:
            return {"type": "unknown", "original_command": command}
        
        # 分析主命令和子命令
        main_command = command
        sub_commands = []
        
        for match in matches:
            sub_commands.append(match.strip())
        
        return {
            "type": "command_substitution",
            "main_command": main_command,
            "sub_commands": sub_commands,
            "original_command": command
        }
    
    @classmethod
    def _parse_pipeline(cls, command: str) -> Dict[str, Any]:
        """解析管道语法"""
        # 分割管道命令
        pipe_commands = [cmd.strip() for cmd in command.split('|')]
        
        return {
            "type": "pipeline",
            "commands": pipe_commands,
            "original_command": command
        }
    
    @classmethod
    def _parse_heredoc(cls, command: str) -> Dict[str, Any]:
        """解析heredoc语法"""
        heredoc_pattern = r'kubectl\s+apply\s+-f\s+-\s+<<(\w+)\s+(.*?)\s+\1'
        match = re.search(heredoc_pattern, command, re.DOTALL)
        
        if match:
            delimiter = match.group(1)
            yaml_content = match.group(2).strip()
            return {
                "type": "heredoc",
                "kubectl_command": "apply -f -",
                "yaml_content": yaml_content,
                "delimiter": delimiter,
                "original_command": command
            }
        
        return {"type": "unknown", "original_command": command}
    
    @classmethod
    def _parse_logical_operators(cls, command: str) -> Dict[str, Any]:
        """解析逻辑操作符"""
        # 分割逻辑操作符
        if '&&' in command:
            commands = [cmd.strip() for cmd in command.split('&&')]
            operator = 'AND'
        elif '||' in command:
            commands = [cmd.strip() for cmd in command.split('||')]
            operator = 'OR'
        elif ';' in command:
            commands = [cmd.strip() for cmd in command.split(';')]
            operator = 'SEQUENCE'
        else:
            return {"type": "unknown", "original_command": command}
        
        return {
            "type": "logical_operators",
            "operator": operator,
            "commands": commands,
            "original_command": command
        }
    
    @classmethod
    def _parse_redirection(cls, command: str) -> Dict[str, Any]:
        """解析重定向语法"""
        # 简单的重定向检测
        if '>' in command:
            parts = command.split('>', 1)
            base_command = parts[0].strip()
            redirect_target = parts[1].strip()
            redirect_type = 'output'
        elif '<' in command:
            parts = command.split('<', 1)
            base_command = parts[0].strip()
            redirect_target = parts[1].strip()
            redirect_type = 'input'
        else:
            return {"type": "unknown", "original_command": command}
        
        return {
            "type": "redirection",
            "base_command": base_command,
            "redirect_target": redirect_target,
            "redirect_type": redirect_type,
            "original_command": command
        }
    
    @classmethod
    def _analyze_command_safety(cls, command_info: Dict[str, Any]) -> tuple[bool, str]:
        """
        分析命令安全性
        
        Args:
            command_info: 命令解析信息
            
        Returns:
            tuple: (是否安全, 警告信息)
        """
        # 超级管理员模式下允许所有命令
        if security_config.is_super_admin_enabled():
            return True, "超级管理员模式：允许所有命令"
        
        command_type = command_info.get("type", "unknown")
        
        if command_type == "simple_kubectl":
            return cls._check_kubectl_safety(command_info["kubectl_command"])
        
        elif command_type == "shell_command":
            if not security_config.is_shell_commands_enabled():
                return False, "Shell命令支持未启用，仅允许kubectl命令"
            return cls._check_shell_safety(command_info["shell_command"])
        
        elif command_type == "pipeline":
            return cls._check_pipeline_safety(command_info["commands"])
        
        elif command_type == "command_substitution":
            return cls._check_command_substitution_safety(command_info)
        
        elif command_type == "logical_operators":
            return cls._check_logical_operators_safety(command_info["commands"])
        
        elif command_type == "heredoc":
            return cls._check_kubectl_safety(command_info["kubectl_command"])
        
        elif command_type == "redirection":
            # 重定向通常比较危险，需要特别检查
            return False, "重定向操作存在安全风险，已阻止执行"
        
        else:
            return False, f"未知命令类型: {command_type}"
    
    @classmethod
    def _check_kubectl_safety(cls, kubectl_command: str) -> tuple[bool, str]:
        """检查kubectl命令安全性"""
        command_lower = kubectl_command.lower().strip()
        command_parts = command_lower.split()
        first_word = command_parts[0] if command_parts else ""
        
        # 检查是否是只读安全命令
        if first_word in cls._get_safe_commands():
            return True, ""
        
        # 检查危险命令
        all_dangerous_commands = cls._get_dangerous_commands()
        for dangerous in all_dangerous_commands:
            if dangerous in command_lower:
                return False, f"检测到危险操作 '{dangerous}'"
        
        # 特殊处理create、scale、apply命令
        if first_word == 'create':
            if len(command_parts) >= 2:
                resource_type = command_parts[1]
                if resource_type in cls._get_safe_create_resources():
                    return True, ""
                else:
                    return False, f"不允许创建资源类型 '{resource_type}'"
        
        elif first_word == 'scale':
            if len(command_parts) >= 2:
                resource_type = command_parts[1].split('/')[0]
                if resource_type in cls._get_safe_scale_resources():
                    return True, ""
                else:
                    return False, f"不允许扩缩容资源类型 '{resource_type}'"
        
        elif first_word == 'apply':
            return True, ""  # apply命令相对安全
        
        return False, f"未知kubectl命令 '{first_word}'"
    
    @classmethod
    def _check_shell_safety(cls, shell_command: str) -> tuple[bool, str]:
        """检查shell命令安全性"""
        command_parts = shell_command.lower().split()
        if not command_parts:
            return False, "空命令"
        
        first_word = command_parts[0]
        
        # 检查危险shell命令
        if first_word in security_config.dangerous_shell_commands:
            return False, f"危险shell命令 '{first_word}' 已被阻止"
        
        # 检查安全shell命令
        if first_word in security_config.safe_shell_commands:
            return True, ""
        
        # 其他命令需要谨慎处理
        return False, f"未知shell命令 '{first_word}'"
    
    @classmethod
    def _check_pipeline_safety(cls, commands: List[str]) -> tuple[bool, str]:
        """检查管道命令安全性"""
        for i, cmd in enumerate(commands):
            cmd = cmd.strip()
            
            # 检查每个管道命令
            if cmd.startswith('kubectl '):
                is_safe, msg = cls._check_kubectl_safety(cmd.replace('kubectl ', ''))
            else:
                # 检查是否是kubectl子命令
                cmd_parts = cmd.split()
                if cmd_parts and cmd_parts[0].lower() in ['get', 'describe', 'logs', 'top', 'version']:
                    is_safe, msg = cls._check_kubectl_safety(cmd)
                else:
                    # 检查shell命令
                    if not security_config.is_shell_commands_enabled():
                        return False, f"管道中的shell命令 '{cmd}' 未启用"
                    is_safe, msg = cls._check_shell_safety(cmd)
            
            if not is_safe:
                return False, f"管道第{i+1}个命令不安全: {msg}"
        
        return True, ""
    
    @classmethod
    def _check_command_substitution_safety(cls, command_info: Dict[str, Any]) -> tuple[bool, str]:
        """检查命令替换安全性"""
        # 检查子命令
        for i, sub_cmd in enumerate(command_info["sub_commands"]):
            if sub_cmd.startswith('kubectl '):
                is_safe, msg = cls._check_kubectl_safety(sub_cmd.replace('kubectl ', ''))
            else:
                # 检查是否是kubectl子命令
                cmd_parts = sub_cmd.split()
                if cmd_parts and cmd_parts[0].lower() in ['get', 'describe', 'logs', 'top', 'version']:
                    is_safe, msg = cls._check_kubectl_safety(sub_cmd)
                else:
                    if not security_config.is_shell_commands_enabled():
                        return False, f"命令替换中的shell命令 '{sub_cmd}' 未启用"
                    is_safe, msg = cls._check_shell_safety(sub_cmd)
            
            if not is_safe:
                return False, f"命令替换第{i+1}个子命令不安全: {msg}"
        
        # 检查主命令
        main_cmd = command_info["main_command"]
        # 暂时移除命令替换部分进行检查
        import re
        main_cmd_clean = re.sub(r'\$\([^)]+\)', 'SUBSTITUTION', main_cmd)
        
        if 'kubectl' in main_cmd_clean:
            # 主命令包含kubectl，需要特殊处理
            return True, ""
        else:
            if not security_config.is_shell_commands_enabled():
                return False, "主命令中的shell操作未启用"
            # 简单检查主命令结构
            return True, ""
    
    @classmethod
    def _check_logical_operators_safety(cls, commands: List[str]) -> tuple[bool, str]:
        """检查逻辑操作符命令安全性"""
        for i, cmd in enumerate(commands):
            cmd = cmd.strip()
            
            # 递归检查每个命令
            cmd_info = cls._detect_command_type(cmd)
            is_safe, msg = cls._analyze_command_safety(cmd_info)
            
            if not is_safe:
                return False, f"逻辑操作第{i+1}个命令不安全: {msg}"
        
        return True, ""
    
    @classmethod
    async def execute_command(cls, command: str, timeout: int = 60) -> Dict[str, Any]:
        """
        执行命令（支持复杂shell语法）
        
        Args:
            command: 要执行的命令
            timeout: 超时时间（秒）
            
        Returns:
            Dict: 执行结果
        """
        try:
            # 解析命令
            command_info = cls._detect_command_type(command)
            
            # 安全检查
            is_safe, warning = cls._analyze_command_safety(command_info)
            if not is_safe:
                return {
                    "success": False,
                    "error": warning,
                    "output": "",
                    "command": command,
                    "command_type": command_info.get("type", "unknown")
                }
            
            # 根据命令类型执行
            command_type = command_info.get("type", "unknown")
            
            if command_type == "simple_kubectl":
                return await cls._execute_simple_kubectl(command_info, timeout)
            
            elif command_type == "pipeline":
                return await cls._execute_pipeline(command_info, timeout)
            
            elif command_type == "command_substitution":
                return await cls._execute_command_substitution(command_info, timeout)
            
            elif command_type == "logical_operators":
                return await cls._execute_logical_operators(command_info, timeout)
            
            elif command_type == "heredoc":
                return await cls._execute_heredoc(command_info, timeout)
            
            elif command_type == "shell_command":
                return await cls._execute_shell_command(command_info, timeout)
            
            else:
                return {
                    "success": False,
                    "error": f"不支持的命令类型: {command_type}",
                    "output": "",
                    "command": command,
                    "command_type": command_type
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"命令执行超时（{timeout}秒）",
                "output": "",
                "command": command
            }
        except Exception as e:
            logger.error(f"执行命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": "",
                "command": command
            }
    
    @classmethod
    async def _execute_simple_kubectl(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行简单kubectl命令"""
        kubectl_command = command_info["kubectl_command"]
        
        try:
            full_command = f"kubectl {kubectl_command}"
            cmd_args = shlex.split(full_command)
        except ValueError as e:
            return {
                "success": False,
                "error": f"命令格式错误: {str(e)}",
                "output": "",
                "command": full_command
            }
        
        logger.info(f"执行kubectl命令: {full_command}")
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else "",
            "command": full_command,
            "return_code": result.returncode,
            "command_type": "simple_kubectl"
        }
    
    @classmethod
    async def _execute_pipeline(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行管道命令"""
        commands = command_info["commands"]
        original_command = command_info["original_command"]
        
        logger.info(f"执行管道命令: {original_command}")
        
        # 使用shell执行管道命令
        result = subprocess.run(
            original_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else "",
            "command": original_command,
            "return_code": result.returncode,
            "command_type": "pipeline",
            "pipeline_commands": commands
        }
    
    @classmethod
    async def _execute_command_substitution(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行命令替换"""
        original_command = command_info["original_command"]
        
        logger.info(f"执行命令替换: {original_command}")
        
        # 使用shell执行命令替换
        result = subprocess.run(
            original_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else "",
            "command": original_command,
            "return_code": result.returncode,
            "command_type": "command_substitution",
            "sub_commands": command_info["sub_commands"]
        }
    
    @classmethod
    async def _execute_logical_operators(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行逻辑操作符命令"""
        original_command = command_info["original_command"]
        operator = command_info["operator"]
        
        logger.info(f"执行逻辑操作命令 ({operator}): {original_command}")
        
        # 使用shell执行逻辑操作
        result = subprocess.run(
            original_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else "",
            "command": original_command,
            "return_code": result.returncode,
            "command_type": "logical_operators",
            "operator": operator,
            "commands": command_info["commands"]
        }
    
    @classmethod
    async def _execute_heredoc(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行heredoc命令"""
        kubectl_command = command_info["kubectl_command"]
        yaml_content = command_info["yaml_content"]
        
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
                temp_file.write(yaml_content)
                temp_file_path = temp_file.name
            
            try:
                full_command = f"kubectl {kubectl_command.replace('-f -', f'-f {temp_file_path}')}"
                cmd_args = shlex.split(full_command)
                
                logger.info(f"执行heredoc命令: {full_command}")
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=os.getcwd()
                )
                
                return {
                    "success": result.returncode == 0,
                    "output": result.stdout,
                    "error": result.stderr if result.stderr else "",
                    "command": full_command,
                    "return_code": result.returncode,
                    "command_type": "heredoc",
                    "yaml_content": yaml_content
                }
                
            finally:
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            return {
                "success": False,
                "error": f"执行heredoc失败: {str(e)}",
                "output": "",
                "command": f"kubectl {kubectl_command}",
                "command_type": "heredoc"
            }
    
    @classmethod
    async def _execute_shell_command(cls, command_info: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        """执行shell命令"""
        shell_command = command_info["shell_command"]
        
        logger.info(f"执行shell命令: {shell_command}")
        
        result = subprocess.run(
            shell_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.stderr else "",
            "command": shell_command,
            "return_code": result.returncode,
            "command_type": "shell_command"
        }

# 为了向后兼容，保留原来的KubectlExecutor类
class KubectlExecutor(EnhancedKubectlExecutor):
    """向后兼容的Kubectl执行器"""
    
    @classmethod
    async def execute_kubectl(cls, command: str, timeout: int = 30) -> Dict[str, Any]:
        """向后兼容的执行方法"""
        return await cls.execute_command(command, timeout)
    
    @classmethod
    def is_safe_command(cls, command: str) -> tuple[bool, str]:
        """向后兼容的安全检查方法"""
        command_info = cls._detect_command_type(command)
        return cls._analyze_command_safety(command_info)

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
                        exec_result = await EnhancedKubectlExecutor.execute_command(current_command)
                        step_execution_history.append({
                            "attempt": retry_count + 1,
                            "command": current_command,
                            "result": exec_result
                        })
                        
                        if exec_result["success"]:
                            step_success = True
                            # 格式化输出
                            formatted_result = OutputFormatter.format_output(
                                exec_result["command"], 
                                exec_result["output"], 
                                output_format
                            )
                        else:
                            # 步骤失败，尝试智能重试
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
                    exec_result = await EnhancedKubectlExecutor.execute_command(current_command)
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
            "default_dangerous_commands": list(Config.get_dangerous_commands()),
            "default_safe_commands": list(Config.get_safe_commands()),
            "default_safe_create_resources": list(Config.get_safe_create_resources()),
            "default_safe_apply_resources": list(Config.get_safe_apply_resources()),
            "default_safe_scale_resources": list(Config.get_safe_scale_resources())
        }
        
        return {
            "success": True,
            "data": {
                "current_config": config,
                "default_config": default_config,
                "description": {
                    "super_admin_mode": "超级管理员模式，启用后允许执行所有命令",
                    "allow_shell_commands": "是否允许执行shell命令组合（管道、命令替换等）",
                    "custom_dangerous_commands": "用户自定义的危险命令列表",
                    "custom_safe_create_resources": "用户自定义的安全创建资源类型",
                    "custom_safe_apply_resources": "用户自定义的安全应用资源类型",
                    "custom_safe_scale_resources": "用户自定义的安全扩缩容资源类型",
                    "safe_shell_commands": "允许的安全shell命令",
                    "dangerous_shell_commands": "禁止的危险shell命令"
                }
            }
        }
    except Exception as e:
        logger.error(f"获取安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取安全配置失败: {str(e)}")

@router.post("/security/config")
async def update_security_config(request: SecurityConfigRequest):
    """更新安全配置"""
    try:
        updated_fields = []
        
        # 更新超级管理员模式
        if request.super_admin_mode is not None:
            if request.super_admin_mode:
                security_config.enable_super_admin_mode()
                updated_fields.append("启用超级管理员模式")
            else:
                security_config.disable_super_admin_mode()
                updated_fields.append("禁用超级管理员模式")
        
        # 更新shell命令支持
        if request.allow_shell_commands is not None:
            if request.allow_shell_commands:
                security_config.enable_shell_commands()
                updated_fields.append("启用shell命令支持")
            else:
                security_config.disable_shell_commands()
                updated_fields.append("禁用shell命令支持")
        
        # 更新危险命令列表
        if request.dangerous_commands is not None:
            # 清空现有自定义危险命令
            security_config.custom_dangerous_commands.clear()
            # 添加新的危险命令
            for cmd in request.dangerous_commands:
                security_config.add_dangerous_command(cmd)
            updated_fields.append(f"更新危险命令列表({len(request.dangerous_commands)}个)")
        
        # 更新安全资源列表
        if request.safe_create_resources is not None:
            security_config.custom_safe_create_resources.clear()
            for resource in request.safe_create_resources:
                security_config.add_safe_resource(resource, 'create')
            updated_fields.append(f"更新安全创建资源列表({len(request.safe_create_resources)}个)")
        
        if request.safe_apply_resources is not None:
            security_config.custom_safe_apply_resources.clear()
            for resource in request.safe_apply_resources:
                security_config.add_safe_resource(resource, 'apply')
            updated_fields.append(f"更新安全应用资源列表({len(request.safe_apply_resources)}个)")
        
        if request.safe_scale_resources is not None:
            security_config.custom_safe_scale_resources.clear()
            for resource in request.safe_scale_resources:
                security_config.add_safe_resource(resource, 'scale')
            updated_fields.append(f"更新安全扩缩容资源列表({len(request.safe_scale_resources)}个)")
        
        # 记录配置更新
        logger.info(f"安全配置已更新: {', '.join(updated_fields)}")
        
        return {
            "success": True,
            "message": f"安全配置更新成功: {', '.join(updated_fields)}",
            "updated_fields": updated_fields,
            "current_config": security_config.get_config()
        }
        
    except Exception as e:
        logger.error(f"更新安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新安全配置失败: {str(e)}")

@router.post("/security/shell-commands/enable")
async def enable_shell_commands():
    """启用shell命令支持"""
    try:
        security_config.enable_shell_commands()
        logger.info("Shell命令支持已启用")
        
        return {
            "success": True,
            "message": "Shell命令支持已启用",
            "warning": "启用shell命令支持可能带来安全风险，请确保您了解相关风险",
            "current_config": security_config.get_config()
        }
    except Exception as e:
        logger.error(f"启用shell命令支持失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启用shell命令支持失败: {str(e)}")

@router.post("/security/shell-commands/disable")
async def disable_shell_commands():
    """禁用shell命令支持"""
    try:
        security_config.disable_shell_commands()
        logger.info("Shell命令支持已禁用")
        
        return {
            "success": True,
            "message": "Shell命令支持已禁用，现在只允许纯kubectl命令",
            "current_config": security_config.get_config()
        }
    except Exception as e:
        logger.error(f"禁用shell命令支持失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"禁用shell命令支持失败: {str(e)}")

@router.post("/security/super-admin/enable")
async def enable_super_admin():
    """启用超级管理员模式"""
    try:
        security_config.enable_super_admin_mode()
        logger.warning("超级管理员模式已启用 - 所有命令都将被允许执行")
        
        return {
            "success": True,
            "message": "超级管理员模式已启用",
            "warning": "超级管理员模式下所有命令都将被允许执行，包括危险操作！请谨慎使用。",
            "current_config": security_config.get_config()
        }
    except Exception as e:
        logger.error(f"启用超级管理员模式失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"启用超级管理员模式失败: {str(e)}")

@router.post("/security/super-admin/disable")
async def disable_super_admin():
    """禁用超级管理员模式"""
    try:
        security_config.disable_super_admin_mode()
        logger.info("超级管理员模式已禁用")
        
        return {
            "success": True,
            "message": "超级管理员模式已禁用，恢复正常安全检查",
            "current_config": security_config.get_config()
        }
    except Exception as e:
        logger.error(f"禁用超级管理员模式失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"禁用超级管理员模式失败: {str(e)}")

@router.post("/security/reset")
async def reset_security_config():
    """重置安全配置到默认状态"""
    try:
        # 重置所有配置
        security_config.disable_super_admin_mode()
        security_config.disable_shell_commands()
        security_config.custom_dangerous_commands.clear()
        security_config.custom_safe_commands.clear()
        security_config.custom_safe_create_resources.clear()
        security_config.custom_safe_apply_resources.clear()
        security_config.custom_safe_scale_resources.clear()
        
        logger.info("安全配置已重置到默认状态")
        
        return {
            "success": True,
            "message": "安全配置已重置到默认状态",
            "current_config": security_config.get_config()
        }
    except Exception as e:
        logger.error(f"重置安全配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重置安全配置失败: {str(e)}")

@router.post("/test-command")
async def test_command(command: str = Body(..., embed=True)):
    """测试命令安全性和执行能力"""
    try:
        # 解析命令
        command_info = EnhancedKubectlExecutor._detect_command_type(command)
        
        # 安全检查
        is_safe, warning = EnhancedKubectlExecutor._analyze_command_safety(command_info)
        
        result = {
            "command": command,
            "command_type": command_info.get("type", "unknown"),
            "is_safe": is_safe,
            "safety_message": warning if not is_safe else "命令通过安全检查",
            "command_analysis": command_info
        }
        
        # 如果命令安全，可以选择执行（但这里只做分析）
        if is_safe:
            result["execution_ready"] = True
            result["message"] = "命令可以安全执行"
        else:
            result["execution_ready"] = False
            result["message"] = f"命令被安全策略阻止: {warning}"
        
        return {
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"测试命令失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"测试命令失败: {str(e)}")

@router.post("/shell/execute")
async def execute_shell_command(request: ShellCommandRequest):
    """
    执行shell命令（支持智能分析）
    
    Args:
        request: shell命令请求
        
    Returns:
        Dict: 执行结果
    """
    try:
        command = request.command.strip()
        timeout = request.timeout or 30
        
        if not command:
            raise HTTPException(status_code=400, detail="命令不能为空")
        
        # 检查是否是自然语言查询（包含中文或明显的自然语言特征）
        import re
        is_natural_language = (
            bool(re.search(r'[\u4e00-\u9fff]', command)) or  # 包含中文
            any(word in command.lower() for word in ['帮我', '请', '创建', '生成', '写入', '如何', 'help me', 'create', 'generate']) or
            '?' in command or '？' in command
        )
        
        if is_natural_language:
            # 这是自然语言查询，需要先通过AI分析
            try:
                # 获取LLM客户端
                from ..core.llm_client import SuperKubectlAgent
                llm_client = SuperKubectlAgent()
                
                # 分析自然语言查询
                analysis_result = await llm_client.analyze_shell_query(command)
                
                if analysis_result.get("success"):
                    # 检查是否有分步执行计划
                    if analysis_result.get("execution_type") == "step_by_step" and analysis_result.get("steps"):
                        # 分步执行模式
                        steps = analysis_result["steps"]
                        logger.info(f"AI分析结果: 分步执行，共{len(steps)}步")
                        
                        # 执行第一步
                        first_step = steps[0]
                        actual_command = first_step["command"]
                        logger.info(f"执行第一步命令: {actual_command}")
                        
                        # 执行命令
                        result = await EnhancedKubectlExecutor.execute_command(actual_command, timeout)
                        
                        # 在结果中添加AI分析信息和步骤信息
                        result["ai_analysis"] = analysis_result.get("ai_analysis", "")
                        result["original_query"] = command
                        result["execution_type"] = "step_by_step"
                        result["current_step"] = 1
                        result["total_steps"] = len(steps)
                        result["step_info"] = first_step
                        result["remaining_steps"] = steps[1:] if len(steps) > 1 else []
                        result["command_explanation"] = first_step.get("purpose", "")
                        
                    elif analysis_result.get("generated_command"):
                        # 单步执行模式（向后兼容）
                        actual_command = analysis_result["generated_command"]
                        logger.info(f"AI分析结果: 单步执行")
                        logger.info(f"生成的命令: {actual_command}")
                        
                        # 执行AI生成的命令
                        result = await EnhancedKubectlExecutor.execute_command(actual_command, timeout)
                        
                        # 在结果中添加AI分析信息
                        result["ai_analysis"] = analysis_result.get("ai_analysis", "")
                        result["original_query"] = command
                        result["generated_command"] = actual_command
                        result["command_explanation"] = analysis_result.get("command_explanation", "")
                        
                    else:
                        # AI分析失败，返回错误
                        return {
                            "success": False,
                            "command": command,
                            "command_type": "natural_language_query",
                            "output": "",
                            "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                            "return_code": -1,
                            "formatted_result": {
                                "type": "error",
                                "command": command,
                                "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                                "content": ""
                            },
                            "execution_time": timeout,
                            "ai_analysis": analysis_result.get("ai_analysis", ""),
                            "original_query": command
                        }
                else:
                    # AI分析失败，返回错误
                    return {
                        "success": False,
                        "command": command,
                        "command_type": "natural_language_query",
                        "output": "",
                        "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                        "return_code": -1,
                        "formatted_result": {
                            "type": "error",
                            "command": command,
                            "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                            "content": ""
                        },
                        "execution_time": timeout,
                        "ai_analysis": analysis_result.get("ai_analysis", ""),
                        "original_query": command
                    }
                    
            except Exception as ai_error:
                logger.error(f"AI分析异常: {str(ai_error)}")
                return {
                    "success": False,
                    "command": command,
                    "command_type": "natural_language_query",
                    "output": "",
                    "error": f"AI分析异常: {str(ai_error)}",
                    "return_code": -1,
                    "formatted_result": {
                        "type": "error",
                        "command": command,
                        "error": f"AI分析异常: {str(ai_error)}",
                        "content": ""
                    },
                    "execution_time": timeout,
                    "original_query": command
                }
        else:
            # 这是普通的Shell命令，直接执行
            result = await EnhancedKubectlExecutor.execute_command(command, timeout)
        
        # 格式化输出
        if result["success"]:
            formatted_result = OutputFormatter.format_output(
                result["command"], 
                result["output"], 
                "auto"
            )
        else:
            formatted_result = {
                "type": "error",
                "command": result["command"],
                "error": result["error"],
                "content": result.get("output", "")
            }
        
        return {
            "success": result["success"],
            "command": result["command"],
            "command_type": result.get("command_type", "unknown"),
            "output": result["output"],
            "error": result.get("error", ""),
            "return_code": result.get("return_code", -1),
            "formatted_result": formatted_result,
            "execution_time": timeout,
            "ai_analysis": result.get("ai_analysis", ""),
            "original_query": result.get("original_query", ""),
            "generated_command": result.get("generated_command", ""),
            "command_explanation": result.get("command_explanation", ""),
            # 新增分步执行相关字段
            "execution_type": result.get("execution_type", "single"),
            "current_step": result.get("current_step", 1),
            "total_steps": result.get("total_steps", 1),
            "step_info": result.get("step_info", {}),
            "remaining_steps": result.get("remaining_steps", [])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"执行shell命令失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"执行shell命令失败: {str(e)}")

@router.get("/shell/status")
async def get_shell_status():
    """获取shell命令执行状态和配置"""
    try:
        config = security_config.get_config()
        
        return {
            "success": True,
            "data": {
                "shell_commands_enabled": config["allow_shell_commands"],
                "super_admin_mode": config["super_admin_mode"],
                "safe_shell_commands": config["safe_shell_commands"],
                "dangerous_shell_commands": config["dangerous_shell_commands"],
                "supported_features": {
                    "command_substitution": "支持 $(command) 语法",
                    "pipelines": "支持 | 管道操作",
                    "logical_operators": "支持 && || ; 逻辑操作符",
                    "kubectl_integration": "完整kubectl命令支持",
                    "safety_checks": "智能安全检查"
                },
                "examples": [
                    "kubectl get pods",
                    "kubectl get namespaces | grep '^a'",
                    "kubectl get pods $(kubectl get namespaces -o name | head -1 | cut -d'/' -f2)",
                    "kubectl get nodes && kubectl get pods --all-namespaces"
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"获取shell状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取shell状态失败: {str(e)}")

@router.post("/shell/validate")
async def validate_shell_command(command: str = Body(..., embed=True)):
    """验证shell命令的安全性和语法"""
    try:
        if not command or not command.strip():
            raise HTTPException(status_code=400, detail="命令不能为空")
        
        command = command.strip()
        
        # 解析命令
        command_info = EnhancedKubectlExecutor._detect_command_type(command)
        
        # 安全检查
        is_safe, warning = EnhancedKubectlExecutor._analyze_command_safety(command_info)
        
        # 语法分析
        syntax_analysis = {
            "command_type": command_info.get("type", "unknown"),
            "complexity": "simple" if command_info.get("type") in ["simple_kubectl", "shell_command"] else "complex",
            "features_used": []
        }
        
        # 分析使用的功能
        if command_info.get("type") == "pipeline":
            syntax_analysis["features_used"].append("管道操作")
        if command_info.get("type") == "command_substitution":
            syntax_analysis["features_used"].append("命令替换")
        if command_info.get("type") == "logical_operators":
            syntax_analysis["features_used"].append("逻辑操作符")
        if "kubectl" in command.lower():
            syntax_analysis["features_used"].append("kubectl命令")
        
        return {
            "success": True,
            "data": {
                "command": command,
                "is_valid": True,
                "is_safe": is_safe,
                "safety_message": warning if not is_safe else "命令通过安全检查",
                "syntax_analysis": syntax_analysis,
                "command_info": command_info,
                "can_execute": is_safe,
                "recommendations": [
                    "建议在测试环境中先验证命令效果" if not is_safe else "命令可以安全执行",
                    "复杂命令建议分步执行以便调试" if syntax_analysis["complexity"] == "complex" else None
                ]
            }
        }
        
    except Exception as e:
        logger.error(f"验证shell命令失败: {str(e)}")
        return {
            "success": False,
            "data": {
                "command": command,
                "is_valid": False,
                "is_safe": False,
                "error": str(e),
                "can_execute": False
            }
        } 

# 系统配置相关的数据模型
class AIConfigRequest(BaseModel):
    hunyuan_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    preferred_model: Optional[str] = 'hunyuan'

class RetryConfigRequest(BaseModel):
    max_retries: Optional[int] = 3
    retry_delay: Optional[int] = 2
    enable_smart_retry: Optional[bool] = True

class ShellConfigRequest(BaseModel):
    whitelist: Optional[List[str]] = []
    blacklist: Optional[List[str]] = []
    enable_validation: Optional[bool] = False

class PerformanceConfigRequest(BaseModel):
    command_timeout: Optional[int] = 60
    max_output_lines: Optional[int] = 1000
    enable_result_cache: Optional[bool] = True

class AITestRequest(BaseModel):
    hunyuan_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    preferred_model: Optional[str] = 'hunyuan'

# 系统配置管理类
class SystemConfigManager:
    """系统配置管理器"""
    
    def __init__(self):
        self.config_file = os.path.join(os.path.dirname(__file__), '../../config/system_config.json')
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            'ai': {
                'hunyuan_api_key': '',
                'openai_api_key': '',
                'preferred_model': 'hunyuan'
            },
            'retry': {
                'max_retries': 3,
                'retry_delay': 2,
                'enable_smart_retry': True
            },
            'shell': {
                'whitelist': [],
                'blacklist': ['rm', 'rmdir', 'mv', 'chmod', 'chown', 'sudo', 'su', 'kill', 'killall', 'reboot', 'shutdown'],
                'enable_validation': False
            },
            'performance': {
                'command_timeout': 60,
                'max_output_lines': 1000,
                'enable_result_cache': True
            }
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 合并默认配置和加载的配置
                    for key in default_config:
                        if key in loaded_config:
                            default_config[key].update(loaded_config[key])
                        else:
                            loaded_config[key] = default_config[key]
                    return loaded_config
            else:
                # 创建配置目录
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                self._save_config(default_config)
                return default_config
        except Exception as e:
            logger.error(f"加载配置文件失败: {str(e)}")
            return default_config
    
    def _save_config(self, config: Dict[str, Any] = None):
        """保存配置文件"""
        try:
            config_to_save = config or self.config
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存配置文件失败: {str(e)}")
            raise
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self.config.copy()
    
    def update_ai_config(self, config: AIConfigRequest) -> bool:
        """更新AI配置"""
        try:
            if config.hunyuan_api_key is not None:
                self.config['ai']['hunyuan_api_key'] = config.hunyuan_api_key
            if config.openai_api_key is not None:
                self.config['ai']['openai_api_key'] = config.openai_api_key
            if config.preferred_model is not None:
                self.config['ai']['preferred_model'] = config.preferred_model
            
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"更新AI配置失败: {str(e)}")
            return False
    
    def update_retry_config(self, config: RetryConfigRequest) -> bool:
        """更新重试配置"""
        try:
            if config.max_retries is not None:
                self.config['retry']['max_retries'] = max(0, min(5, config.max_retries))
            if config.retry_delay is not None:
                self.config['retry']['retry_delay'] = max(1, min(10, config.retry_delay))
            if config.enable_smart_retry is not None:
                self.config['retry']['enable_smart_retry'] = config.enable_smart_retry
            
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"更新重试配置失败: {str(e)}")
            return False
    
    def update_shell_config(self, config: ShellConfigRequest) -> bool:
        """更新Shell配置"""
        try:
            if config.whitelist is not None:
                self.config['shell']['whitelist'] = config.whitelist
            if config.blacklist is not None:
                self.config['shell']['blacklist'] = config.blacklist
            if config.enable_validation is not None:
                self.config['shell']['enable_validation'] = config.enable_validation
            
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"更新Shell配置失败: {str(e)}")
            return False
    
    def update_performance_config(self, config: PerformanceConfigRequest) -> bool:
        """更新性能配置"""
        try:
            if config.command_timeout is not None:
                self.config['performance']['command_timeout'] = max(10, min(300, config.command_timeout))
            if config.max_output_lines is not None:
                self.config['performance']['max_output_lines'] = max(100, min(10000, config.max_output_lines))
            if config.enable_result_cache is not None:
                self.config['performance']['enable_result_cache'] = config.enable_result_cache
            
            self._save_config()
            return True
        except Exception as e:
            logger.error(f"更新性能配置失败: {str(e)}")
            return False
    
    def reset_config(self) -> bool:
        """重置配置为默认值"""
        try:
            self.config = self._load_config()
            # 清空现有配置，重新加载默认配置
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
            self.config = self._load_config()
            return True
        except Exception as e:
            logger.error(f"重置配置失败: {str(e)}")
            return False

# 全局系统配置管理器实例
system_config_manager = SystemConfigManager()

# 系统配置API路由

@router.get("/config/system")
async def get_system_config():
    """获取系统配置"""
    try:
        config = system_config_manager.get_config()
        # 隐藏敏感信息
        if config.get('ai', {}).get('hunyuan_api_key'):
            config['ai']['hunyuan_api_key'] = '*' * 8
        if config.get('ai', {}).get('openai_api_key'):
            config['ai']['openai_api_key'] = '*' * 8
        
        return {
            "success": True,
            "config": config
        }
    except Exception as e:
        logger.error(f"获取系统配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")

@router.post("/config/ai")
async def update_ai_config(request: AIConfigRequest):
    """更新AI配置"""
    try:
        success = system_config_manager.update_ai_config(request)
        if success:
            return {"success": True, "message": "AI配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="AI配置更新失败")
    except Exception as e:
        logger.error(f"更新AI配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@router.post("/config/retry")
async def update_retry_config(request: RetryConfigRequest):
    """更新重试配置"""
    try:
        success = system_config_manager.update_retry_config(request)
        if success:
            return {"success": True, "message": "重试配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="重试配置更新失败")
    except Exception as e:
        logger.error(f"更新重试配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@router.post("/config/shell")
async def update_shell_config(request: ShellConfigRequest):
    """更新Shell配置"""
    try:
        success = system_config_manager.update_shell_config(request)
        if success:
            return {"success": True, "message": "Shell配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="Shell配置更新失败")
    except Exception as e:
        logger.error(f"更新Shell配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@router.post("/config/performance")
async def update_performance_config(request: PerformanceConfigRequest):
    """更新性能配置"""
    try:
        success = system_config_manager.update_performance_config(request)
        if success:
            return {"success": True, "message": "性能配置更新成功"}
        else:
            raise HTTPException(status_code=500, detail="性能配置更新失败")
    except Exception as e:
        logger.error(f"更新性能配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")

@router.get("/config/export")
async def export_config():
    """导出配置"""
    try:
        config = system_config_manager.get_config()
        return config
    except Exception as e:
        logger.error(f"导出配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

@router.post("/config/import")
async def import_config(config: Dict[str, Any]):
    """导入配置"""
    try:
        # 验证配置格式
        required_keys = ['ai', 'retry', 'shell', 'performance']
        for key in required_keys:
            if key not in config:
                raise HTTPException(status_code=400, detail=f"配置缺少必需的键: {key}")
        
        # 更新配置
        system_config_manager.config = config
        system_config_manager._save_config()
        
        return {"success": True, "message": "配置导入成功"}
    except Exception as e:
        logger.error(f"导入配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")

@router.post("/config/reset")
async def reset_config():
    """重置配置"""
    try:
        success = system_config_manager.reset_config()
        if success:
            return {"success": True, "message": "配置重置成功"}
        else:
            raise HTTPException(status_code=500, detail="配置重置失败")
    except Exception as e:
        logger.error(f"重置配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"重置失败: {str(e)}")

@router.get("/ai/status")
async def get_ai_status():
    """获取AI服务状态"""
    try:
        # 检查AI客户端是否可用
        from ..core.llm_client import llm_client
        
        if llm_client and hasattr(llm_client, 'client') and llm_client.client:
            return {
                "available": True,
                "model": getattr(llm_client, 'model_name', 'Unknown'),
                "provider": getattr(llm_client, 'provider', 'Unknown')
            }
        else:
            return {
                "available": False,
                "model": None,
                "provider": None
            }
    except Exception as e:
        logger.error(f"获取AI状态失败: {str(e)}")
        return {
            "available": False,
            "model": None,
            "provider": None,
            "error": str(e)
        }

@router.post("/ai/test")
async def test_ai_connection(request: AITestRequest):
    """测试AI连接"""
    try:
        # 这里可以实现AI连接测试逻辑
        # 暂时返回模拟结果
        if request.hunyuan_api_key or request.openai_api_key:
            return {
                "success": True,
                "message": "AI连接测试成功",
                "model": request.preferred_model
            }
        else:
            return {
                "success": False,
                "error": "未提供API密钥"
            }
    except Exception as e:
        logger.error(f"AI连接测试失败: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@router.get("/system/status")
async def get_system_status():
    """获取系统状态"""
    try:
        import platform
        import sys
        import time
        from datetime import datetime, timedelta
        
        # 获取系统信息
        start_time = getattr(get_system_status, '_start_time', time.time())
        if not hasattr(get_system_status, '_start_time'):
            get_system_status._start_time = start_time
        
        uptime_seconds = time.time() - start_time
        uptime = str(timedelta(seconds=int(uptime_seconds)))
        
        # 获取AI状态
        try:
            ai_status_response = await get_ai_status()
            ai_available = ai_status_response.get('available', False)
            ai_model = ai_status_response.get('model', 'Unknown')
        except Exception as e:
            logger.warning(f"获取AI状态失败: {str(e)}")
            ai_available = False
            ai_model = 'Unknown'
        
        # 获取配置状态
        try:
            config = system_config_manager.get_config()
            hunyuan_configured = bool(config.get('ai', {}).get('hunyuan_api_key'))
            openai_configured = bool(config.get('ai', {}).get('openai_api_key'))
        except Exception as e:
            logger.warning(f"获取配置状态失败: {str(e)}")
            config = {}
            hunyuan_configured = False
            openai_configured = False
        
        # 获取安全配置状态
        try:
            security_config = SecurityConfig()
            super_admin_mode = security_config.is_super_admin_enabled()
            allow_shell_commands = security_config.is_shell_commands_enabled()
        except Exception as e:
            logger.warning(f"获取安全配置失败: {str(e)}")
            super_admin_mode = False
            allow_shell_commands = False
        
        # 检查Kubernetes连接
        try:
            import subprocess
            result = subprocess.run(['kubectl', 'version', '--client=true'], 
                                  capture_output=True, text=True, timeout=5)
            kubectl_available = result.returncode == 0
            
            # 尝试获取集群信息
            if kubectl_available:
                try:
                    cluster_result = subprocess.run(['kubectl', 'cluster-info'], 
                                                  capture_output=True, text=True, timeout=10)
                    k8s_connected = cluster_result.returncode == 0
                    
                    # 获取当前上下文
                    context_result = subprocess.run(['kubectl', 'config', 'current-context'], 
                                                  capture_output=True, text=True, timeout=5)
                    current_context = context_result.stdout.strip() if context_result.returncode == 0 else 'Unknown'
                    
                    # 获取集群版本
                    version_result = subprocess.run(['kubectl', 'version', '--short'], 
                                                  capture_output=True, text=True, timeout=10)
                    k8s_version = 'Unknown'
                    if version_result.returncode == 0:
                        lines = version_result.stdout.split('\n')
                        for line in lines:
                            if 'Server Version' in line:
                                k8s_version = line.split(':')[-1].strip()
                                break
                except Exception:
                    k8s_connected = False
                    current_context = 'Unknown'
                    k8s_version = 'Unknown'
            else:
                k8s_connected = False
                current_context = 'Unknown'
                k8s_version = 'Unknown'
        except Exception as e:
            logger.warning(f"检查Kubernetes状态失败: {str(e)}")
            kubectl_available = False
            k8s_connected = False
            current_context = 'Unknown'
            k8s_version = 'Unknown'
        
        return {
            "success": True,
            "status": {
                "system": {
                    "os": f"{platform.system()} {platform.release()}",
                    "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                    "app_version": "1.0.0",
                    "uptime": uptime
                },
                "ai": {
                    "hunyuan_status": "available" if hunyuan_configured else "not_configured",
                    "openai_status": "available" if openai_configured else "not_configured",
                    "current_model": config.get('ai', {}).get('preferred_model', 'auto'),
                    "service_available": ai_available
                },
                "kubernetes": {
                    "connected": k8s_connected,
                    "version": k8s_version,
                    "current_context": current_context,
                    "kubectl_available": kubectl_available
                },
                "security": {
                    "super_admin_mode": super_admin_mode,
                    "allow_shell_commands": allow_shell_commands
                }
            }
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {str(e)}")
        return {
            "success": False,
            "message": str(e),
            "status": {
                "system": {
                    "os": "Unknown",
                    "python_version": "Unknown", 
                    "app_version": "1.0.0",
                    "uptime": "Unknown"
                },
                "ai": {
                    "hunyuan_status": "unknown",
                    "openai_status": "unknown",
                    "current_model": "unknown",
                    "service_available": False
                },
                "kubernetes": {
                    "connected": False,
                    "version": "Unknown",
                    "current_context": "Unknown",
                    "kubectl_available": False
                },
                "security": {
                    "super_admin_mode": False,
                    "allow_shell_commands": False
                }
            }
        }

# 在文件末尾添加缺失的API端点

@router.post("/shell/smart")
async def execute_smart_shell_command(request: ShellCommandRequest):
    """
    智能Shell命令执行 - 专门用于前端智能执行按钮
    
    Args:
        request: shell命令请求
        
    Returns:
        Dict: 执行结果
    """
    try:
        command = request.command.strip()
        timeout = request.timeout or 30
        
        if not command:
            raise HTTPException(status_code=400, detail="命令不能为空")
        
        # 获取LLM客户端进行智能分析
        from ..core.llm_client import SuperKubectlAgent
        llm_client = SuperKubectlAgent()
        
        # 分析自然语言查询
        analysis_result = await llm_client.analyze_shell_query(command)
        
        if analysis_result.get("success"):
            # 检查是否有分步执行计划
            if analysis_result.get("execution_type") == "step_by_step" and analysis_result.get("steps"):
                # 分步执行模式
                steps = analysis_result["steps"]
                logger.info(f"智能执行: 分步执行，共{len(steps)}步")
                
                # 执行第一步
                first_step = steps[0]
                actual_command = first_step["command"]
                logger.info(f"执行第一步命令: {actual_command}")
                
                # 执行命令
                result = await EnhancedKubectlExecutor.execute_command(actual_command, timeout)
                
                # 在结果中添加AI分析信息和步骤信息
                result["ai_analysis"] = analysis_result.get("ai_analysis", "")
                result["original_query"] = command
                result["execution_type"] = "step_by_step"
                result["current_step"] = 1
                result["total_steps"] = len(steps)
                result["step_info"] = first_step
                result["remaining_steps"] = steps[1:] if len(steps) > 1 else []
                result["command_explanation"] = first_step.get("purpose", "")
                
                return result
                
            elif analysis_result.get("generated_command"):
                # 单步执行模式（向后兼容）
                actual_command = analysis_result["generated_command"]
                logger.info(f"智能执行: 单步执行")
                logger.info(f"生成的命令: {actual_command}")
                
                # 执行AI生成的命令
                result = await EnhancedKubectlExecutor.execute_command(actual_command, timeout)
                
                # 在结果中添加AI分析信息
                result["ai_analysis"] = analysis_result.get("ai_analysis", "")
                result["original_query"] = command
                result["generated_command"] = actual_command
                result["command_explanation"] = analysis_result.get("command_explanation", "")
                
                return result
                
            else:
                # AI分析失败，返回错误
                return {
                    "success": False,
                    "command": command,
                    "command_type": "natural_language_query",
                    "output": "",
                    "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                    "return_code": -1,
                    "formatted_result": {
                        "type": "error",
                        "command": command,
                        "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                        "content": ""
                    },
                    "execution_time": timeout,
                    "ai_analysis": analysis_result.get("ai_analysis", ""),
                    "original_query": command
                }
        else:
            # AI分析失败，返回错误
            return {
                "success": False,
                "command": command,
                "command_type": "natural_language_query",
                "output": "",
                "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                "return_code": -1,
                "formatted_result": {
                    "type": "error",
                    "command": command,
                    "error": f"AI分析失败: {analysis_result.get('ai_analysis', '未知错误')}",
                    "content": ""
                },
                "execution_time": timeout,
                "ai_analysis": analysis_result.get("ai_analysis", ""),
                "original_query": command
            }
                
    except Exception as e:
        logger.error(f"智能Shell命令执行失败: {str(e)}")
        return {
            "success": False,
            "command": command,
            "command_type": "smart_execution",
            "output": "",
            "error": f"智能执行失败: {str(e)}",
            "return_code": -1,
            "formatted_result": {
                "type": "error",
                "command": command,
                "error": f"智能执行失败: {str(e)}",
                "content": ""
            },
            "execution_time": timeout,
            "original_query": command
        }

@router.post("/shell/analyze")
async def analyze_shell_query_endpoint(request: ShellCommandRequest):
    """
    Shell查询分析 - 专门用于前端分析按钮
    
    Args:
        request: shell命令请求
        
    Returns:
        Dict: 分析结果
    """
    try:
        command = request.command.strip()
        
        if not command:
            raise HTTPException(status_code=400, detail="命令不能为空")
        
        # 获取LLM客户端进行智能分析
        from ..core.llm_client import SuperKubectlAgent
        llm_client = SuperKubectlAgent()
        
        # 分析自然语言查询
        analysis_result = await llm_client.analyze_shell_query(command)
        
        if analysis_result.get("success"):
            # 格式化分析结果以适配前端显示
            formatted_result = {
                "success": True,
                "query": command,
                "ai_analysis": analysis_result.get("ai_analysis", ""),
                "execution_type": analysis_result.get("execution_type", "single_step"),
                "can_execute": analysis_result.get("can_execute", True),
                "safety_check": analysis_result.get("safety_check", {"is_safe": True, "warning": ""}),
                "recommendations": analysis_result.get("recommendations", [])
            }
            
            # 根据执行类型添加相应信息
            if analysis_result.get("execution_type") == "step_by_step":
                formatted_result["total_steps"] = analysis_result.get("total_steps", 0)
                formatted_result["steps"] = analysis_result.get("steps", [])
                formatted_result["execution_strategy"] = analysis_result.get("execution_strategy", "sequential")
            else:
                # 单步执行模式
                formatted_result["generated_command"] = analysis_result.get("generated_command", "")
                formatted_result["command_explanation"] = analysis_result.get("command_explanation", "")
            
            return formatted_result
        else:
            return {
                "success": False,
                "query": command,
                "error": analysis_result.get("ai_analysis", "分析失败"),
                "ai_analysis": analysis_result.get("ai_analysis", ""),
                "can_execute": False,
                "safety_check": {"is_safe": False, "warning": "分析失败"}
            }
                
    except Exception as e:
        logger.error(f"Shell查询分析失败: {str(e)}")
        return {
            "success": False,
            "query": command,
            "error": f"分析失败: {str(e)}",
            "ai_analysis": f"分析异常: {str(e)}",
            "can_execute": False,
            "safety_check": {"is_safe": False, "warning": "分析异常"}
        }