# 混合标注模块集成设计

- 日期：2026-11-05
- 状态：已确认
- 来源项目：`H:\Git\1CF_win11\Label-fast-main_混合标注`
- 目标项目：`H:\Git\1CF_win11\Label-fast-main`

## 1. 目标

把混合标注（PDF/图片 → Markdown → 实体/关系标注）集成到 数据标注与分类工具 左侧导航栏，
作为一个需要登录的页面，视觉与 数据标注与分类工具 的 Ink & Signal 设计系统统一；
后端、OCR Worker、MinerU 模型保持独立目录与独立进程。

## 2. 服务拓扑

```text
Vite 前端 :5175
 ├─ /api/*     → 数据标注与分类工具 后端 :3002（JWT）
 ├─ /gb-api/*  → 国标后端 :8000
 └─ /mix-api/* → 混合后端 :3200（去前缀）
                     │
                     ▼
              OCR Worker :8870（仅 127.0.0.1）
                     │
                     ▼
              MinerU API :18000（仅 127.0.0.1）
```

- 混合后端、OCR Worker、MinerU API 仅监听 `127.0.0.1`。
- Vite 仍监听 `0.0.0.0`。
- 混合 API 不接入 JWT；页面由前端路由守卫保护，网络层靠本机监听隔离。

## 3. 目录布局

```text
Label-fast-main/
├── mixed_annotation/
│   ├── backend/           # 原样迁移，含 data/（3 个演示项目）
│   ├── ocr_worker/        # 原样迁移，排除 data/ 临时任务
│   ├── models/            # 全部 2.16GB 模型
│   ├── docs/
│   ├── samples/           # 零件工艺标注 jsonl、GBT 4423-2020.pdf
│   ├── README.md
│   ├── environment-cfwin11.yml
│   └── requirements-lock-cfwin11.txt
├── frontend/src/modules/mixed-annotation/
│   ├── views/MixedAnnotationView.vue
│   ├── components/AppHeader.vue
│   ├── components/project/*.vue
│   ├── components/workspace/*.vue
│   ├── components/common/EmptyState.vue
│   ├── api/client.ts
│   ├── types.ts
│   ├── utils/{blocks,markdown}.ts
│   ├── composables/useMarkdownAnnotation.ts
│   └── styles/{app,markdown}.css
└── start.bat              # 六服务启动
```

不迁移：`.git`、`.ruff_cache`、`__pycache__`、`node_modules`、`dist`、
`paddlepaddle-3.3.1-cp39...whl`、压缩包；`ocr_worker/data` 为临时产物。

`.gitignore` 追加：
- `mixed_annotation/models/`
- `mixed_annotation/backend/data/`
- `mixed_annotation/ocr_worker/data/`
- `mixed_annotation/.ruff_cache/`

## 4. 前端设计

### 4.1 路由与导航

- `/app` 子路由新增：
  - `path: 'mixed'`
  - `name: 'mixed-annotation'`
  - `meta.title: '混合标注'`
- 左侧导航第 5 项：标签「混合」，图标为文档 + Markdown 线条。
- AppHeader 眉题：`Mixed Annotation`。
- 路由继承 `/app` 的 `requiresAuth`。

### 4.2 页面结构

- 页面根节点 `.mx-root`，高度 100%，填满 `app-main`，禁止 `100vh`。
- 顶部为页内工具栏（由原 `AppHeader.vue` 改造）：
  - 去掉 `数据标注与分类工具.` 品牌块与品牌副标题；
  - 保留项目下拉、当前文件状态、导出 ZIP、后端在线状态；
  - 类名改为 `mx-header*`。
- 主体 `.mx-body` 横向：左侧项目面板 330px，右侧工作区。
- `.mx-main` 内部滚动；Markdown/PDF 工作区保持原有分栏、同步滚动、图表弹窗。
- 保留原混合页的 `ProjectPanel`、`UploadPanel`、`FileList`、`ConversionProgress`、
  `MixedWorkspace`、`MarkdownAnnotator`、`MarkdownEditor`、`PdfPreview`、`FigureDialog`、
  `EmptyState` 组件。

### 4.3 样式统一与隔离

- 混合前端已使用同一套 Ink & Signal 令牌与字体；删除其 `:root`、`html/body` 规则，
  改为继承 数据标注与分类工具 全局令牌。
- 所有选择器限定在 `.mx-root` 下，`@media` 内部同样限定，
  `@keyframes` 名称加 `mx-` 前缀并同步 `animation` 引用。
- 已确认的冲突类重命名：
  - `app-body → mx-body`
  - `app-main → mx-main`
  - `app-header → mx-header`
  - `header-brand → mx-header-brand`
  - `btn → mx-btn`
  - `btn-primary → mx-btn-primary`
  - `btn-danger → mx-btn-danger`
  - `btn-icon → mx-btn-icon`
  - `btn-sm → mx-btn-sm`
  - `input → mx-input`
  - `empty-state → mx-empty-state`
  - `empty-state-icon → mx-empty-state-icon`
  - `status-dot → mx-status-dot`
  - `label-chip → mx-label-chip`
- `markdown.css` 中 `.markdown-content` 等规则限定在 `.mx-root` 下。

