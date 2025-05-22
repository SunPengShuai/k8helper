from kubernetes import client, config
from typing import Dict, Any

class KubernetesClient:
    def __init__(self):
        self.v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        self.metrics_api = client.CustomObjectsApi()

def init_kubernetes_client() -> KubernetesClient:
    """初始化 Kubernetes 客户端"""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return KubernetesClient() 