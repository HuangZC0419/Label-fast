# -*- coding: utf-8 -*-
"""航空标准分类 FastAPI 应用。"""

import atexit
import hashlib
import logging
import math
import shutil
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
from analysis import analyze_pending_file, analyze_reference_file
from classifier import (
    ClassificationPipeline,
    build_reference,
    classify_pending,
    classify_pending_groups,
)
from excel_io import (
    ExcelError,
    group_pending_records,
    load_pending,
    read_reference,
    read_table,
)
from export import (
    ExportError,
    classification_filename,
    export_pending_workbook,
    export_results,
)

LOGGER = logging.getLogger("aircraft_standard_classifier")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_SUFFIXES = (".xlsx", ".xlsm")
PIPELINE_CACHE_SIZE = 4
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
SPREADSHEET_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
# Windows 的 mimetypes 会读取注册表，.js 可能被判成 text/plain，导致浏览器拒绝加载 ES module。
STATIC_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}
UPLOAD_ROOT = Path(tempfile.mkdtemp(prefix="aircraft_std_classify_"))
atexit.register(lambda: shutil.rmtree(str(UPLOAD_ROOT), ignore_errors=True))

TASKS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
TASK_LOCK = threading.RLock()
UPLOADS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
UPLOAD_LOCK = threading.RLock()
PIPELINE_CACHE: "OrderedDict[str, ClassificationPipeline]" = OrderedDict()
PIPELINE_LOCK = threading.RLock()
MAX_UPLOADS = 24


