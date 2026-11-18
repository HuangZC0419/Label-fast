# Win7 离线部署：FastAPI 托管前端 dist —— 设计文档

- 日期：2026-10-26
- 状态：已实现并验证（目标 Win7 实机冒烟待用户执行）
- 范围：前端静态部署能力 + Win7 启动脚本 + Python 3.8 兼容性收敛
- 不在范围：降级 Vite/Vue/TypeScript、重写前端、改造后端业务逻辑

## 1. 背景

项目前端使用 Vue 3.5 + Vite 6。Vite 6 要求 Node 18+，而目标部署环境是 Windows 7：

- Win7 官方支持的最后一个 Node.js 版本是 13.6.0（Node 14+ 不再保证 Win7 可运行）；
- Win7 官方支持的最后一个 Python 版本是 3.8.10；
- Win7 上最后一个 Chrome/Edge 内核版本是 109。

用户已确认：**只需要在 Win7 上部署运行，不需要在 Win7 上开发或打包前端**。因此不降级前端工具链，改为：

1. 在任意 Node 18+ 机器上构建一次 `frontend/dist`；
2. 把 `dist` 随项目拷贝到 Win7；
3. 由 FastAPI 同时提供 `/api/*` 和前端静态文件；
4. Win7 上只运行 Python 3.8 + uvicorn，**完全不安装 Node**。

这样「Node 10 能不能跑」在部署机上是伪命题：部署机不需要 Node。

## 2. 现状确认

`backend/main.py` 已经具备静态托管能力：

- `backend/main.py:57-58`：`PROJECT_ROOT` 与 `FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"`；
- `backend/main.py:575-592`：`GET /{full_path:path}` 作为 SPA 回退，优先返回 `dist` 下的真实文件，找不到则返回 `dist/index.html`；
- `backend/main.py:577-578`：`/api` 前缀不会被静态回退吞掉；
- `backend/main.py:579-585`：`dist/index.html` 不存在时返回明确的构建提示。

因此本方案不需要新建静态服务器，只需补齐产物、MIME/缓存细节、启动脚本、Python 3.8 依赖约束和文档。

## 3. 运行架构

```
构建机（Node 18+，任意系统）                Win7 部署机（Python 3.8.10）
┌──────────────────────────┐            ┌──────────────────────────────────┐
│ cd frontend              │            │ start-win7.bat                   │
│ npm ci                   │            │  └─ uvicorn main:app :8000        │
│ npm run build            │  拷贝项目   │       ├─ /api/*  → FastAPI 接口   │
│ → frontend/dist          │ ─────────► │       └─ 其它   → frontend/dist   │
└──────────────────────────┘            │ 浏览器 Chrome/Edge 109            │
                                        └──────────────────────────────────┘
```

- 访问地址：`http://127.0.0.1:8000`（用户已确认只监听本机回环地址）。
- 同源访问，不涉及 CORS；现有 `ALLOWED_ORIGINS` 仅用于 5173 开发模式，无需修改。
- 开发模式 `start.bat` 保持原样（后端 8000 + Vite 5173）。

## 4. 详细改动

### 4.1 `backend/main.py`：静态文件 MIME 与缓存

**问题 1：Windows 的 MIME 推断不可靠。**
Starlette 的 `FileResponse` 未指定 `media_type` 时会使用 Python `mimetypes.guess_type()`。Windows 上该函数会读取注册表，`.js` 可能被推断为 `text/plain`，浏览器会以「Expected a JavaScript module script」为由拒绝加载 ES module，页面白屏。

**改法：**

- 新增模块级常量 `STATIC_MEDIA_TYPES`，至少覆盖：
  - `.html` → `text/html; charset=utf-8`
  - `.js` / `.mjs` → `text/javascript; charset=utf-8`
  - `.css` → `text/css; charset=utf-8`
  - `.json` / `.map` → `application/json`
  - `.svg` → `image/svg+xml`
  - `.png` / `.jpg` / `.jpeg` / `.gif` / `.webp` → 对应 `image/*`
  - `.ico` → `image/x-icon`
  - `.woff` → `font/woff`，`.woff2` → `font/woff2`，`.ttf` → `font/ttf`
  - `.txt` → `text/plain; charset=utf-8`
- `spa_fallback` 返回 `FileResponse` 时显式传入 `media_type`；未知后缀回退到现有 `mimetypes` 行为。

**问题 2：缓存策略缺失。**

