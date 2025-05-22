import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    # 基础配置
    APP_NAME = "k8helper"
    VERSION = "0.1.0"
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # API配置
    API_HOST = os.getenv("API_HOST", "0.0.0.0")
    API_PORT = int(os.getenv("API_PORT", "8080"))
    
    # Kubernetes配置
    KUBE_CONFIG = os.getenv("KUBE_CONFIG", str(Path.home() / ".kube" / "config"))
    
    # 腾讯云配置
    TENCENT_SECRET_ID = os.getenv("TENCENT_SECRET_ID", "your_secret_id")
    TENCENT_SECRET_KEY = os.getenv("TENCENT_SECRET_KEY", "sk-aKKx6Qee16fJWZSy6rD8H5blDKeaKIJV76j9SyTBePoxT2Y1")
    TENCENT_REGION = os.getenv("TENCENT_REGION", "ap-guangzhou")
    
    # LLM配置
    HUNYUAN_API_KEY = os.getenv("HUNYUAN_API_KEY", "test_key")  # 临时使用测试密钥
    HUNYUAN_SECRET_KEY = os.getenv("HUNYUAN_SECRET_KEY", "test_secret")  # 临时使用测试密钥
    
    @classmethod
    def validate(cls):
        """验证必要的配置项"""
        # 由于已经设置了默认值，所以不再需要检查是否为空
        return True
            
    @classmethod
    def get_k8s_config(cls):
        """获取Kubernetes配置"""
        return {
            "kubeconfig": cls.KUBE_CONFIG
        }
        
    @classmethod
    def get_tencent_config(cls):
        """获取腾讯云配置"""
        return {
            "secret_id": cls.TENCENT_SECRET_ID,
            "secret_key": cls.TENCENT_SECRET_KEY,
            "region": cls.TENCENT_REGION
        }
        
    @classmethod
    def get_hunyuan_config(cls):
        """获取混元配置"""
        return {
            "api_key": cls.HUNYUAN_API_KEY,
            "secret_key": cls.HUNYUAN_SECRET_KEY
        } 