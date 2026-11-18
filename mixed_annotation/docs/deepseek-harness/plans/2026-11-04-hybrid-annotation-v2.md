# 数据标注与分类工具 混合标注 v2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 数据标注与分类工具 增加段落级标注、PDF 拖框截图、图表标注、双文件导出，并让知识库能导入 graph.jsonl 建图。

**Architecture:** OCR Worker 输出逐页 Markdown 偏移（pages.json）；后端切块为 blocks.json 并作为唯一权威；前端逐块渲染 Markdown，段落打标与实体标注共存；图表由前端高清离屏截图上传，后端存文件级 assets；导出保留旧 annotations.jsonl 并新增 graph.jsonl。

**Tech Stack:** FastAPI + Pydantic 2、Vue 3 + TypeScript + Vite、pdf.js、PP-StructureV3 Worker、JSONL 文件存储。

**设计文档:** `docs/deepseek-harness/specs/2026-11-04-hybrid-annotation-v2-design.md`

---

## 任务总览与并行分组

| 阶段 | 任务 | 负责 Agent | 文件所有权 |
|---|---|---|---|
| 1（并行） | A. 后端模型/存储/切块/路由 | backend-python-architect | `backend/schemas.py`、`storage.py`、`services/block_service.py`、`routes/files.py`、`routes/annotations.py`、`routes/figures.py`、`app.py`、`serializers.py`、`config.py` |
| 1（并行） | B. Worker pages.json | backend-python-architect | `ocr_worker/convert.py` |
| 1（并行） | C. 前端逐块渲染与段落标注 | frontend-vue-engineer | `frontend/src/types.ts`、`api/client.ts`、`utils/blocks.ts`、`MarkdownAnnotator.vue`、`useMarkdownAnnotation.ts`、`MixedWorkspace.vue` |
| 1（并行） | D. 知识库 graph 导入 | backend-python-architect | 知识库 `jsonl_import.py`、`datasource.py`、`frontend/src/App.vue` |
| 2（并行） | E. 前端 PDF 截图与图表 | frontend-vue-engineer | `PdfPreview.vue`、`FigureDialog.vue`、`MixedWorkspace.vue`（在 C 完成后衔接） |
| 2（并行） | F. 后端双文件导出 | backend-python-architect | `backend/services/export_service.py` |
| 3 | G. 审查与集成验证 | code-review-debugger | 全仓库 |

---

## Task A：后端模型、存储、切块、路由

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/storage.py`
- Create: `backend/services/block_service.py`
- Create: `backend/routes/figures.py`
- Modify: `backend/routes/files.py`
- Modify: `backend/routes/annotations.py`
- Modify: `backend/serializers.py`
- Modify: `backend/config.py`
- Modify: `backend/app.py`
- Create: `backend/tests/test_blocks.py`
- Create: `backend/tests/test_figure_rules.py`

- [ ] **Step 1: 扩展 schemas**

在 `backend/schemas.py` 增加：

```python
class ParagraphAnnotation(BaseModel):
    blockId: str
    label: str
    note: str = ""

    @field_validator("blockId")
    @classmethod
    def validate_block_id(cls, value: str) -> str:
        value = value.strip()
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


class FigureCreate(BaseModel):
    kind: Literal["figure", "table"]
    page: int = Field(ge=1)
    bbox: list[float] = Field(min_length=4, max_length=4)
    number: str = ""
    caption: str = ""
    label: str = ""
    paragraphId: str = ""
    note: str = ""


class FigurePatch(BaseModel):
    number: str | None = None
    caption: str | None = None
    label: str | None = None
    paragraphId: str | None = None
    note: str | None = None
```

`AnnotationSpan` 增加 `blockId: str = ""`；`AnnotationInput` 增加：

```python
    paragraphs: list[ParagraphAnnotation] = Field(default_factory=list)
```

并在 `model_validator` 中校验段落 blockId 不重复。

- [ ] **Step 2: 写 block_service**

`backend/services/block_service.py` 公开：

```python
def parse_blocks(markdown: str, pages: list[dict] | None = None) -> dict
def load_blocks(file_id: str) -> dict
def rebuild_blocks(file_id: str) -> dict
def blocks_path(file_id: str) -> Path
def pages_path(file_id: str) -> Path
def save_pages(file_id: str, payload: dict) -> None
def validate_block(blocks: dict, block_id: str) -> bool
```

切块规则（按行扫描，保留原始偏移）：
- 空行跳过。
- ``` 围栏：整段一个 `code` 块。
- `^#{1,6}\s+`：一个 `heading` 块。
- 连续 `|` 行：一个 `table` 块。
- 连续 `^\s*([-*+]|\d+\.)\s+`：一个 `list` 块。
- 连续 `^>`：一个 `blockquote` 块。
- 单行 `^\s*!\[[^\]]*\]\([^)]*\)\s*$`：一个 `image` 块。
- 连续 `<` 开头行：一个 `html` 块。
- 其余连续非空行：一个 `paragraph` 块。