- `dist/index.html` 设置 `Cache-Control: no-cache`，保证前端重新构建后用户能拿到新入口；
- `dist/assets/*` 是 Vite 带内容哈希的文件，设置 `Cache-Control: public, max-age=31536000, immutable`；
- 其余文件不额外设置缓存头。

**问题 3：缺失的静态资源会返回 200 + index.html。**
当前逻辑对任何不存在的路径都返回 `index.html`。如果浏览器请求一个不存在的 `assets/xxx.js`，会拿到 HTML 内容并被当成 JS 解析，报错信息具有误导性。

**改法：** 当 `full_path` 带文件后缀（`Path(full_path).suffix` 非空）且文件不存在时，返回 404 `ApiError("NOT_FOUND", ...)`；只有无后缀路径才回退到 `index.html`。`/api` 前缀的 404 行为保持不变。

**安全约束：** 保留现有的 `FRONTEND_DIST.resolve() in candidate.parents` 路径穿越校验，不得放宽。

### 4.2 `backend/requirements.txt`：Python 3.8 依赖收敛

现状依赖中有两个包在 Python 3.8 上会解析到不兼容的新版本：

- `uvicorn` 0.34.0+ 要求 Python ≥ 3.9；
- `python-multipart` 0.0.21+ 要求 Python ≥ 3.10。

改为环境标记，保证 3.8 安装结果确定：

```text
fastapi>=0.110,<0.116
uvicorn>=0.29,<0.34; python_version < "3.9"
uvicorn>=0.29,<0.35; python_version >= "3.9"
python-multipart>=0.0.9,<0.0.21; python_version < "3.9"
python-multipart>=0.0.9; python_version >= "3.9"
openpyxl>=3.1,<4
```

传递依赖由 pip 按 `Requires-Python` 自动回退：

- `starlette` 0.45.0+ 要求 ≥ 3.9，3.8 上会选 0.44.x（已验证 0.44.0 支持 3.8）；
- `pydantic` 2.11.0+ 要求 ≥ 3.9，3.8 上会选 2.10.x（已验证 2.10.6 支持 3.8）。

后端源码已核查：未使用 `match` 语句、`list[...]` 内置泛型、`X | None`、`removeprefix`、`functools.cache` 等 3.9+ 语法/API，Python 3.8 可以解析。

### 4.3 新增 `start-win7.bat`

职责：在 Win7 上一键启动「后端 + 前端静态页」，不触碰 Node/Vite。

流程：

1. `cd /d "%~dp0"`；
2. 检查 `frontend\dist\index.html` 是否存在，不存在则提示「请在 Node 18+ 机器上执行 npm run build 后拷贝 dist」并退出；
3. 按 `start.bat` 相同的方式定位 conda（PATH 或 `F:\anaconda2024.06\condabin\conda.bat`）并激活 `CF`；
4. 检查 `fastapi, uvicorn, openpyxl, multipart` 是否已安装，缺失则 `pip install -r backend\requirements.txt`；
5. 新窗口启动：
   `python -m uvicorn main:app --host 127.0.0.1 --port 8000`
6. 用 Python（而非 PowerShell）轮询 `http://127.0.0.1:8000/api/health`，最多等 60 秒。原因：Win7 自带 PowerShell 2.0，`Invoke-WebRequest` 不可用；Python 3.8 的 `urllib.request` 一定可用；
7. 健康检查通过后 `start "" "http://127.0.0.1:8000"`；超时则打印后端窗口的错误提示并退出。

说明：`start.bat` 不做修改，继续用于开发模式。

### 4.4 `README.md`：新增「Win7 离线部署」章节

内容包括：

- 构建机要求：Node 18+；
- 构建命令：`cd frontend && npm ci && npm run build`；
- 需要拷贝的内容：整个项目目录（至少包含 `backend/`、`frontend/dist/`、`start-win7.bat`）；
- Win7 要求：Python 3.8.10、conda 环境 `CF`、Chrome/Edge 109 或 Firefox ESR 115；
- Win7 命令：`pip install -r backend\requirements.txt`，然后双击 `start-win7.bat`；
- 明确写出：**Win7 上不需要安装 Node**；
- 可选：如需局域网访问，把 `--host 127.0.0.1` 改为 `--host 0.0.0.0` 并放行防火墙（默认不开启）。

### 4.5 生成 `frontend/dist/`

- 在构建机执行 `npm ci && npm run build`；
- 产物随项目交付，Win7 上无需重新构建；
- `dist` 不手工编辑，后续前端变更必须在 Node 18+ 机器重新构建。

## 5. 发布流程

