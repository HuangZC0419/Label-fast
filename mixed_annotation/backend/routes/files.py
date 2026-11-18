"""文件上传、转换与 Markdown / 原始文件读取路由。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, Response, UploadFile, status
from fastapi.responses import FileResponse

from config import (
    ALLOWED_UPLOADS,
    DEFAULT_DPI,
    DEFAULT_ENABLE_FORMULA,
    DEFAULT_ENABLE_TABLE,
    MAX_DPI,
    MAX_UPLOAD_BYTES,
    MIN_DPI,
)
from errors import (
    BadRequestError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceError,
)
from schemas import ConversionOptions, MarkdownUpdate
from serializers import serialize_file
from services import block_service, conversion_service, queue_service
from storage import (
    create_file,
    delete_file,
    get_file,
    has_annotations,
    markdown_path,
    read_markdown,
    reset_annotations,
    resolve_asset,
    resolve_figure_asset,
    save_markdown,
    source_path,
    update_file,
)
from utils import (
    clean_display_filename,
    normalize_extension,
    validate_magic_header,
)

router = APIRouter(prefix="/api", tags=["files"])

logger = logging.getLogger(__name__)

_UPLOAD_CHUNK = 1024 * 1024


def _reset_after_markdown_edit(file_id: str) -> None:
    """Markdown 内容变化后：删除旧页码映射、重建 blocks、清空文本类标注。

    图表记录与截图资产保留；失效的 paragraphId 置空。
    """

    block_service.delete_pages(file_id)
    try:
        blocks = block_service.rebuild_blocks(file_id)
    except Exception:
        logger.exception("Markdown 保存后重建 blocks 失败：file_id=%s", file_id)
        # 无法校验段落归属时保留原值，等待 GET /blocks 懒重建后再处理。
        reset_annotations(file_id, valid_paragraph_ids=None)
        return
    valid_ids = {
        str(item.get("id"))
        for item in blocks.get("blocks", [])
        if isinstance(item, dict) and item.get("id")
    }
    reset_annotations(file_id, valid_paragraph_ids=valid_ids)


def _public_detail(meta: dict) -> dict:
    result = serialize_file(meta)
    result["has_markdown"] = markdown_path(meta).is_file()
    result["has_annotations"] = has_annotations(meta["id"])
    return result


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise PayloadTooLargeError(
                    f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 限制"
                )
            handle.write(chunk)
    if total == 0:
        raise BadRequestError("上传文件为空")
    return total


@router.post(
    "/projects/{project_id}/files",
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    enable_table: bool = Form(DEFAULT_ENABLE_TABLE),
    enable_formula: bool = Form(DEFAULT_ENABLE_FORMULA),
    dpi: int = Form(DEFAULT_DPI),
    defer_conversion: bool = Form(False),
) -> dict:
    """保存原始文件并创建记录。

    ``defer_conversion=True`` 时只入库并交给夜间串行队列，不立即转换；
    默认 False，保持单文件上传后立即提交 OCR Worker 的原有行为。
    """

    if dpi < MIN_DPI or dpi > MAX_DPI:
        raise BadRequestError(f"dpi 必须在 {MIN_DPI} 到 {MAX_DPI} 之间")

    extension = normalize_extension(file.filename)
    allowed = ALLOWED_UPLOADS.get(extension)
    if allowed is None:
        raise BadRequestError("仅支持 PDF、PNG、JPG、JPEG 文件")
    source_type, media_type = allowed

    try:
        display_name = clean_display_filename(file.filename)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc

    # 先以 uploading 入库：队列只认领 uploaded，因此校验完成前不会
    # 把半截文件提交给 OCR Worker。
    meta, target = create_file(
        project_id,
        display_name,
        extension,
        source_type=source_type,
        enable_table=enable_table,
        enable_formula=enable_formula,
        dpi=dpi,
        initial_status="uploading",
    )
    file_id = meta["id"]

    saved_ok = False
    try:
        await _save_upload(file, target)
        with target.open("rb") as handle:
            head = handle.read(1024)
        if not validate_magic_header(extension, head):
            raise BadRequestError("文件内容与扩展名不匹配")
        saved_ok = True
    except OSError as exc:
        raise ServiceError(500, "保存上传文件失败") from exc
    finally:
        # 任何失败（超限、校验失败、ClientDisconnect、CancelledError 等）
        # 都保证只清理一次记录与半截源文件。
        try:
            await file.close()
        finally:
            if not saved_ok:
                try:
                    delete_file(file_id)
                except NotFoundError:
                    pass
                except Exception:
                    logger.exception(
                        "清理上传失败记录失败：file_id=%s", file_id
                    )

    if defer_conversion:
        # 仅入库：校验通过后才切到 uploaded，交给夜间队列串行转换。
        try:
            updated = update_file(
                file_id,
                {
                    "status": "uploaded",
                    "progress": 0,
                    "stage": "排队中",
                    "message": "",
                    "error": "",
                    "task_id": "",
                },
            )
        except Exception:
            # 切队失败时不能留下 uploaded 记录，按上传失败清理。
            try:
                delete_file(file_id)
            except Exception:
                logger.exception("清理入队失败记录失败：file_id=%s", file_id)
            raise
        queue_service.wake()
        return _public_detail(updated)

    try:
        updated = await conversion_service.start_conversion(
            file_id,
            enable_table=enable_table,
            enable_formula=enable_formula,
            dpi=dpi,
            reset_results=False,
            filename=meta["source_filename"],
            content_type=media_type,
        )
    except Exception:
        # 文件已完整落盘；标记失败，保留记录供用户重试。
        try:
            update_file(
                file_id,
                {
                    "status": "failed",
                    "stage": "转换失败",
                    "message": "无法启动转换，请重试",
                    "error": "无法启动转换，请重试",
                },
            )
        except Exception:
            pass
        raise
    return _public_detail(updated)


@router.get("/files/{file_id}")
def get_file_detail(file_id: str) -> dict:
    return _public_detail(get_file(file_id))


@router.get("/files/{file_id}/status")
def get_file_status(file_id: str) -> dict:
    meta = get_file(file_id)
    return {
        "status": meta.get("status", "failed"),
        "progress": int(meta.get("progress") or 0),
        "stage": meta.get("stage", ""),
        "message": meta.get("message", ""),
        "error": meta.get("error", ""),
        "page_count": int(meta.get("page_count") or 0),
    }


@router.post("/files/{file_id}/convert", status_code=status.HTTP_202_ACCEPTED)
async def reconvert_file(
    file_id: str,
    payload: ConversionOptions | None = Body(default=None),
) -> dict:
    meta = get_file(file_id)
    options = payload or ConversionOptions()
    enable_table = (
        meta.get("enable_table", DEFAULT_ENABLE_TABLE)
        if options.enable_table is None
        else options.enable_table
    )
    enable_formula = (
        meta.get("enable_formula", DEFAULT_ENABLE_FORMULA)
        if options.enable_formula is None
        else options.enable_formula
    )
    dpi = int(meta.get("dpi", DEFAULT_DPI) if options.dpi is None else options.dpi)
    extension = f".{meta.get('source_ext', '')}"
    media_type = ALLOWED_UPLOADS.get(extension, ("image", "application/octet-stream"))[1]

    updated = await conversion_service.start_conversion(
        file_id,
        enable_table=bool(enable_table),
        enable_formula=bool(enable_formula),
        dpi=dpi,
        reset_results=True,
        filename=meta["source_filename"],
        content_type=media_type,
    )
    return _public_detail(updated)


@router.get("/files/{file_id}/markdown")
def get_markdown(file_id: str) -> dict:
    meta = get_file(file_id)
    content = read_markdown(file_id)
    if content is None:
        raise NotFoundError("Markdown 尚未生成")
    return {"markdown": content, "page_count": int(meta.get("page_count") or 0)}


@router.put("/files/{file_id}/markdown")
def put_markdown(file_id: str, payload: MarkdownUpdate) -> dict:
    meta = save_markdown(file_id, payload.markdown)
    _reset_after_markdown_edit(file_id)
    return {
        "markdown": payload.markdown,
        "page_count": int(meta.get("page_count") or 0),
    }


@router.get("/files/{file_id}/blocks")
def get_blocks(file_id: str) -> dict:
    """返回块切分结果；blocks.json 缺失或过期时懒重建。"""

    return block_service.load_blocks(file_id)


@router.get("/files/{file_id}/figure-assets/{name}")
def get_figure_asset(file_id: str, name: str) -> FileResponse:
    path = resolve_figure_asset(file_id, name)
    return FileResponse(
        path,
        media_type="image/png",
        content_disposition_type="inline",
    )


@router.get("/files/{file_id}/source")
def get_source(file_id: str) -> FileResponse:
    meta = get_file(file_id)
    path = source_path(meta)
    if not path.is_file():
        raise NotFoundError("原始文件不存在")
    extension = f".{meta.get('source_ext', '')}"
    media_type = ALLOWED_UPLOADS.get(extension, ("image", "application/octet-stream"))[1]
    return FileResponse(
        path,
        media_type=media_type,
        filename=meta.get("name") or path.name,
        content_disposition_type="inline",
    )


@router.get("/files/{file_id}/assets/{asset_path:path}")
def get_asset(file_id: str, asset_path: str) -> FileResponse:
    path = resolve_asset(file_id, asset_path)
    return FileResponse(path)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_file(file_id: str) -> Response:
    delete_file(file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
