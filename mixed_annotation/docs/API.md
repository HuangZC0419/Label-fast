# 混合标注 API 契约（v2）

## 主应用后端（端口 3200）

所有接口以 `/api` 为前缀。

### 项目

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/projects` | 项目列表 |
| POST | `/api/projects` | 创建项目：`{name, labels, relation_types}` |
| GET | `/api/projects/{pid}` | 项目详情 + 文件列表 |
| PATCH | `/api/projects/{pid}` | 更新名称/标签/关系类型 |
| DELETE | `/api/projects/{pid}` | 删除项目及其数据 |
| GET | `/api/projects/{pid}/export-zip` | 导出 ZIP：原始文件 + Markdown + 图表资产 + `annotations.jsonl` + `graph.jsonl` |

### 文件与转换

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/projects/{pid}/files` | multipart：`file`、`enable_table`、`enable_formula`、`dpi`、`defer_conversion`；默认保存后自动开始 OCR，`defer_conversion=true` 时只入库进入串行队列 |
| GET | `/api/files/{fid}` | 文件详情 + 转换状态 |
| GET | `/api/files/{fid}/status` | `{status, progress, stage, message, error}` |
| POST | `/api/files/{fid}/convert` | 重新转换，body 可带 `{enable_table, enable_formula, dpi}`；保留图表记录与截图 |
| GET | `/api/files/{fid}/markdown` | `{markdown, page_count}` |
| PUT | `/api/files/{fid}/markdown` | `{markdown}`；保存后重建 blocks，清空实体/关系/段落标注，保留图表 |
| GET | `/api/files/{fid}/blocks` | 段落块结构 `{version, markdown_hash, pages, sections, blocks}` |
| GET | `/api/files/{fid}/source` | 原始 PDF/图片文件 |
| GET | `/api/files/{fid}/assets/{path}` | Markdown 中引用的图片资源 |
| GET | `/api/files/{fid}/figure-assets/{name}` | 图表截图资产 |
| DELETE | `/api/files/{fid}` | 删除文件及标注 |

### 批量导入与夜间串行队列

- 上传接口新增 `defer_conversion` 表单字段：
  - `false`（默认）：保存后立即提交 OCR Worker，保持原行为；
  - `true`：只保存并进入队列，返回 `status="uploaded"`、`stage="排队中"`，由后端队列串行识别。
- 文件状态流转：
  - `defer_conversion=false`：`uploading`（仅内部，上传中）→ `converting` → `completed` / `failed`；
  - `defer_conversion=true`：`uploading` → `uploaded`（排队中）→ `converting` → `completed` / `failed`。
  - `uploading` 记录不会出现在 `GET /api/projects/{pid}` 的文件列表中；服务重启时
    会清理残留的 `uploading` 记录（源文件尚未完成写入，不自动转换）。
- 队列按内部字段 `queue_seq`（导入时生成，不对外暴露）升序处理，跨项目全局串行；
  默认并发 1，可通过 `MIX_CONVERSION_CONCURRENCY` 调整。
- 队列状态持久化在各文件 `meta.json`；服务重启时残留的 `converting` 会退回
  `uploaded` 并自动续跑，不会丢失整批任务。
- OCR Worker 不可用时队列暂停等待（`MIX_QUEUE_WORKER_RETRY_SECONDS`，默认 30 秒），
  文件保持排队；连接/5xx 类失败最多自动重试 `MIX_QUEUE_MAX_RETRIES`（默认 3）次；
  4xx 业务错误（`OCR 任务不存在` / `OCR 结果不存在` 除外，这两种可重试）直接标记
  失败并继续下一个文件，避免坏文件占住队首。
- 队列内单个文件的识别超时由 `MIX_QUEUE_TASK_TIMEOUT_SECONDS` 控制（默认 3600 秒），
  超时后标记失败并继续下一个，避免一个卡死任务阻塞整夜；普通立即转换仍使用 6 小时超时。
