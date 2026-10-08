# ============================================================
# LabelFast Docker 镜像 — 多阶段构建
# 目标环境：RHEL 7.6 / x86_64 / Docker 20.10.9+
# ============================================================

# ---------- 阶段 1：构建前端 ----------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# 利用 Docker 缓存层：先装依赖
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：运行时 ----------
FROM python:3.10-slim
WORKDIR /app/backend

# 安装系统依赖（onnxruntime 需要 libgomp1）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装图像标注器额外依赖（如有）
COPY backend/图像标注器/requirements.txt ./图像标注器/
RUN pip install --no-cache-dir -r ./图像标注器/requirements.txt

# 复制后端代码
COPY backend/ .

# 下载离线前端资源（Vue.js + Tailwind CDN，用于图像标注平台）
RUN mkdir -p 图像标注器/label_system/static \
    && curl -sL -o 图像标注器/label_system/static/vue.global.js \
       https://unpkg.com/vue@3/dist/vue.global.prod.js \
    && curl -sL -o 图像标注器/label_system/static/tailwind.js \
       https://cdn.tailwindcss.com

# 创建种子数据备份（首次部署 volume 为空时自动恢复）
RUN mkdir -p /app/seed; \
    cp 文本标注器/storage/文本标注器.db /app/seed/ 2>/dev/null || true; \
    cp -r 文本标注器/projects /app/seed/text-projects 2>/dev/null || true; \
    cp -r 图像标注器/projects /app/seed/image-projects 2>/dev/null || true; \
    cp 图像标注器/projects.json /app/seed/ 2>/dev/null || true

# 复制前端构建产物
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# 启动脚本
COPY docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 3002
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "3002"]
