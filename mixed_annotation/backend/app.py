"""数据标注与分类工具 混合标注主应用入口（端口 3200）。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import (
    FRONTEND_DIST,
    MAX_MARKDOWN_BYTES,
    MAX_UPLOAD_BYTES,
    OCR_WORKER_URL,
)
from errors import ServiceError
from routes import annotations, export, figures, files, projects
from services import conversion_service, queue_service
from storage import (
    cleanup_stale_uploads,
    initialize_storage,
    migrate_figure_asset_names,
    migrate_file_dirs,
    migrate_project_dirs,
    requeue_interrupted_conversions,
)
from utils import ensure_within

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_MAX_REQUEST_BODY = max(MAX_UPLOAD_BYTES, MAX_MARKDOWN_BYTES) + 2 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 迁移顺序固定：项目目录 → 文件目录 → 图表资产 → 初始化。
    # 前一步完成最终布局后，后一步才能稳定解析文件与资产路径。
    migrated = migrate_project_dirs()
    if migrated:
        logger.info("项目目录迁移完成：%s 个", migrated)
    migrated_files = migrate_file_dirs()
    if migrated_files:
        logger.info("文件目录迁移完成：%s 个", migrated_files)
    renamed_assets = migrate_figure_asset_names()
    if renamed_assets:
        logger.info("图表资产重命名完成：%s 个", renamed_assets)
    initialize_storage()
    stale = cleanup_stale_uploads()
    if stale:
        logger.warning("已清理 %s 个残留的上传中记录", stale)
    interrupted = requeue_interrupted_conversions()
    if interrupted:
        logger.warning("已将 %s 个中断的转换重新排队", interrupted)
    # 队列必须运行在当前事件循环（uvicorn 主循环）内。
    await queue_service.start()
    logger.info("主应用启动完成，OCR Worker: %s", OCR_WORKER_URL)
    try:
        yield
    finally:
        # 先停队列（worker 被取消时会把在途文件退回 uploaded），
        # 再停止立即转换任务。
        await queue_service.stop()
        await conversion_service.shutdown_conversion_tasks()


app = FastAPI(
    title="数据标注与分类工具 混合标注",
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
                return JSONResponse(
                    status_code=413,
                    content={"detail": "请求体过大"},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Content-Length 不合法"},
            )
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


@app.exception_handler(ServiceError)
async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    if errors:
        first = errors[0]
        location = ".".join(
            str(part) for part in first.get("loc", ()) if part not in {"body", "query", "path"}
        )
        message = first.get("msg", "参数不合法")
        detail = f"请求参数不合法：{location + ' ' if location else ''}{message}"
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
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
    )


app.include_router(projects.router)
app.include_router(files.router)
app.include_router(annotations.router)
app.include_router(figures.router)
app.include_router(export.router)


@app.get("/api/health", tags=["health"])
def health() -> dict:
    return {
        "status": "ok",
        "service": "label-fast-mixed",
        "version": "0.1.0",
        "ocr_worker_url": OCR_WORKER_URL,
        "active_conversions": conversion_service.active_conversion_count(),
    }


def _frontend_index() -> Path | None:
    index = FRONTEND_DIST / "index.html"
    return index if index.is_file() else None


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        return JSONResponse(status_code=404, content={"detail": "API 不存在"})

    index = _frontend_index()
    if index is not None and full_path:
        try:
            candidate = ensure_within(FRONTEND_DIST, FRONTEND_DIST / full_path)
        except ValueError:
            return JSONResponse(status_code=404, content={"detail": "资源不存在"})
        if candidate.is_file():
            return FileResponse(candidate)

    if index is not None:
        return FileResponse(index)

    if not full_path:
        return {
            "name": "数据标注与分类工具 混合标注",
            "status": "ok",
            "message": "前端尚未构建，API 可用",
            "api": "/api/health",
        }
    return JSONResponse(status_code=404, content={"detail": "资源不存在"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=3200)