- 前端一次选择整个文件夹，按相对路径自然排序后逐个上传；项目内同名文件由前端
  自动跳过。上传完成后可关闭页面，OCR 阶段完全由后端执行。
- 同一 `backend/data` 目录只应运行一个混合标注后端进程；多进程部署会破坏
  队列认领与启动恢复的串行假设。`MIX_CONVERSION_CONCURRENCY` 大于 1 时不再
  保证严格串行。

### 标注

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/files/{fid}/annotations` | 读取标注 `{text, spans, relations, paragraphs, figures}` |
| PUT | `/api/files/{fid}/annotations` | 保存实体/关系/段落标注；自动保留已有 figures |

标注结构：

```json
{
  "text": "渲染后的纯文本（canonical text）",
  "spans": [
    { "id": 1, "start": 0, "end": 4, "label": "工艺", "text": "该零件", "blockId": "b0003" }
  ],
  "relations": [
    { "fromId": 1, "toId": 2, "type": "使用_材料" }
  ],
  "paragraphs": [
    { "blockId": "b0003", "label": "要求", "note": "" }
  ],
  "figures": [
    {
      "id": "fig_0001",
      "kind": "figure",
      "caption": "OD·JZ型端子结构",
      "note": "",
      "page": 4,
      "bbox": [72.0, 120.0, 520.0, 380.0],
      "assetPath": "assets/figures/fig_0001.png"
    }
  ]
}
```

说明：
- `spans[].blockId` 可选，表示实体所在段落。
- `paragraphs[].blockId` 必须存在于 `blocks.json`。
- 图表通过独立接口维护；`PUT /annotations` 不会覆盖 figures。
- 图表记录只包含 `id/kind/caption/note/page/bbox/assetPath`（另含内部
  `created_at/updated_at`）；历史数据中的 `number/label/paragraphId` 在读取、
  更新与导出时一律忽略并剔除，不会报错。

### 图表（截图）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/files/{fid}/figures` | multipart：`file`(PNG) + `meta`(JSON)；创建截图记录 |
| PATCH | `/api/files/{fid}/figures/{figure_id}` | 仅修改 `caption/note` |
| DELETE | `/api/files/{fid}/figures/{figure_id}` | 删除记录与截图资产 |

`meta` 示例：

```json
{
  "kind": "figure",
  "page": 4,
  "bbox": [72.0, 120.0, 520.0, 380.0],
  "caption": "OD·JZ型端子结构",
  "note": ""
}
```

约束：PNG magic；≤20MB；`page` 在文档范围内；`bbox` 落在页面尺寸内（有 `pages.json` 时）。图表不归属段落，也不再有编号/标签字段。

### 导出结构

每个文件一行 `annotations.jsonl`：

```json
{
  "project_id": "uuid",
  "project_name": "项目名",
  "file_id": "uuid",
  "file_name": "GBT 4423-2020.pdf",
  "source_file": "GBT 4423-2020.pdf",
  "markdown_file": "GBT 4423-2020.md",
  "source_path": "original/GBT 4423-2020.pdf",
  "markdown_path": "markdown/GBT 4423-2020.md",
  "text": "canonical text",
  "spans": [{ "id": 1, "start": 0, "end": 4, "label": "工艺", "text": "该零件" }],
  "relations": [{ "fromId": 1, "toId": 2, "type": "使用_材料" }],
  "paragraphs": [
    { "block_id": "b0003", "label": "要求", "note": "", "text": "3.1 结构和尺寸", "page": 3, "section_number": "3.1", "section_title": "结构和尺寸" }
  ],
  "figures": [
    { "id": "fig_0001", "kind": "figure", "caption": "...", "note": "", "page": 4, "bbox": [72, 120, 520, 380], "asset_path": "assets/GBT 4423-2020/fig_0001.png" }
  ],
  "pages": [{ "page": 1, "width": 595.3, "height": 841.9 }],
  "meta": {
    "export_version": "labelfast-hybrid/v2",
    "standard_id": "GBT 4423-2020",
    "block_count": 42,
    "paragraph_count": 3,
    "figure_count": 1
  },
  "updated_at": "2026-11-04T12:00:00Z"
}
```

