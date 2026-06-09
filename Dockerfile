FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.10-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 系统依赖（使用国内源加速）
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖（使用国内源加速）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install -r /app/backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 后端代码
COPY backend/ /app/backend/

# 创建默认开发账号
RUN cd /app/backend && python seed_dev_user.py

# 前端静态文件
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 持久化数据目录
RUN mkdir -p /app/backend/data /app/backend/BERT

EXPOSE 8000

WORKDIR /app/backend
CMD ["python", "serve_static.py"]
