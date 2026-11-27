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
| PATCH | `/api/projects/{pid}` | 增量更新名称/实体标签/关系类型（只增不减，见下） |
| GET | `/api/projects/{pid}/labels/usage` | 实体/段落标签引用计数 + 字典缺失标签 |
| POST | `/api/projects/{pid}/labels/restore` | 把被引用但字典缺失的标签补回字典 |
| POST | `/api/projects/{pid}/split` | 按文件序号区间拆成多个新项目（文件移动，源项目保留） |
| DELETE | `/api/projects/{pid}` | 删除项目及其数据 |
| GET | `/api/projects/{pid}/export-zip` | 导出 ZIP：原始文件 + Markdown + 图表资产 + `annotations.jsonl` + `graph.jsonl` |

#### 项目字典：增量合并（多人协同）

背景：多人同时标注时，前端曾把整份 `labels` 数组覆盖写回，后保存者会抹掉别人
新增的标签。现在 `PATCH /api/projects/{pid}` 对字典只做**增量合并**。

请求体字段（全部可选）：

```json
{
  "name": "可选：新项目名",
  "labels": ["旧客户端兼容字段：只作为追加项"],
  "relation_types": ["旧客户端兼容字段：只作为追加项"],
  "labels_add": ["新增实体标签"],
  "labels_remove": ["要删除的实体标签"],
  "relation_types_add": ["新增关系类型"],
  "relation_types_remove": ["要删除的关系类型"],
  "shortcuts_set": { "适用范围": "q", "机械性能": "Ctrl+K" },
  "shortcuts_unset": ["实验步骤"],
  "force": false
}
```

语义（服务端在同一把锁内完成，`project.json` 与 `projects.json` 各只写一次）：

1. `labels` / `relation_types` **只作为追加项**，与现有字典求并集；即使旧前端
   提交整份数组也不会删除任何已有条目。
2. 真正删除只能通过 `labels_remove` / `relation_types_remove`；同一标签同时出现
   在增删两侧时按「新增」处理（新增是非破坏性操作）。
3. 删除仍被标注引用的**实体标签**时：`force=false` 返回 **409**，`detail` 带上
   每个标签的引用条数；`force=true` 才允许删除。删除不修改任何标注数据。
4. 合并顺序：保留现有顺序，新增项按传入顺序追加到末尾；去空白、去重、单条 ≤200 字
   （超限返回 422）。
5. `shortcuts_set` / `shortcuts_unset` 在同一把锁内先合并字典（含 `labels_add`）
   再应用：标签必须存在于合并后的字典，否则 **400**；覆盖项规范化后存储；
   有效快捷键（默认 1–9 + 覆盖项）冲突返回 **409**；`labels_remove` 会同步清理
   被删标签的覆盖项。详见「项目级自定义快捷键」。
6. 成功返回合并后的完整项目对象（含 `name` / `shortcuts` 更新）。

409 示例（`detail` 为单行中文，含引用条数）：

```
标签「适用范围」6 处、「机械性能」3 处 仍被标注引用，删除后这些标注将失去标签。请先调整标注，或确认后强制删除。
```

`GET /api/projects/{pid}/labels/usage`（只读，不写盘）：

```json
{
  "used": { "工艺参数": 9, "适用范围": 6, "机械性能": 3 },
  "missing": ["工艺参数", "适用范围", "机械性能"]
}
```

- `used`：项目内 `spans[].label` + `paragraphs[].label` 的引用计数，按引用数降序、
  其次标签名排序；缺失/损坏的 `annotations.json` 跳过。
- `missing`：`used` 中不在项目字典里的标签，排序规则同上。

`POST /api/projects/{pid}/labels/restore`（只增不减，幂等）：

```json
{
  "id": "uuid",
  "name": "国标3",
  "labels": ["已有标签", "工艺参数", "适用范围", "机械性能"],
  "relation_types": ["包含"],
  "created_at": "2026-11-10T07:47:00Z",
  "updated_at": "2026-11-24T09:12:00Z",
  "restored": ["工艺参数", "适用范围", "机械性能"]
}
```

- 已有标签顺序不变，缺失标签按「引用数降序、其次标签名」追加到末尾；
- 没有缺失标签时不写盘，返回 `restored: []`；
- 响应在项目字段之外额外带 `restored`（本次补回的标签）。

#### 项目拆分（按文件序号区间）

`POST /api/projects/{pid}/split`

```json
{
  "groups": [
    { "name": "国标3-A", "start": 1, "end": 30 },
    { "name": "国标3-B", "start": 31, "end": 50 }
  ]
}
```

响应（`project` 为完整项目对象，含 `labels` / `relation_types` / `shortcuts`）：

```json
{
  "projects": [
    {
      "project": { "id": "uuid", "name": "国标3-A", "labels": ["适用范围"], "relation_types": ["包含"], "shortcuts": { "适用范围": "q" }, "created_at": "...", "updated_at": "..." },
      "file_count": 30,
      "file_ids": ["uuid", "..."]
    }
  ],
  "source_project": { "id": "uuid", "name": "国标3", "labels": ["适用范围"], "relation_types": ["包含"], "shortcuts": { "适用范围": "q" }, "created_at": "...", "updated_at": "..." }
}
```

