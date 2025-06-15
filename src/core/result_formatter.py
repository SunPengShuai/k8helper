import re
import json
import yaml
from typing import Dict, Any, List, Optional
from ..utils.logger import get_logger

logger = get_logger(__name__)

class ResultFormatter:
    """结果格式化器"""
    
    def __init__(self):
        pass
    
    def format_output(self, output: str, output_format: str = "auto") -> Dict[str, Any]:
        """
        格式化kubectl命令输出
        
        Args:
            output: 命令输出
            output_format: 输出格式 (table/text/auto)
            
        Returns:
            Dict: 格式化后的结果
        """
        if not output.strip():
            return {
                "type": "text",
                "content": "命令执行成功，但没有输出内容"
            }
        
        # 自动检测格式
        if output_format == "auto":
            output_format = self._detect_format(output)
        
        if output_format == "table":
            return self._format_as_table(output)
        else:
            return self._format_as_text(output)
    
    def _detect_format(self, output: str) -> str:
        """自动检测最佳输出格式"""
        lines = output.strip().split('\n')
        if len(lines) >= 2:
            # 检查是否有表头
            first_line = lines[0]
            if any(header in first_line.upper() for header in ['NAME', 'READY', 'STATUS', 'AGE', 'NAMESPACE']):
                return "table"
        
        return "text"
    
    def _format_as_table(self, output: str) -> Dict[str, Any]:
        """格式化为表格"""
        lines = output.strip().split('\n')
        if len(lines) < 2:
            return self._format_as_text(output)
        
        try:
            # 解析表头
            header_line = lines[0]
            headers = re.split(r'\s{2,}', header_line.strip())
            
            # 解析数据行
            data_rows = []
            for line in lines[1:]:
                if line.strip():
                    # 使用正则表达式分割，保持与表头对齐
                    row_data = re.split(r'\s{2,}', line.strip())
                    # 确保行数据长度与表头匹配
                    while len(row_data) < len(headers):
                        row_data.append("")
                    data_rows.append(row_data[:len(headers)])
            
            return {
                "type": "table",
                "headers": headers,
                "data": data_rows,
                "total_rows": len(data_rows)
            }
            
        except Exception as e:
            logger.warning(f"表格解析失败: {str(e)}, 回退到文本格式")
            return self._format_as_text(output)
    
    def _format_as_text(self, output: str) -> Dict[str, Any]:
        """格式化为文本"""
        # 检查是否是YAML或JSON格式
        content_type = "text"
        try:
            # 尝试解析为JSON
            json.loads(output)
            content_type = "json"
        except:
            try:
                # 尝试解析为YAML
                yaml.safe_load(output)
                if output.strip().startswith(('apiVersion:', 'kind:', 'metadata:')):
                    content_type = "yaml"
            except:
                pass
        
        return {
            "type": "text",
            "content_type": content_type,
            "content": output,
            "line_count": len(output.split('\n'))
        } 