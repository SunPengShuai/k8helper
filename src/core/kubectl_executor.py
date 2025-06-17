import subprocess
import shlex
import re
import json
import yaml
import os
from typing import Dict, Any, List, Optional
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)

class KubectlExecutor:
    """Kubectl命令执行器 - 支持完整命令和shell命令"""
    
    # 危险命令列表
    DANGEROUS_COMMANDS = [
        'delete', 'drain', 'cordon', 'uncordon', 'taint', 'patch', 'replace'
    ]
    
    # 安全命令列表
    SAFE_COMMANDS = [
        'get', 'describe', 'logs', 'top', 'explain', 'version', 'cluster-info',
        'config', 'auth', 'api-resources', 'api-versions'
    ]
    
    # 安全的创建资源类型
    SAFE_CREATE_RESOURCES = [
        'configmap', 'secret', 'namespace', 'serviceaccount', 'deployment', 
        'service', 'pod', 'replicaset', 'daemonset', 'statefulset', 'job', 'cronjob'
    ]
    
    # 安全的apply资源类型
    SAFE_APPLY_RESOURCES = [
        'deployment', 'service', 'configmap', 'secret', 'ingress', 'pod',
        'replicaset', 'daemonset', 'statefulset', 'job', 'cronjob'
    ]
    
    # 安全的scale资源类型
    SAFE_SCALE_RESOURCES = [
        'deployment', 'replicaset', 'statefulset'
    ]
    
    # 安全的shell命令
    SAFE_SHELL_COMMANDS = [
        'ls', 'pwd', 'cat', 'echo', 'df', 'free', 'ps', 'whoami', 
        'date', 'uname', 'head', 'tail', 'grep', 'wc', 'sort', 'uniq',
        'find', 'which', 'whereis', 'id', 'uptime', 'hostname'
    ]
    
    # 危险的shell命令
    DANGEROUS_SHELL_COMMANDS = [
        'rm', 'rmdir', 'mv', 'cp', 'chmod', 'chown', 'sudo', 'su',
        'kill', 'killall', 'pkill', 'reboot', 'shutdown', 'halt',
        'dd', 'fdisk', 'mkfs', 'mount', 'umount', 'format', 'del'
    ]
    
    def __init__(self, security_config=None):
        self.config = Config()
        self.security_config = security_config
        
    def _get_security_config(self):
        """获取安全配置实例"""
        if self.security_config:
            return self.security_config
        
        # 动态导入避免循环依赖
        try:
            from ..api.routes import SecurityConfig
            return SecurityConfig()
        except ImportError:
            logger.warning("无法导入SecurityConfig，使用默认安全策略")
            return None
        
    def execute_command(self, command: str) -> Dict[str, Any]:
        """
        执行完整命令（kubectl命令或shell命令）
        
        Args:
            command: 完整的命令（包含kubectl前缀或其他命令前缀）
            
        Returns:
            Dict: 执行结果
        """
        try:
            command = command.strip()
            if not command:
                return {
                    "success": False,
                    "error": "命令不能为空",
                    "output": ""
                }
            
            logger.info(f"执行命令: {command}")
            
            # 安全检查
            if not self._is_command_safe(command):
                return {
                    "success": False,
                    "error": "命令被安全策略阻止",
                    "output": ""
                }
            
            # 检测命令类型并执行
            if self._is_kubectl_command(command):
                return self._execute_kubectl_command(command)
            elif self._is_shell_pipeline(command):
                return self._execute_shell_pipeline(command)
            else:
                return self._execute_shell_command(command)
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "命令执行超时",
                "output": ""
            }
        except Exception as e:
            logger.error(f"执行命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": ""
            }
    
    def _is_kubectl_command(self, command: str) -> bool:
        """检查是否是kubectl命令"""
        return command.startswith('kubectl ')
    
    def _is_shell_pipeline(self, command: str) -> bool:
        """检查是否是shell管道命令"""
        return '|' in command or '&&' in command or '||' in command or '$(' in command
    
    def _execute_kubectl_command(self, command: str) -> Dict[str, Any]:
        """执行kubectl命令"""
        try:
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.getcwd()
            )
            
            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            
            if not success and not error:
                error = f"命令执行失败，返回码: {result.returncode}"
            
            return {
                "success": success,
                "output": output,
                "error": error if not success else "",
                "return_code": result.returncode,
                "command_type": "kubectl"
            }
            
        except Exception as e:
            logger.error(f"执行kubectl命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"kubectl命令执行失败: {str(e)}",
                "output": "",
                "command_type": "kubectl"
            }
    
    def _execute_shell_pipeline(self, command: str) -> Dict[str, Any]:
        """执行shell管道命令"""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.getcwd()
            )
            
            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            
            if not success and not error:
                error = f"命令执行失败，返回码: {result.returncode}"
            
            return {
                "success": success,
                "output": output,
                "error": error if not success else "",
                "return_code": result.returncode,
                "command_type": "shell_pipeline"
            }
            
        except Exception as e:
            logger.error(f"执行shell管道命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"shell管道命令执行失败: {str(e)}",
                "output": "",
                "command_type": "shell_pipeline"
            }
    
    def _execute_shell_command(self, command: str) -> Dict[str, Any]:
        """执行简单shell命令"""
        try:
            # 对于简单命令，优先使用shlex.split
            try:
                result = subprocess.run(
                    shlex.split(command),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=os.getcwd()
                )
            except ValueError:
                # 如果shlex.split失败，使用shell=True
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=os.getcwd()
                )
            
            success = result.returncode == 0
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            
            if not success and not error:
                error = f"命令执行失败，返回码: {result.returncode}"
            
            return {
                "success": success,
                "output": output,
                "error": error if not success else "",
                "return_code": result.returncode,
                "command_type": "shell"
            }
            
        except Exception as e:
            logger.error(f"执行shell命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"shell命令执行失败: {str(e)}",
                "output": "",
                "command_type": "shell"
            }
    
    def _is_command_safe(self, command: str) -> bool:
        """检查命令是否安全"""
        try:
            # 获取安全配置
            security_config = self._get_security_config()
            
            # 如果启用了超级管理员模式，允许所有命令
            if security_config and security_config.is_super_admin_enabled():
                logger.info("超级管理员模式已启用，允许执行所有命令")
                return True
            
            # 检查是否是kubectl命令
            if self._is_kubectl_command(command):
                return self._is_kubectl_safe(command)
            else:
                return self._is_shell_command_safe(command)
            
        except Exception as e:
            logger.error(f"安全检查失败: {str(e)}")
            return False
    
    def _is_kubectl_safe(self, command: str) -> bool:
        """检查kubectl命令是否安全"""
        try:
            # 解析命令
            parts = shlex.split(command)
            if len(parts) < 2:
                return False
            
            # 第一个参数应该是kubectl
            if parts[0] != 'kubectl':
                return False
            
            # 获取子命令
            subcommand = parts[1]
            
            # 检查是否是安全命令
            if subcommand in self.SAFE_COMMANDS:
                return True
            
            # 检查是否是危险命令
            if subcommand in self.DANGEROUS_COMMANDS:
                logger.warning(f"危险kubectl命令被阻止: {subcommand}")
                return False
            
            # 检查特殊命令
            if subcommand == 'create':
                return self._is_create_safe(parts)
            elif subcommand == 'apply':
                return self._is_apply_safe(parts)
            elif subcommand == 'scale':
                return self._is_scale_safe(parts)
            
            # 默认允许其他kubectl命令
            return True
            
        except Exception as e:
            logger.error(f"kubectl安全检查失败: {str(e)}")
            return False
    
    def _is_shell_command_safe(self, command: str) -> bool:
        """检查shell命令是否安全"""
        try:
            # 获取安全配置
            security_config = self._get_security_config()
            
            # 如果禁用了shell命令，则不允许
            if security_config and not security_config.is_shell_commands_enabled():
                logger.warning("Shell命令被禁用")
                return False
            
            # 对于管道命令，检查每个组件
            if self._is_shell_pipeline(command):
                return self._is_pipeline_safe(command)
            
            # 获取第一个单词（命令名）
            first_word = command.strip().split()[0] if command.strip() else ""
            
            # 检查是否是危险命令
            if first_word in self.DANGEROUS_SHELL_COMMANDS:
                logger.warning(f"危险shell命令被阻止: {first_word}")
                return False
            
            # 检查是否是安全命令
            if first_word in self.SAFE_SHELL_COMMANDS:
                return True
            
            # 对于其他命令，默认不允许（除非在超级管理员模式下）
            logger.warning(f"未知shell命令被阻止: {first_word}")
            return False
            
        except Exception as e:
            logger.error(f"shell安全检查失败: {str(e)}")
            return False
    
    def _is_pipeline_safe(self, command: str) -> bool:
        """检查管道命令是否安全"""
        try:
            # 简单的管道安全检查 - 检查是否包含危险命令
            for dangerous_cmd in self.DANGEROUS_SHELL_COMMANDS:
                if dangerous_cmd in command:
                    logger.warning(f"管道命令包含危险命令: {dangerous_cmd}")
                    return False
            
            # 如果包含kubectl，认为是安全的
            if 'kubectl' in command:
                return True
            
            # 检查是否只包含安全的shell命令
            words = re.findall(r'\b\w+\b', command)
            for word in words:
                if word in self.DANGEROUS_SHELL_COMMANDS:
                    logger.warning(f"管道命令包含危险命令: {word}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"管道安全检查失败: {str(e)}")
            return False
    
    def _is_create_safe(self, parts: List[str]) -> bool:
        """检查create命令是否安全"""
        if len(parts) < 3:
            return False
        
        resource_type = parts[2]
        return resource_type in self.SAFE_CREATE_RESOURCES
    
    def _is_apply_safe(self, parts: List[str]) -> bool:
        """检查apply命令是否安全"""
        # apply命令相对安全，但可以添加更多检查
        return True
    
    def _is_scale_safe(self, parts: List[str]) -> bool:
        """检查scale命令是否安全"""
        if len(parts) < 3:
            return False
        
        resource_type = parts[2].split('/')[0]  # 处理 deployment/name 格式
        return resource_type in self.SAFE_SCALE_RESOURCES
    
    @staticmethod
    async def execute_kubectl(command: str) -> Dict[str, Any]:
        """静态方法，用于向后兼容"""
        # 动态导入避免循环依赖
        try:
            from ..api.routes import security_config
            executor = KubectlExecutor(security_config)
        except ImportError:
            logger.warning("无法导入security_config，使用默认安全策略")
            executor = KubectlExecutor()
        return executor.execute_command(command) 