import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import json

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 设置测试环境变量
os.environ["TESTING"] = "true"
os.environ["OPENAI_API_KEY"] = "test-key"
os.environ["LOG_LEVEL"] = "DEBUG"
os.environ["KUBERNETES_NAMESPACE"] = "test-namespace"
os.environ["KUBERNETES_CONFIG_PATH"] = "/root/.kube/config"

from src.core.agent import K8HelperAgent
from src.utils.k8s_client import KubernetesClient

class TestK8HelperAgent(unittest.TestCase):
    """测试K8HelperAgent类"""
    
    def setUp(self):
        """测试前的准备工作"""
        # 重置KubernetesClient单例
        KubernetesClient.reset_instance()
        
        # 创建agent实例
        self.agent = K8HelperAgent()
        
        # 模拟Kubernetes客户端
        self.agent.k8s_client = MagicMock()
        self.agent.k8s_client._client = MagicMock()
    
    def tearDown(self):
        """测试后的清理工作"""
        pass
    
    def test_analyze_intent(self):
        """测试意图分析"""
        with patch('openai.resources.chat.completions.Completions.create') as mock_create:
            # 模拟OpenAI API响应
            mock_create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content=json.dumps({
                    "tool": "pod_analyzer",
                    "parameters": {"pod_name": "test-pod"}
                })))]
            )
            # 测试意图分析
            intent = self.agent._analyze_intent("检查 test-pod 的状态")
            self.assertEqual(intent["tool"], "pod_analyzer")
            self.assertEqual(intent["parameters"]["pod_name"], "test-pod")
    
    def test_process_query(self):
        """测试查询处理"""
        # 模拟Pod分析结果
        self.agent._analyze_pod = MagicMock(return_value={
            "success": True,
            "message": "Pod状态: Running"
        })
        
        # 模拟意图分析
        with patch.object(self.agent, '_analyze_intent') as mock_analyze_intent:
            mock_analyze_intent.return_value = {
                "tool": "pod_analyzer",
                "parameters": {
                    "pod_name": "test-pod"
                }
            }
            
            # 测试查询处理
            result = self.agent.process_query("检查 test-pod 的状态")
            self.assertTrue(result["success"])
            self.assertEqual(result["message"], "Pod状态: Running")
    
    def test_analyze_pod(self):
        """测试Pod分析"""
        # 模拟Kubernetes客户端响应
        self.agent.k8s_client.get_pod_status.return_value = {
            "status": "Running",
            "message": "Pod状态: Running"
        }
        
        # 测试Pod分析
        result = self.agent._analyze_pod({"pod_name": "test-pod"})
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Pod状态: Running")
    
    def test_create_resource(self):
        """测试资源创建"""
        # 模拟Kubernetes客户端响应
        self.agent.k8s_client.create_deployment.return_value = {
            "name": "test-deployment",
            "replicas": 2,
            "status": "success"
        }
        
        # 测试资源创建
        result = self.agent._create_resource({
            "type": "deployment",
            "name": "test-deployment",
            "image": "nginx:latest",
            "replicas": 2
        })
        self.assertEqual(result["name"], "test-deployment")
        self.assertEqual(result["replicas"], 2)
    
    def test_delete_resource(self):
        """测试资源删除"""
        # 模拟Kubernetes客户端响应
        self.agent.k8s_client.delete_deployment.return_value = None
        
        # 测试资源删除
        result = self.agent._delete_resource({
            "type": "deployment",
            "name": "test-deployment"
        })
        self.assertEqual(result["message"], "成功删除Deployment: test-deployment")

if __name__ == '__main__':
    unittest.main() 