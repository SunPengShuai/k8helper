from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os
from pathlib import Path
from .api.routes import router
from .utils.config import Config
from .utils.logger import get_logger

logger = get_logger(__name__)

# 创建FastAPI应用
app = FastAPI(
    title=Config.APP_NAME,
    version=Config.VERSION,
    description="Kubernetes智能助手API"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 创建静态文件目录
static_dir = Path(__file__).parent.parent / "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# 注册路由
app.include_router(router, prefix="/api/v1")

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def get_home():
    """返回首页"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>K8Helper - Kubernetes智能助手</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                line-height: 1.6;
            }
            .container {
                max-width: 1200px;
                margin: 0 auto;
            }
            h1 {
                color: #333;
                margin-bottom: 20px;
            }
            .query-form {
                margin-bottom: 20px;
            }
            .query-input {
                width: 80%;
                padding: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            .submit-btn {
                padding: 10px 20px;
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
            }
            .submit-btn:hover {
                background-color: #45a049;
            }
            .result-container {
                margin-top: 20px;
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 15px;
                background-color: #f9f9f9;
            }
            .tool-info {
                margin-bottom: 10px;
                padding: 10px;
                background-color: #e9e9e9;
                border-radius: 4px;
            }
            .code {
                font-family: monospace;
                background-color: #f5f5f5;
                padding: 10px;
                border-left: 3px solid #4CAF50;
                white-space: pre-wrap;
                word-wrap: break-word;
                margin: 10px 0;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
            }
            table, th, td {
                border: 1px solid #ddd;
            }
            th, td {
                text-align: left;
                padding: 12px;
            }
            th {
                background-color: #f2f2f2;
            }
            tr:hover {
                background-color: #f5f5f5;
            }
            .section-title {
                background-color: #e1e1e1;
                padding: 8px;
                margin-top: 12px;
                font-weight: bold;
            }
            .section-content {
                margin-left: 15px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>K8Helper - Kubernetes智能助手</h1>
            
            <div class="query-form">
                <input type="text" id="query-input" class="query-input" placeholder="输入你想查询的Kubernetes问题，例如：如何查看所有Pod的状态？">
                <button id="submit-btn" class="submit-btn">查询</button>
            </div>
            
            <div id="result-container" class="result-container" style="display: none;"></div>
        </div>
        
        <script>
            document.getElementById('submit-btn').addEventListener('click', function() {
                const query = document.getElementById('query-input').value;
                if (!query) return;
                
                // 显示加载状态
                const resultContainer = document.getElementById('result-container');
                resultContainer.style.display = 'block';
                resultContainer.innerHTML = '<p>正在处理查询...</p>';
                
                // 发送请求
                fetch('/api/v1/query', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ query: query })
                })
                .then(response => response.json())
                .then(data => {
                    displayResult(data);
                })
                .catch(error => {
                    resultContainer.innerHTML = `<p>查询出错: ${error}</p>`;
                });
            });
            
            function displayResult(data) {
                const resultContainer = document.getElementById('result-container');
                let html = '';
                
                // 工具信息
                html += `<div class="tool-info">
                    <strong>执行工具:</strong> ${data.tool_name}<br>
                    <strong>参数:</strong> ${JSON.stringify(data.parameters)}
                </div>`;
                
                // 根据格式化结果类型显示不同内容
                if (data.formatted_result) {
                    const fr = data.formatted_result;
                    switch (fr.type) {
                        case 'table':
                            html += `<h3>执行命令: ${fr.command}</h3>`;
                            html += '<table><tr>';
                            // 表头
                            fr.headers.forEach(header => {
                                html += `<th>${header}</th>`;
                            });
                            html += '</tr>';
                            
                            // 数据行
                            fr.data.forEach(row => {
                                html += '<tr>';
                                fr.headers.forEach(header => {
                                    html += `<td>${row[header] || ''}</td>`;
                                });
                                html += '</tr>';
                            });
                            html += '</table>';
                            break;
                            
                        case 'describe':
                            html += `<h3>Pod 详情: ${fr.pod_name} (${fr.namespace})</h3>`;
                            Object.keys(fr.sections).forEach(section => {
                                html += `<div class="section-title">${section}</div>`;
                                html += '<div class="section-content">';
                                fr.sections[section].forEach(line => {
                                    html += `${line}<br>`;
                                });
                                html += '</div>';
                            });
                            break;
                            
                        case 'logs':
                            html += `<h3>Pod 日志: ${fr.pod_name} (${fr.namespace})</h3>`;
                            html += '<div class="code">';
                            fr.lines.forEach(line => {
                                html += `${line}<br>`;
                            });
                            html += '</div>';
                            break;
                            
                        default:
                            html += `<div class="code">${fr.content}</div>`;
                    }
                } else {
                    // 原始结果
                    html += `<div class="code">${data.result}</div>`;
                }
                
                resultContainer.innerHTML = html;
            }
            
            // 按回车键提交
            document.getElementById('query-input').addEventListener('keyup', function(event) {
                if (event.key === 'Enter') {
                    document.getElementById('submit-btn').click();
                }
            });
        </script>
    </body>
    </html>
    """

@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化操作"""
    try:
        # 验证配置
        Config.validate()
        logger.info("配置验证通过")
    except Exception as e:
        logger.error(f"配置验证失败: {str(e)}")
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=Config.API_HOST,
        port=Config.API_PORT,
        reload=Config.DEBUG
    ) 