class ApiError(Exception):
    """带 HTTP 状态码与稳定错误码的业务异常。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class PredictRequest(BaseModel):
    name: str
    code: str = ""
    task_id: str = ""


class ExportRequest(BaseModel):
    task_id: str
    overrides: Dict[str, str] = Field(default_factory=dict)


class ClassifyTaskRequest(BaseModel):
    reference_id: str
    pending_id: str
    threshold: float = config.DEFAULT_THRESHOLD


app = FastAPI(title="航空标准分类服务", version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _error_payload(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _file_digest(path: Path) -> str:
    hasher = hashlib.md5()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_pipeline(
    reference_path: Path, digest: Optional[str] = None
) -> ClassificationPipeline:
    """按「参照表路径 + 内容 MD5」缓存已训练模型，最多保留 4 份。"""
    path = Path(reference_path)
    key = "{}::{}".format(path.resolve(), digest or _file_digest(path))
    with PIPELINE_LOCK:
        cached = PIPELINE_CACHE.get(key)
        if cached is not None:
            PIPELINE_CACHE.move_to_end(key)
            return cached

        records, mapping_rows, _sheet = read_reference(path)
        reference = build_reference(records, mapping_rows)
        pipeline = ClassificationPipeline(reference)
        PIPELINE_CACHE[key] = pipeline
        while len(PIPELINE_CACHE) > PIPELINE_CACHE_SIZE:
            PIPELINE_CACHE.popitem(last=False)
    return pipeline


def _cleanup_task(task: Dict[str, Any]) -> None:
    for path_key, flag_key, label in (
        ("reference_path", "reference_is_temp", "临时参照表"),
        ("pending_path", "pending_is_temp", "临时待分类表"),
    ):
        if not task.get(flag_key):
            continue
        path = Path(task.get(path_key) or "")
        try:
            if path.is_file() and UPLOAD_ROOT in path.resolve().parents:
                path.unlink()
        except OSError:
            LOGGER.warning("%s清理失败：%s", label, path, exc_info=True)


def _get_task(task_id: str) -> Dict[str, Any]:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is not None:
            TASKS.move_to_end(task_id)
    if task is None:
        raise ApiError("TASK_NOT_FOUND", "任务不存在或已过期，请重新上传文件", 404)
    return task


def _cleanup_upload(upload: Dict[str, Any]) -> None:
    path = Path(upload.get("path") or "")
    try:
        if path.is_file() and UPLOAD_ROOT in path.resolve().parents:
            path.unlink()
    except OSError:
        LOGGER.warning("临时上传文件清理失败：%s", path, exc_info=True)


def _register_upload(kind: str, path: Path, digest: str, analysis: Dict[str, Any]) -> str:
    upload_id = uuid.uuid4().hex
    upload = {
        "id": upload_id,
        "kind": kind,
        "path": str(path),
        "digest": digest,
        "analysis": analysis,
    }
    with UPLOAD_LOCK:
        UPLOADS[upload_id] = upload
        UPLOADS.move_to_end(upload_id)
        while len(UPLOADS) > MAX_UPLOADS:
            _old_id, old_upload = UPLOADS.popitem(last=False)
            _cleanup_upload(old_upload)
    return upload_id


def _get_upload(upload_id: str, kind: str) -> Dict[str, Any]:
    with UPLOAD_LOCK:
        upload = UPLOADS.get(upload_id)
        if upload is not None:
            UPLOADS.move_to_end(upload_id)
    if upload is None or upload.get("kind") != kind:
        label = "参照表" if kind == "reference" else "待分类目录"
        raise ApiError(
            "UPLOAD_NOT_FOUND",
            "{}不存在或已过期，请重新上传".format(label),
            404,
        )
    return upload


async def _save_upload(upload: UploadFile, prefix: str) -> Tuple[Path, str]:
    """流式保存上传文件到临时目录，同时返回内容 MD5。"""
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ApiError(
            "UNSUPPORTED_FILE",
            "只支持 .xlsx / .xlsm 文件：{}".format(filename or "未命名文件"),
        )

    target = UPLOAD_ROOT / "{}_{}{}".format(prefix, uuid.uuid4().hex, suffix)
    hasher = hashlib.md5()
    size = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ApiError(
                        "FILE_TOO_LARGE",
                        "文件不能超过 20MB：{}".format(filename),
                    )
                handle.write(chunk)
                hasher.update(chunk)
        if size == 0:
            raise ApiError("EMPTY_FILE", "文件内容为空：{}".format(filename))
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    finally:
        await upload.close()
    return target, hasher.hexdigest()


def _classify_job(
    pending_path: Path,
    reference_path: Path,
    digest: str,
    threshold: float,
) -> Dict[str, Any]:
    pipeline = _load_pipeline(reference_path, digest)
    items, dedup_reports = load_pending(pending_path)
    return classify_pending(pipeline, items, threshold, dedup_reports)


def _classify_group_job(
    pending_path: Path,
    reference_path: Path,
    digest: str,
    threshold: float,
) -> Dict[str, Any]:
    pipeline = _load_pipeline(reference_path, digest)
    _header, records, _sheet = read_table(
        pending_path, required_fields=("name",), source="待分类目录"
    )
    items, reports, meta = group_pending_records(records)
    if not items:
        raise ExcelError("INVALID_FILE", "待分类目录没有可用的标准名称")
    return classify_pending_groups(pipeline, items, threshold, reports, meta)


def _resolve_reference() -> Path:
    path = Path(config.DEFAULT_REFERENCE)
    if not path.is_file():
        raise ApiError(
            "REFERENCE_NOT_FOUND",
            "默认参照表不存在：{}".format(path),
            404,
        )
    return path


def _register_task(
    reference_path: Path,
    digest: str,
    threshold: float,
    payload: Dict[str, Any],
    reference_is_temp: bool,
    pending_path: Optional[Path] = None,
    pending_is_temp: bool = False,
) -> str:
    task_id = uuid.uuid4().hex
    task = {
        "task_id": task_id,
        "reference_path": str(reference_path),
        "reference_digest": digest,
        "reference_is_temp": reference_is_temp,
        "pending_path": str(pending_path) if pending_path is not None else "",
        "pending_is_temp": pending_is_temp,
        "threshold": threshold,
        "payload": payload,
    }
    with TASK_LOCK:
        TASKS[task_id] = task
        TASKS.move_to_end(task_id)
        while len(TASKS) > config.MAX_TASKS:
            _old_id, old_task = TASKS.popitem(last=False)
            _cleanup_task(old_task)
    return task_id


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": config.APP_VERSION,
        # 分类类别完全由上传的参照表决定，服务本身不内置类别。
        "categories": [],
    }


@app.post("/api/reference/analyze")
async def analyze_reference(reference_file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传已分类国标表，返回分类分布、国标号清单与数据体检结果。"""
    display_name = Path(reference_file.filename or "").name
    path, digest = await _save_upload(reference_file, "reference")
    try:
        analysis = await run_in_threadpool(analyze_reference_file, path)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    analysis["file"]["name"] = display_name or path.name
    reference_id = _register_upload("reference", path, digest, analysis)
    response: Dict[str, Any] = {"reference_id": reference_id}
    response.update(analysis)
    return response


