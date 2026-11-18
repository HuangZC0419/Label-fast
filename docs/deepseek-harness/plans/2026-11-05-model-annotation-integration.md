# 模型标注模块集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把「基于模型的标注」作为独立后端 + 统一前端模块集成到 数据标注与分类工具 左侧菜单「模型」，视觉统一为浅色 Ink & Signal。

**Architecture:** 后端以 CFwin11 + MinerU 独立运行在 8267；前端把 7418 行 App.vue 拆成视图与作用域 CSS，接入 `/app/model`，接口经 Vite `/model-api` 前缀代理。

**Tech Stack:** Vue 3 + Vite 6 + FastAPI + transformers/torch + MinerU。

**提交策略:** 用户未要求提交，本计划不包含 `git commit`。

---

## 并行执行地图

| 执行者 | 任务 | 依赖 |
| --- | --- | --- |
| Agent A | Task 1 后端/模型/数据迁移 | 无 |
| Agent B | Task 2 前端视图拆分与 API/去品牌/去深色 | 无 |
| Agent D | Task 4 路由/导航/代理/启动/文档/依赖 | 无 |
| Agent C | Task 3 CSS 作用域与主题映射 | 必须等 B 产出 styles 文件 |
| 主 Agent | Task 5 安装依赖、构建、测试、截图 | A/B/C/D 完成 |

---

## Task 1: 迁移模型标注后端、模型与数据

**Files:**
- Create: `model_annotation/backend/**`
- Create: `model_annotation/input/**`
- Create: `model_annotation/output/**`
- Create: `model_annotation/docs/**`
- Create: `model_annotation/samples/**`
- Create: `model_annotation/README.md`

- [ ] **Step 1: 创建目录**

```powershell
$dst='H:\Git\1CF_win11\Label-fast-main\model_annotation'
New-Item -ItemType Directory -Force "$dst\backend","$dst\input","$dst\output","$dst\docs","$dst\samples" | Out-Null
```

- [ ] **Step 2: 复制 backend（含 models/data/datasets/test_output，排除缓存）**

```powershell
$src='H:\Git\1CF_win11\基于模型的标注\backend'
$dst='H:\Git\1CF_win11\Label-fast-main\model_annotation\backend'
Get-ChildItem $src -Recurse -File | Where-Object {
  $_.FullName -notmatch '__pycache__|\.pytest_cache|\.model_cache|\.pyc$'
} | ForEach-Object {
  $rel=$_.FullName.Substring($src.Length).TrimStart('\')
  $target=Join-Path $dst $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
```

- [ ] **Step 3: 复制 input/output**

```powershell
robocopy 'H:\Git\1CF_win11\基于模型的标注\input' 'H:\Git\1CF_win11\Label-fast-main\model_annotation\input' /E /MT:8 /NFL /NDL /NJH /NJS /NP
robocopy 'H:\Git\1CF_win11\基于模型的标注\output' 'H:\Git\1CF_win11\Label-fast-main\model_annotation\output' /E /MT:8 /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed" }
```

- [ ] **Step 4: 复制 docs 与样例**

```powershell
$src='H:\Git\1CF_win11\基于模型的标注'
$dst='H:\Git\1CF_win11\Label-fast-main\model_annotation'
Get-ChildItem "$src\docs" -Recurse -File | ForEach-Object {
  $rel=$_.FullName.Substring("$src\docs".Length).TrimStart('\')
  $target=Join-Path "$dst\docs" $rel
  New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
  Copy-Item $_.FullName $target -Force
}
Copy-Item "$src\NER测试文本.txt","$src\测试文本.png","$src\测试文本_annotations.jsonl" "$dst\samples\" -Force
```

不复制：`MinerU.zip`、`论文图`、根目录 `1.pdf`/`2.pdf`/`3.pdf`/`4.png`/`test.pdf`（input 已有）、
`.git`、`.pytest_cache`、`node_modules`、`frontend`、`package-lock.json`、`AGENTS.md`。

- [ ] **Step 5: 写 `model_annotation/README.md`**

