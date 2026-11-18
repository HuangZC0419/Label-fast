# 混合标注模块集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把混合标注（PDF/图片 → Markdown → 实体/关系标注）作为独立后端 + 前端模块集成到 数据标注与分类工具 左侧导航，视觉统一且不污染现有页面。

**Architecture:** 混合后端、OCR Worker、MinerU API 作为独立进程运行；前端源码迁入 `frontend/src/modules/mixed-annotation`，新增 `/app/mixed` 路由，接口经 Vite `/mix-api` 前缀代理；混合 CSS 作用域到 `.mx-root` 并重命名冲突类。

**Tech Stack:** Vue 3 + TypeScript + Vite 6 + FastAPI + MinerU 3.1.6 + pdfjs-dist + markdown-it。

**提交策略:** 用户未要求提交，本计划不包含 `git commit`。

---

## 并行执行地图

| 执行者 | 任务 | 依赖 |
| --- | --- | --- |
| Agent A | Task 1 后端/OCR/模型/数据迁移 | 无 |
| Agent B | Task 2 前端模块迁移与组件适配 | 无 |
| Agent C | Task 3 CSS 作用域与类名重命名 | 与 B 共用映射，文件不重叠 |
| Agent D | Task 4 路由/导航/代理/启动/文档/依赖 | 无 |
| 主 Agent | Task 5 安装依赖、构建、测试、截图 | A/B/C/D 完成 |

---

## Task 1: 迁移混合后端、OCR Worker、模型与数据

**Files:**
- Create: `mixed_annotation/backend/**`
- Create: `mixed_annotation/ocr_worker/**`
- Create: `mixed_annotation/models/**`
- Create: `mixed_annotation/docs/**`
- Create: `mixed_annotation/samples/**`
- Create: `mixed_annotation/README.md`

- [ ] **Step 1: 创建目录**

```powershell
$dst='H:\Git\1CF_win11\Label-fast-main\mixed_annotation'
New-Item -ItemType Directory -Force "$dst\backend","$dst\ocr_worker","$dst\models","$dst\docs","$dst\samples" | Out-Null
```

- [ ] **Step 2: 复制 backend（含 data，排除缓存）**

```powershell
$src='H:\Git\1CF_win11\Label-fast-main_混合标注\backend'
$dst='H:\Git\1CF_win11\Label-fast-main\mixed_annotation\backend'
Get-ChildItem $src -Recurse -File | Where-Object {
  $_.FullName -notmatch '__pycache__|\.pytest_cache|\.ruff_cache|\.pyc$'
} | ForEach-Object {
  $rel=$_.FullName.Substring($src.Length).TrimStart('\')
  $target=Join-Path $dst $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
```

- [ ] **Step 3: 复制 ocr_worker（排除 data 与缓存）**

```powershell
$src='H:\Git\1CF_win11\Label-fast-main_混合标注\ocr_worker'
$dst='H:\Git\1CF_win11\Label-fast-main\mixed_annotation\ocr_worker'
Get-ChildItem $src -Recurse -File | Where-Object {
  $_.FullName -notmatch '__pycache__|\.pytest_cache|\.ruff_cache|\\data\\|\.pyc$'
} | ForEach-Object {
  $rel=$_.FullName.Substring($src.Length).TrimStart('\')
  $target=Join-Path $dst $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
```

- [ ] **Step 4: 复制全部模型（约 2.16GB）**

```powershell
robocopy 'H:\Git\1CF_win11\Label-fast-main_混合标注\models' 'H:\Git\1CF_win11\Label-fast-main\mixed_annotation\models' /E /MT:16 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed: $LASTEXITCODE" }
```

- [ ] **Step 5: 复制 docs、样例与环境文件**