1. 构建机：`cd frontend && npm ci && npm run build`；
2. 确认 `frontend/dist/index.html` 存在；
3. 拷贝整个项目目录到 Win7；
4. Win7：`conda activate CF`，`pip install -r backend\requirements.txt`（首次）；
5. 双击 `start-win7.bat`；
6. 浏览器访问 `http://127.0.0.1:8000`。

## 6. 验证计划

### 6.1 构建

- `npm ci` 成功；
- `npm run build` 成功，生成 `dist/index.html` 与 `dist/assets/*.js|*.css`。

### 6.2 静态托管（本机 Python 3.9 即可）

启动 `python -m uvicorn main:app --host 127.0.0.1 --port 8000` 后验证：

| 请求 | 期望 |
|---|---|
| `GET /` | 200，`text/html` |
| `GET /assets/<真实文件>.js` | 200，`text/javascript` |
| `GET /assets/<不存在的文件>.js` | 404，不再返回 index.html |
| `GET /api/health` | 200，JSON |
| 上传 → 分析 → 分类 → 导出 | 全流程走通（复用 `backend/tests/`） |

### 6.3 Python 3.8 兼容性

- 语法：用 Python 3.8 解释器对 `backend/` 执行 `compileall`；
- 依赖：用 `pip download -r backend/requirements.txt --python-version 38 --only-binary=:all:` 验证所有依赖都有 3.8 可用版本且可解析；
- 本机没有 Win7，最终需在目标 Win7 机器上做一次人工冒烟测试（启动 + 四步流程）。

### 6.4 浏览器

- Vite 6 默认构建目标为 Chrome 107，Chrome/Edge 109 可运行；
- 前端源码未使用 Chrome 110+ 专有 JS API/CSS 特性（已核查）；
- 不涉及 IE11。

## 7. 风险与回滚

| 风险 | 影响 | 应对 |
|---|---|---|
| Python 3.8 已 EOL | 依赖只能锁在旧版本，安全更新有限 | 仅内网使用；记录版本约束 |
| Win7 / Chrome 109 已 EOL | 浏览器安全问题 | 仅内网使用 |
| dist 未随包交付 | 页面 404 并提示构建 | `start-win7.bat` 启动前检查并明确报错 |
| 前端后续变更 | Win7 上无法重建 | 文档写明必须在 Node 18+ 机器重建 dist |
| MIME 推断异常 | 白屏、模块加载失败 | 显式 `STATIC_MEDIA_TYPES` |

回滚：删除 `start-win7.bat`、还原 `backend/main.py` 与 `requirements.txt` 的改动、删除 `frontend/dist` 即可；开发模式 `start.bat` 始终不受影响。

## 8. 验收标准

1. Win7（Python 3.8.10 + conda CF）上双击 `start-win7.bat` 能打开页面；
2. 页面四步流程（数据体检 → 待分类目录 → 执行分类 → 结果复核/导出）全部可用；
3. `/assets/*.js` 响应头为 JavaScript MIME；
4. 不存在的静态文件返回 404；
5. 部署机不需要 Node；
6. 原有开发模式 `start.bat` 行为不变。

## 9. 实现与验证结果（2026-10-26）

| 项目 | 结果 |
|---|---|
| 前端构建（Node 22.15.0，Vite 6.4.5） | `vue-tsc --noEmit` 与 `vite build` 通过，生成 `dist/index.html` + `assets/index-*.js|css` |
| 静态托管 | `/` → 200 `text/html`；`/assets/*.js` → 200 `text/javascript`；`/assets/*.css` → 200 `text/css` |
| 缓存头 | `index.html` → `no-cache`；`assets/*` → `public, max-age=31536000, immutable` |
| 缺失资源 | `/assets/nope.js` → 404（不再返回 index.html） |
| SPA 回退 | `/some-route` → 200 `text/html` |
| 后端测试 | Python 3.9.25：52/52 通过；Python 3.8.10：52/52 通过 |
| Python 3.8 依赖解析 | fastapi 0.115.14 / uvicorn 0.33.0 / starlette 0.44.0 / pydantic 2.10.6 / python-multipart 0.0.20 / openpyxl 3.1.5，均有 cp38 或 py3 轮子 |
| 浏览器端到端 | Chrome headless 访问后 Vue 应用成功挂载并渲染侧边栏 |
| `start-win7.bat` 干跑 | dist 检查、conda CF 激活、Python/依赖检查、健康轮询均按预期执行，退出码 0 |
| Win7 实机 | 待用户在目标机器执行一次冒烟测试 |