`graph.jsonl` 每行一个对象，首行为 meta：

```json
{"record":"meta","format":"labelfast-hybrid/v2","file_id":"uuid","file_name":"GBT 4423-2020.pdf","standard_id":"GBT 4423-2020"}
{"record":"node","id":"doc:<file_id>","kind":"document","name":"GBT 4423-2020","label":"文件","attributes":{...}}
{"record":"node","id":"sec:<file_id>:s0005","kind":"section","name":"3.1 结构和尺寸","label":"章节","attributes":{"number":"3.1","page":"3"}}
{"record":"node","id":"par:<file_id>:b0006","kind":"paragraph","name":"OD·JZ型端子...","label":"尺寸","attributes":{"block_id":"b0006","page":"3","section":"3.1","text":"..."}}
{"record":"node","id":"fig:<file_id>:fig_0001","kind":"figure","name":"OD·JZ型端子结构","label":"图","attributes":{"asset_path":"assets/GBT 4423-2020/fig_0001.png","page":"4","bbox":"72,120,520,380","caption":"OD·JZ型端子结构"}}
{"record":"node","id":"ent:<file_id>:1","kind":"entity","name":"T2铜板","label":"材料","attributes":{"block_id":"b0009","page":"4"}}
{"record":"edge","id":"e:doc>section","source":"doc:<file_id>","target":"sec:<file_id>:s0005","relation":"包含","kind":"hierarchy"}
{"record":"edge","id":"e:ent>par","source":"ent:<file_id>:1","target":"par:<file_id>:b0006","relation":"出现在","kind":"relation"}
```

边类型与 `kind`：

- `包含`（文档/章节/段落/图表层级）：`kind="hierarchy"`。
- `出现在`（实体→段落）：`kind="relation"`，表示实体与段落的关联，不是父子层级。
- 用户定义的实体关系：`kind="relation"`。

图表不再有“段落→图表”的归属边。

图表节点规则：`label` 固定为 `图`/`表`；`name` 取 `caption`，为空时退化为 `图`/`表`；`attributes` 只保留 `asset_path/page/bbox/caption`。

ZIP 结构（`<safe_stem>` 为上传文件名去扩展名，不再追加内部 id；同名文件依次使用 `_2`、`_3`）：

```
<project_name>/
├── original/<safe_stem>.<ext>                        原始 PDF/图片
├── markdown/<safe_stem>.md                           单文件：Markdown
│   markdown/images/...                               单文件：Markdown 图片
├── markdown/<safe_stem>/<safe_stem>.md               多文件：Markdown
│   markdown/<safe_stem>/images/...                   多文件：Markdown 图片
├── assets/<safe_stem>/<figure_filename>              图表截图（fig_0001.png / tbl_0001.png）
├── blocks/<safe_stem>.json                           后端切块结果
├── annotations.jsonl                                 兼容格式 + paragraphs/figures/pages/meta
├── graph.jsonl                                       图谱节点与边
├── manifest.json                                     版本、文件清单、资产清单
└── README.txt
```

## OCR Worker（内部端口 8870）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/convert` | multipart：`file`、`enable_table`、`enable_formula`、`dpi`；返回 `{task_id}` |
| GET | `/tasks/{task_id}` | `{status, progress, stage, message, error, page_count}` |
| GET | `/tasks/{task_id}/result.zip` | 完成后的 `result.md` + `images/` + `pages.json` ZIP |

`pages.json` 记录每页 Markdown 的字符区间、页面尺寸（PDF 为 pt、图片为 px）与跨页延续标记，供主应用切块与页码映射。

Worker 默认支持 3 个 MinerU 常驻 API 并发任务（`OCR_WORKER_CONCURRENCY` 可调）；主应用上传后轮询 Worker 状态，完成后下载结果 ZIP 并解压到项目目录。
