# 数据标注与分类工具 混合标注 v2 设计

日期：2026-11-04
状态：已确认，进入实现

## 1. 目标

在现有“Markdown 字符偏移实体标注”的基础上，增加：

1. **段落级标注**：OCR 后自动切段，每个段落可整体打标签（复用项目实体标签），段内仍可做实体/关系标注。
2. **图片/表格标注**：在 PDF 预览页拖框截图，保存 PNG + 页码 + bbox + 编号/标题/归属段落。
3. **双文件导出**：保留兼容的 `annotations.jsonl`，新增 `graph.jsonl + assets/ + manifest.json` 供知识库建图。
4. **知识库导入侧**：识别 `graph.jsonl`，把 document / section / paragraph / figure / table / entity 节点及边导入图谱。

非目标：本轮不做知识库侧的图片/表格展示 UI；不做版面 bbox 级段落锚定；不做模型训练或自动实体识别。

## 2. 已确认决策

| 问题 | 决策 |
|---|---|
| 段落产生方式 | 自动切段 + 整段打标签 |
| 截图入口 | PDF 预览页拖框截图 |
| 输出格式 | 双文件：兼容 + 图谱格式 |
| 本轮范围 | 数据标注与分类工具 + 知识库导入侧 |
| 标签体系 | 复用现有实体标签 |
| 图表归属 | 自动就近 + 可手动改 |
| 编辑 Markdown | 沿用现状：提示并失效（保留图表记录） |

## 3. 架构与数据流

```
上传 → OCR Worker（逐页）
        ├─ result.md
        ├─ images/
        └─ pages.json（每页 markdown 区间 + 页面尺寸 pt/px + 延续标记）
      → 后端保存 pages.json，重建 blocks.json
      → 前端逐块渲染 Markdown（每块独立 v-html，data-block-id）
      → 段落打标 / 段内实体标注 / PDF 拖框截图
      → annotations.json（spans + relations + paragraphs + figures）
      → 导出 annotations.jsonl + graph.jsonl + assets/ + manifest.json
      → 知识库导入 graph.jsonl 建图
```

### 3.1 切块（后端权威）

新增 `backend/services/block_service.py`，把 `result.md` 切为顶级块：

- 类型：`heading` / `paragraph` / `list` / `table` / `image` / `code` / `blockquote` / `html`。
- 每个块记录：`id`（`b0001`）、`index`、`type`、`markdown`（原始片段）、`text`（纯文本）、`start/end`（在 result.md 中的字符区间）、`lineStart/lineEnd`、`page/pageEnd`、`sectionId/sectionNumber/sectionTitle`。
- 章节：标题行按 `^(#{1,6})\s+` 识别，条款号按 `^(\d+(?:\.\d+)*|附录[A-Z]|[A-Z]\d*)` 提取；后续块继承最近标题。
- 页码：用 `pages.json` 的每页 `[start,end)` 区间把块起始偏移映射为页码；缺失 pages.json 时页码为 0（前端显示“—”）。
- 块 ID 按顺序生成；Markdown 变化后重新切块，旧段落标注失效。

### 3.2 前端渲染

- 前端不再整篇 `v-html`，而是按 blocks 逐块渲染：每个块一个 `<section data-block-id>`，内部 `v-html`。
- 段落打标入口在块左侧 gutter；仅 `heading/paragraph/list/blockquote` 可打段落标签。
- 实体 span 增加可选 `blockId`：打实体标签时取选区最近的 `[data-block-id]`，用于图谱“实体出现在段落”。
- 逐块渲染后 canonical text 与整篇渲染保持一致（块级换行会折叠），旧 span 偏移继续有效。

### 3.3 重新转换与 Markdown 编辑

- 重新 OCR / 编辑 Markdown：清空 `text/spans/relations/paragraphs`，删除旧 `pages.json` 与 `blocks.json` 后重建；**保留 `figures` 记录与截图资产**，失效的 `paragraphId` 置空。
- `PUT /annotations` 只写文本/段落标注，自动保留已有 figures。
- 图表通过独立接口 CRUD，避免与标注保存互相覆盖。

## 4. 数据模型

```python
class ParagraphAnnotation(BaseModel):
    blockId: str
    label: str
    note: str = ""

class FigureAnnotation(BaseModel):
    id: str
    kind: Literal["figure", "table"]
    label: str = ""
    number: str = ""
    caption: str = ""
    note: str = ""
    page: int
    bbox: list[float]        # [x0,y0,x1,y1]，PDF pt / 图片 px，左上原点
    paragraphId: str = ""
    assetPath: str           # "assets/figures/fig_0001.png"
```

`AnnotationInput` 增加 `paragraphs`；`AnnotationSpan` 增加 `blockId: str = ""`。
`annotations.json` 结构：

```json
{
  "text": "...", "spans": [], "relations": [],
  "paragraphs": [{"blockId":"b0006","label":"尺寸","note":""}],
  "figures": [{"id":"fig_0001","kind":"figure","page":4,"bbox":[72,120,520,380],
               "number":"图1","caption":"...","paragraphId":"b0006",
               "assetPath":"assets/figures/fig_0001.png"}],
  "updated_at": "..."
}
```

资产落盘：`backend/data/projects/<pid>/files/<fid>/assets/figures/<figure_id>.png`。
访问路由：`GET /api/files/{fid}/figure-assets/{name}`。

