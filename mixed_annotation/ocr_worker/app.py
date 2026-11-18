"""数据标注与分类工具 OCR Worker（内部端口 8870）。"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

import convert
import engine
import mineru_engine
from config import (
    ALLOWED_UPLOADS,
    DEFAULT_DPI,
    DEFAULT_ENABLE_FORMULA,
    DEFAULT_ENABLE_TABLE,
    MAX_DPI,
    MAX_UPLOAD_BYTES,
    MIN_DPI,
    MINERU_API_URL,
    MINERU_MODE,
    MINERU_PYTHON,
    MINERU_RUNNER,
    OCR_WORKER_CONCURRENCY,
    PADDLE_CACHE_DIR,
    TASK_RETENTION_SECONDS,
    TASKS_DIR,
)
from task_store import TaskStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_store = TaskStore()
_semaphore: asyncio.Semaphore | None = None
_worker_concurrency: int = 1
_background_tasks: set[asyncio.Task[Any]] = set()
_cleanup_task: asyncio.Task[Any] | None = None
_MAX_REQUEST_BODY = MAX_UPLOAD_BYTES + 2 * 1024 * 1024


class WorkerError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_header(extension: str, head: bytes) -> bool:
    if extension == ".pdf":
        return b"%PDF-" in head[:1024]
    if extension == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    return False


def _clean_filename(filename: str | None) -> tuple[str, str, str]:
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    if not raw.strip():
        raise WorkerError(400, "缺少文件名")
    raw = "".join(ch for ch in raw if ord(ch) >= 32).strip()
    extension = Path(raw).suffix.lower()
    media_type = ALLOWED_UPLOADS.get(extension)
    if media_type is None:
        raise WorkerError(400, "仅支持 PDF、PNG、JPG、JPEG 文件")
    return raw, extension, media_type


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise WorkerError(413, "文件超过 Worker 上传大小限制")
            handle.write(chunk)
    if total == 0:
        raise WorkerError(400, "上传文件为空")


def _cleanup_expired(active_ids: set[str]) -> int:
    cutoff = time.time() - TASK_RETENTION_SECONDS
    _store.purge_finished_before(cutoff)
    removed = 0
    if not TASKS_DIR.is_dir():
        return 0
    for child in TASKS_DIR.iterdir():
        if not child.is_dir() or child.name in active_ids:
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60 * 60)
        try:
            await asyncio.to_thread(_cleanup_expired, _store.active_ids())
        except Exception:
            logger.exception("清理过期 OCR 任务失败")


async def _run_task(task_id: str) -> None:
    assert _semaphore is not None
    await _semaphore.acquire()
    task = _store.get(task_id)
    if task is None:
        _semaphore.release()
        return
    try:
        _store.update(task_id, status="running", progress=1, stage="准备 OCR")
        options = task["options"]

        def on_progress(progress: int, stage: str, page_count: int | None) -> None:
            changes: dict[str, Any] = {
                "progress": max(0, min(100, int(progress))),
                "stage": stage,
            }
            if page_count is not None:
                changes["page_count"] = int(page_count)
            _store.update(task_id, **changes)

        result = await asyncio.to_thread(
            convert.convert_document,
            Path(task["source_path"]),
            Path(task["task_dir"]),
            enable_table=bool(options["enable_table"]),
            enable_formula=bool(options["enable_formula"]),
            dpi=int(options["dpi"]),
            progress=on_progress,
            engine=options.get("engine", ""),
        )
        _store.update(
            task_id,
            status="completed",
            progress=100,
            stage="完成",
            message="；".join(result.warnings),
            error="",
            page_count=result.page_count,
        )
        logger.info(
            "任务 %s 完成：引擎=%s，%s 页，%s 字符，%.1fs",
            task_id,
            result.engine,
            result.page_count,
            result.markdown_chars,
            result.elapsed_seconds,
        )
    except asyncio.CancelledError:
        _store.update(
            task_id,
            status="failed",
            stage="已取消",
            message="任务已取消",
            error="任务已取消",
        )
        raise
    except Exception as exc:
        logger.exception("OCR 任务失败：%s", task_id)
        message = str(exc).strip()[:1000] or "OCR 转换失败"
        _store.update(
            task_id,
            status="failed",
            stage="转换失败",
            message=message,
            error=message,
        )
    finally:
        _semaphore.release()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _semaphore, _cleanup_task, _worker_concurrency
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    PADDLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 并发计算：显式配置优先；auto 时 API 可用就用 3（实测吞吐已接近上限），
    # 子进程模式每任务都要加载模型，保持 1 避免显存争抢。
    api_ok, api_reason = await asyncio.to_thread(mineru_engine.api_available)
    if OCR_WORKER_CONCURRENCY > 0:
        _worker_concurrency = OCR_WORKER_CONCURRENCY
    else:
        _worker_concurrency = 3 if api_ok else 1
    _worker_concurrency = max(1, _worker_concurrency)
    _semaphore = asyncio.Semaphore(_worker_concurrency)

    await asyncio.to_thread(_cleanup_expired, set())
    _cleanup_task = asyncio.create_task(_cleanup_loop(), name="ocr-cleanup")
    selected = await asyncio.to_thread(mineru_engine.select_engine)
    available, reason = mineru_engine.mineru_available()
    mode = (MINERU_MODE or "auto").strip().lower()
    transport = (
        "mineru-api"
        if selected == "mineru" and mode != "subprocess" and api_ok
        else "subprocess"
        if selected == "mineru"
        else "paddle"
    )
    logger.info(
        "OCR Worker 启动，引擎=%s（传输=%s，MINERU_MODE=%s，API 可用=%s：%s），"
        "并发=%s，子进程可用=%s（%s），模型缓存：%s",
        selected,
        transport,
        mode,
        api_ok,
        api_reason,
        _worker_concurrency,
        available,
        reason,
        PADDLE_CACHE_DIR,
    )
    try:
        yield
    finally:
        if _cleanup_task is not None:
            _cleanup_task.cancel()
            await asyncio.gather(_cleanup_task, return_exceptions=True)
        for task in list(_background_tasks):
            task.cancel()
        if _background_tasks:
            await asyncio.gather(*list(_background_tasks), return_exceptions=True)
        _background_tasks.clear()
        logger.info("OCR Worker 已停止")


app = FastAPI(
    title="数据标注与分类工具 OCR Worker",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def guard_requests(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_REQUEST_BODY:
                return JSONResponse(status_code=413, content={"detail": "请求体过大"})
        except ValueError:
            return JSONResponse(
                status_code=400, content={"detail": "Content-Length 不合法"}
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


@app.exception_handler(WorkerError)
async def handle_worker_error(_: Request, exc: WorkerError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    if errors:
        first = errors[0]
        location = ".".join(
            str(part)
            for part in first.get("loc", ())
            if part not in {"body", "query", "path"}
        )
        detail = (
            "请求参数不合法："
            f"{location + ' ' if location else ''}{first.get('msg', '参数错误')}"
        )
    else:
        detail = "请求参数不合法"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.get("/health", tags=["health"])
def health() -> dict:
    selected = mineru_engine.select_engine()
    mineru_ok, mineru_reason = mineru_engine.mineru_available()
    api_ok, api_reason = mineru_engine.api_available()
    return {
        "status": "ok",
        "service": "label-fast-ocr-worker",
        # engine 为按 OCR_ENGINE 实际选中的引擎；engine_name 保留原字段含义。
        "engine": selected,
        "engine_name": "MinerU" if selected == "mineru" else "PP-StructureV3",
        "engine_loaded": engine.pipeline_loaded() if selected == "paddle" else False,
        "mineru_available": mineru_ok,
        "mineru_reason": mineru_reason,
        "mineru_mode": (MINERU_MODE or "auto").strip().lower() or "auto",
        "mineru_api_available": api_ok,
        "mineru_api_url": MINERU_API_URL,
        "mineru_api_reason": api_reason,
        "worker_concurrency": _worker_concurrency,
        "mineru_python": str(MINERU_PYTHON),
        "mineru_runner": str(MINERU_RUNNER),
        "model_cache": str(PADDLE_CACHE_DIR),
        "queued_or_running": len(_store.active_ids()),
    }


@app.post("/convert", tags=["tasks"])
async def create_conversion(
    file: UploadFile = File(...),
    enable_table: bool = Form(DEFAULT_ENABLE_TABLE),
    enable_formula: bool = Form(DEFAULT_ENABLE_FORMULA),
    dpi: int = Form(DEFAULT_DPI),
    engine: str = Form(""),
) -> dict:
    if dpi < MIN_DPI or dpi > MAX_DPI:
        raise WorkerError(400, f"dpi 必须在 {MIN_DPI} 到 {MAX_DPI} 之间")

    engine_mode = (engine or "").strip().lower()
    if engine_mode and engine_mode not in {"auto", "mineru", "paddle"}:
        raise WorkerError(400, "engine 仅支持 auto、mineru 或 paddle")

    filename, extension, _media_type = _clean_filename(file.filename)
    task_id = str(uuid.uuid4())
    task_dir = TASKS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    source_path = task_dir / f"source{extension}"

    try:
        try:
            await _save_upload(file, source_path)
        finally:
            await file.close()
        with source_path.open("rb") as handle:
            head = handle.read(1024)
        if not _validate_header(extension, head):
            raise WorkerError(400, "文件内容与扩展名不匹配")
    except BaseException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise

    _store.create(
        task_id,
        source_path=str(source_path),
        task_dir=str(task_dir),
        filename=filename,
        options={
            "enable_table": bool(enable_table),
            "enable_formula": bool(enable_formula),
            "dpi": int(dpi),
            "engine": engine_mode,
        },
    )
    background = asyncio.create_task(_run_task(task_id), name=f"ocr-task-{task_id}")
    _background_tasks.add(background)
    background.add_done_callback(_background_tasks.discard)
    logger.info(
        "接受 OCR 任务 %s：%s，engine=%s，table=%s，formula=%s，dpi=%s",
        task_id,
        filename,
        engine_mode or "auto",
        enable_table,
        enable_formula,
        dpi,
    )
    return {"task_id": task_id}


@app.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: str) -> dict:
    payload = _store.public(task_id)
    if payload is None:
        raise WorkerError(404, "任务不存在")
    return payload


@app.get("/tasks/{task_id}/result.zip", tags=["tasks"])
def get_result_zip(task_id: str) -> FileResponse:
    task = _store.get(task_id)
    if task is None:
        raise WorkerError(404, "任务不存在")
    status = task.get("status")
    if status in {"queued", "running"}:
        raise WorkerError(409, "任务尚未完成")
    if status != "completed":
        raise WorkerError(409, "任务失败，没有可下载的结果")
    result_zip = Path(task["task_dir"]) / "result.zip"
    if not result_zip.is_file():
        raise WorkerError(404, "结果文件不存在")
    return FileResponse(
        result_zip,
        media_type="application/zip",
        filename="result.zip",
    )


@app.post("/tasks/cleanup", tags=["tasks"])
async def cleanup_tasks() -> dict:
    """手动清理过期任务；正常运行时每小时也会自动清理。"""

    removed = await asyncio.to_thread(_cleanup_expired, _store.active_ids())
    return {"removed": removed}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8870)
