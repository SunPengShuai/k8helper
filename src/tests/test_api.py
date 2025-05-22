import pytest
from fastapi.testclient import TestClient
from ..main import app

client = TestClient(app)

def test_health_check():
    """测试健康检查接口"""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_query_pod():
    """测试Pod查询接口"""
    response = client.post(
        "/api/v1/query",
        json={
            "query": "查看名为nginx的Pod状态",
            "context": {
                "available_tools": [
                    {
                        "name": "pod_analyzer",
                        "description": "分析Pod状态和日志"
                    }
                ]
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "analysis" in data
    assert "raw_result" in data 