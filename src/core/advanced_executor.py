import asyncio
import subprocess
import shlex
import tempfile
import os
import signal
import threading
import time
from typing import Dict, Any, List, Optional, Tuple
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)

class AdvancedShellExecutor:
    """高级Shell执行器 - 支持复杂shell语法、脚本执行和任务中断"""
    
    def __init__(self):
        self.config = Config()
        self.running_processes: Dict[str, subprocess.Popen] = {}
        self.process_lock = threading.Lock()
        
    def register_process(self, task_id: str, process: subprocess.Popen):
        """注册运行中的进程"""
        with self.process_lock:
            self.running_processes[task_id] = process
            logger.info(f"注册进程: {task_id}, PID: {process.pid}")
    
    def unregister_process(self, task_id: str):
        """注销进程"""
        with self.process_lock:
            if task_id in self.running_processes:
                del self.running_processes[task_id]
                logger.info(f"注销进程: {task_id}")
    
    def terminate_process(self, task_id: str) -> bool:
        """终止指定任务的进程"""
        with self.process_lock:
            if task_id in self.running_processes:
                process = self.running_processes[task_id]
                try:
                    # 尝试优雅终止
                    process.terminate()
                    # 等待3秒
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        # 强制杀死
                        process.kill()
                        process.wait()
                    
                    logger.info(f"成功终止进程: {task_id}, PID: {process.pid}")
                    return True
                except Exception as e:
                    logger.error(f"终止进程失败: {task_id}, 错误: {str(e)}")
                    return False
        return False
    
    async def execute_command(self, command: str, task_id: Optional[str] = None, 
                            timeout: int = 300, check_cancelled_callback=None) -> Dict[str, Any]:
        """
        执行命令，支持复杂shell语法
        
        Args:
            command: 要执行的命令
            task_id: 任务ID，用于中断控制
            timeout: 超时时间（秒）
            check_cancelled_callback: 检查是否被取消的回调函数
            
        Returns:
            Dict: 执行结果
        """
        try:
            logger.info(f"执行高级命令: {command}")
            
            # 检查是否是kubectl命令，如果是则添加前缀
            if self._is_kubectl_command(command):
                command = f"kubectl {command}"
            
            # 创建临时脚本文件来执行复杂命令
            script_content = self._prepare_script(command)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as script_file:
                script_file.write(script_content)
                script_path = script_file.name
            
            try:
                # 使脚本可执行
                os.chmod(script_path, 0o755)
                
                # 执行脚本
                process = subprocess.Popen(
                    ['/bin/bash', script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid  # 创建新的进程组
                )
                
                if task_id:
                    self.register_process(task_id, process)
                
                # 异步等待进程完成，支持中断检查
                stdout_lines = []
                stderr_lines = []
                
                start_time = time.time()
                
                while process.poll() is None:
                    # 检查是否被取消
                    if check_cancelled_callback and check_cancelled_callback(task_id):
                        logger.info(f"任务 {task_id} 被取消，终止进程")
                        try:
                            # 终止整个进程组
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            process.wait(timeout=3)
                        except:
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except:
                                pass
                        
                        return {
                            "success": False,
                            "error": "任务被用户中断",
                            "output": "",
                            "cancelled": True
                        }
                    
                    # 检查超时
                    if time.time() - start_time > timeout:
                        logger.warning(f"命令执行超时: {command}")
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            process.wait(timeout=3)
                        except:
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except:
                                pass
                        
                        return {
                            "success": False,
                            "error": f"命令执行超时 ({timeout}秒)",
                            "output": "",
                            "timeout": True
                        }
                    
                    # 短暂等待
                    await asyncio.sleep(0.1)
                
                # 获取输出
                stdout, stderr = process.communicate()
                return_code = process.returncode
                
                if task_id:
                    self.unregister_process(task_id)
                
                # 处理结果
                success = return_code == 0
                output = stdout.strip() if stdout else ""
                error = stderr.strip() if stderr else ""
                
                if not success and not error:
                    error = f"命令执行失败，返回码: {return_code}"
                
                logger.info(f"命令执行完成: 成功={success}, 返回码={return_code}")
                
                return {
                    "success": success,
                    "output": output,
                    "error": error if not success else "",
                    "return_code": return_code
                }
                
            finally:
                # 清理临时脚本文件
                try:
                    os.unlink(script_path)
                except:
                    pass
                
        except Exception as e:
            logger.error(f"执行命令失败: {str(e)}")
            if task_id:
                self.unregister_process(task_id)
            
            return {
                "success": False,
                "error": f"执行失败: {str(e)}",
                "output": ""
            }
    
    def _is_kubectl_command(self, command: str) -> bool:
        """检查是否是kubectl命令"""
        # 如果命令已经以kubectl开头，则不是
        if command.strip().startswith('kubectl'):
            return False
        
        # 检查是否是kubectl子命令
        kubectl_subcommands = [
            'get', 'describe', 'create', 'delete', 'apply', 'patch', 'replace',
            'logs', 'exec', 'port-forward', 'proxy', 'cp', 'auth', 'config',
            'cluster-info', 'top', 'cordon', 'uncordon', 'drain', 'taint',
            'label', 'annotate', 'scale', 'autoscale', 'rollout', 'set',
            'wait', 'attach', 'run', 'expose', 'edit', 'explain'
        ]
        
        first_word = command.strip().split()[0] if command.strip() else ""
        return first_word in kubectl_subcommands
    
    def _prepare_script(self, command: str) -> str:
        """准备执行脚本"""
        script_lines = [
            "#!/bin/bash",
            "set -e",  # 遇到错误立即退出
            "set -o pipefail",  # 管道中任何命令失败都会导致整个管道失败
            "",
            "# 设置环境变量",
            "export KUBECONFIG=${KUBECONFIG:-~/.kube/config}",
            "",
            "# 执行命令",
            command
        ]
        
        return "\n".join(script_lines)
    
    async def execute_script(self, script_content: str, task_id: Optional[str] = None,
                           timeout: int = 600, check_cancelled_callback=None) -> Dict[str, Any]:
        """
        执行脚本内容
        
        Args:
            script_content: 脚本内容
            task_id: 任务ID
            timeout: 超时时间
            check_cancelled_callback: 检查取消的回调
            
        Returns:
            Dict: 执行结果
        """
        try:
            logger.info(f"执行脚本，任务ID: {task_id}")
            
            # 创建临时脚本文件
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as script_file:
                script_file.write(script_content)
                script_path = script_file.name
            
            try:
                # 使脚本可执行
                os.chmod(script_path, 0o755)
                
                # 执行脚本
                process = subprocess.Popen(
                    ['/bin/bash', script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    preexec_fn=os.setsid
                )
                
                if task_id:
                    self.register_process(task_id, process)
                
                # 异步等待并支持中断
                start_time = time.time()
                
                while process.poll() is None:
                    # 检查取消
                    if check_cancelled_callback and check_cancelled_callback(task_id):
                        logger.info(f"脚本任务 {task_id} 被取消")
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            process.wait(timeout=3)
                        except:
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except:
                                pass
                        
                        return {
                            "success": False,
                            "error": "脚本执行被用户中断",
                            "output": "",
                            "cancelled": True
                        }
                    
                    # 检查超时
                    if time.time() - start_time > timeout:
                        logger.warning(f"脚本执行超时")
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            process.wait(timeout=3)
                        except:
                            try:
                                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                            except:
                                pass
                        
                        return {
                            "success": False,
                            "error": f"脚本执行超时 ({timeout}秒)",
                            "output": "",
                            "timeout": True
                        }
                    
                    await asyncio.sleep(0.1)
                
                # 获取结果
                stdout, stderr = process.communicate()
                return_code = process.returncode
                
                if task_id:
                    self.unregister_process(task_id)
                
                success = return_code == 0
                output = stdout.strip() if stdout else ""
                error = stderr.strip() if stderr else ""
                
                if not success and not error:
                    error = f"脚本执行失败，返回码: {return_code}"
                
                return {
                    "success": success,
                    "output": output,
                    "error": error if not success else "",
                    "return_code": return_code
                }
                
            finally:
                try:
                    os.unlink(script_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"执行脚本失败: {str(e)}")
            if task_id:
                self.unregister_process(task_id)
            
            return {
                "success": False,
                "error": f"脚本执行失败: {str(e)}",
                "output": ""
            }
    
    def get_running_tasks(self) -> List[str]:
        """获取当前运行中的任务列表"""
        with self.process_lock:
            return list(self.running_processes.keys())
    
    def terminate_all_tasks(self):
        """终止所有运行中的任务"""
        with self.process_lock:
            task_ids = list(self.running_processes.keys())
            for task_id in task_ids:
                self.terminate_process(task_id) 