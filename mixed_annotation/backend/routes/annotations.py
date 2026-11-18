"""实体与关系标注路由。"""

from __future__ import annotations

from fastapi import APIRouter

from schemas import AnnotationInput
from serializers import serialize_annotation
from storage import load_annotations, save_annotations

router = APIRouter(prefix="/api/files", tags=["annotations"])


@router.get("/{file_id}/annotations")
def get_annotations(file_id: str) -> dict:
    return serialize_annotation(load_annotations(file_id))


@router.put("/{file_id}/annotations")
def put_annotations(file_id: str, payload: AnnotationInput) -> dict:
    # 以 canonical text 为准重新切片，确保导出的 span.text 与偏移一致。
    spans = [
        {
            "id": span.id,
            "start": span.start,
            "end": span.end,
            "label": span.label,
            "text": payload.text[span.start : span.end],
            "blockId": span.blockId,
        }
        for span in payload.spans
    ]
    relations = [
        {
            "fromId": relation.fromId,
            "toId": relation.toId,
            "type": relation.type,
        }
        for relation in payload.relations
    ]
    paragraphs = [
        {"blockId": item.blockId, "label": item.label, "note": item.note}
        for item in payload.paragraphs
    ]
    record = save_annotations(
        file_id,
        {
            "text": payload.text,
            "spans": spans,
            "relations": relations,
            "paragraphs": paragraphs,
        },
    )
    return serialize_annotation(record)