必须包含：
- 模块说明（文档解析 + NER 训练/推理 + 标注）。
- 目录说明。
- 单独运行：
  `call conda activate CFwin11`
  `cd /d <仓库根>\model_annotation\backend`
  `set PYTHONNOUSERSITE=1`
  `python -m uvicorn main:app --host 127.0.0.1 --port 8267`
- 集成运行：根目录 `start.bat` 启动七服务；前端通过 `/model-api` 代理。
- 生产部署：Docker 不包含本模块，需要额外进程与 `/model-api` 反向代理。
- 模型、input、output、datasets 不进入 git。

- [ ] **Step 6: 验证**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend'
& 'E:\Anaconda\envs\CFwin11\python.exe' -c "import main; print('backend ok')"
& 'E:\Anaconda\envs\CFwin11\python.exe' -m pytest tests -q
Pop-Location
```

Expected: backend ok；pytest 全部通过。若生成 `__pycache__`/`.pytest_cache`/`.model_cache`，最后清理。

- [ ] **Step 7: 检查模型与数据**

```powershell
$m=Get-ChildItem 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend\models' -Recurse -File | Measure-Object Length -Sum
"models files=$($m.Count) sizeGB=$([math]::Round($m.Sum/1GB,2))"
Test-Path 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend\models\chinese-roberta-wwm-ext\model.safetensors'
Test-Path 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend\models\728c03e3110c\model\model.safetensors'
```

Expected: 约 2.36GB，两个 True。

---

## Task 2: 前端视图拆分与适配

**Files:**
- Create: `frontend/src/modules/model-annotation/views/ModelAnnotationView.vue`
- Create: `frontend/src/modules/model-annotation/styles/model-annotation.css`（原样导出，供 Task 3 处理）

- [ ] **Step 1: 复制 App.vue**

```powershell
New-Item -ItemType Directory -Force 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\model-annotation\views','H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\model-annotation\styles' | Out-Null
Copy-Item 'H:\Git\1CF_win11\基于模型的标注\frontend\src\App.vue' 'H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\model-annotation\views\ModelAnnotationView.vue' -Force
```

- [ ] **Step 2: 抽出样式**

把 `ModelAnnotationView.vue` 中 `<style>` 到 `</style>` 的全部内容（约第 3373–7418 行）
原样写入 `styles/model-annotation.css`，然后从视图中删除整个 `<style>` 块。

在 `<script setup>` 顶部加入：

```js
import '../styles/model-annotation.css'
```

- [ ] **Step 3: 修改 API 基地址**

`resolveApiBase()`：

```js
function resolveApiBase() {
  return '/model-api'
}
```

- [ ] **Step 4: 删除品牌块**

删除模板中整个 `.sidebar-brand` 块（含 `brand-icon`、`brand-text`、`Precisor`），
保留历史记录区域与模型管理按钮。

- [ ] **Step 5: 删除深色模式**

- 删除侧栏 footer 中的深色模式切换 `<button class="nav-item" ...>`。
- 删除 `const isDarkMode = ref(false)`。
- 删除 `watch(isDarkMode, ...)`。
- 删除 `window.matchMedia('(prefers-color-scheme: dark)')` 自动置深色的初始化。
- 删除根节点 `:class="{ 'theme-dark': isDarkMode }"`。
- 确保模板与脚本不再出现 `isDarkMode` / `theme-dark`。

- [ ] **Step 6: 页面根节点与布局类**

模板：

```vue
<div class="model-root">
  <div class="model-shell">
    ...
  </div>