@app.post("/api/pending/analyze")
async def analyze_pending(pending_file: UploadFile = File(...)) -> Dict[str, Any]:
    """上传待分类目录，返回去重、缺失与预览信息。"""
    display_name = Path(pending_file.filename or "").name
    path, digest = await _save_upload(pending_file, "pending")
    try:
        analysis = await run_in_threadpool(analyze_pending_file, path)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    analysis["file"]["name"] = display_name or path.name
    pending_id = _register_upload("pending", path, digest, analysis)
    response: Dict[str, Any] = {"pending_id": pending_id}
    response.update(analysis)
    return response


@app.post("/api/tasks/classify")
async def classify_task(request: ClassifyTaskRequest) -> Dict[str, Any]:
    """使用已上传并通过体检的参照表与待分类目录执行分类。"""
    threshold = float(request.threshold)
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ApiError("INVALID_THRESHOLD", "阈值必须大于 0 且小于 1")

    reference = _get_upload(request.reference_id, "reference")
    pending = _get_upload(request.pending_id, "pending")
    reference_path = Path(reference["path"])
    pending_source = Path(pending["path"])

    suffix = pending_source.suffix.lower() or ".xlsx"
    task_pending_path = UPLOAD_ROOT / "task_pending_{}{}".format(
        uuid.uuid4().hex, suffix
    )
    shutil.copyfile(pending_source, task_pending_path)
    try:
        payload = await run_in_threadpool(
            _classify_group_job,
            task_pending_path,
            reference_path,
            reference["digest"],
            threshold,
        )
    except Exception:
        try:
            task_pending_path.unlink()
        except OSError:
            pass
        raise

    payload["columns"] = reference["analysis"].get("columns") or {}
    payload["pending"] = {
        "file_name": pending["analysis"]["file"]["name"],
        "sheet": pending["analysis"]["file"]["sheet"],
        "header_row": pending["analysis"]["file"].get("header_row", 1),
        "columns": pending["analysis"].get("columns") or {},
    }
    task_id = _register_task(
        reference_path,
        reference["digest"],
        threshold,
        payload,
        reference_is_temp=False,
        pending_path=task_pending_path,
        pending_is_temp=True,
    )
    response: Dict[str, Any] = {"task_id": task_id}
    response.update(payload)
    return response


@app.post("/api/classify")
async def classify(
    pending_file: UploadFile = File(...),
    reference_file: Optional[UploadFile] = File(None),
    threshold: float = Form(config.DEFAULT_THRESHOLD),
) -> Dict[str, Any]:
    if not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ApiError("INVALID_THRESHOLD", "阈值必须大于 0 且小于 1")

    pending_path: Optional[Path] = None
    reference_path: Optional[Path] = None
    reference_is_temp = False
    try:
        pending_path, _pending_digest = await _save_upload(pending_file, "pending")

        if reference_file is not None and (reference_file.filename or "").strip():
            reference_path, reference_digest = await _save_upload(
                reference_file, "reference"
            )
            reference_is_temp = True
        else:
            reference_path = _resolve_reference()
            reference_digest = _file_digest(reference_path)

        payload = await run_in_threadpool(
            _classify_job, pending_path, reference_path, reference_digest, threshold
        )
        task_id = _register_task(
            reference_path,
            reference_digest,
            threshold,
            payload,
            reference_is_temp,
        )
        response: Dict[str, Any] = {"task_id": task_id}
        response.update(payload)
        return response
    except Exception:
        if reference_is_temp and reference_path is not None:
            try:
                reference_path.unlink()
            except OSError:
                pass
        raise
    finally:
        if pending_path is not None:
            try:
                pending_path.unlink()
            except OSError:
                pass


@app.post("/api/predict")
def predict(request: PredictRequest) -> Dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise ApiError("INVALID_PARAMETER", "标准名称不能为空")

    if request.task_id:
        task = _get_task(request.task_id)
        pipeline = _load_pipeline(
            Path(task["reference_path"]), task["reference_digest"]
        )
    else:
        reference_path = _resolve_reference()
        pipeline = _load_pipeline(reference_path, _file_digest(reference_path))
    return pipeline.predict(name, request.code)


