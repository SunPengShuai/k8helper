import pytest
from unittest.mock import MagicMock, patch
from kubernetes import client
from ..core.pod_analyzer import PodAnalyzer

@pytest.fixture
def mock_k8s_client():
    """创建模拟的 Kubernetes 客户端"""
    return MagicMock(spec=client.CoreV1Api)

@pytest.fixture
def pod_analyzer(mock_k8s_client):
    """创建 PodAnalyzer 实例"""
    return PodAnalyzer(mock_k8s_client)

def test_get_pod_status(pod_analyzer, mock_k8s_client):
    """测试获取 Pod 状态"""
    # 准备测试数据
    namespace = "test-namespace"
    pod_name = "test-pod"
    
    # 创建模拟的 Pod 对象
    mock_pod = MagicMock()
    mock_pod.metadata.name = pod_name
    mock_pod.metadata.namespace = namespace
    mock_pod.status.phase = "Running"
    mock_pod.status.host_ip = "10.0.0.1"
    mock_pod.status.pod_ip = "10.0.0.2"
    
    # 模拟容器状态
    mock_container = MagicMock()
    mock_container.name = "test-container"
    mock_container.ready = True
    mock_container.restart_count = 0
    mock_container.state.running = MagicMock()
    mock_container.state.running.started_at = "2024-01-01T00:00:00Z"
    mock_pod.status.container_statuses = [mock_container]
    
    # 模拟 Pod 条件
    mock_condition = MagicMock()
    mock_condition.type = "Ready"
    mock_condition.status = "True"
    mock_condition.reason = "PodReady"
    mock_condition.message = "Pod is ready"
    mock_pod.status.conditions = [mock_condition]
    
    # 配置模拟对象
    mock_k8s_client.read_namespaced_pod.return_value = mock_pod
    
    # 执行测试
    result = pod_analyzer.get_pod_status(namespace, pod_name)
    
    # 验证结果
    assert result['name'] == pod_name
    assert result['namespace'] == namespace
    assert result['status'] == "Running"
    assert result['host_ip'] == "10.0.0.1"
    assert result['pod_ip'] == "10.0.0.2"
    assert len(result['containers']) == 1
    assert result['containers'][0]['name'] == "test-container"
    assert result['containers'][0]['ready'] is True
    assert result['containers'][0]['restart_count'] == 0
    assert result['containers'][0]['state']['type'] == "running"
    mock_k8s_client.read_namespaced_pod.assert_called_once_with(
        name=pod_name,
        namespace=namespace
    )

def test_get_container_state(pod_analyzer):
    """测试获取容器状态"""
    # 测试运行状态
    running_state = MagicMock()
    running_state.running = MagicMock()
    running_state.running.started_at = "2024-01-01T00:00:00Z"
    running_state.waiting = None
    running_state.terminated = None
    
    result = pod_analyzer._get_container_state(running_state)
    assert result['type'] == "running"
    assert result['started_at'] == "2024-01-01T00:00:00Z"
    
    # 测试等待状态
    waiting_state = MagicMock()
    waiting_state.running = None
    waiting_state.waiting = MagicMock()
    waiting_state.waiting.reason = "ContainerCreating"
    waiting_state.waiting.message = "Creating container"
    waiting_state.terminated = None
    
    result = pod_analyzer._get_container_state(waiting_state)
    assert result['type'] == "waiting"
    assert result['reason'] == "ContainerCreating"
    assert result['message'] == "Creating container"
    
    # 测试终止状态
    terminated_state = MagicMock()
    terminated_state.running = None
    terminated_state.waiting = None
    terminated_state.terminated = MagicMock()
    terminated_state.terminated.reason = "Completed"
    terminated_state.terminated.message = "Container completed"
    terminated_state.terminated.exit_code = 0
    terminated_state.terminated.started_at = "2024-01-01T00:00:00Z"
    terminated_state.terminated.finished_at = "2024-01-01T00:01:00Z"
    
    result = pod_analyzer._get_container_state(terminated_state)
    assert result['type'] == "terminated"
    assert result['reason'] == "Completed"
    assert result['message'] == "Container completed"
    assert result['exit_code'] == 0
    assert result['started_at'] == "2024-01-01T00:00:00Z"
    assert result['finished_at'] == "2024-01-01T00:01:00Z"

