import subprocess
import shlex
import re
import json
import yaml
from typing import Dict, Any, List, Optional
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)

class KubectlExecutor:
    """Kubectl命令执行器"""
    
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
        执行kubectl命令
        
        Args:
            command: kubectl命令（不包含kubectl前缀）
            
        Returns:
            Dict: 执行结果
        """
        try:
            # 确保命令以kubectl开头
            if not command.strip().startswith('kubectl'):
                command = f"kubectl {command}"
            
            logger.info(f"执行kubectl命令: {command}")
            
            # 安全检查
            if not self._is_command_safe(command):
                return {
                    "success": False,
                    "error": "命令被安全策略阻止",
                    "output": ""
                }
            
            # 执行命令
            result = subprocess.run(
                shlex.split(command),
                capture_output=True,
                text=True,
                timeout=60
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
                "return_code": result.returncode
            }
            
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "命令执行超时",
                "output": ""
            }
        except Exception as e:
            logger.error(f"执行kubectl命令失败: {str(e)}")
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": ""
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
                logger.warning(f"危险命令被阻止: {subcommand}")
                return False
            
            # 检查特殊命令
            if subcommand == 'create':
                return self._is_create_safe(parts)
            elif subcommand == 'apply':
                return self._is_apply_safe(parts)
            elif subcommand == 'scale':
                return self._is_scale_safe(parts)
            
            # 默认允许其他命令
            return True
            
        except Exception as e:
            logger.error(f"安全检查失败: {str(e)}")
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