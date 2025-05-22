from typing import Dict, List, Optional
import subprocess
from kubernetes import client, config
from ..utils.logger import get_logger
from ..utils.config import Config

logger = get_logger(__name__)

class KubernetesClient:
    def __init__(self):
        """初始化Kubernetes客户端"""
        try:
            config.load_kube_config()
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.batch_v1 = client.BatchV1Api()
            self.networking_v1 = client.NetworkingV1Api()
            self.storage_v1 = client.StorageV1Api()
            self.rbac_v1 = client.RbacAuthorizationV1Api()
            self.autoscaling_v1 = client.AutoscalingV1Api()
            self.custom_objects_api = client.CustomObjectsApi()
        except Exception as e:
            logger.error(f"初始化Kubernetes客户端失败: {str(e)}")
            raise
            
    def execute_command(self, command: str, input_data: Optional[str] = None) -> Dict:
        """
        执行kubectl命令
        
        Args:
            command: kubectl命令
            input_data: 输入数据（用于管道操作）
            
        Returns:
            Dict: 执行结果
        """
        try:
            full_command = f"kubectl {command}"
            process = subprocess.Popen(
                full_command,
                shell=True,
                stdin=subprocess.PIPE if input_data else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            stdout, stderr = process.communicate(input=input_data)
            
            return {
                "success": process.returncode == 0,
                "output": stdout if process.returncode == 0 else stderr,
                "error": stderr if process.returncode != 0 else None
            }
        except Exception as e:
            logger.error(f"执行命令失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            }
            
    def get_pods(self, namespace: str = "default") -> Dict:
        """获取Pod列表"""
        try:
            pods = self.v1.list_namespaced_pod(namespace)
            return {
                "success": True,
                "output": [pod.metadata.name for pod in pods.items]
            }
        except Exception as e:
            logger.error(f"获取Pod列表失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            }
            
    def describe_pod(self, pod_name: str, namespace: str = "default") -> Dict:
        """获取Pod详细信息"""
        try:
            pod = self.v1.read_namespaced_pod(pod_name, namespace)
            return {
                "success": True,
                "output": pod
            }
        except Exception as e:
            logger.error(f"获取Pod详细信息失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            }
            
    def get_pod_logs(self, pod_name: str, namespace: str = "default") -> Dict:
        """获取Pod日志"""
        try:
            logs = self.v1.read_namespaced_pod_log(pod_name, namespace)
            return {
                "success": True,
                "output": logs
            }
        except Exception as e:
            logger.error(f"获取Pod日志失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            }
            
    def get_nodes(self) -> Dict:
        """获取节点列表"""
        try:
            nodes = self.v1.list_node()
            return {
                "success": True,
                "output": [node.metadata.name for node in nodes.items]
            }
        except Exception as e:
            logger.error(f"获取节点列表失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            }
            
    def get_cluster_info(self) -> Dict:
        """获取集群信息"""
        try:
            version = self.v1.get_api_resources()
            return {
                "success": True,
                "output": version
            }
        except Exception as e:
            logger.error(f"获取集群信息失败: {str(e)}")
            return {
                "success": False,
                "output": None,
                "error": str(e)
            } 