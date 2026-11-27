"""跨项目实体标签目录：供「从其他项目导入标签」弹窗使用。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from storage import label_catalog

router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.get("/catalog")
def get_label_catalog(
    exclude_project_id: str | None = Query(default=None, alias="exclude"),
) -> dict:
    """汇总所有项目（可排除当前项目）的实体标签与引用次数。

    ``exclude`` 传当前项目 id 时，只统计其他项目；
    返回 ``{"labels": [{label, project_count, usage_count}]}``。
    """

    return {"labels": label_catalog(exclude_project_id)}
