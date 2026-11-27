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
    """项目增量更新请求。

    字典字段的语义（多人协同修复，见 docs/多人协同标签覆盖修复.md）：

    - ``labels`` / ``relation_types`` 保留以兼容旧前端包，但**只作为追加项**
      （与现有字典求并集），收到全量数组也不会删除任何已有条目；
    - 真正删除必须通过 ``labels_remove`` / ``relation_types_remove``；
    - 删除仍被标注引用的实体标签需要 ``force=True``，否则服务层返回 409。

    项目级快捷键（见 docs/项目拆分与自定义快捷键.md）：

    - ``shortcuts_set``：``{标签名: 组合键}``，逐项覆盖默认的 1–9；
    - ``shortcuts_unset``：删除覆盖项，回落到默认（前 9 个标签）或「无快捷键」。

    校验在这里一次完成（去空白、去重、200 字上限），服务层只处理干净列表。
    快捷键的**格式/保留键/冲突**校验属于业务规则（返回 400/409），
    由 ``services.shortcut_service`` 完成，这里只做类型与长度收敛。
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    # 旧字段：降级为追加项，防止旧前端整份覆盖别人新增的标签。
    labels: list[str] | None = None
    relation_types: list[str] | None = None
    # 新字段：显式增量。
    labels_add: list[str] | None = None
    labels_remove: list[str] | None = None
    relation_types_add: list[str] | None = None
    relation_types_remove: list[str] | None = None
    # 项目级自定义快捷键：只提交显式覆盖项与清除项。
    shortcuts_set: dict[str, str] | None = None
    shortcuts_unset: list[str] | None = None
    # 删除仍被标注引用的标签时，必须显式确认。
    force: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value

    @field_validator(
        "labels",
        "relation_types",
        "labels_add",
        "labels_remove",
        "relation_types_add",
        "relation_types_remove",
        "shortcuts_unset",
    )
    @classmethod
    def validate_string_lists(cls, value: list[str] | None, info) -> list[str] | None:
        if value is None:
            return None
        return normalize_string_list(value, info.field_name)

    @field_validator("shortcuts_set")
    @classmethod
    def validate_shortcuts_set(
        cls, value: dict[str, str] | None
    ) -> dict[str, str] | None:
        if value is None:
            return None
        normalized: dict[str, str] = {}
        for label, shortcut in value.items():
            key = str(label).strip()
            if not key:
                raise ValueError("快捷键对应的标签名不能为空")
            if len(key) > 200:
                raise ValueError("快捷键对应的标签名过长")
            text = str(shortcut).strip()
            if not text:
                raise ValueError(f"标签「{key}」的快捷键不能为空")
            normalized[key] = text
        return normalized


class ProjectSplitGroup(BaseModel):
    """一组拆分区间：文件序号 1 基、闭区间 ``[start, end]``。

    序号范围、区间重叠、新项目重名等语义校验都依赖项目当前文件总数 N，
    只能在 ``storage.split_project`` 里完成（失败统一返回 400），
    因此这里只做类型收敛。
    """

    name: str = ""
    start: int
    end: int


class ProjectSplitRequest(BaseModel):
    """按文件序号区间拆分项目；``groups`` 的顺序就是响应的项目顺序。"""

    groups: list[ProjectSplitGroup] = Field(default_factory=list)


class ExcelExportRequest(BaseModel):
    """多项目标注明细导出请求。

    入参在这里就完成「去空白 + 保序去重」：服务层因此只处理干净的 id 列表，
    路由层也不需要再做一次防御性清洗。空数组、全空白项都会在 before 校验
    阶段被拦下并返回中文 422，而不是落到服务层产生空工作簿。
    """

    project_ids: list[str] = Field(min_length=1, max_length=200)

    @field_validator("project_ids", mode="before")
    @classmethod
    def normalize_project_ids(cls, value):
        # 非列表交给 Pydantic 报类型错误，这里只处理可枚举的序列。
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("项目 id 必须是字符串")
            current = item.strip()
            if not current or current in seen:
                continue
            seen.add(current)
            normalized.append(current)
        if not normalized:
            raise ValueError("请至少选择一个项目")
        return normalized


class ConversionOptions(BaseModel):
    enable_table: bool | None = None
    enable_formula: bool | None = None
    dpi: int | None = Field(default=None, ge=MIN_DPI, le=MAX_DPI)
    # auto：正常走 MinerU 自动判断（坏文字层会自动转 OCR）；
    # txt：只用 PDF 文本层；ocr：强制整页 OCR。
    parse_method: Literal["auto", "txt", "ocr"] | None = None


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
