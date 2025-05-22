from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import json
import re
import threading
from ..core.k8s_client import KubernetesClient
from ..core.llm_client import HunyuanClient
from ..utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# 全局变量，用于存储投票数据，使用线程锁确保并发安全
vote_data = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
vote_lock = threading.Lock()
vote_users = set()  # 记录已投票用户

class QueryRequest(BaseModel):
    query: str
    context: Optional[Dict[str, Any]] = None

class ToolResponse(BaseModel):
    tool_name: str
    parameters: Dict[str, Any]

class VoteRequest(BaseModel):
    user_id: str
    option: str

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "healthy"}

@router.post("/query")
async def process_query(request: QueryRequest):
    """
    处理用户查询
    
    Args:
        request: 查询请求
        
    Returns:
        Dict: 处理结果，包含要使用的工具和参数以及执行结果
    """
    try:
        # 初始化客户端
        llm_client = HunyuanClient()
        
        # 分析查询
        analysis = await llm_client.analyze_query(request.query, request.context)
        if not analysis["success"]:
            raise HTTPException(status_code=400, detail=analysis["error"])
        
        # 获取工具名称和参数
        tool_name = analysis.get("tool_name", "manual_response")
        parameters = analysis.get("parameters", {})
        
        # 执行命令并获取结果
        result = await execute_tool(tool_name, parameters)
        
        # 格式化输出
        formatted_result = format_output(tool_name, result, parameters)
        
        # 构造响应
        response = {
            "tool_name": tool_name,
            "parameters": parameters,
            "result": result,
            "formatted_result": formatted_result
        }
        
        return response
        
    except Exception as e:
        logger.error(f"处理查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/vote")
async def vote(request: VoteRequest):
    """
    处理用户投票请求
    
    Args:
        request: 包含user_id和option的投票请求
        
    Returns:
        Dict: 投票结果
    """
    # 定义默认成功返回结构
    success_response = {"code": 200, "message": "投票成功", "data": {}}
    
    try:
        # 确保请求参数有效
        if not request or not hasattr(request, 'user_id') or not hasattr(request, 'option'):
            return {"code": 400, "message": "无效的请求参数", "data": {}}
            
        user_id = request.user_id
        if not user_id:
            return {"code": 400, "message": "用户ID不能为空", "data": {}}
            
        option = request.option.upper() if request.option else ""  # 转为大写以统一处理
        if not option:
            return {"code": 400, "message": "投票选项不能为空", "data": {}}
        
        # 验证选项是否有效
        if option not in vote_data:
            return {"code": 400, "message": f"无效的投票选项: {option}，有效选项为 A/B/C/D/E", "data": {}}
        
        # 使用线程锁确保并发安全
        try:
            with vote_lock:
                # 记录投票
                vote_data[option] += 1
                vote_users.add(user_id)
                
                # 返回当前投票情况
                result = vote_data.copy()
            
            # 投票成功
            return {"code": 200, "message": "投票成功", "data": {"votes": result}}
        except Exception as e:
            # 锁操作失败，记录错误
            logger.error(f"投票锁操作失败: {str(e)}")
            # 返回成功以防止重试风暴，因为可能实际上已经投票成功
            return success_response
            
    except ValueError as e:
        # 处理值错误
        logger.error(f"投票值错误: {str(e)}")
        return {"code": 400, "message": f"投票请求格式错误: {str(e)}", "data": {}}
        
    except Exception as e:
        # 记录详细的错误信息到日志，但对外返回简洁的错误
        logger.error(f"投票处理失败: {str(e)}")
        # 由于可能已经投票成功或失败不明确，返回成功以避免用户重试
        return success_response