每个块：

```python
{
  "id": f"b{index + 1:04d}",
  "index": index,
  "type": block_type,
  "markdown": source_slice,
  "text": plain_text(source_slice),
  "start": start_offset,
  "end": end_offset,
  "lineStart": start_line,
  "lineEnd": end_line,
  "page": page_for(start_offset),
  "pageEnd": page_for(max(start_offset, end_offset - 1)),
  "sectionId": current_section_id,
  "sectionNumber": current_section_number,
  "sectionTitle": current_section_title,
}
```

章节：heading 文本去 `#` 后匹配 `^(\d+(?:\.\d+)*|附录[A-Z]|[A-Z]\d*)`；section id 为 `s{heading index:04d}`。
页码：`pages` 每项 `{page,width,height,start,end}`；找到 `start <= offset < end` 的页；找不到返回 0。

返回：

```python
{"version": 1, "markdown_hash": "sha256:...", "pages": pages or [],
 "sections": [...], "blocks": [...]}
```

`rebuild_blocks(file_id)` 读取 markdown 与 `pages.json`，写 `blocks.json`（文件级，原子写）；`load_blocks` 在缺失或 hash 不匹配时调用 `rebuild_blocks`。

- [ ] **Step 3: 扩展 storage**

在 `backend/storage.py` 增加：

```python
def pages_path(file_meta) -> Path: return file_dir(file_meta) / "pages.json"
def blocks_path(file_meta) -> Path: return file_dir(file_meta) / "blocks.json"
def figure_assets_dir(file_meta) -> Path: return file_dir(file_meta) / "assets" / "figures"
def resolve_figure_asset(file_id: str, name: str) -> Path
```

`resolve_figure_asset` 只允许单层文件名，拒绝 `/`、`..`、绝对路径，必须 `is_file()`。
`_empty_annotations()` 增加 `"paragraphs": [], "figures": []`；`load_annotations` 保证二者为 list。
`save_annotations` 改为保留已有 figures：

```python
existing = load_annotations(file_id)
record = {"text": payload["text"], "spans": payload["spans"],
          "relations": payload["relations"], "paragraphs": payload["paragraphs"],
          "figures": existing.get("figures", []), "updated_at": utc_now()}
```

`clear_results(file_id, clear_annotations=True)`：删除 markdown 目录、`pages.json`、`blocks.json`；若 `clear_annotations`，读取旧标注，保留 `figures`，写回只含 figures 的记录；若没有 figures 则删除 annotations.json。

新增图表存储函数（均在 `_LOCK` 内）：

```python
def add_figure(file_id, figure: dict, content: bytes) -> dict
def update_figure(file_id, figure_id: str, changes: dict) -> dict
def delete_figure(file_id, figure_id: str) -> None
def list_figures(file_id) -> list[dict]
```

`add_figure` 按 kind 生成 `fig_0001` / `tbl_0001`，写资产到 `figure_assets_dir`（临时文件 + `os.replace`），记录 `assetPath`。

- [ ] **Step 4: 路由**

`backend/routes/files.py` 增加：

```python
@router.get("/files/{file_id}/blocks")
def get_blocks(file_id: str) -> dict:
    return block_service.load_blocks(file_id)

@router.get("/files/{file_id}/figure-assets/{name}")
def get_figure_asset(file_id: str, name: str) -> FileResponse:
    return FileResponse(resolve_figure_asset(file_id, name))
```

`PUT /markdown` 在保存后：删除 `pages.json`、`block_service.rebuild_blocks(file_id)`、清空文本/段落标注（保留 figures）。

`backend/routes/figures.py` 新建：

```python
router = APIRouter(prefix="/api/files", tags=["figures"])

@router.post("/{file_id}/figures", status_code=201)
async def create_figure(file_id: str, file: UploadFile = File(...), meta: str = Form(...)) -> dict:
    # FigureCreate.model_validate_json(meta)
    # 校验 PNG magic、大小、page/bbox
    # storage.add_figure(...)

@router.patch("/{file_id}/figures/{figure_id}")
def patch_figure(file_id: str, figure_id: str, payload: FigurePatch) -> dict: ...

@router.delete("/{file_id}/figures/{figure_id}", status_code=204)
def remove_figure(file_id: str, figure_id: str) -> Response: ...
```

