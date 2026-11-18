"""API 请求模型与结构校验。"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from config import MAX_DPI, MAX_MARKDOWN_BYTES, MIN_DPI
from utils import normalize_string_list


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    labels: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value

    @field_validator("labels", "relation_types")
    @classmethod
    def validate_string_lists(cls, value: list[str], info) -> list[str]:
        return normalize_string_list(value, info.field_name)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    labels: list[str] | None = None
    relation_types: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value

    @field_validator("labels", "relation_types")
    @classmethod
    def validate_string_lists(cls, value: list[str] | None, info) -> list[str] | None:
        if value is None:
            return None
        return normalize_string_list(value, info.field_name)


class ConversionOptions(BaseModel):
    enable_table: bool | None = None
    enable_formula: bool | None = None
    dpi: int | None = Field(default=None, ge=MIN_DPI, le=MAX_DPI)


class MarkdownUpdate(BaseModel):
    markdown: str

    @field_validator("markdown")
    @classmethod
    def validate_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            raise ValueError("Markdown 内容过大")
        return value


class AnnotationSpan(BaseModel):
    id: int
    start: int
    end: int
    label: str
    text: str = ""
    # 实体所在段落块；旧数据缺省为空字符串，保持向后兼容。
    blockId: str = ""

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("实体标签不能为空")
        if len(value) > 200:
            raise ValueError("实体标签过长")
        return value

    @field_validator("blockId")
    @classmethod
    def validate_block_id(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 64:
            raise ValueError("实体 blockId 过长")
        return value


class ParagraphAnnotation(BaseModel):
    """整段标注：一个块只允许打一个段落标签。"""

    blockId: str
    label: str
    note: str = ""

    @field_validator("blockId")
    @classmethod
    def validate_block_id(cls, value: str) -> str:
        value = (value or "").strip()
        if not value or len(value) > 64:
            raise ValueError("段落 blockId 不合法")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("段落标签不合法")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 2000:
            raise ValueError("段落备注过长")
        return value


class FigureCreate(BaseModel):
    """图表创建元数据；截图 PNG 通过 multipart 的 file 字段上传。"""

    kind: Literal["figure", "table"]
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    caption: str = ""
    note: str = ""

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4 or not all(math.isfinite(item) for item in value):
            raise ValueError("bbox 必须是 4 个有限数值")
        x0, y0, x1, y1 = value
        if x0 < 0 or y0 < 0:
            raise ValueError("bbox 坐标不能为负")
        if x1 <= x0 or y1 <= y0:
            raise ValueError("bbox 右下角必须大于左上角")
        return [float(item) for item in value]

    @field_validator("caption")
    @classmethod
    def validate_caption(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 500:
            raise ValueError("图表标题过长")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) > 2000:
            raise ValueError("图表备注过长")
        return value


class FigurePatch(BaseModel):
    """图表可编辑字段；未提供的字段保持不变。

    历史请求中的 number/label/paragraphId 不属于契约字段，按 Pydantic
    默认行为忽略，避免旧前端在过渡期直接报错。
    """

    caption: str | None = None
    note: str | None = None

    @field_validator("caption")
    @classmethod
    def validate_caption(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 500:
            raise ValueError("图表标题过长")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 2000:
            raise ValueError("图表备注过长")
        return value


class AnnotationRelation(BaseModel):
    fromId: int
    toId: int
    type: str

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("关系类型不能为空")
        if len(value) > 200:
            raise ValueError("关系类型过长")
        return value


class AnnotationInput(BaseModel):
    text: str
    spans: list[AnnotationSpan] = Field(default_factory=list)
    relations: list[AnnotationRelation] = Field(default_factory=list)
    paragraphs: list[ParagraphAnnotation] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def validate_text_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            raise ValueError("标注文本过大")
        return value

    @model_validator(mode="after")
    def validate_offsets_and_references(self) -> "AnnotationInput":
        span_ids: set[int] = set()
        text_length = len(self.text)
        for span in self.spans:
            if span.id in span_ids:
                raise ValueError(f"实体 id 重复：{span.id}")
            span_ids.add(span.id)
            if span.start < 0 or span.end <= span.start:
                raise ValueError(f"实体 {span.id} 的区间不合法")
            if span.end > text_length:
                raise ValueError(f"实体 {span.id} 超出文本范围")
        for relation in self.relations:
            if relation.fromId not in span_ids or relation.toId not in span_ids:
                raise ValueError("关系引用了不存在的实体")
        paragraph_blocks: set[str] = set()
        for paragraph in self.paragraphs:
            if paragraph.blockId in paragraph_blocks:
                raise ValueError(f"段落 blockId 重复：{paragraph.blockId}")
            paragraph_blocks.add(paragraph.blockId)
        return self
