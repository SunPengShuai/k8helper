from typing import Dict, List, Optional
import yaml
from kubernetes import client
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ResourceCreator:
    """Kubernetes 资源创建工具类"""
    
    def __init__(self, k8s_client: client.CoreV1Api):
        self.k8s_client = k8s_client
        self.apps_v1 = client.AppsV1Api()
        self.networking_v1 = client.NetworkingV1Api()
        
    def create_deployment(self, namespace: str, name: str, 
                         image: str, replicas: int = 1,
                         labels: Optional[Dict] = None) -> Dict:
        """创建 Deployment"""
        try:
            if labels is None:
                labels = {"app": name}
                
            deployment = client.V1Deployment(
                metadata=client.V1ObjectMeta(name=name),
                spec=client.V1DeploymentSpec(
                    replicas=replicas,
                    selector=client.V1LabelSelector(
                        match_labels=labels
                    ),
                    template=client.V1PodTemplateSpec(
                        metadata=client.V1ObjectMeta(labels=labels),
                        spec=client.V1PodSpec(
                            containers=[
                                client.V1Container(
                                    name=name,
                                    image=image
                                )
                            ]
                        )
                    )
                )
            )
            
            result = self.apps_v1.create_namespaced_deployment(
                namespace=namespace,
                body=deployment
            )
            
            return {
                'name': result.metadata.name,
                'namespace': result.metadata.namespace,
                'replicas': result.spec.replicas,
                'status': 'created'
            }
            
        except Exception as e:
            logger.error(f"创建 Deployment 失败: {str(e)}")
            raise
            
    def create_service(self, namespace: str, name: str,
                      selector: Dict, ports: List[Dict]) -> Dict:
        """创建 Service"""
        try:
            service = client.V1Service(
                metadata=client.V1ObjectMeta(name=name),
                spec=client.V1ServiceSpec(
                    selector=selector,
                    ports=[
                        client.V1ServicePort(
                            port=port['port'],
                            target_port=port.get('target_port', port['port']),
                            protocol=port.get('protocol', 'TCP')
                        ) for port in ports
                    ]
                )
            )
            
            result = self.k8s_client.create_namespaced_service(
                namespace=namespace,
                body=service
            )
            
            return {
                'name': result.metadata.name,
                'namespace': result.metadata.namespace,
                'cluster_ip': result.spec.cluster_ip,
                'ports': [{'port': p.port, 'target_port': p.target_port} 
                         for p in result.spec.ports]
            }
            
        except Exception as e:
            logger.error(f"创建 Service 失败: {str(e)}")
            raise
            
    def create_ingress(self, namespace: str, name: str,
                      rules: List[Dict]) -> Dict:
        """创建 Ingress"""
        try:
            ingress_rules = []
            for rule in rules:
                http_paths = []
                for path in rule['paths']:
                    http_paths.append(
                        client.V1HTTPIngressPath(
                            path=path['path'],
                            path_type=path.get('path_type', 'Prefix'),
                            backend=client.V1IngressBackend(
                                service=client.V1IngressServiceBackend(
                                    name=path['service_name'],
                                    port=client.V1ServiceBackendPort(
                                        number=path['service_port']
                                    )
                                )
                            )
                        )
                    )
                    
                ingress_rules.append(
                    client.V1IngressRule(
                        host=rule['host'],
                        http=client.V1HTTPIngressRuleValue(
                            paths=http_paths
                        )
                    )
                )
                
            ingress = client.V1Ingress(
                metadata=client.V1ObjectMeta(name=name),
                spec=client.V1IngressSpec(
                    rules=ingress_rules
                )
            )
            
            result = self.networking_v1.create_namespaced_ingress(
                namespace=namespace,
                body=ingress
            )
            
            return {
                'name': result.metadata.name,
                'namespace': result.metadata.namespace,
                'rules': [
                    {
                        'host': rule.host,
                        'paths': [
                            {
                                'path': path.path,
                                'service': path.backend.service.name
                            } for path in rule.http.paths
                        ]
                    } for rule in result.spec.rules
                ]
            }
            
        except Exception as e:
            logger.error(f"创建 Ingress 失败: {str(e)}")
            raise
            
    def create_from_yaml(self, namespace: str, yaml_content: str) -> Dict:
        """从 YAML 创建资源"""
        try:
            resources = yaml.safe_load_all(yaml_content)
            results = []
            
            for resource in resources:
                kind = resource['kind']
                name = resource['metadata']['name']
                
                if kind == 'Deployment':
                    result = self.apps_v1.create_namespaced_deployment(
                        namespace=namespace,
                        body=resource
                    )
                elif kind == 'Service':
                    result = self.k8s_client.create_namespaced_service(
                        namespace=namespace,
                        body=resource
                    )
                elif kind == 'Ingress':
                    result = self.networking_v1.create_namespaced_ingress(
                        namespace=namespace,
                        body=resource
                    )
                else:
                    logger.warning(f"不支持的资源类型: {kind}")
                    continue
                    
                results.append({
                    'kind': kind,
                    'name': result.metadata.name,
                    'namespace': result.metadata.namespace,
                    'status': 'created'
                })
                
            return {
                'created_resources': results,
                'total': len(results)
            }
            
        except Exception as e:
            logger.error(f"从 YAML 创建资源失败: {str(e)}")
            raise 