语义：

- **文件序号**以 `GET /api/projects/{pid}` 返回的 `files` 顺序为准（1 基、闭区间），
  即 `created_at` 倒序、同一秒内 `queue_seq` 兜底；`status == "uploading"` 的记录
  被排除（与详情接口一致），`uploaded` / `completed` / `failed` 均可移动；
- 每组创建一个**新项目**，全量继承源项目的 `labels` / `relation_types` / `shortcuts`；
- 文件以**移动**方式进入新项目：整个文件目录（source、markdown、assets、figures、
  blocks、pages、`annotations.json`、`meta.json`）一起迁移，文件 `id` **不变**，
  `meta.json` 的 `project_id` / `dir_name` / `updated_at` 同步更新，目标项目内
  目录名冲突按既有 ` (2)` / ` (3)` 规则去重；
- 源项目**保留**（不删除），只移走被分配的文件；源项目的字典与快捷键不被修改。
  区间留空即「留在源项目」，全部拆走时源项目文件为空；
- 全流程持有进程锁，**要么全成功要么全回滚**：任一步失败会把已移动文件移回源项目、
  删除已创建的项目，再返回中文 `detail`；
- 回滚边界：如果连「移回源项目」都失败（例如目录被其它进程占用），服务端**保留**
  已创建的项目而不是删除目录，避免把用户文件一起删掉，此时 `detail` 会提示
  「部分文件未能回滚……请手动检查后整理」，需要人工整理。

错误码：

| 状态码 | 场景 | `detail` 示例 |
|---|---|---|
| 400 | `groups` 为空 / 超过 50 组 | `拆分分组不能为空，请至少添加一组文件区间` |
| 400 | 名称为空、超过 120 字、本次内重名 | `第 2 组的新项目名称「国标3-A」与本次提交的其他组重复` |
| 400 | 序号越界或 `start > end` | `第 1 组（「国标3-A」）的文件序号必须在 1–50 之间，且起始序号不大于结束序号` |
| 400 | 区间重叠（含端点相同） | `拆分区间重叠：「国标3-A」1–30 与 「国标3-B」30–50 存在交叉，请调整后重试` |
| 404 | 项目不存在 / id 非 UUID | `项目不存在` |
| 409 | 被选中文件正在转换 | `文件「GB 17945-2010.pdf」正在转换，移动会中断识别。请等待转换结束或取消转换后再拆分。` |
| 500 | 移动/写盘失败（已回滚） | `移动文件「xxx.pdf」失败，请关闭占用该目录的程序后重试` / `拆分项目失败，已回滚全部改动，请稍后重试` |

#### 项目级自定义快捷键

`project.json`（以及所有返回项目的接口）包含 `shortcuts: {标签名: 组合键}`，
**只保存用户显式设置过的覆盖项**；旧项目没有该字段时按 `{}` 返回。

有效快捷键 = 默认规则「前 9 个标签 → 数字 1–9」+ 覆盖项（覆盖项优先）。
快捷键是**项目级**的，项目之间完全独立。

按键格式（服务端规范化后存储）：

- 单键：`1`、`q`（单键字母统一小写）、`!`、`F2`；
- 组合键：`Ctrl+K`、`Alt+Shift+P`（修饰键固定顺序 `Ctrl+Alt+Shift`，
  组合键内字母按键显示为大写）；
- `Ctrl` / `Control`、`Alt` / `Option`、`Shift` 大小写不敏感，修饰键顺序会被重排；
- 别名同样接受：`esc` → `Escape`、`del` → `Delete`、`up` → `ArrowUp`、`pgdn` → `PageDown`；
- 保留键不可设置（400）：`Escape`、`Delete`、`Backspace`、`Enter`、`Tab`、`Space`、
  四个方向键、`Home`、`End`、`PageUp`、`PageDown`、`Ctrl+Z`、`Ctrl+S`、`Ctrl+1`…`Ctrl+9`。

写入走 `PATCH /api/projects/{pid}`（增量，见上文）：

```json
{ "shortcuts_set": { "适用范围": "q", "机械性能": "Ctrl+K" }, "shortcuts_unset": ["实验步骤"] }
```

- 标签必须在**合并 `labels_add` 之后**的字典内，否则 **400**
  （`标签「不存在」不存在，无法设置快捷键`）；
- 规范化示例：`CTRL+k` → `Ctrl+K`、`shift+alt+p` → `Alt+Shift+P`、`P` → `p`、`f2` → `F2`；
- 有效快捷键冲突 → **409**，`detail` 列出冲突组合键与全部冲突标签，例如
  `快捷键「1」被标签「适用范围」、「机械性能」同时占用。请为其中一个标签更换快捷键后重试。`；
- `shortcuts_unset` 删除覆盖项后回落到默认 1–9，若不是前 9 个标签则「无快捷键」；
- `labels_remove` 删除标签时同步删除该标签的覆盖项；
- 新建项目默认 `shortcuts: {}`；拆分项目时新项目整份继承源项目的 `shortcuts`。

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
