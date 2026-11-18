# 国标分类模块集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GB_fenlei 的航空标准分类功能作为独立后端进程 + 数据标注与分类工具 前端模块，集成到左侧导航栏并通过统一设计系统呈现。

**Architecture:** GB 后端整体迁移到 `GB_fenlei/backend`，独立端口运行；GB 前端源码迁移到 `frontend/src/modules/gb-fenlei`，新增 `/app/classify` 路由，接口经 Vite `/gb-api` 前缀代理到 GB 后端；GB 样式全部限定在 `.gb-module` 作用域并映射到 数据标注与分类工具 的 Ink & Signal 令牌。

**Tech Stack:** Vue 3 + TypeScript + vue-router + Vite 6 + FastAPI。

**提交策略:** 用户未要求提交，本计划不包含 `git commit` 步骤；所有改动完成并验证后由用户决定是否提交。

---

## 并行执行地图

| 执行者 | 任务 | 依赖 |
| --- | --- | --- |
| Agent A | Task 1 后端/文档/样例外迁 | 无 |
| Agent B | Task 2 + Task 3 前端模块与组件适配 | 无 |
| Agent C | Task 4 样式作用域与主题统一 | 与 B 按同一映射并行 |
| Agent D | Task 5 + Task 6 路由/导航/代理/启动脚本 | 无 |
| 主 Agent | Task 7 汇总验证与修复 | A/B/C/D 全部完成 |

---

## Task 1: 迁移 GB 后端、文档与样例数据

**Files:**
- Create: `GB_fenlei/backend/**`
- Create: `GB_fenlei/docs/**`
- Create: `GB_fenlei/samples/*.xlsx`
- Create: `GB_fenlei/README.md`

- [ ] **Step 1: 创建目标目录**

```powershell
New-Item -ItemType Directory -Force `
  'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\backend', `
  'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\docs', `
  'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\samples'
