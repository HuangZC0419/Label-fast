"""主应用运行配置。

所有可调参数集中在此处，避免业务代码中出现硬编码路径或端口。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

DATA_DIR = Path(
    os.getenv("BACKEND_DATA_DIR", str(BASE_DIR / "data"))
).expanduser().resolve()
PROJECTS_INDEX_PATH = DATA_DIR / "projects.json"
PROJECTS_DIR = DATA_DIR / "projects"

FRONTEND_DIST = Path(
    os.getenv("FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist"))
).expanduser().resolve()

OCR_WORKER_URL = os.getenv("OCR_WORKER_URL", "http://127.0.0.1:8870").rstrip("/")
OCR_POLL_INTERVAL = float(os.getenv("OCR_POLL_INTERVAL_SECONDS", "1"))
OCR_CONNECT_TIMEOUT = float(os.getenv("OCR_CONNECT_TIMEOUT_SECONDS", "10"))
OCR_STATUS_TIMEOUT = float(os.getenv("OCR_STATUS_TIMEOUT_SECONDS", "15"))
OCR_SUBMIT_TIMEOUT = float(os.getenv("OCR_SUBMIT_TIMEOUT_SECONDS", "120"))
OCR_DOWNLOAD_TIMEOUT = float(os.getenv("OCR_DOWNLOAD_TIMEOUT_SECONDS", "300"))
# 图表小图 OCR（标题预填）：单张小图通常 1–2 秒，这里给足模型首次加载余量。
OCR_REGION_TIMEOUT = float(os.getenv("OCR_REGION_TIMEOUT_SECONDS", "60"))
# 队列在提交前探测 Worker /health，超时必须足够短，避免拖住夜间串行队列。
OCR_HEALTH_TIMEOUT = float(os.getenv("OCR_HEALTH_TIMEOUT_SECONDS", "3"))
OCR_TASK_TIMEOUT = float(os.getenv("OCR_TASK_TIMEOUT_SECONDS", str(6 * 60 * 60)))
# 夜间串行队列的单文件超时：默认 1 小时，避免一个卡死任务占住队首整夜。
# 普通单文件转换仍使用上面的 OCR_TASK_TIMEOUT（6 小时）。
OCR_QUEUE_TASK_TIMEOUT = float(
    os.getenv("MIX_QUEUE_TASK_TIMEOUT_SECONDS", str(60 * 60))
)
OCR_MAX_CONSECUTIVE_POLL_ERRORS = int(
    os.getenv("OCR_MAX_CONSECUTIVE_POLL_ERRORS", "5")
)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
MAX_MARKDOWN_BYTES = int(os.getenv("MAX_MARKDOWN_MB", "20")) * 1024 * 1024
# 前端离屏截图上传的 PNG 上限，防止单次标注请求占用过多内存/磁盘。
MAX_FIGURE_BYTES = int(os.getenv("MAX_FIGURE_MB", "20")) * 1024 * 1024
MAX_EXTRACTED_RESULT_BYTES = (
    int(os.getenv("MAX_EXTRACTED_RESULT_MB", "1024")) * 1024 * 1024
)
MAX_RESULT_ZIP_BYTES = int(os.getenv("MAX_RESULT_ZIP_MB", "1024")) * 1024 * 1024

DEFAULT_DPI = 200
MIN_DPI = 72
MAX_DPI = 600
DEFAULT_ENABLE_TABLE = True
DEFAULT_ENABLE_FORMULA = False

# 扩展名白名单：用于识别源类型和返回正确的 Content-Type。
ALLOWED_UPLOADS: dict[str, tuple[str, str]] = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
}

# 原始文件写入时使用的统一文件名后缀（实际扩展名取自白名单）。
SOURCE_STEM = "source"