`app.py` 注册 `figures.router`。
`config.py` 增加 `MAX_FIGURE_BYTES = 20 * 1024 * 1024`。
`serializers.serialize_annotation` 增加 `paragraphs`、`figures`。

- [ ] **Step 5: 测试**

`backend/tests/test_blocks.py`：用一段包含标题、段落、列表、表格、图片、代码的 Markdown，断言块类型、章节号、页码映射、block id。
`backend/tests/test_figure_rules.py`：断言 bbox 四元数、page>=1、id 生成规则。

运行：

```bash
cd backend && python -m unittest discover -s tests -v
```

预期：全部 PASS。

---

## Task B：Worker 输出 pages.json

**Files:**
- Modify: `ocr_worker/convert.py`
- Create: `ocr_worker/tests/test_pages.py`

- [ ] **Step 1: 替换拼接逻辑**

实现纯函数：

```python
def _assemble_pages(pages: list[dict]) -> tuple[str, list[dict]]:
    parts: list[str] = []
    page_map: list[dict] = []
    cursor = 0
    for item in pages:
        text = str(item.get("markdown_texts", "")).strip()
        start = cursor
        if parts:
            start += 2  # "\n\n"
        end = start + len(text)
        page_map.append({
            "page": item["page"],
            "start": start,
            "end": end,
            "width": item.get("width", 0),
            "height": item.get("height", 0),
            "continuation": bool(item.get("page_continuation_flags")),
        })
        parts.append(text)
        cursor = end + (2 if len(parts) > 1 else 0)
    return "\n\n".join(parts), page_map
```

（注意：先 append 再判断分隔符的边界，测试要覆盖。）

- [ ] **Step 2: 页面尺寸**

PDF：`page.rect.width/height`；图片：`PIL.Image.open(source_path).size`。
在 `page_info` 中写入 `page`、`width`、`height`。

- [ ] **Step 3: 输出 pages.json**

`output_dir / "pages.json"` 写入 `{"version": 1, "page_count": ..., "pages": page_map}`；`_build_result_zip` 增加该文件。

- [ ] **Step 4: 测试**

`ocr_worker/tests/test_pages.py` 断言三页拼接的 start/end、空页、连续分隔符。

运行：

```bash
cd ocr_worker && python -m unittest discover -s tests -v
```

---

## Task C：前端逐块渲染与段落标注

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/utils/blocks.ts`
- Modify: `frontend/src/components/workspace/MarkdownAnnotator.vue`
- Modify: `frontend/src/composables/useMarkdownAnnotation.ts`
- Modify: `frontend/src/components/workspace/MixedWorkspace.vue`

- [ ] **Step 1: 类型**

```ts
export interface BlockInfo {
  id: string; index: number; type: string; markdown: string; text: string
  start: number; end: number; page: number; pageEnd: number
  sectionId: string; sectionNumber: string; sectionTitle: string
}
export interface PageInfo { page: number; width: number; height: number; start: number; end: number }
export interface BlocksPayload { version: number; markdown_hash: string; pages: PageInfo[]; sections: unknown[]; blocks: BlockInfo[] }
export interface ParagraphAnnotation { blockId: string; label: string; note: string }
export interface FigureAnnotation {
  id: string; kind: 'figure' | 'table'; label: string; number: string
  caption: string; note: string; page: number; bbox: number[]
  paragraphId: string; assetPath: string
}
```

`AnnotationSpan` 增加 `blockId?: string`；`AnnotationRecord` 增加 `paragraphs?: ParagraphAnnotation[]`、`figures?: FigureAnnotation[]`。

- [ ] **Step 2: 逐块渲染工具**

`frontend/src/utils/blocks.ts`：

```ts
import type { BlockInfo } from '../types'
import { renderMarkdown } from './markdown'

export interface RenderedBlock { block: BlockInfo; html: string }

