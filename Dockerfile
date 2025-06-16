FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY requirements.txt .
COPY src/ src/
COPY config.yml .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建日志目录
RUN mkdir -p logs

# 设置环境变量
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 8080

# 启动命令
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"] 