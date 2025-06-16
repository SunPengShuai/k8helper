import uvicorn
from src.main import app
from src.utils.config import Config

if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=Config.API_HOST,
        port=Config.API_PORT,
        reload=Config.API_RELOAD
    ) 