export function renderBlocks(blocks: BlockInfo[], fileId: string): RenderedBlock[] {
  if (!blocks.length) return []
  return blocks.map((block) => ({
    block,
    html: renderMarkdown(block.markdown, { fileId }),
  }))
}
```

- [ ] **Step 3: MarkdownAnnotator**

- props 增加 `blocks: BlockInfo[]`。
- 用 `v-for="item in renderedBlocks"` 渲染 `<section class="md-block" :data-block-id="item.block.id">`，内部 `v-html="item.html"`；不再使用整篇 `renderedHtml`。
- 每个可打标签的块（heading/paragraph/list/blockquote）左侧加 gutter 按钮；点击弹出标签列表，选中后写入段落标注。
- `getPayload()` 返回 `{ text, spans, relations, paragraphs }`；span 增加 `blockId`：打标签时从选区 startContainer 向上找 `[data-block-id]`。
- `loadAnnotations` 恢复段落标注；`hasAnnotations` 包含 paragraphs；`clearAnnotations` 清空。
- 无 blocks 时回退为单块渲染整篇 Markdown，保证兼容。

- [ ] **Step 4: MixedWorkspace**

- 加载 `GET /api/files/{fid}/blocks`，存入 `blocks`，传给 `MarkdownAnnotator`。
- `normalizeAnnotationRecord` 增加 paragraphs/figures。
- `applyMarkdown` 清空 payload 增加 `paragraphs: []`；确认文案包含“段落标注”。
- 保存成功后无需重载 blocks，但 `PUT /markdown` 后重新加载 blocks。

- [ ] **Step 5: 验证**

```bash
cd frontend && npm run typecheck && npm run build
```

手工：打开已有标注文件，确认旧 span 高亮位置未漂移；段落打标后保存，重新加载可恢复。

---

## Task D：知识库 graph.jsonl 导入

**Files:**
- Modify: `H:\Git\1CF\知识库软件win7\backend\app\services\jsonl_import.py`
- Modify: `H:\Git\1CF\知识库软件win7\backend\app\routers\datasource.py`
- Modify: `H:\Git\1CF\知识库软件win7\frontend\src\App.vue`
- Create: `H:\Git\1CF\知识库软件win7\backend\tests\test_graph_jsonl.py`

- [ ] **Step 1: 检测格式**

读取首行非空 JSON；若含 `"record"` 且值为 `meta/node/edge`，或含 `"format":"labelfast-hybrid/v2"`，走 graph 解析。

- [ ] **Step 2: 解析与建图**

`parse_graph_jsonl(path)` 返回 `(nodes, edges, summary)`：
- node：`id="lf:"+raw_id`，`name`、`label`、`x=0,y=0,parent_id=None`、`attributes=[{"key":k,"value":str(v)} ...]`、`origin="labelfast:"+file_name`。
- edge：`id=str(uuid4())`，source/target 同样加 `lf:` 前缀，`kind="parent-child"` if raw kind=="hierarchy" else `"relation"`，`weight=None`（hierarchy）或 `1.0`，`origin` 同上。
- summary：`records`、`files`、`entities`、`relations`、`labels`、`sample_nodes`、`sample_edges`、`preserve_ids: True`、`format: "labelfast-hybrid/v2"`。

- [ ] **Step 3: 接入 datasource**

`/file/upload` 与 `/jsonl/import` 在 `ext == ".jsonl"` 时先检测 graph 格式；命中则调用 `parse_graph_jsonl`，跳过旧 `parse_jsonl/build_graph`。保持现有大小/条数限制。

- [ ] **Step 4: 前端合并保留 id**

`App.vue` 的 `onImportNodes`：当 `summary.preserve_ids === true` 时，按 `node.id` 去重、保留原 id；否则维持旧的 `label::name` 合并。平移逻辑不变。

- [ ] **Step 5: 测试**

```bash
cd "H:/Git/1CF/知识库软件win7/backend" && python -m pytest tests -q
```

新增测试覆盖：节点 id 前缀、边 kind、attributes 转换、preserve_ids。

---

## Task E：前端 PDF 截图与图表（C 完成后）

**Files:**
- Modify: `frontend/src/components/workspace/PdfPreview.vue`
- Create: `frontend/src/components/workspace/FigureDialog.vue`
- Modify: `frontend/src/components/workspace/MixedWorkspace.vue`
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: PdfPreview 截图模式**

- 增加 props `figures: FigureAnnotation[]`，emit `region-selected`、`figure-selected`。
- 工具栏增加“截图”切换按钮；开启后 canvas 上显示选区层，`pointerdown/move/up` 绘制矩形。
- 鼠标抬起时把 CSS 像素换算为 PDF pt：`pt = cssPx / (viewport.width / baseViewport.width)`；图片按 naturalWidth 比例换算。
- 暴露 `captureRegion(bbox): Promise<Blob>`：当前页离屏渲染到 `scale = 200/72` 的 canvas，按 bbox 裁剪，`canvas.toBlob('image/png')`；图片源用 `drawImage` 裁剪。
- 在页面上叠加已有 figures 的彩色矩形，点击 emit `figure-selected`。

- [ ] **Step 2: FigureDialog**

表单：类型（图/表）、编号（自动建议 `图N`/`表N`）、标题、标签（项目 labels + 空）、归属段落（blocks 中 page<=figure.page 的最近段落，默认最后一项）、备注；显示截图预览；确定/取消。

- [ ] **Step 3: MixedWorkspace 集成**

- 加载 figures（从 annotation record）。
- 处理 `region-selected`：打开 FigureDialog，确认后 `captureRegion(bbox)` → `POST /api/files/{fid}/figures`（FormData: file + meta JSON）→ 更新 figures。
- 处理 `figure-selected`：打开编辑弹窗 → `PATCH`；删除走 `DELETE`。
- 保存标注时 figures 不放入 payload（后端保留）。

- [ ] **Step 4: 验证**

```bash
cd frontend && npm run typecheck && npm run build
```

手工：PDF 第 3 页拖框 → 填图1 → 保存 → 刷新仍在；删除后资产消失；扫描件同样可用。

---

## Task F：后端双文件导出（A 完成后）

**Files:**
- Modify: `backend/services/export_service.py`
- Create: `backend/tests/test_export_graph.py`

- [ ] **Step 1: annotations.jsonl 扩展**

每行增加：

```python
"paragraphs": [enriched paragraphs],
"figures": [figures with zip-relative asset_path],
"pages": [{"page": p["page"], "width": p["width"], "height": p["height"]} for p in pages],
"meta": {"export_version": "labelfast-hybrid/v2", "standard_id": standard_id,
         "block_count": len(blocks["blocks"]), "paragraph_count": ...,
         "figure_count": ...},