@app.post("/api/export")
def export(request: ExportRequest) -> Dict[str, Any]:
    task = _get_task(request.task_id)
    payload = task["payload"]
    categories = [
        item["profession"]
        for item in payload.get("categories") or []
        if item.get("profession")
    ]
    overrides: Dict[int, str] = {}
    for key, value in request.overrides.items():
        try:
            index = int(key)
        except (TypeError, ValueError):
            raise ApiError("INVALID_OVERRIDE", "人工复核的序号无效：{}".format(key))
        profession = str(value or "").strip()
        if profession not in categories:
            raise ApiError(
                "INVALID_OVERRIDE",
                "未知的专业名称：{}".format(profession or "空"),
            )
        overrides[index] = profession

    output_dir = Path(config.OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = classification_filename(output_dir)
    if task.get("pending_path"):
        path = export_pending_workbook(
            Path(task["pending_path"]),
            payload,
            overrides,
            output_dir / filename,
            categories=categories,
        )
    else:
        path = export_results(
            payload,
            overrides,
            output_dir / filename,
            threshold=task["threshold"],
            categories=categories,
        )
    return {
        "path": str(path),
        "download_url": "/api/download/" + quote(filename, safe=""),
        "filename": filename,
    }


@app.get("/api/download/{filename}")
def download(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    if (
        not filename
        or safe_name != filename
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
        or Path(safe_name).suffix.lower() != ".xlsx"
    ):
        raise ApiError("INVALID_FILENAME", "文件名不合法", 400)

    output_dir = Path(config.OUTPUT_DIR).resolve()
    target = (output_dir / safe_name).resolve()
    if output_dir != target.parent and output_dir not in target.parents:
        raise ApiError("INVALID_FILENAME", "文件名不合法", 400)
    if not target.is_file():
        raise ApiError("FILE_NOT_FOUND", "文件不存在：{}".format(safe_name), 404)
    return FileResponse(
        str(target), media_type=SPREADSHEET_MEDIA_TYPE, filename=safe_name
    )


# ---------------------------------------------------------------------------
# 前端静态资源与 SPA 回退（必须在 API 路由之后注册）
# ---------------------------------------------------------------------------


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise ApiError("NOT_FOUND", "接口不存在：/{}".format(full_path), 404)
    index_file = FRONTEND_DIST / "index.html"
    if not index_file.is_file():
        raise ApiError(
            "NOT_FOUND",
            "前端页面尚未构建，请先在 frontend 目录执行 npm run build",
            404,
        )
    if full_path:
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_file() and (
            FRONTEND_DIST.resolve() in candidate.parents
        ):
            suffix = candidate.suffix.lower()
            cache_control = None
            if suffix == ".html":
                cache_control = "no-cache"
            elif full_path.startswith("assets/"):
                cache_control = "public, max-age=31536000, immutable"
            headers = {"Cache-Control": cache_control} if cache_control else None
            return FileResponse(
                str(candidate),
                media_type=STATIC_MEDIA_TYPES.get(suffix),
                headers=headers,
            )
        if candidate.suffix:
            raise ApiError(
                "NOT_FOUND", "静态资源不存在：/{}".format(full_path), 404
            )
    return FileResponse(
        str(index_file),
        media_type=STATIC_MEDIA_TYPES[".html"],
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# 统一异常处理
# ---------------------------------------------------------------------------


_NOT_FOUND_CODES = {"FILE_NOT_FOUND", "SHEET_NOT_FOUND", "TASK_NOT_FOUND", "NOT_FOUND"}


def _status_for_code(code: str, default: int = 400) -> int:
    return 404 if code in _NOT_FOUND_CODES else default


@app.exception_handler(ApiError)
async def api_error_handler(_request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.code, exc.message),
    )


@app.exception_handler(ExcelError)
async def excel_error_handler(_request, exc: ExcelError) -> JSONResponse:
    return JSONResponse(
        status_code=_status_for_code(exc.code),
        content=_error_payload(exc.code, exc.message),
    )


@app.exception_handler(ExportError)
async def export_error_handler(_request, exc: ExportError) -> JSONResponse:
    return JSONResponse(
        status_code=_status_for_code(exc.code),
        content=_error_payload(exc.code, exc.message),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request, exc: RequestValidationError) -> JSONResponse:
    details: List[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = error.get("msg", "参数不合法")
        details.append("{}：{}".format(location or "请求参数", message))
    return JSONResponse(
        status_code=400,
        content=_error_payload(
            "INVALID_PARAMETER", "请求参数不合法；{}".format("；".join(details))
        ),
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 405:
        code = "METHOD_NOT_ALLOWED"
    else:
        code = "HTTP_ERROR"
    message = exc.detail if isinstance(exc.detail, str) else "请求失败"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code, message),
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_request, exc: Exception) -> JSONResponse:
    LOGGER.exception("未处理的服务器异常", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=_error_payload("INTERNAL_ERROR", "服务器内部错误，请稍后重试"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
