# ==========================================
# 后端 Dockerfile (FastAPI + Prefect)
# ==========================================

# 1. 使用官方 Python 轻量级镜像
FROM python:3.11-slim

# 2. 设置工作目录
WORKDIR /app

# 3. 设置环境变量
# PYTHONDONTWRITEBYTECODE: 防止生成 .pyc 文件，保持容器整洁
# PYTHONUNBUFFERED: 确保 Python 日志直接输出到 Docker 控制台，不被缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 4. 安装系统级依赖
# build-essential: 用于编译 C/C++ 扩展（如 readability, lxml, faiss 等）
# git: 如果你的 requirements.txt 中有 git+https://... 的依赖，必须安装 git
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# 5. 复制依赖文件并安装
# 利用 Docker 缓存层，只要 requirements.txt 没变，下次构建就会秒过
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ⚠️ 注意：这里故意不 COPY 业务代码 (backend/, pipeline/ 等)！
# 业务代码将通过 docker-compose.yml 的 volumes 挂载到 /app 目录，实现热更新。

# 6. 暴露 FastAPI 端口
EXPOSE 8000

# 7. 默认启动命令 (兜底，实际运行由 docker-compose 的 command 覆盖)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]