### 4.4 接口访问

- `api/client.ts` 的 `apiUrl()` 基地址改为 `/mix-api`。
- `utils/markdown.ts` 的图片/资源地址解析同步使用 `/mix-api`。
- Vite 代理：

```ts
'/mix-api': {
  target: `http://127.0.0.1:${process.env.MIX_BACKEND_PORT || '3200'}`,
  changeOrigin: true,
  rewrite: (path) => path.replace(/^\/mix-api/, ''),
}
```

### 4.5 依赖

- 新增 `pdfjs-dist@^4.10.38`、`markdown-it@^14.1.0`、`dompurify@^3.2.4`。
- 新增开发依赖 `@types/markdown-it@^14.1.2`。
- PDF.js worker 继续通过 `pdfjs-dist/build/pdf.worker.min.mjs?url` 由 Vite 打包。

## 5. 后端、数据与模型

- 混合后端与 OCR Worker 代码零改动。
- 迁移 `backend/data`（projects.json + 3 个演示项目，约 22.4MB）。
- 全部复制 `models`（约 2.16GB）。
- `ocr_worker/data` 不迁移，运行时自动创建。
- CFwin11 已具备 MinerU 3.1.6、torch、Paddle 依赖，不重装。
- 数据路径由 `config.py` 基于 `__file__` 计算，迁移目录后无需改代码。

## 6. 启动脚本

根目录 `start.bat` 扩展为六窗口：

| 窗口 | 默认端口 | 监听 |
| --- | --- | --- |
| 数据标注与分类工具 后端 | 3002 | 127.0.0.1 |
| GB 后端 | 8000 | 127.0.0.1 |
| 混合后端 | 3200 | 127.0.0.1 |
| OCR Worker | 8870 | 127.0.0.1 |
| MinerU API | 18000 | 127.0.0.1 |
| 前端 | 5175 | 0.0.0.0 |

要求：

1. 六个端口均用 TcpListener 探测并顺延。
2. 设置模型环境变量：
   - `MODELSCOPE_CACHE=%~dp0mixed_annotation\models\modelscope`
   - `HF_HOME=%~dp0mixed_annotation\models\huggingface`
   - `HF_HUB_CACHE=%~dp0mixed_annotation\models\huggingface\hub`
   - `TORCH_HOME=%~dp0mixed_annotation\models\torch`
   - `OCR_WORKER_DATA_DIR=%~dp0mixed_annotation\ocr_worker\data`
   - `MINERU_API_OUTPUT_ROOT=%~dp0mixed_annotation\ocr_worker\data\mineru_api_output`
   - `MINERU_MODEL_SOURCE=modelscope`、`HF_HUB_DISABLE_SYMLINKS=1`
   - `MINERU_RUNNER=%~dp0mixed_annotation\ocr_worker\mineru_runner.py`
3. 先启动 MinerU API，最多等待 20 秒；未就绪则 `MINERU_MODE=subprocess`、
   `OCR_WORKER_CONCURRENCY=1`。
4. 设置 `OCR_WORKER_URL`、`MINERU_API_URL`、`OCR_ENGINE=mineru`、
   `MINERU_MODE=auto`、`OCR_WORKER_CONCURRENCY=3`、
   `MINERU_API_TASK_RETENTION_SECONDS=3600`。
5. 通过 `start /D "..."` 指定工作目录，支持含空格路径。
6. 将 `MIX_BACKEND_PORT` 传给前端。
7. 打印六个实际地址与手动启动步骤。

## 7. 鉴权与数据流

- 页面需要登录；未登录跳转 `/login`。
- 混合后端与 Worker 仅本机监听，避免局域网绕过登录直接调用 API。
- 混合项目数据独立于 数据标注与分类工具 SQLite 与国标数据。
- 多用户共用同一份混合项目数据，定位为本地单用户工具。

## 8. 验证

1. `npm install` 后 `npm run build` 通过。
2. 混合后端 `pytest` 全部通过。
3. 健康检查：
   - `http://127.0.0.1:<混合后端>/api/health`
   - `http://127.0.0.1:<Worker>/health`
   - `http://127.0.0.1:<MinerU>/health`
   - 通过 Vite：`/mix-api/api/health`
4. 无头 Chrome 截图：
   - `/app/mixed` 页面正常渲染；
   - 文本标注页样式不受混合 CSS 影响；
   - 未登录访问 `/app/mixed` 跳转登录。
5. 打开已有演示项目，加载 Markdown/PDF 工作区，确认 PDF.js、标注与图块弹窗可用。
6. 用样例 PDF 走一次上传 → 转换 → 标注 → 导出链路。

## 9. 已知边界

- Docker/生产环境仍只包含 数据标注与分类工具 主后端；混合后端、Worker、MinerU 需要额外进程，
  并为 `/mix-api` 配置反向代理。写入 README。
- 2.16GB 模型与 22MB 项目数据不进入 git，但会迁移到本地目录。
- Worker 任务状态在内存中，重启后未完成任务丢失。
- MinerU `/health` 不代表模型已加载，首次转换约 40 秒。
- PaddleOCR 回退已禁用，仅使用 MinerU。
