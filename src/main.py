from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
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

# 获取CORS配置
cors_config = Config.get_cors_config()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_config.get('allow_origins', ['*']),
    allow_credentials=cors_config.get('allow_credentials', True),
    allow_methods=cors_config.get('allow_methods', ['*']),
    allow_headers=cors_config.get('allow_headers', ['*'])
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
    """返回静态HTML首页"""
    static_html_path = static_dir / "index.html"
    if static_html_path.exists():
        return FileResponse(static_html_path)
    else:
        # 如果静态文件不存在，返回简单的错误页面
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{Config.APP_NAME} - 错误</title>
            <meta charset="UTF-8">
        </head>
        <body>
            <h1>{Config.APP_NAME}</h1>
            <p>静态文件未找到，请检查 static/index.html 文件是否存在。</p>
        </body>
        </html>
        """)

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
        reload=Config.API_RELOAD
    ) 