```

- [ ] **Step 2: 复制后端源码，排除可再生成文件**

```powershell
$src = 'H:\Git\1CF_win11\GB_fenlei\backend'
$dst = 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\backend'
Get-ChildItem $src -Recurse -File | Where-Object {
  $_.FullName -notmatch '__pycache__|\.pytest_cache|\\wheels-py37\\|\.pyc$'
} | ForEach-Object {
  $rel = $_.FullName.Substring($src.Length).TrimStart('\')
  $target = Join-Path $dst $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
```

- [ ] **Step 3: 复制文档与样例**

```powershell
$docs = 'H:\Git\1CF_win11\GB_fenlei\docs'
$docsDst = 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\docs'
Get-ChildItem $docs -Recurse -File | ForEach-Object {
  $rel = $_.FullName.Substring($docs.Length).TrimStart('\')
  $target = Join-Path $docsDst $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
Copy-Item 'H:\Git\1CF_win11\GB_fenlei\测试集.xlsx' 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\samples\' -Force
Copy-Item 'H:\Git\1CF_win11\GB_fenlei\待分类目录.xlsx' 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\samples\' -Force
Copy-Item 'H:\Git\1CF_win11\GB_fenlei\分类好国标.xlsx' 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\samples\' -Force
```

- [ ] **Step 4: 写模块说明 `GB_fenlei/README.md`**

内容必须包含：

```markdown
# 航空标准分类（GB_fenlei）模块

本目录是 数据标注与分类工具 集成的国标分类后端，保持独立运行能力。

## 目录
- `backend/`：FastAPI 服务，入口 `main.py`
- `docs/`：原项目设计文档
- `samples/`：样例 Excel

## 单独运行
```bat
call conda activate CFwin11
cd /d <仓库根>\GB_fenlei\backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```
访问 http://127.0.0.1:8000/docs

## 集成运行
根目录 `start.bat` 会自动探测端口并启动本服务；
前端通过 Vite `/gb-api` 前缀代理访问，例如 `/gb-api/api/health`。

## 生产部署
若前端由 数据标注与分类工具 后端静态托管，需要在部署层为 `/gb-api` 配置反向代理到本服务端口。
```

- [ ] **Step 5: 验证后端可导入、测试通过**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\backend'
conda run -n CFwin11 python -c "import main; print(main.app.title)"
conda run -n CFwin11 python -m pytest tests/test_api.py tests/test_workflow.py -q
Pop-Location
```

Expected: 打印 `航空标准分类服务`，测试 `32 passed`。

- [ ] **Step 6: 确认没有迁移生成物**

```powershell
Get-ChildItem 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei' -Recurse -Force |
  Where-Object { $_.FullName -match '__pycache__|\.pytest_cache|wheels-py37|\\\.git\\' }
```

Expected: 无输出。

---

## Task 2: 创建前端模块并迁移基础文件

**Files:**
- Create: `frontend/src/modules/gb-fenlei/api.ts`
- Create: `frontend/src/modules/gb-fenlei/types.ts`
- Create: `frontend/src/modules/gb-fenlei/format.ts`
- Create: `frontend/src/modules/gb-fenlei/components/*.vue`
- Create: `frontend/src/modules/gb-fenlei/views/StandardClassifyView.vue`

- [ ] **Step 1: 创建目录并复制基础文件**

```powershell
$src = 'H:\Git\1CF_win11\GB_fenlei\frontend\src'
$dst = 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei'
New-Item -ItemType Directory -Force "$dst\components", "$dst\views"
Copy-Item "$src\api.ts", "$src\types.ts", "$src\format.ts" $dst -Force
Copy-Item "$src\components\*.vue" "$dst\components\" -Force
Copy-Item "$src\App.vue" "$dst\views\StandardClassifyView.vue" -Force
Copy-Item "$src\styles.css" "$dst\styles.css" -Force
```

- [ ] **Step 2: 修改 `api.ts` 的基地址**

把：

```ts
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");
```

改为：

```ts
// 国标分类后端由 Vite 代理转发：/gb-api/api/* -> http://127.0.0.1:<GB_BACKEND_PORT>/api/*
const BASE = "/gb-api";
```

其余请求逻辑、`resolveDownloadUrl`、`errorMessage` 全部保持不变。

- [ ] **Step 3: 修正视图文件内的组件导入路径**

`views/StandardClassifyView.vue` 中把所有：

```ts
import AppSidebar from "./components/AppSidebar.vue";
import PendingStep from "./components/PendingStep.vue";
import ReferenceStep from "./components/ReferenceStep.vue";
import ResultsStep from "./components/ResultsStep.vue";
import RunStep from "./components/RunStep.vue";
```

改为：

```ts
import AppSidebar from "../components/AppSidebar.vue";
import PendingStep from "../components/PendingStep.vue";
import ReferenceStep from "../components/ReferenceStep.vue";
import ResultsStep from "../components/ResultsStep.vue";
import RunStep from "../components/RunStep.vue";
```

`api`、`types` 的 `./api`、`./types` 仍能解析到模块根目录，保持不变。

- [ ] **Step 4: 确认模块内无对外部相对路径的依赖**

```powershell
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\*.ts','H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\components\*.vue','H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\views\*.vue' -Pattern 'from "\.\./\.\./|from ''\.\./\.\./' 
```

Expected: 无输出。

---

## Task 3: 组件适配（模块包裹、冲突类名、弹窗、去品牌）

**Files:**
- Modify: `frontend/src/modules/gb-fenlei/views/StandardClassifyView.vue`
- Modify: `frontend/src/modules/gb-fenlei/components/*.vue`

- [ ] **Step 1: 给视图根节点加 `.gb-module` 包裹**

把 `StandardClassifyView.vue` 顶层模板：

```vue
<template>
  <div class="app-shell">
```

改为：

```vue
<template>
  <div class="gb-module">
    <div class="app-shell">
```

并在原 `</div>`（app-shell 结束）后再补一个 `</div>` 关闭 `.gb-module`。

- [ ] **Step 2: 应用 5 个冲突类名重命名**

全局替换（模板和 CSS 都要改）：

| 旧类名 | 新类名 |
| --- | --- |
| `app-main` | `gb-main` |
| `btn` | `gb-btn` |
| `btn-primary` | `gb-btn-primary` |
| `sidebar` | `gb-sidebar` |
| `stat-label` | `gb-stat-label` |

替换时按“长串优先”的顺序执行，避免 `btn-primary` 先被 `btn` 截断：

```text
btn-primary -> gb-btn-primary
btn -> gb-btn
app-main -> gb-main
sidebar -> gb-sidebar
stat-label -> gb-stat-label
```

注意只替换类名 token（`class="..."`、`:class` 中的类名、CSS 选择器），
不要替换变量名、函数名或普通文本。

- [ ] **Step 3: 关闭 DataDialog 的 Teleport**

`components/DataDialog.vue` 第 122 行：

```vue
<Teleport to="body">
```

改为：

```vue
<Teleport to="body" disabled>
```

原因：Teleport 到 body 后元素脱离 `.gb-module`，作用域样式无法命中。

- [ ] **Step 4: 移除 AppSidebar 的品牌块**

删除 `components/AppSidebar.vue` 模板中的整段：

```vue
<div class="brand">
  <div class="brand-mark" aria-hidden="true">...</div>
  <div class="brand-text">
    <strong>航空标准分类</strong>
    <span>标准目录分类工作台</span>
  </div>
</div>
```

保留 `<nav class="side-nav">` 内已有的 `<p class="side-nav-title">工作流程</p>`，
把文字改为 `分类流程`。

- [ ] **Step 5: 检查无残留旧类名**

```powershell
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\components\*.vue','H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\views\*.vue' -Pattern 'class="[^"]*\b(btn|btn-primary|app-main|sidebar|stat-label)\b'
```

Expected: 无输出。

---

## Task 4: 样式作用域与 Ink & Signal 主题统一

**Files:**
- Modify: `frontend/src/modules/gb-fenlei/styles.css`

- [ ] **Step 1: 替换全局调色板为 `.gb-module` 令牌映射**

删除原 `:root { ... }` 整块，替换为：

```css
.gb-module {
  /* 数据标注与分类工具 Ink & Signal 令牌映射 */
  --bg: var(--paper);
  --surface: var(--surface);
  --surface-subtle: var(--surface-sunken);
  --surface-hover: var(--surface-sunken);
  --border: var(--line);
  --border-strong: var(--line-strong);
  --border-soft: #ece7dd;
  --text: var(--ink);
  --text-2: var(--ink-2);
  --text-3: var(--ink-3);
  --primary: var(--signal);
  --primary-hover: var(--signal-deep);
  --primary-soft: var(--signal-soft);
  --primary-border: #f0c4b5;
  --success: var(--success);
  --success-soft: var(--success-bg);
  --success-border: #b7dfc8;
  --warning: var(--warning);
  --warning-soft: var(--warning-bg);
  --warning-border: #ecd39a;
  --danger: var(--danger);
  --danger-soft: var(--danger-bg);
  --danger-border: #f3c2bd;
  --radius: var(--radius-sm);
  --radius-lg: var(--radius);
  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
  --shadow-panel: var(--shadow-xs);
  --transition: var(--transition-fast);

  /* 侧栏改为暖纸浅色 */
  --sidebar: var(--surface);
  --sidebar-raised: var(--signal-soft);
  --sidebar-text: var(--ink-2);
  --sidebar-muted: var(--ink-4);

  height: 100%;
  min-height: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.55;
}
```

同时删除原 `html, body { min-height: 100%; }` 和 `body { ... }` 规则。

- [ ] **Step 2: 将所有选择器限定在 `.gb-module` 下**

规则：
- 普通选择器：`.app-shell {` → `.gb-module .app-shell {`
- 多选择器逗号列表：每一项都加前缀
- `@media` 内部的选择器同样加前缀，`@media` 本身不限定
- `@keyframes` 单独保留，名称统一加 `gb-` 前缀，并同步修改 `animation:` 引用
- 元素选择器（`button`、`input`、`table`、`h1`、`p` 等）改为 `.gb-module button` 等

示例：

```css
.gb-module .gb-main { ... }
.gb-module .topbar { ... }
.gb-module .content { ... }
@media (max-width: 1100px) {
  .gb-module .some-class { ... }
}
```

- [ ] **Step 3: 修正固定定位布局**

把原侧栏与主区：

```css
.app-shell { display: flex; min-height: 100vh; }
.sidebar { position: fixed; inset: 0 auto 0 0; width: 250px; ... }
.app-main { margin-left: 250px; ... }
```

改为：

```css
.gb-module .app-shell {
  display: flex;
  height: 100%;
  min-height: 0;
}

.gb-module .gb-sidebar {
  position: relative;
  inset: auto;
  z-index: 1;
  display: flex;
  flex-direction: column;
  width: 250px;
  flex: 0 0 250px;
  height: 100%;
  background: var(--surface);
  color: var(--ink-2);
  border-right: 1px solid var(--line);
}

.gb-module .gb-main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  margin-left: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.gb-module .content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 28px 40px;
}
```

- [ ] **Step 4: 浅色侧栏内部元素配色**

按现有选择器逐项改为浅色方案：

- `.gb-sidebar` 顶部/底部边框改用 `var(--line)`
- `.side-nav-item` 默认 `color: var(--ink-2)`，hover 背景 `var(--surface-sunken)`
- `.side-nav-item.current` 背景 `var(--signal-soft)`，文字 `var(--signal-ink)`
- `.side-nav-item.current::before` 背景 `var(--signal)`
- `.side-nav-index` 边框 `var(--line-strong)`，文字 `var(--ink-3)`
- `.side-nav-item.done .side-nav-index` 边框/背景使用成功色系
- `.side-nav-item.current .side-nav-index` 边框 `var(--signal)`，文字 `var(--signal)`
- `.side-nav-desc`、`.sidebar-note`、`.service-version` 使用 `var(--ink-4)`
- `.service-dot` 默认 `var(--ink-4)`，`.online` 用 `var(--success)`，`.offline` 用 `var(--danger)`

- [ ] **Step 5: 校验样式文件没有未限定作用域的选择器**

```powershell
$css = Get-Content 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\styles.css' -Raw
# 人工确认以下模式不存在（:root、html、body 顶层规则）
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\styles.css' -Pattern '^(:root|html|body)\b'
```

Expected: 无输出。

- [ ] **Step 6: 校验冲突类名已全部替换**

```powershell
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\gb-fenlei\styles.css' -Pattern '^\.(btn|btn-primary|app-main|sidebar|stat-label)\b'
```

Expected: 无输出。

---

## Task 5: 路由、左侧导航与页眉标题

**Files:**
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/AppNavRail.vue`
- Modify: `frontend/src/components/AppHeader.vue`

- [ ] **Step 1: 新增路由**

在 `router/index.ts` 的 `/app` children 中、`qa` 路由之后加入：

```ts
        {
          path: 'classify',
          name: 'standard-classify',
          component: () => import('../modules/gb-fenlei/views/StandardClassifyView.vue'),
          meta: { title: '航空标准分类' },
        },
```

- [ ] **Step 2: 左侧导航新增入口**

在 `AppNavRail.vue` 的 `.nav-items` 中、问答项之后加入：

```vue
      <RouterLink
        to="/app/classify"
        class="app-nav-item"
        title="航空标准分类"
        aria-label="航空标准分类"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3 3 7.5 12 12l9-4.5z" />
            <path d="m3 12 9 4.5 9-4.5" />
            <path d="m3 16.5 9 4.5 9-4.5" />
          </svg>
        </span>
        <span class="app-nav-label">国标</span>
      </RouterLink>
```

- [ ] **Step 3: 页眉眉题新增分支**

在 `AppHeader.vue` 的 `moduleEyebrow` switch 中加：

```ts
    case 'standard-classify':
      return 'Standard Classification'
```

- [ ] **Step 4: 验证路由名称一致**

```powershell
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\router\index.ts' -Pattern "standard-classify"
Select-String -Path 'H:\Git\1CF_win11\Label-fast-main\frontend\src\components\AppHeader.vue' -Pattern "standard-classify"
```

Expected: 各 1 处命中。

---

## Task 6: Vite 代理、三服务启动脚本与文档

**Files:**
- Modify: `frontend/vite.config.ts`
- Replace: `start.bat`
- Modify: `README_zh.md`
- Modify: `README.md`

- [ ] **Step 1: 修改 `vite.config.ts`**

在 `backendPort` 定义之后加入：

```ts
// 国标分类后端端口，由 start.bat 探测后通过 GB_BACKEND_PORT 传入
const gbBackendPort = process.env.GB_BACKEND_PORT || '8000'
const gbBackendTarget = `http://127.0.0.1:${gbBackendPort}`
```

在 `proxy` 中增加：

```ts
      '/gb-api': {
        target: gbBackendTarget,
        changeOrigin: true,
        // 去掉 /gb-api 前缀：/gb-api/api/health -> /api/health
        rewrite: (path: string) => path.replace(/^\/gb-api/, ''),
      },
```

- [ ] **Step 2: 重写 `start.bat`（内容保持 ASCII，避免编码问题）**

```bat
@echo off
chcp 65001 >nul 2>&1
setlocal

echo.
echo ============================================
echo   数据标注与分类工具 Workspace - Starting services
echo ============================================
echo.
echo   Detecting free ports...

set "BACKEND_PORT=3002"
set "GB_BACKEND_PORT=8000"
set "FRONTEND_PORT=5175"

for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p=3002; while($p -lt 65535){ try { $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch { $p++ } }"`) do set "BACKEND_PORT=%%p"

for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p=8000; while($p -lt 65535){ try { $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch { $p++ } }"`) do set "GB_BACKEND_PORT=%%p"

for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "$p=5175; while($p -lt 65535){ try { $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Any,$p); $l.Start(); $l.Stop(); Write-Output $p; break } catch { $p++ } }"`) do set "FRONTEND_PORT=%%p"

echo   数据标注与分类工具 backend:     %BACKEND_PORT%
echo   GB classifier backend: %GB_BACKEND_PORT%
echo   Frontend:              %FRONTEND_PORT%
echo.
echo   数据标注与分类工具 API:  http://localhost:%BACKEND_PORT%
echo   数据标注与分类工具 docs: http://localhost:%BACKEND_PORT%/docs
echo   GB API docs:    http://localhost:%GB_BACKEND_PORT%/docs
echo   Frontend:       http://localhost:%FRONTEND_PORT%
echo.
echo   Three new windows will open.
echo   Close each window to stop its service.
echo.

echo [1/3] Starting 数据标注与分类工具 backend (conda: CFwin11)...
start "数据标注与分类工具-Backend" cmd /k "call conda activate CFwin11 && cd /d %~dp0backend && python -m uvicorn server:app --host 127.0.0.1 --port %BACKEND_PORT% --reload"

echo [2/3] Starting GB classifier backend (conda: CFwin11)...
start "GB-Fenlei-Backend" cmd /k "call conda activate CFwin11 && cd /d %~dp0GB_fenlei\backend && python -m uvicorn main:app --host 127.0.0.1 --port %GB_BACKEND_PORT%"

echo [3/3] Starting frontend...
start "数据标注与分类工具-Frontend" cmd /k "set BACKEND_PORT=%BACKEND_PORT% && set GB_BACKEND_PORT=%GB_BACKEND_PORT% && set FRONTEND_PORT=%FRONTEND_PORT% && cd /d %~dp0frontend && npm run dev -- --port %FRONTEND_PORT%"

timeout /t 3 /nobreak >nul 2>&1

echo.
echo ============================================
echo   All services started.
echo   Frontend:       http://localhost:%FRONTEND_PORT%
echo   数据标注与分类工具 API:  http://localhost:%BACKEND_PORT%
echo   GB API:         http://localhost:%GB_BACKEND_PORT%
echo ============================================
echo.
echo Press any key to close this window (services keep running)...
pause >nul

rem ===========================================================================
rem Manual start (equivalent commands)
rem   Backend 数据标注与分类工具:
rem     call conda activate CFwin11
rem     cd /d <repo>\backend
rem     python -m uvicorn server:app --host 127.0.0.1 --port 3002 --reload
rem   Backend GB:
rem     call conda activate CFwin11
rem     cd /d <repo>\GB_fenlei\backend
rem     python -m uvicorn main:app --host 127.0.0.1 --port 8000
rem   Frontend:
rem     cd /d <repo>\frontend
rem     set BACKEND_PORT=3002
rem     set GB_BACKEND_PORT=8000
rem     npm run dev
rem ===========================================================================
```

- [ ] **Step 3: 更新 `README_zh.md`**

在“前端路由”或类似章节补充：

```markdown
### 航空标准分类（国标分类）

- 入口：登录后左侧导航「国标」，路由 `/app/classify`
- 后端：`GB_fenlei/backend`，独立进程，默认端口 8000
- 前端模块：`frontend/src/modules/gb-fenlei`
- 接口代理：前端 `/gb-api/api/*` → 国标后端 `/api/*`
- 单独运行后端：
  ```bat
  call conda activate CFwin11
  cd GB_fenlei\backend
  python -m uvicorn main:app --host 127.0.0.1 --port 8000
  ```
```

- [ ] **Step 4: 更新 `README.md`**

用英文补充等价的小节，说明模块路径、路由、代理前缀与启动方式。

- [ ] **Step 5: 校验 Vite 配置可解析**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npx vite --version
Pop-Location
```

Expected: 打印 Vite 版本，无配置语法错误。

---

## Task 7: 汇总验证

**Files:** 无新增；只验证与修复。

- [ ] **Step 1: 前端类型检查**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm run typecheck
Pop-Location
```

Expected: exit 0。

- [ ] **Step 2: 前端生产构建**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm run build
Pop-Location
```

Expected: 构建成功，`dist` 生成，无未解析导入。

- [ ] **Step 3: GB 后端健康检查**

在后台启动：

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\backend'
Start-Process -FilePath 'conda' -ArgumentList 'run','-n','CFwin11','python','-m','uvicorn','main:app','--host','127.0.0.1','--port','8123' -WindowStyle Hidden
Pop-Location
```

等待后请求：

```powershell
Invoke-RestMethod 'http://127.0.0.1:8123/api/health'
```

Expected: `status = ok`，包含 `version` 字段。

- [ ] **Step 4: 验证 Vite 代理**

启动前端 dev server（使用测试端口 5199，`GB_BACKEND_PORT=8123`）：

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
$env:GB_BACKEND_PORT='8123'
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev','--','--port','5199' -WindowStyle Hidden
Pop-Location
```

等待后请求：

```powershell
Invoke-RestMethod 'http://127.0.0.1:5199/gb-api/api/health'
```

Expected: 返回与 Step 3 一致的 JSON。

- [ ] **Step 5: 验证页面资源可访问**

```powershell
(Invoke-WebRequest 'http://127.0.0.1:5199/').StatusCode
(Invoke-WebRequest 'http://127.0.0.1:5199/src/modules/gb-fenlei/views/StandardClassifyView.vue').StatusCode
```

Expected: 两个 200。

- [ ] **Step 6: 运行 GB 后端测试**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\GB_fenlei\backend'
conda run -n CFwin11 python -m pytest tests -q
Pop-Location
```

Expected: 全部通过。

- [ ] **Step 7: 清理测试进程**

关闭 Step 3/4 启动的后台进程（按端口查找）：

```powershell
Get-NetTCPConnection -LocalPort 8123,5199 -State Listen -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

- [ ] **Step 8: 人工浏览器验收**

1. 运行根目录 `start.bat`，确认三个窗口启动并打印实际端口；
2. 打开前端地址，登录后左侧出现「国标」；
3. 点击进入 `/app/classify`，确认：
   - 页内浅色步骤栏与 数据标注与分类工具 配色一致；
   - 四步流程可切换；
   - 上传参照表与待分类表后能执行分类并导出；
   - 浏览器控制台无样式/接口错误；
4. 退出登录后直接访问 `/app/classify`，确认跳转登录页。

---

## 自检清单

- 规格覆盖：目录结构、登录路由、左侧导航、页内浅色步骤栏、样式令牌映射、`/gb-api` 代理、三窗口启动、
  文档、测试，均有对应任务。
- 无 TBD/TODO/占位步骤。
- 类名映射在 Task 3 与 Task 4 中一致：`app-main→gb-main`、`btn→gb-btn`、
  `btn-primary→gb-btn-primary`、`sidebar→gb-sidebar`、`stat-label→gb-stat-label`。
