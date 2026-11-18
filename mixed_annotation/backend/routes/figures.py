"""PDF 拖框截图（图表/表格）的创建、修改与删除路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Response, UploadFile, status
from pydantic import ValidationError

from config import MAX_FIGURE_BYTES
from errors import BadRequestError
from schemas import FigureCreate, FigurePatch
from services import block_service
from storage import add_figure, delete_figure, get_file, update_figure

router = APIRouter(prefix="/api/files", tags=["figures"])

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def validate_png_upload(content: bytes) -> None:
    """校验截图大小与 PNG magic；失败统一返回 400。"""

    if not content:
        raise BadRequestError("截图内容为空")
    if len(content) > MAX_FIGURE_BYTES:
        raise BadRequestError(
            f"截图超过 {MAX_FIGURE_BYTES // (1024 * 1024)}MB 限制"
        )
    if not content.startswith(_PNG_MAGIC):
        raise BadRequestError("仅支持 PNG 截图")


def validate_figure_against_pages(
    page: int,
    bbox: list[float],
    pages: list[dict[str, Any]],
    page_count: int,
) -> None:
    """校验页码是否在文档范围内、bbox 是否落在页面尺寸内。"""

    if page < 1:
        raise BadRequestError("页码不合法")
    page_numbers = {
        int(item["page"])
        for item in pages
        if isinstance(item, dict) and isinstance(item.get("page"), int)
    }
    known_count = max([page_count, *page_numbers]) if page_numbers else page_count
    if known_count > 0 and page > known_count:
        raise BadRequestError(f"页码超出范围（1-{known_count}）")

    entry = next(
        (
            item
            for item in pages
            if isinstance(item, dict) and int(item.get("page") or 0) == page
        ),
        None,
    )
    if entry is None:
        # 没有该页尺寸信息时只能做数值层面的校验。
        return
    width = float(entry.get("width") or 0)
    height = float(entry.get("height") or 0)
    if width <= 0 or height <= 0:
        return
    x0, y0, x1, y1 = bbox
    # 允许 1pt/px 的换算误差，避免前端取整导致边界误判。
    tolerance = 1.0
    if (
        x0 > width + tolerance
        or y0 > height + tolerance
        or x1 > width + tolerance
        or y1 > height + tolerance
    ):
        raise BadRequestError("截图范围超出页面尺寸")


def _parse_meta(raw: str) -> FigureCreate:
    try:
        return FigureCreate.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors()
        message = errors[0].get("msg", "图表参数不合法") if errors else "图表参数不合法"
        raise BadRequestError(f"图表参数不合法：{message}") from exc


@router.post(
    "/{file_id}/figures",
    status_code=status.HTTP_201_CREATED,
)
async def create_figure(
    file_id: str,
    file: UploadFile = File(...),
    meta: str = Form(...),
) -> dict:
    payload = _parse_meta(meta)
    try:
        content = await file.read(MAX_FIGURE_BYTES + 1)
    finally:
        await file.close()

    validate_png_upload(content)
    file_meta = get_file(file_id)
    page_count = int(file_meta.get("page_count") or 0)
    validate_figure_against_pages(
        payload.page,
        payload.bbox,
        block_service.load_pages(file_id),
        page_count,
    )

    figure = add_figure(file_id, payload.model_dump(), content)
    return figure


@router.patch("/{file_id}/figures/{figure_id}")
def patch_figure(
    file_id: str, figure_id: str, payload: FigurePatch
) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    return update_figure(file_id, figure_id, changes)


@router.delete(
    "/{file_id}/figures/{figure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_figure(file_id: str, figure_id: str) -> Response:
    delete_figure(file_id, figure_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