def test_analyze_pod_health(pod_analyzer, mock_k8s_client):
    """测试分析 Pod 健康状态"""
    # 准备测试数据
    namespace = "test-namespace"
    pod_name = "test-pod"
    
    # 创建模拟的 Pod 对象
    mock_pod = MagicMock()
    mock_pod.metadata.name = pod_name
    mock_pod.metadata.namespace = namespace
    mock_pod.status.phase = "Running"
    
    # 模拟容器状态
    mock_container = MagicMock()
    mock_container.name = "test-container"
    mock_container.ready = False
    mock_container.restart_count = 3
    mock_container.state.waiting = MagicMock()
    mock_container.state.waiting.reason = "CrashLoopBackOff"
    mock_container.state.waiting.message = "Container is crashing"
    mock_pod.status.container_statuses = [mock_container]
    
    # 模拟 Pod 条件
    mock_condition = MagicMock()
    mock_condition.type = "Ready"
    mock_condition.status = "False"
    mock_condition.reason = "ContainersNotReady"
    mock_condition.message = "Containers are not ready"
    mock_pod.status.conditions = [mock_condition]
    
    # 配置模拟对象
    mock_k8s_client.read_namespaced_pod.return_value = mock_pod
    
    # 执行测试
    result = pod_analyzer.analyze_pod_health(namespace, pod_name)
    
    # 验证结果
    assert result['pod_name'] == pod_name
    assert result['namespace'] == namespace
    assert result['overall_status'] == "unhealthy"
    assert result['pod_phase'] == "Running"
    assert len(result['container_health']) == 1
    assert result['container_health'][0]['status'] == "unhealthy"
    assert result['container_health'][0]['restart_count'] == 3
    assert len(result['pod_conditions']) == 1
    assert len(result['recommendations']) > 0

def test_list_pods(pod_analyzer, mock_k8s_client):
    """测试列出 Pod"""
    # 准备测试数据
    namespace = "test-namespace"
    
    # 创建模拟的 Pod 列表
    mock_pod = MagicMock()
    mock_pod.metadata.name = "test-pod"
    mock_pod.metadata.namespace = namespace
    mock_pod.metadata.labels = {"app": "test"}
    mock_pod.status.phase = "Running"
    mock_pod.status.host_ip = "10.0.0.1"
    mock_pod.status.pod_ip = "10.0.0.2"
    
    mock_container = MagicMock()
    mock_container.name = "test-container"
    mock_container.image = "test-image:latest"
    mock_pod.spec.containers = [mock_container]
    
    mock_pod_list = MagicMock()
    mock_pod_list.items = [mock_pod]
    mock_k8s_client.list_namespaced_pod.return_value = mock_pod_list
    
    # 执行测试
    result = pod_analyzer.list_pods(namespace)
    
    # 验证结果
    assert len(result) == 1
    assert result[0]['name'] == "test-pod"
    assert result[0]['namespace'] == namespace
    assert result[0]['status'] == "Running"
    assert result[0]['labels'] == {"app": "test"}
    assert len(result[0]['containers']) == 1
    assert result[0]['containers'][0]['name'] == "test-container"
    assert result[0]['containers'][0]['image'] == "test-image:latest"
    mock_k8s_client.list_namespaced_pod.assert_called_once_with(
        namespace=namespace,
        label_selector=None
    )

def test_get_pod_status_error(pod_analyzer, mock_k8s_client):
    """测试获取 Pod 状态时的错误处理"""
    # 配置模拟对象抛出异常
    mock_k8s_client.read_namespaced_pod.side_effect = Exception("API Error")
    
    # 验证异常被正确抛出
    with pytest.raises(Exception) as exc_info:
        pod_analyzer.get_pod_status("test-namespace", "test-pod")
    
    assert "API Error" in str(exc_info.value) 