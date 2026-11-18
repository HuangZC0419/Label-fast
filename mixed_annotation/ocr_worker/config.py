"""OCR Worker 配置。

API / Worker / 主后端统一运行在命名 conda 环境 ``CFwin11``（Python 3.12），
模型缓存与运行数据全部放在项目目录内，便于离线复制与整体迁移。

当前为 MinerU-only：PaddleOCR 回退已禁用（Paddle C++ 无法读取中文项目路径）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(os.path.abspath(__file__)).parent
PROJECT_ROOT = ROOT_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    """读取目录类环境变量；未设置时使用项目内默认路径。"""

    raw = os.getenv(name, "").strip()
    path = Path(raw).expanduser() if raw else default
    return Path(os.path.abspath(path))


# Worker 任务目录：默认 ocr_worker/data，可用 OCR_WORKER_DATA_DIR 覆盖。
DATA_DIR = _env_path("OCR_WORKER_DATA_DIR", ROOT_DIR / "data")
TASKS_DIR = DATA_DIR / "tasks"

# PaddleOCR 回退已禁用（中文项目路径下 Paddle C++ 无法读取模型）。
# 保留路径兼容 engine.py 的导入；实际运行不会加载 Paddle 模型。
PADDLE_CACHE_DIR = _env_path(
    "PADDLE_PDX_CACHE_HOME", PROJECT_ROOT / "models" / "paddlex"
)

# PaddleX 在 import 时读取这些变量，必须早于 paddleocr 导入。
os.environ["PADDLE_PDX_CACHE_HOME"] = str(PADDLE_CACHE_DIR)
# 离线部署时跳过模型源连通性探测；首次在线下载仍可正常进行。
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# PaddlePaddle 3.3 在 CPU 上启用 MKLDNN + PIR 时会抛出
# ConvertPirAttribute2RuntimeAttribute 未实现的错误，这里默认关闭 MKLDNN。
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# 快速模式：使用 PP-OCRv5 mobile 文本检测/识别与轻量版面模型，
# 速度提升明显，精度略有下降。通过 OCR_FAST_MODE=1 开启。
FAST_MODE = _env_flag("OCR_FAST_MODE", False)
if FAST_MODE:
    os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", "16")

# ---------------------------------------------------------------------------
# MinerU 引擎
#
# API / Worker / 主后端统一使用 CFwin11（Python 3.12），MinerU 直接在该环境
# 内运行；Worker 通过常驻 API 或子进程调用它。这里只保存路径与运行参数，
# 不在模块导入时加载任何 MinerU 依赖。
# ---------------------------------------------------------------------------
OCR_ENGINE = os.getenv("OCR_ENGINE", "auto").strip().lower()  # auto|mineru|paddle
# 默认使用当前 Worker 解释器（即 CFwin11），不再指向任何外部 MinerU 环境。
MINERU_PYTHON = Path(
    os.getenv("MINERU_PYTHON", sys.executable)
).expanduser()
MINERU_RUNNER = Path(
    os.getenv("MINERU_RUNNER", str(ROOT_DIR / "mineru_runner.py"))
).expanduser()
MINERU_BACKEND = os.getenv("MINERU_BACKEND", "pipeline").strip() or "pipeline"
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "ch").strip()
MINERU_PARSE_METHOD = os.getenv("MINERU_PARSE_METHOD", "auto").strip() or "auto"
MINERU_DEVICE_MODE = os.getenv("MINERU_DEVICE_MODE", "").strip()
MINERU_HIGH_ACCURACY = _env_flag("MINERU_HIGH_ACCURACY", False)
MINERU_TIMEOUT_SECONDS = int(os.getenv("MINERU_TIMEOUT_SECONDS", "3600"))
MINERU_MODEL_SOURCE = os.getenv("MINERU_MODEL_SOURCE", "").strip()

# 常驻 mineru-api 传输（推荐）。Worker 通过 HTTP 调用独立运行的
# ``mineru-api`` 服务，模型只加载一次；不可用时按 MINERU_MODE 回退子进程。
# MINERU_MODE: auto（API 优先，失败回退子进程）| api（只用 API）| subprocess。
MINERU_MODE = os.getenv("MINERU_MODE", "auto").strip().lower() or "auto"
MINERU_API_URL = os.getenv(
    "MINERU_API_URL", "http://127.0.0.1:18000"
).strip().rstrip("/")
MINERU_API_TIMEOUT_SECONDS = int(
    os.getenv("MINERU_API_TIMEOUT_SECONDS", "3600")
)
MINERU_API_POLL_SECONDS = float(os.getenv("MINERU_API_POLL_SECONDS", "1.0"))
# /health 探测超时；api_available() 结果缓存 2 秒，避免每个请求阻塞。
MINERU_API_HEALTH_TIMEOUT_SECONDS = float(
    os.getenv("MINERU_API_HEALTH_TIMEOUT_SECONDS", "2.0")
)
# Worker 同时处理的任务数；0 表示自动（API 可用时 3，否则 1）。
OCR_WORKER_CONCURRENCY = int(os.getenv("OCR_WORKER_CONCURRENCY", "0"))

MAX_UPLOAD_BYTES = int(os.getenv("OCR_MAX_UPLOAD_MB", "100")) * 1024 * 1024
TASK_RETENTION_SECONDS = int(
    os.getenv("OCR_TASK_RETENTION_SECONDS", str(24 * 60 * 60))
)
MIN_DPI = 72
MAX_DPI = 600
DEFAULT_DPI = 200
DEFAULT_ENABLE_TABLE = True
DEFAULT_ENABLE_FORMULA = False

ALLOWED_UPLOADS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
