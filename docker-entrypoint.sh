#!/bin/sh

echo "[LabelFast] 检查数据卷..."

# ---- 文本标注器 - SQLite 数据库 ----
NEED_SEED_DB=false
DB_PATH="/app/backend/文本标注器/storage/文本标注器.db"
if [ ! -f "$DB_PATH" ]; then
    NEED_SEED_DB=true
elif [ -f "$DB_PATH" ]; then
    # DB 文件存在但可能是空的——检查 SQLite header 大小
    DB_SIZE=$(wc -c < "$DB_PATH" 2>/dev/null || echo 0)
    if [ "$DB_SIZE" -lt 1024 ]; then
        echo "[LabelFast] 检测到空数据库 (${DB_SIZE} bytes)，需要重新播种"
        NEED_SEED_DB=true
    fi
fi

if [ "$NEED_SEED_DB" = true ]; then
    echo "[LabelFast] 初始化文本标注数据库..."
    if [ -f /app/seed/文本标注器.db ]; then
        SEED_SIZE=$(wc -c < /app/seed/文本标注器.db 2>/dev/null || echo 0)
        if [ "$SEED_SIZE" -gt 4096 ]; then
            cp /app/seed/文本标注器.db "$DB_PATH"
            echo "[LabelFast] 文本标注数据库已从种子恢复 (${SEED_SIZE} bytes)"
        else
            echo "[LabelFast] 警告：种子数据库也无效 (${SEED_SIZE} bytes)，跳过恢复"
        fi
    else
        echo "[LabelFast] 未找到种子数据库，将创建空数据库"
    fi
fi

# ---- 文本标注器 - 项目数据 ----
if [ ! -d /app/backend/文本标注器/projects ] || [ -z "$(ls -A /app/backend/文本标注器/projects 2>/dev/null)" ]; then
    echo "[LabelFast] 初始化文本标注项目数据..."
    mkdir -p /app/backend/文本标注器/projects
    if [ -d /app/seed/text-projects ] && [ -n "$(ls -A /app/seed/text-projects 2>/dev/null)" ]; then
        cp -r /app/seed/text-projects/* /app/backend/文本标注器/projects/ 2>/dev/null || true
        echo "[LabelFast] 文本标注项目数据已从种子恢复"
    fi
fi

# ---- 图像标注器 - 项目数据 ----
if [ ! -d /app/backend/图像标注器/projects ] || [ -z "$(ls -A /app/backend/图像标注器/projects 2>/dev/null)" ]; then
    echo "[LabelFast] 初始化图像标注项目数据..."
    mkdir -p /app/backend/图像标注器/projects
    if [ -d /app/seed/image-projects ] && [ -n "$(ls -A /app/seed/image-projects 2>/dev/null)" ]; then
        cp -r /app/seed/image-projects/* /app/backend/图像标注器/projects/ 2>/dev/null || true
        echo "[LabelFast] 图像标注项目数据已从种子恢复"
    fi
fi

# ---- 图像标注器 - 项目索引 ----
if [ ! -f /app/backend/图像标注器/projects.json ]; then
    echo "[LabelFast] 初始化图像标注项目索引..."
    if [ -f /app/seed/projects.json ]; then
        cp /app/seed/projects.json /app/backend/图像标注器/
        echo "[LabelFast] 图像标注项目索引已从种子恢复"
    fi
fi

echo "[LabelFast] 数据卷检查完成，启动服务..."
exec "$@"