```powershell
$src='H:\Git\1CF_win11\Label-fast-main_混合标注'
$dst='H:\Git\1CF_win11\Label-fast-main\mixed_annotation'
Get-ChildItem "$src\docs" -Recurse -File | ForEach-Object {
  $rel=$_.FullName.Substring("$src\docs".Length).TrimStart('\')
  $target=Join-Path "$dst\docs" $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
Copy-Item "$src\GBT+4423-2020.pdf" "$dst\samples\" -Force
Copy-Item "$src\environment-cfwin11.yml" "$dst\" -Force
Copy-Item "$src\requirements-lock-cfwin11.txt" "$dst\" -Force
Get-ChildItem "$src\零件工艺标注" -Recurse -File | ForEach-Object {
  $rel=$_.FullName.Substring("$src\零件工艺标注".Length).TrimStart('\')
  $target=Join-Path "$dst\samples\零件工艺标注" $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
```

不复制：`.git`、`.ruff_cache`、`零件工艺标注.zip`、`paddlepaddle-3.3.1-cp39-cp39-win_amd64.whl`、
`ocr_worker\data`、`frontend`、`node_modules`、`dist`。

- [ ] **Step 6: 写 `mixed_annotation/README.md`**

必须包含：
- 模块说明：混合标注后端 + OCR Worker + 本地模型。
- 目录说明。
- 单独运行（MinerU API、Worker、后端）的等价命令。
- 集成运行：根目录 `start.bat` 启动六服务；前端通过 `/mix-api` 代理。
- 生产部署：Docker 不包含本模块，需要额外进程与 `/mix-api` 反向代理。
- 模型与数据不进入 git。

- [ ] **Step 7: 验证**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\mixed_annotation\backend'
& 'E:\Anaconda\envs\CFwin11\python.exe' -c "import app; print('backend ok')"
& 'E:\Anaconda\envs\CFwin11\python.exe' -m pytest tests -q
Pop-Location
Push-Location 'H:\Git\1CF_win11\Label-fast-main\mixed_annotation\ocr_worker'
& 'E:\Anaconda\envs\CFwin11\python.exe' -c "import app; print('worker ok')"
Pop-Location
```

Expected: backend ok、pytest 全部通过、worker ok。

- [ ] **Step 8: 检查生成物与大小**

```powershell
Get-ChildItem 'H:\Git\1CF_win11\Label-fast-main\mixed_annotation' -Recurse -Force |
  Where-Object { $_.FullName -match '__pycache__|\.pytest_cache|\.ruff_cache' }
