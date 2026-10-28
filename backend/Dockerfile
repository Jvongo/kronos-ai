# 使用Python 3.11官方镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_DEFAULT_TIMEOUT=200

# 安装系统依赖（deb.debian.org在本机网络不可达，切换阿里云Debian镜像）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements文件
COPY requirements.txt .

# 安装CPU版torch（避免拉取2.5GB+的CUDA依赖）
RUN pip install --upgrade pip && \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

# 安装Python依赖
RUN pip install -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p data/models data/cache data/logs data/database

# 暴露端口
EXPOSE 8000

# 设置健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]