```

`standard_id` 从文件名提取：`^([A-Z]{2,}\s*[\d.]+(?:[-—]\d{4})?)`，失败则用文件名去扩展名。

- [ ] **Step 2: 写 graph.jsonl**

纯函数 `build_graph_rows(project, meta, blocks, annotations, asset_map) -> list[dict]`：
- meta 行。
- document 节点 `doc:<file_id>`。
- 每个 section 节点 `sec:<file_id>:<section_id>`。
- 仅已标注段落节点 `par:<file_id>:<block_id>`。
- 每个 figure `fig:<file_id>:<figure_id>`。
- 每个 span `ent:<file_id>:<span_id>`。
- 边：doc→section、section→paragraph、doc→figure、paragraph→figure（附有）、entity→paragraph（出现在）、实体关系。
- 所有 attributes 值转字符串；bbox `"x0,y0,x1,y1"`。

- [ ] **Step 3: 写 assets/blocks/manifest**

- 资产复制到 ZIP：单文件 `assets/figures/<name>`；多文件 `assets/<folder>/<name>`。
- blocks：单文件 `blocks/blocks.json`；多文件 `blocks/<folder>.json`。
- `manifest.json`：`format/version/exported_at/project/files[]`，files 含 source/markdown/blocks/figures 清单。
- README 更新结构说明。

- [ ] **Step 4: 测试**

`backend/tests/test_export_graph.py`：构造 2 个 section、3 个段落（2 个已标注）、1 个 figure、2 个实体，断言节点数与边 id；断言 annotation 行含 paragraphs/figures/meta。

```bash
cd backend && python -m unittest discover -s tests -v
```

---

## Task G：审查与集成验证

- [ ] 后端单元测试：`cd backend && python -m unittest discover -s tests -v`
- [ ] Worker 单元测试：`cd ocr_worker && python -m unittest discover -s tests -v`
- [ ] 前端类型与构建：`cd frontend && npm run typecheck && npm run build`
- [ ] 知识库测试：`cd "H:/Git/1CF/知识库软件win7/backend" && python -m pytest tests -q`
- [ ] 手工 E2E：
  1. 上传国标 PDF，等待 OCR。
  2. 确认段落 gutter 出现，给 3.1/3.2/3.3 打标签。
  3. 段内给“T2铜板”打实体标签，保存。
  4. PDF 第 4 页拖框截图，类型“表”，编号“表1”，归属 3.1，保存。
  5. 导出 ZIP，检查 `annotations.jsonl`、`graph.jsonl`、`assets/`、`blocks/`、`manifest.json`。
  6. 把 `graph.jsonl` 导入知识库，确认出现 文件/章节/段落/图/实体 节点与“包含/附有/出现在”边。
  7. 修改 Markdown，确认提示清空段落/实体标注、图表仍在。
- [ ] 修复审查发现的问题，再次运行上述命令。

---

## 自审

- 规格覆盖：段落（C/A）、图表截图（E）、双文件导出（F）、知识库导入（D）、页码锚定（B/A）、重转保留图表（A）均有任务。
- 类型一致：`blockId`、`paragraphId`、`assetPath`、`preserve_ids` 在前后端任务中命名一致。
- 无占位符：所有任务给出文件路径、接口契约、测试命令与关键代码。