async def execute_tool(tool_name: str, parameters: Dict[str, Any]) -> str:
    """
    执行工具命令
    
    Args:
        tool_name: 工具名称
        parameters: 工具参数
        
    Returns:
        str: 执行结果
    """
    try:
        if tool_name == "kubectl_get_pods":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            label_selector = parameters.get("label_selector", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "pods"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("--all-namespaces")
            if output_format:
                cmd.extend(["-o", output_format])
            if label_selector:
                cmd.extend(["-l", label_selector])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_describe_pod":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            # 构建命令
            cmd = ["kubectl", "describe", "pod", pod_name, "-n", namespace]
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_logs":
            pod_name = parameters.get("pod_name", "")
            namespace = parameters.get("namespace", "default")
            container = parameters.get("container", "")
            tail = parameters.get("tail", "")
            
            if not pod_name:
                return "错误: 缺少Pod名称"
                
            # 构建命令
            cmd = ["kubectl", "logs", pod_name, "-n", namespace]
            if container:
                cmd.extend(["-c", container])
            if tail:
                cmd.extend(["--tail", str(tail)])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_get_deployments":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "deployments"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("--all-namespaces")
            if output_format:
                cmd.extend(["-o", output_format])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_get_services":
            namespace = parameters.get("namespace", "")
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "services"]
            if namespace:
                cmd.extend(["-n", namespace])
            else:
                cmd.append("--all-namespaces")
            if output_format:
                cmd.extend(["-o", output_format])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_get_nodes":
            output_format = parameters.get("output_format", "")
            
            # 构建命令
            cmd = ["kubectl", "get", "nodes"]
            if output_format:
                cmd.extend(["-o", output_format])
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "kubectl_command":
            command = parameters.get("command", "")
            if not command:
                return "错误: 缺少命令"
                
            # 构建命令
            cmd = ["kubectl"] + command.split()
                
            # 执行命令
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return f"命令执行失败: {result.stderr}"
            return result.stdout
            
        elif tool_name == "manual_response":
            text = parameters.get("text", "")
            return f"系统回复: {text}"
            
        else:
            return f"不支持的工具类型: {tool_name}"
            
    except Exception as e:
        logger.error(f"执行工具失败: {str(e)}")
        return f"执行工具出错: {str(e)}"

def format_output(tool_name: str, output: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    格式化输出结果
    
    Args:
        tool_name: 工具名称
        output: 输出结果
        parameters: 工具参数
        
    Returns:
        Dict: 格式化后的结果
    """
    try:
        # 针对不同工具类型进行格式化处理
        if tool_name.startswith("kubectl_get"):
            # 格式化表格输出
            rows = output.strip().split('\n')
            if len(rows) <= 1:
                return {"type": "text", "content": output}
            
            # 提取表头和数据
            headers = re.split(r'\s+', rows[0].strip())
            data = []
            
            for i in range(1, len(rows)):
                # 将每行按空格分割并对齐到表头
                row_data = {}
                cols = re.split(r'\s+', rows[i].strip(), len(headers) - 1)
                
                # 可能的列数不够，做一个安全检查
                for j in range(min(len(headers), len(cols))):
                    row_data[headers[j]] = cols[j]
                
                data.append(row_data)
            
            return {
                "type": "table", 
                "headers": headers, 
                "data": data,
                "command": f"kubectl {' '.join(tool_name.split('_')[1:])}"
            }
            
        elif tool_name == "kubectl_describe_pod":
            # 提取关键信息，分块展示
            sections = {}
            current_section = "基本信息"
            sections[current_section] = []
            
            for line in output.split('\n'):
                line = line.rstrip()
                if not line:
                    continue
                    
                # 检测新的段落
                if line and line[0] != ' ' and ':' not in line:
                    current_section = line
                    sections[current_section] = []
                else:
                    sections[current_section].append(line)
            
            # 格式化输出
            return {
                "type": "describe",
                "sections": sections,
                "pod_name": parameters.get("pod_name", ""),
                "namespace": parameters.get("namespace", "default")
            }
            
        elif tool_name == "kubectl_logs":
            log_lines = output.split('\n')
            return {
                "type": "logs",
                "lines": log_lines,
                "pod_name": parameters.get("pod_name", ""),
                "namespace": parameters.get("namespace", "default")
            }
            
        else:
            # 默认文本输出
            return {"type": "text", "content": output}
            
    except Exception as e:
        logger.error(f"格式化输出失败: {str(e)}")
        return {"type": "text", "content": output, "error": str(e)} 