```

Expected: 无输出。模型目录文件数与源目录一致（可抽样比对关键 .safetensors 大小）。

---

## Task 2: 迁移前端模块并适配视图与 API

**Files:**
- Create: `frontend/src/modules/mixed-annotation/views/MixedAnnotationView.vue`
- Create: `frontend/src/modules/mixed-annotation/components/**`
- Create: `frontend/src/modules/mixed-annotation/api/client.ts`
- Create: `frontend/src/modules/mixed-annotation/types.ts`
- Create: `frontend/src/modules/mixed-annotation/utils/*.ts`
- Create: `frontend/src/modules/mixed-annotation/composables/useMarkdownAnnotation.ts`

- [ ] **Step 1: 创建目录并复制源码（不含 styles）**

```powershell
$src='H:\Git\1CF_win11\Label-fast-main_混合标注\frontend\src'
$dst='H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation'
New-Item -ItemType Directory -Force "$dst\views","$dst\api","$dst\utils","$dst\composables","$dst\components\project","$dst\components\workspace","$dst\components\common" | Out-Null
Copy-Item "$src\types.ts" $dst -Force
Copy-Item "$src\api\client.ts" "$dst\api\" -Force
Copy-Item "$src\utils\blocks.ts","$src\utils\markdown.ts" "$dst\utils\" -Force
Copy-Item "$src\composables\useMarkdownAnnotation.ts" "$dst\composables\" -Force
Copy-Item "$src\components\AppHeader.vue" "$dst\components\" -Force
Copy-Item "$src\components\project\*.vue" "$dst\components\project\" -Force
Copy-Item "$src\components\workspace\*.vue" "$dst\components\workspace\" -Force
Copy-Item "$src\components\common\*.vue" "$dst\components\common\" -Force
Copy-Item "$src\App.vue" "$dst\views\MixedAnnotationView.vue" -Force
```

不要复制 `styles`（由 Task 3 负责）。

- [ ] **Step 2: 修改 API 基地址**

`api/client.ts` 中：

```ts
const API_BASE = '/mix-api'

export function apiUrl(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const withApi =
    normalized === '/api' || normalized.startsWith('/api/')
      ? normalized
      : `/api${normalized}`
  return `${API_BASE}${withApi}`
}
```

说明：`/api/health` → `/mix-api/api/health`；Vite 去 `/mix-api` 后后端仍收到 `/api/health`。

- [ ] **Step 3: 修正 Markdown 资源地址**

`utils/markdown.ts` 的 `resolveMarkdownAssetUrl`：

把原逻辑：

```ts
if (
  /^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value) ||
  value.startsWith('/api/') ||
  value.startsWith('api/')
) {
  return value.startsWith('api/') ? `/${value}` : value
}
```

改为：

```ts
if (/^(?:[a-z][a-z0-9+.-]*:|\/\/|#)/i.test(value)) {
  return value
}
if (value.startsWith('/api/') || value.startsWith('api/')) {
  return apiUrl(value.startsWith('/') ? value : `/${value}`)
}
```

确保旧 Markdown 中已有的 `/api/files/...` 图片地址会加上 `/mix-api`。

- [ ] **Step 4: 修正视图导入路径**

`views/MixedAnnotationView.vue`：
- `./components/...` → `../components/...`
- `./api/client` → `../api/client`
- `./types` → `../types`

组件内原有的 `../types`、`../../types`、`../../utils/...`、`../../api/client` 等相对路径
保持有效（模块根目录结构与原 `src/` 对齐），不要改动。

- [ ] **Step 5: 视图根节点与语义标签**

- `<div class="mixed-app">` → `<div class="mx-root">`
- 内层 `<main class="app-main">` → `<div class="mx-main">`，闭合标签同步。
- 在 `<script setup>` 顶部加入：

```ts
import "../styles/app.css";
import "../styles/markdown.css";
```

- [ ] **Step 6: 工具栏去掉品牌**

`components/AppHeader.vue`：
- 模板根 `<header class="app-header">` → `<div class="mx-header">`（闭合标签同步）。
- 删除整个 `.header-brand` 品牌块（含 `brand-wordmark`、`brand-dot`、`brand-sub`）。
- 保留项目下拉、当前文件状态、导出 ZIP、在线状态。

- [ ] **Step 7: 应用类名映射（.vue 全目录）**

按“长串优先”替换完整 class token：

```text
btn-primary   -> mx-btn-primary
btn-danger    -> mx-btn-danger
btn-icon      -> mx-btn-icon
btn-sm        -> mx-btn-sm
btn           -> mx-btn
app-body      -> mx-body
app-main      -> mx-main
app-header    -> mx-header
header-brand  -> mx-header-brand
input         -> mx-input
empty-state-icon -> mx-empty-state-icon
empty-state   -> mx-empty-state
status-dot    -> mx-status-dot
label-chip    -> mx-label-chip
```

只替换类名 token（class 属性、:class 字符串、组件内 `<style scoped>` 选择器），
不要改 `<input>` 标签、变量名或普通文本。注意不要误伤 `btn-file`、`input-*` 等。

- [ ] **Step 8: 自检**

```powershell
$m='H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation'
Select-String -Path "$m\components\*.vue","$m\components\*\*.vue","$m\views\*.vue" -Pattern '(?<![\w-])(app-body|app-main|app-header|header-brand|btn|btn-primary|btn-danger|btn-icon|btn-sm|input|empty-state|empty-state-icon|status-dot|label-chip)(?![\w-])'
```

Expected: 无输出（`mx-*` 不应被匹配）。

---

## Task 3: CSS 作用域与主题统一

**Files:**
- Create: `frontend/src/modules/mixed-annotation/styles/app.css`
- Create: `frontend/src/modules/mixed-annotation/styles/markdown.css`

- [ ] **Step 1: 复制两份样式**

```powershell
Copy-Item 'H:\Git\1CF_win11\Label-fast-main_混合标注\frontend\src\styles\app.css' 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation\styles\app.css' -Force
Copy-Item 'H:\Git\1CF_win11\Label-fast-main_混合标注\frontend\src\styles\markdown.css' 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation\styles\markdown.css' -Force
```

- [ ] **Step 2: 删除全局规则**

- 删除 `:root { ... }`（混合令牌与 数据标注与分类工具 全局基本一致，直接继承）。
- 删除 `html, body, #app { height: 100%; }`、`html { ... }`、`body { ... }`。
- 保留 `*` box-sizing 可删除（全局已有）。
- 删除 `::selection` 全局规则或改为 `.mx-root ::selection`。
- `@keyframes spin` 改名为 `mx-spin`，同步 `animation` 引用。

- [ ] **Step 3: 作用域化**

所有普通选择器加 `.mx-root ` 前缀，例如：

```css
.mx-root .mx-header { ... }
.mx-root .mx-body { ... }
.mx-root .project-sidebar { ... }
```

- `@media` 内部选择器同样加前缀。
- `.mixed-app` 改为 `.mx-root`（根节点本身）。
- 元素选择器（`button`、`input`、`table`、`h1` 等）改为 `.mx-root button` 等。

- [ ] **Step 4: 布局适配外层 app-main**

```css
.mx-root {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--paper);
}
.mx-root .mx-body {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  overflow: hidden;
}
.mx-root .mx-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
```

- 原 `.app-main` 的暖纸渐变背景保留在 `.mx-main`。
- 原 `.app-header` 的 64px 高度、backdrop-filter 保留在 `.mx-header`。
- 检查媒体查询中的 `height: 100vh` 改为 `100%`。

- [ ] **Step 5: 应用类名映射（两个 CSS 文件）**

按 Task 2 Step 7 的同一映射替换 CSS 选择器，只替换完整类名 token。

- [ ] **Step 6: 自检**

```powershell
$css='H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation\styles\app.css','H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\mixed-annotation\styles\markdown.css'
Select-String -Path $css -Pattern '^(:root|html|body)\b'
Select-String -Path $css -Pattern '^\.(app-body|app-main|app-header|header-brand|btn|btn-primary|btn-danger|btn-icon|btn-sm|input|empty-state|empty-state-icon|status-dot|label-chip)(?![\w-])'
```

Expected: 两条命令均无输出。

- [ ] **Step 7: 无头 Chrome 样式抽检（可选但推荐）**

构造临时 HTML 引入 数据标注与分类工具 `app.css` + 本模块 `app.css`，检查 `.mx-root` 背景为
`#F6F3EC`、`.mx-btn` 背景为 `#E4572E`、侧栏背景为 `#FFFDF9`。

---

## Task 4: 路由、导航、代理、启动脚本、依赖与文档

**Files:**
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/AppNavRail.vue`
- Modify: `frontend/src/components/AppHeader.vue`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Modify: `start.bat`
- Modify: `.gitignore`
- Modify: `README_zh.md`
- Modify: `README.md`

- [ ] **Step 1: 路由**

在 `/app` children 中、classify 路由之后加入：

```ts
        {
          path: 'mixed',
          name: 'mixed-annotation',
          component: () => import('../modules/mixed-annotation/views/MixedAnnotationView.vue'),
          meta: { title: '混合标注' },
        },
```

- [ ] **Step 2: 左侧导航**

在「国标」项之后加入：

```vue
      <RouterLink
        to="/app/mixed"
        class="app-nav-item"
        title="混合标注"
        aria-label="混合标注"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M15 3v4h4" />
            <path d="M8 12h6M8 16h4" />
            <path d="m17 15 2 2 2-2" />
          </svg>
        </span>
        <span class="app-nav-label">混合</span>
      </RouterLink>
```

- [ ] **Step 3: 眉题**

`AppHeader.vue` switch 新增：

```ts
    case 'mixed-annotation':
      return 'Mixed Annotation'
```

- [ ] **Step 4: Vite 代理**

在 `gbBackendTarget` 后加入：

```ts
// 混合标注后端端口，由 start.bat 探测后通过 MIX_BACKEND_PORT 传入
const mixBackendPort = process.env.MIX_BACKEND_PORT || '3200'
const mixBackendTarget = `http://127.0.0.1:${mixBackendPort}`
```

proxy 中增加：

```ts
      '/mix-api': {
        target: mixBackendTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/mix-api/, ''),
      },
```

- [ ] **Step 5: 前端依赖**

`frontend/package.json` 增加：

```json
    "dompurify": "^3.2.4",
    "markdown-it": "^14.1.0",
    "pdfjs-dist": "^4.10.38",
```

devDependencies 增加：

```json
    "@types/markdown-it": "^14.1.2",
```

- [ ] **Step 6: 启动脚本六服务**

保留现有三服务逻辑，新增混合后端、OCR Worker、MinerU API。

端口变量：
- `MIX_BACKEND_PORT=3200`
- `OCR_WORKER_PORT=8870`
- `MINERU_API_PORT=18000`

模型/OCR 环境变量（在启动任何进程前设置）：

```bat
set "MIX_ROOT=%~dp0mixed_annotation"
set "MODELSCOPE_CACHE=%MIX_ROOT%\models\modelscope"
set "HF_HOME=%MIX_ROOT%\models\huggingface"
set "HF_HUB_CACHE=%MIX_ROOT%\models\huggingface\hub"
set "TORCH_HOME=%MIX_ROOT%\models\torch"
set "OCR_WORKER_DATA_DIR=%MIX_ROOT%\ocr_worker\data"
set "MINERU_API_OUTPUT_ROOT=%MIX_ROOT%\ocr_worker\data\mineru_api_output"
set "MINERU_MODEL_SOURCE=modelscope"
set "HF_HUB_DISABLE_SYMLINKS=1"
set "MINERU_RUNNER=%MIX_ROOT%\ocr_worker\mineru_runner.py"
set "MINERU_DEVICE_MODE=cuda"
set "OCR_ENGINE=mineru"
set "MINERU_MODE=auto"
set "OCR_WORKER_CONCURRENCY=3"
set "MINERU_BACKEND=pipeline"
set "MINERU_LANGUAGE=ch"
set "MINERU_PARSE_METHOD=auto"
set "MINERU_HIGH_ACCURACY=0"
set "MINERU_API_MAX_CONCURRENT_REQUESTS=3"
set "MINERU_API_TASK_RETENTION_SECONDS=3600"
```

启动顺序：
1. MinerU API（127.0.0.1，端口探测），等待 20 秒健康检查；
   失败则 `MINERU_MODE=subprocess`、`OCR_WORKER_CONCURRENCY=1`。
2. OCR Worker（127.0.0.1，工作目录 `%MIX_ROOT%\ocr_worker`）。
3. 混合后端（127.0.0.1，工作目录 `%MIX_ROOT%\backend`）。
4. 数据标注与分类工具 后端、GB 后端、前端（保持现有）。
5. 设置 `OCR_WORKER_URL=http://127.0.0.1:%OCR_WORKER_PORT%`、
   `MINERU_API_URL=http://127.0.0.1:%MINERU_API_PORT%`。
6. 前端窗口传入 `BACKEND_PORT`、`GB_BACKEND_PORT`、`MIX_BACKEND_PORT`、`FRONTEND_PORT`。
7. 打印六个实际地址与手动启动步骤。

要求：所有 `start` 使用 `start "title" /D "路径"`，文件 ASCII + CRLF。

- [ ] **Step 7: `.gitignore`**

追加：

```gitignore
# Mixed annotation runtime data / models
mixed_annotation/models/
mixed_annotation/backend/data/
mixed_annotation/ocr_worker/data/
mixed_annotation/.ruff_cache/
```

- [ ] **Step 8: README**

`README_zh.md` / `README.md` 增加「混合标注」小节：
- 入口：登录后左侧「混合」，路由 `/app/mixed`。
- 前端模块：`frontend/src/modules/mixed-annotation`。
- 后端：`mixed_annotation/backend`（3200）、OCR Worker（8870）、MinerU API（18000）。
- 代理：`/mix-api/api/*` → 混合后端 `/api/*`。
- 模型目录与首次 OCR 加载时间。
- 生产/Docker 不包含本模块，需要额外进程与 `/mix-api` 反向代理。
- `start.bat` 启动六服务。

- [ ] **Step 9: 自检**

```powershell
Select-String -Path 'frontend/src/router/index.ts' -Pattern 'mixed-annotation'
Select-String -Path 'frontend/src/components/AppHeader.vue' -Pattern 'mixed-annotation'
Select-String -Path 'frontend/vite.config.ts' -Pattern 'mix-api'
Select-String -Path 'start.bat' -Pattern 'MinerU|OCR_WORKER_PORT|MIX_BACKEND_PORT'
```

Expected: 均有命中。

---

## Task 5: 安装依赖、构建、测试与浏览器验证

- [ ] **Step 1: 安装前端依赖**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm install
Pop-Location
```

Expected: 成功安装 `pdfjs-dist`、`markdown-it`、`dompurify`、`@types/markdown-it`。
若网络不可用，可从混合项目 `frontend\node_modules` 复制对应包，但仍需更新 `package-lock.json`。

- [ ] **Step 2: 类型检查与构建**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm run build
Pop-Location
```

Expected: exit 0，生成 `Standard...` 与 `MixedAnnotationView-*.js/css` 产物。

- [ ] **Step 3: 后端测试**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\mixed_annotation\backend'
& 'E:\Anaconda\envs\CFwin11\python.exe' -m pytest tests -q
Pop-Location
```

Expected: 全部通过。

- [ ] **Step 4: 启动六服务并做健康检查**

先做简化版：启动混合后端 3211、Worker 8871、MinerU API 18001（测试端口），
检查：
- `http://127.0.0.1:3211/api/health`
- `http://127.0.0.1:8871/health`
- `http://127.0.0.1:18001/health`
然后用 Vite 测试端口 5199 + `MIX_BACKEND_PORT=3211` 检查
`http://127.0.0.1:5199/mix-api/api/health`。

Expected: 均返回健康状态。

- [ ] **Step 5: 浏览器验证**

无头 Chrome：
1. 未登录访问 `/app/mixed` → 登录页。
2. 临时预览页加载 `MixedAnnotationView`，截图确认：
   - 工具栏无重复品牌；
   - 左侧项目面板、右侧工作区；
   - 暖纸背景、朱砂强调与 数据标注与分类工具 一致；
   - 无横向溢出。
3. 同时截图文本标注页，确认混合 CSS 未污染。

- [ ] **Step 6: 已有项目加载与转换**

- 在临时预览或登录后的页面中选择一个已有项目，打开已转换文件，确认 Markdown/PDF 渲染。
- 用 `mixed_annotation/samples` 或已有 PDF 走一次上传 → 转换 → 打开结果；
  MinerU 首次加载约 40 秒，确认最终生成 Markdown 与图片。

- [ ] **Step 7: 清理**

停止测试端口进程，删除临时预览文件与截图，清理 `mixed_annotation` 下
`__pycache__`/`.pytest_cache`/`.ruff_cache`（不删除 models 与 backend/data）。
```

---

## 自检清单

- 规格覆盖：目录、六进程、`/mix-api` 代理、登录守卫、本机监听、页内工具栏、CSS 作用域、
  模型/数据迁移、启动脚本、文档、验证，均有对应任务。
- 类名映射在 Task 2、Task 3 完全一致。
- 无 TBD/TODO/占位步骤。
