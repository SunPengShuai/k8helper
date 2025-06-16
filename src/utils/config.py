import os
import yaml
from pathlib import Path
from typing import Dict, Any, List

class Config:
    """统一配置管理类"""
    
    _config_data = None
    _config_file_path = None
    
    @classmethod
    def _load_config(cls):
        """加载配置文件"""
        if cls._config_data is None:
            # 确定配置文件路径
            if cls._config_file_path is None:
                current_dir = Path(__file__).parent.parent.parent
                cls._config_file_path = current_dir / "config.yml"
            
            # 读取配置文件
            try:
                with open(cls._config_file_path, 'r', encoding='utf-8') as f:
                    cls._config_data = yaml.safe_load(f)
            except FileNotFoundError:
                raise FileNotFoundError(f"配置文件未找到: {cls._config_file_path}")
            except yaml.YAMLError as e:
                raise ValueError(f"配置文件格式错误: {e}")
    
    @classmethod
    def _get_config_value(cls, key_path: str, default=None):
        """获取配置值，支持嵌套键路径如 'app.name'"""
        cls._load_config()
        
        keys = key_path.split('.')
        value = cls._config_data
        
        try:
            for key in keys:
                value = value[key]
            
            # 处理环境变量替换
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                return os.getenv(env_var, default)
            
            return value
        except (KeyError, TypeError):
            # 如果配置不存在，尝试从环境变量获取
            env_key = key_path.upper().replace('.', '_')
            return os.getenv(env_key, default)
    
    # 基础配置
    @classmethod
    @property
    def APP_NAME(cls):
        return cls._get_config_value('app.name', 'k8helper')
    
    @classmethod
    @property
    def VERSION(cls):
        return cls._get_config_value('app.version', '0.1.0')
    
    @classmethod
    @property
    def DEBUG(cls):
        debug_value = cls._get_config_value('app.debug', False)
        if isinstance(debug_value, str):
            return debug_value.lower() == 'true'
        return debug_value
    
    # API配置
    @classmethod
    @property
    def API_HOST(cls):
        return cls._get_config_value('api.host', '0.0.0.0')
    
    @classmethod
    @property
    def API_PORT(cls):
        port = cls._get_config_value('api.port', 8080)
        return int(port)
    
    @classmethod
    @property
    def API_RELOAD(cls):
        return cls._get_config_value('api.reload', True)
    
    # Kubernetes配置
    @classmethod
    @property
    def KUBE_CONFIG(cls):
        config_path = cls._get_config_value('kubernetes.config_path', '~/.kube/config')
        return str(Path(config_path).expanduser())
    
    @classmethod
    @property
    def KUBE_NAMESPACE(cls):
        return cls._get_config_value('kubernetes.namespace', 'default')
    
    # 腾讯云配置
    @classmethod
    @property
    def TENCENT_SECRET_ID(cls):
        return cls._get_config_value('tencent.secret_id', 'your_secret_id')
    
    @classmethod
    @property
    def TENCENT_SECRET_KEY(cls):
        return cls._get_config_value('tencent.secret_key', 'your_secret_key')
    
    @classmethod
    @property
    def TENCENT_REGION(cls):
        return cls._get_config_value('tencent.region', 'ap-guangzhou')
    
    # LLM配置
    @classmethod
    @property
    def HUNYUAN_API_KEY(cls):
        return cls._get_config_value('llm.hunyuan.api_key', 'test_key')
    
    @classmethod
    @property
    def HUNYUAN_SECRET_KEY(cls):
        return cls._get_config_value('llm.hunyuan.secret_key', 'test_secret')
    
    @classmethod
    @property
    def OPENAI_API_KEY(cls):
        return cls._get_config_value('llm.openai.api_key', None)
    
    # 日志配置
    @classmethod
    @property
    def LOG_LEVEL(cls):
        return cls._get_config_value('logging.level', 'INFO')
    
    @classmethod
    @property
    def LOG_DIR(cls):
        return cls._get_config_value('logging.log_dir', 'logs')
    
    @classmethod
    @property
    def LOG_FILE_NAME(cls):
        return cls._get_config_value('logging.file_name', 'k8helper.log')
    
    # 安全配置
    @classmethod
    def get_security_config(cls) -> Dict[str, Any]:
        """获取安全配置"""
        cls._load_config()
        return cls._config_data.get('security', {})
    
    @classmethod
    def get_dangerous_commands(cls) -> List[str]:
        """获取危险命令列表"""
        return cls._get_config_value('security.dangerous_commands', [])
    
    @classmethod
    def get_safe_commands(cls) -> List[str]:
        """获取安全命令列表"""
        return cls._get_config_value('security.safe_commands', [])
    
    @classmethod
    def get_safe_create_resources(cls) -> List[str]:
        """获取安全创建资源列表"""
        return cls._get_config_value('security.safe_create_resources', [])
    
    @classmethod
    def get_safe_scale_resources(cls) -> List[str]:
        """获取安全扩缩容资源列表"""
        return cls._get_config_value('security.safe_scale_resources', [])
    
    @classmethod
    def get_safe_apply_resources(cls) -> List[str]:
        """获取安全应用资源列表"""
        return cls._get_config_value('security.safe_apply_resources', [])
    
    # CORS配置
    @classmethod
    def get_cors_config(cls) -> Dict[str, Any]:
        """获取CORS配置"""
        return cls._get_config_value('api.cors', {
            'allow_origins': ['*'],
            'allow_credentials': True,
            'allow_methods': ['*'],
            'allow_headers': ['*']
        })
    
    # 服务配置
    @classmethod
    def get_services_config(cls) -> List[Dict[str, Any]]:
        """获取服务配置"""
        return cls._get_config_value('services', [])
    
    # 工具配置
    @classmethod
    def get_tools_config(cls) -> List[Dict[str, Any]]:
        """获取工具配置"""
        return cls._get_config_value('tools', [])
    
    # Docker配置
    @classmethod
    def get_docker_config(cls) -> Dict[str, Any]:
        """获取Docker配置"""
        return cls._get_config_value('docker', {})
    
    @classmethod
    def validate(cls):
        """验证配置"""
        try:
            cls._load_config()
            # 检查关键配置项
            if not cls.APP_NAME:
                raise ValueError("应用名称不能为空")
            if cls.API_PORT <= 0 or cls.API_PORT > 65535:
                raise ValueError("API端口必须在1-65535范围内")
            return True
        except Exception as e:
            raise ValueError(f"配置验证失败: {str(e)}")
    
    @classmethod
    def get_k8s_config(cls):
        """获取Kubernetes配置"""
        return {
            "kubeconfig": cls.KUBE_CONFIG,
            "namespace": cls.KUBE_NAMESPACE
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
    
    @classmethod
    def set_config_file_path(cls, path: str):
        """设置配置文件路径"""
        cls._config_file_path = Path(path)
        cls._config_data = None  # 重置配置数据以便重新加载 