## 5. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/files/{fid}/blocks` | 返回 blocks.json；缺失或 hash 不匹配时懒重建 |
| POST | `/api/files/{fid}/figures` | multipart：`file`(PNG) + `meta`(JSON) 创建截图记录 |
| PATCH | `/api/files/{fid}/figures/{figure_id}` | 修改编号/标题/标签/归属/备注 |
| DELETE | `/api/files/{fid}/figures/{figure_id}` | 删除记录与资产 |
| PUT | `/api/files/{fid}/annotations` | 写 text/spans/relations/paragraphs，保留 figures |
| GET | `/api/files/{fid}/figure-assets/{name}` | 读取截图 |
| GET | `/api/files/{fid}/markdown` | 保持原契约 |
| PUT | `/api/files/{fid}/markdown` | 保存后重建 blocks、清空文本/段落标注、保留 figures |

`POST /figures` 的 `meta`：

```json
{"kind":"figure","page":4,"bbox":[72,120,520,380],"number":"图1",
 "caption":"OD·JZ型端子结构","label":"结构图","paragraphId":"b0006","note":""}
```

校验：PNG magic；≤20MB；page 在 page_count 内；bbox 非负且落在页面尺寸内；paragraphId 必须存在于 blocks（或空）。

## 6. 导出

```
<项目名>/
├── original/...
├── markdown/.../result.md, images/
├── assets/figures/...                截图资产（多文件时按文件文件夹分目录）
├── blocks/blocks.json 或 blocks/<folder>.json
├── annotations.jsonl                 兼容格式 + paragraphs/figures/pages/meta
├── graph.jsonl                       图谱节点+边
├── manifest.json                     版本、文件清单、资产清单
└── README.txt
```

### 6.1 annotations.jsonl

保留 `file_name/text/spans/relations`；新增：

- `paragraphs`: `{block_id,label,note,text,page,section_number,section_title}`
- `figures`: 记录 + `asset_path`（ZIP 内相对路径）
- `pages`: `[{page,width,height}]`
- `meta`: `{export_version:"labelfast-hybrid/v2", standard_id, block_count, paragraph_count, figure_count}`

旧知识库导入器忽略新字段，继续可用。

### 6.2 graph.jsonl

每行一个对象：

```json
{"record":"meta","format":"labelfast-hybrid/v2","file_name":"...","exported_at":"..."}
{"record":"node","id":"doc:<file_id>","kind":"document","name":"GBT 4423-2020","label":"文件","attributes":{...}}
{"record":"node","id":"sec:<file_id>:s0005","kind":"section","name":"3.1 结构和尺寸","label":"章节","attributes":{"number":"3.1","page":"3"}}
{"record":"node","id":"par:<file_id>:b0006","kind":"paragraph","name":"OD·JZ型端子...","label":"尺寸","attributes":{"block_id":"b0006","page":"3","section":"3.1","text":"..."}}
{"record":"node","id":"fig:<file_id>:fig_0001","kind":"figure","name":"图1 OD·JZ型端子结构","label":"图","attributes":{"asset_path":"assets/...","page":"4","bbox":"72,120,520,380","paragraph_id":"b0006","caption":"..."}}
{"record":"node","id":"ent:<file_id>:1","kind":"entity","name":"T2铜板","label":"材料","attributes":{"block_id":"b0009","page":"4"}}
{"record":"edge","id":"e:...","source":"...","target":"...","relation":"包含","kind":"hierarchy"}
```

- 只输出：document、全部 section、**已打标签的 paragraph**、全部 figure/table、全部 entity。
- 边：doc→section、section→paragraph、doc→figure（以上 `kind="hierarchy"`，即 `包含`）、entity→paragraph（`relation="出现在"`，`kind="relation"`）、实体关系（`kind="relation"`）。图表不输出 paragraph→figure 归属边。
- `attributes` 值统一为字符串；bbox 用逗号分隔。

## 7. 知识库导入

- `jsonl_import.py` 新增 `parse_graph_jsonl`：检测首行 `record` 字段；节点保留显式 id（前缀 `lf:`），attributes 转为 `[{key,value}]`；边 kind 映射 hierarchy→parent-child，其余→relation。
- `datasource.py` 的 upload/import 在检测到 graph 格式时走新解析器，返回 `summary.preserve_ids=true`。
- 前端导入合并：当 `preserve_ids` 为真时按 `node.id` 去重并保留 id，不再按 `label::name` 合并；导入后整体平移布局。
- 资产只保存 `asset_path` 属性，本轮不做展示；后续知识库增加“资产根目录”配置即可解析。

## 8. 错误处理

- Worker 缺失 `pages.json`：正常完成，blocks 页码为 0；前端提示“页码不可用”。
- blocks 生成失败：转换标记完成，`GET /blocks` 懒重建；持续失败返回 500 并提示。
- 截图超限/非 PNG/bbox 越界：400，前端弹窗保留输入。
- 图表资产丢失：列表加载时标记 `missing`，允许删除记录。
- Markdown 编辑后旧段落标注：前端确认清空；服务端同样清空文本/段落标注，保留图表。

## 9. 测试

- 后端（`unittest`）：块切分（标题/段落/列表/表格/图片/代码/章节号/页码映射）、graph 导出节点边数量与 id、figures 存储与 bbox 校验、annotations 保存保留 figures。
- Worker：`_assemble_pages` 的页码偏移与页面尺寸。
- 知识库（pytest）：graph.jsonl 解析、id 前缀、边 kind 映射、preserve_ids。
- 前端：`npm run typecheck`、`npm run build`；手工回归：加载旧标注文件，确认 span 偏移未漂移；段落打标、截图创建/编辑/删除、导出 ZIP 结构。