</div>
```

类名映射（模板与脚本中的类名字符串）：

```text
app-shell       -> model-shell
app-sidebar     -> model-sidebar
app-main-wrap   -> model-main-wrap
app-main        -> model-main
app-header      -> model-header
btn-primary     -> model-btn-primary
btn-sm          -> model-btn-sm
stat-item       -> model-stat-item
stat-label      -> model-stat-label
status-dot      -> model-status-dot
toast-icon      -> model-toast-icon
```

Vue `<Transition name="toast">` 改为 `<Transition name="model-toast">`。

只替换完整类名 token，不要改普通文本或变量名。

- [ ] **Step 7: 自检**

```powershell
$v='H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\model-annotation\views\ModelAnnotationView.vue'
Select-String -Path $v -Pattern 'isDarkMode|theme-dark|sidebar-brand|Precisor|<style'
Select-String -Path $v -Pattern 'return ''/model-api'''
Select-String -Path $v -Pattern 'class="model-root"|class="model-shell"'
```

Expected：第一条无输出；后两条有命中。

不要运行项目级 typecheck（Task 3/4 仍在并行）。

---

## Task 3: CSS 作用域与主题映射（依赖 Task 2）

**Files:**
- Modify: `frontend/src/modules/model-annotation/styles/model-annotation.css`

- [ ] **Step 1: 替换 `:root` 为 `.model-root` 令牌映射**

删除原 `:root { ... }`，替换为：

```css
.model-root {
  --color-bg: var(--paper);
  --color-bg-alt: var(--paper-deep);
  --color-surface: var(--surface);
  --color-surface-hover: var(--surface-sunken);
  --color-surface-elevated: var(--surface-raised);
  --color-primary: var(--signal);
  --color-primary-hover: var(--signal-deep);
  --color-primary-light: var(--signal-soft);
  --color-primary-soft: #f0c4b5;
  --color-accent: var(--warning);
  --color-accent-hover: #8f6518;
  --color-accent-light: var(--warning-bg);
  --color-success: var(--success);
  --color-success-light: var(--success-bg);
  --color-warning: var(--warning);
  --color-warning-light: var(--warning-bg);
  --color-danger: var(--danger);
  --color-danger-light: var(--danger-bg);
  --color-text: var(--ink);
  --color-text-secondary: var(--ink-3);
  --color-text-muted: var(--ink-4);
  --color-border: var(--line);
  --color-border-light: #ece7dd;
  --color-code-bg: var(--surface-sunken);
  --color-bg-subtle: var(--surface-sunken);
  --color-overlay: rgba(23, 24, 27, 0.45);

  --shadow-xs: var(--shadow-xs);
  --shadow-sm: var(--shadow-sm);
  --shadow-md: var(--shadow);
  --shadow-lg: var(--shadow-lg);
  --shadow-xl: var(--shadow-lg);
  --shadow-card: var(--shadow-sm);

  --radius-xs: var(--radius-xs);
  --radius-sm: var(--radius-sm);
  --radius-md: var(--radius);
  --radius-lg: var(--radius-md);
  --radius-xl: var(--radius-lg);
  --radius-full: 9999px;

  --sidebar-width: 240px;
  --sidebar-collapsed-width: 64px;
  --header-height: 56px;
  --wizard-height: 52px;

  --transition-fast: var(--transition-fast);
  --transition-base: var(--transition);
  --transition-slow: var(--transition-slow);

  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);

  height: 100%;
  min-height: 0;
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.6;
}
```

注意：`--shadow-xs`、`--radius-xs`、`--transition-fast`、`--font-sans` 等与全局同名，
直接继承即可，不要写 `var(--同名)` 的自引用；上表中同名映射行如造成自引用请删除该行。
`--shadow-md`、`--radius-md` 等不同名的映射保留。

- [ ] **Step 2: 删除深色主题**

删除整个 `.app-shell.theme-dark { ... }` 块，以及所有 `.theme-dark` 选择器
（例如 `.app-shell.theme-dark .panel-body`、`.theme-dark .toast.success` 等）。

- [ ] **Step 3: 删除全局规则**

- 删除 `*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }`
- 删除 `html { ... }`
- 删除 `body { ... }`

- [ ] **Step 4: 类名映射**

对 CSS 选择器应用 Task 2 Step 6 的同一映射，另加：

```text
toast              -> model-toast
toast-icon         -> model-toast-icon
toast-enter-active -> model-toast-enter-active
toast-leave-active -> model-toast-leave-active
toast-move         -> model-toast-move
```

按长串优先，避免 `btn-sm` 被 `btn` 截断；不要改 `btn-secondary` 等未列出的类。

- [ ] **Step 5: 作用域化**

所有普通选择器加 `.model-root ` 前缀（`.model-root` 自身规则除外）：
- `.model-shell` → `.model-root .model-shell`
- `.model-sidebar` → `.model-root .model-sidebar`
- `.model-header` → `.model-root .model-header`
- `.model-main` → `.model-root .model-main`
- 元素选择器 `button/input/...` → `.model-root button` 等
- `@media` 内部选择器同样加前缀
- `@keyframes` 名称统一加 `model-` 前缀，并同步 `animation:` 引用

- [ ] **Step 6: 布局高度**

```css
.model-root .model-shell {
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--color-bg);
}
.model-root .model-sidebar {
  height: 100%;
}
.model-root .model-main-wrap {
  height: 100%;
  min-height: 0;
}
.model-root .model-main {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
```

检查媒体查询中的 `100vh` 改为 `100%`。

- [ ] **Step 7: 自检**

```powershell
$css='H:\Git\1CF_win11\Label-fast-main\frontend\src\modules\model-annotation\styles\model-annotation.css'
Select-String -Path $css -Pattern '^(:root|html|body)\b|theme-dark'
Select-String -Path $css -Pattern '^\.(app-shell|app-sidebar|app-main|app-header|btn-primary|btn-sm|status-dot|stat-item|stat-label|toast)(?![\w-])'
Select-String -Path $css -Pattern '100vh|100dvh'
```

Expected：三条均无输出（`@media print` 内如保留需人工确认）。

---

## Task 4: 路由、导航、代理、依赖、启动脚本与文档

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

在 `/app` children 中、mixed 路由之后加入：

```ts
        {
          path: 'model',
          name: 'model-annotation',
          component: () => import('../modules/model-annotation/views/ModelAnnotationView.vue'),
          meta: { title: '模型标注' },
        },
```

- [ ] **Step 2: 左侧导航**

在「混合」项之后加入：

```vue
      <RouterLink
        to="/app/model"
        class="app-nav-item"
        title="模型标注"
        aria-label="模型标注"
      >
        <span class="app-nav-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M15 3v4h4" />
            <path d="M8 12h6M8 16h4" />
            <circle cx="17" cy="17" r="3" />
          </svg>
        </span>
        <span class="app-nav-label">模型</span>
      </RouterLink>
```

- [ ] **Step 3: 眉题**

`AppHeader.vue` switch 新增：

```ts
    case 'model-annotation':
      return 'Model Annotation'
```

- [ ] **Step 4: Vite 代理**

在 mixBackendTarget 后加入：

```ts
// 模型标注后端端口，由 start.bat 探测后通过 MODEL_BACKEND_PORT 传入
const modelBackendPort = process.env.MODEL_BACKEND_PORT || '8267'
const modelBackendTarget = `http://127.0.0.1:${modelBackendPort}`
```

proxy 中增加：

```ts
      '/model-api': {
        target: modelBackendTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/model-api/, ''),
      },
```

- [ ] **Step 5: 前端依赖**

`package.json` dependencies 增加：

```json
    "axios": "^1.6.8",
    "chart.js": "^4.4.0",
    "marked": "^12.0.1",
    "turndown": "^7.2.4",
    "turndown-plugin-gfm": "^1.0.2",
```

- [ ] **Step 6: start.bat 七服务**

新增：

```bat
set "MODEL_BACKEND_PORT=8267"
```

端口探测（TcpListener，8267 起顺延）。

启动（放在 MinerU API 与混合后端之后、前端之前）：

```bat
echo [6/7] Starting Model Annotation backend (conda: CFwin11) on port %MODEL_BACKEND_PORT%...
start "Model-Annotation-Backend" /D "%~dp0model_annotation\backend" cmd /k "call conda activate CFwin11 && set PYTHONNOUSERSITE=1 && python -m uvicorn main:app --host 127.0.0.1 --port %MODEL_BACKEND_PORT%"
```

前端窗口环境变量增加：

```bat
set MODEL_BACKEND_PORT=%MODEL_BACKEND_PORT%
```

打印地址增加：

```bat
echo   Model backend:  http://localhost:%MODEL_BACKEND_PORT%
```

窗口编号更新为 1/7 … 7/7；手动步骤注释补充模型后端命令。

- [ ] **Step 7: `.gitignore`**

追加：

```gitignore
# Model annotation runtime data / models
model_annotation/backend/models/
model_annotation/backend/datasets/
model_annotation/backend/.model_cache/
model_annotation/input/
model_annotation/output/
```

- [ ] **Step 8: README**

`README_zh.md` / `README.md` 增加「模型标注 / Model Annotation」小节：
- 入口：登录后左侧「模型」，路由 `/app/model`
- 前端模块：`frontend/src/modules/model-annotation`
- 后端：`model_annotation/backend`，端口 8267（CFwin11 + MinerU）
- 代理：`/model-api/*` → 模型标注后端
- 模型目录 2.36GB，首次推理/training 加载较慢
- 生产/Docker 不包含本模块，需要额外进程与 `/model-api` 反向代理
- start.bat 启动七服务

- [ ] **Step 9: 自检**

```powershell
Select-String -Path 'frontend/src/router/index.ts' -Pattern 'model-annotation'
Select-String -Path 'frontend/src/components/AppHeader.vue' -Pattern 'model-annotation'
Select-String -Path 'frontend/vite.config.ts' -Pattern 'model-api'
Select-String -Path 'start.bat' -Pattern 'MODEL_BACKEND_PORT|Model-Annotation'
```

Expected：均有命中。

---

## Task 5: 安装依赖、构建与端到端验证

- [ ] **Step 1: 安装前端依赖**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm install
Pop-Location
```

- [ ] **Step 2: 类型检查与构建**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\frontend'
npm run build
Pop-Location
```

Expected: exit 0，产出 `ModelAnnotationView-*.js/css`。

- [ ] **Step 3: 后端测试**

```powershell
Push-Location 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend'
& 'E:\Anaconda\envs\CFwin11\python.exe' -m pytest tests -q
Pop-Location
```

- [ ] **Step 4: API 与代理健康检查**

启动模型后端测试端口 8271：

```powershell
$env:PYTHONNOUSERSITE='1'
Push-Location 'H:\Git\1CF_win11\Label-fast-main\model_annotation\backend'
Start-Process -FilePath 'E:\Anaconda\envs\CFwin11\python.exe' -ArgumentList '-m','uvicorn','main:app','--host','127.0.0.1','--port','8271' -PassThru -WindowStyle Hidden
Pop-Location
```

检查：
- `http://127.0.0.1:8271/options`
- `http://127.0.0.1:8271/models`
- `http://127.0.0.1:8271/history`
然后 Vite 测试端口 5199 + `MODEL_BACKEND_PORT=8271`，检查
`http://127.0.0.1:5199/model-api/options`。

- [ ] **Step 5: 浏览器验证**

- 临时预览页加载 `ModelAnnotationView`，截图确认：
  - 无 Precisor 品牌；
  - 浅色暖纸 + 朱砂配色；
  - 内部侧栏、页头、向导栏正常；
  - 无横向溢出。
- 未登录访问 `/app/model` → 登录页。
- 同时确认文本/混合页面样式未受影响。

- [ ] **Step 6: 可选推理验证**

若时间允许，用已有模型 `728c03e3110c` 调用 `/model/infer` 一段测试文本，确认返回实体。
首次加载 BERT 约数十秒。

- [ ] **Step 7: 清理**

停止测试进程，删除临时预览文件与截图，清理 `model_annotation` 下
`__pycache__`/`.pytest_cache`/`.model_cache`（不删除 models 与 input/output）。
```

---

## 自检清单

- 规格覆盖：七进程、`/model-api`、登录守卫、浅色强制、品牌移除、CSS 作用域、令牌映射、
  模型/数据迁移、启动脚本、文档、验证，均有对应任务。
- 类名映射在 Task 2 与 Task 3 完全一致。
- 无 TBD/TODO/占位步骤。
