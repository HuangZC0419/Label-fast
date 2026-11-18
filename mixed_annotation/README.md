# 混合标注模块（mixed_annotation）

本目录是 数据标注与分类工具 主仓库中的**混合标注**子模块，由三部分组成：

1. **混合标注后端**（`backend/`）：独立 FastAPI 服务，负责项目、实体标签、关系类型、
   文件上传、Markdown 编辑、标注与导出。
2. **OCR Worker**（`ocr_worker/`）：独立 FastAPI 服务，把 PDF / 图片转换为
   Markdown + 图片 + `pages.json`，通过常驻 MinerU API 或 MinerU 子进程执行 OCR。
3. **本地模型**（`models/`）：MinerU / Torch 使用的离线模型缓存，约 2.16 GB，
   随模块目录整体复制，不提交到 git。

主仓库前端通过 Vite 的 `/mix-api` 代理访问本模块后端；本模块不包含前端代码，
也不修改主仓库的 `frontend/`、根 `start.bat` 或主后端路由。

## 目录说明

```
mixed_annotation/
├─ backend/                   混合标注 FastAPI 主应用
│  ├─ app.py                  应用入口
│  ├─ config.py               配置（环境变量 + 项目内默认路径）
│  ├─ routes/                 项目 / 文件 / 标注 / 导出 / 图片路由
│  ├─ services/               业务逻辑
│  ├─ tests/                  后端测试（pytest）
│  └─ data/                   运行数据：projects.json + 各项目目录（不进入 git）
├─ ocr_worker/                OCR Worker（FastAPI）
│  ├─ app.py                  Worker 入口
│  ├─ engine.py               OCR 引擎选择（MinerU-only）
│  ├─ mineru_engine.py        常驻 MinerU API 客户端
│  ├─ mineru_runner.py        MinerU 子进程入口
│  ├─ task_store.py           任务状态存储
│  ├─ models/                 Worker 自带的小型 Paddle 版面模型缓存
│  ├─ tests/                  Worker 测试
│  └─ data/                   OCR 任务临时目录（不进入 git，首次运行自动创建）
├─ models/                    离线模型缓存（不进入 git，约 2.16 GB）
│  ├─ modelscope/             MinerU pipeline 模型（ModelScope 源）
│  ├─ huggingface/            HuggingFace 缓存
│  ├─ torch/                  Torch 预训练权重
│  └─ paddlex/                历史 Paddle 缓存（当前流程不加载）
├─ docs/                      API 与设计说明
├─ samples/                   示例 PDF 与已标注样例
│  ├─ GBT+4423-2020.pdf       国标示例 PDF
│  └─ 零件工艺标注/           示例工程的 Markdown、图片、原始 PDF 与 annotations.jsonl
├─ environment-cfwin11.yml    conda 环境导出
└─ requirements-lock-cfwin11.txt  pip freeze 锁定清单
```

运行期所有路径均可通过环境变量覆盖；未设置时默认指向模块目录内部。

## 运行环境

全部服务统一使用命名 conda 环境 **CFwin11**（Python 3.12）：

```bat
call conda activate CFwin11
```

在 `cmd` 中请使用 `call conda activate`，否则后续命令不会切换到该环境。
本文命令默认在 `mixed_annotation` 目录下执行；也可用 `set "MIX_ROOT=<本目录绝对路径>"`。

先设置模块内路径（每个新窗口都要设置）：

```bat
set "MIX_ROOT=%~dp0"
set "MODELSCOPE_CACHE=%MIX_ROOT%models\modelscope"
set "HF_HOME=%MIX_ROOT%models\huggingface"
set "HF_HUB_CACHE=%MIX_ROOT%models\huggingface\hub"
set "TORCH_HOME=%MIX_ROOT%models\torch"
set "OCR_WORKER_DATA_DIR=%MIX_ROOT%ocr_worker\data"
set "MINERU_API_OUTPUT_ROOT=%MIX_ROOT%ocr_worker\data\mineru_api_output"
set "MINERU_MODEL_SOURCE=modelscope"
set "HF_HUB_DISABLE_SYMLINKS=1"
if not exist "%OCR_WORKER_DATA_DIR%" mkdir "%OCR_WORKER_DATA_DIR%"
if not exist "%MINERU_API_OUTPUT_ROOT%" mkdir "%MINERU_API_OUTPUT_ROOT%"
```

> MinerU 必须用 `python -m mineru.cli.fast_api` 启动，不要使用克隆环境里的
> `mineru-api.exe`（其启动器可能仍指向旧解释器）。

## 单独运行

以下三个服务可在独立窗口中分别启动，关闭窗口即停止对应服务。

### 1) MinerU 常驻 API（默认端口 18000）

```bat
call conda activate CFwin11
python -m mineru.cli.fast_api --host 127.0.0.1 --port 18000
```

健康检查：`http://127.0.0.1:18000/health`。

### 2) OCR Worker（默认端口 8870）

```bat
call conda activate CFwin11
set "MINERU_MODE=auto"
set "MINERU_API_URL=http://127.0.0.1:18000"
set "OCR_WORKER_CONCURRENCY=3"
cd /d "%MIX_ROOT%ocr_worker"
python -m uvicorn app:app --host 0.0.0.0 --port 8870
```

- `MINERU_MODE=auto`：API 可用时优先 API，失败回退 MinerU 子进程；
- `MINERU_MODE=api`：只走常驻 API；
- `MINERU_MODE=subprocess`：只走子进程（每次任务重新加载模型）。
- 常驻 API 不可用时，建议设置 `MINERU_MODE=subprocess` 与
  `OCR_WORKER_CONCURRENCY=1`。

### 3) 混合标注后端（默认端口 3200）

```bat
call conda activate CFwin11
set "OCR_WORKER_URL=http://127.0.0.1:8870"
cd /d "%MIX_ROOT%backend"
python -m uvicorn app:app --host 0.0.0.0 --port 3200
```

接口文档：`http://127.0.0.1:3200/docs`。

### 测试（可选）

```bat
cd /d "%MIX_ROOT%backend"
python -m pytest tests -q
```

## 整文件夹批量导入（夜间识别）

1. 在页面左侧创建或选择项目。
2. 在 Import 面板点击“导入整个文件夹”，选择包含 PDF 的目录
   （支持 PDF / PNG / JPG，递归扫描子目录）。
3. 前端按文件夹内相对路径自然排序，逐个上传；项目内同名文件自动跳过。
4. 上传完成后即可关闭页面，混合标注后端会按导入顺序串行识别（默认 1 个并发）。
5. 第二天打开页面，已完成文件可直接标注；失败文件可在文件列表重试。

说明：

- **上传阶段**需要保持页面打开；**OCR 阶段**完全在后端进行，与浏览器无关。
- 队列状态持久化在 `backend/data/projects/<pid>/files/<fid>/meta.json`；
  服务重启时会把中断的转换重新排队并自动续跑。
- OCR Worker / MinerU 不可用时队列会暂停等待，不会把整批文件连续标记失败。
- 可调环境变量：
  - `MIX_CONVERSION_CONCURRENCY`：队列并发，默认 `1`（严格串行）；
  - `MIX_QUEUE_WORKER_RETRY_SECONDS`：Worker 不可用时的等待秒数，默认 `30`；
  - `MIX_QUEUE_MAX_RETRIES`：单个文件因服务故障的最大自动重试次数，默认 `3`；
  - `MIX_QUEUE_TASK_TIMEOUT_SECONDS`：队列内单个文件的识别超时，默认 `3600`
    秒（1 小时），避免一个卡死任务阻塞整夜；普通单文件上传仍使用 6 小时超时；
  - `MAX_UPLOAD_MB`：单个文件上传上限，默认 `100`。
- 同一 `backend/data` 目录只应运行一个混合标注后端进程；多进程部署会破坏
  队列认领与启动恢复的串行假设。
- `MIX_CONVERSION_CONCURRENCY` 大于 `1` 会并行识别，不再保证严格串行。

## 集成运行

集成到主仓库后，根目录 `start.bat` 负责统一启动**六个服务**：

1. 数据标注与分类工具 主后端（前端 `/api` 代理目标）
2. GB-Fenlei 后端（前端 `/gb-api` 代理目标）
3. 混合标注后端（本模块 `backend/`，前端 `/mix-api` 代理目标）
4. OCR Worker（本模块 `ocr_worker/`）
5. MinerU 常驻 API
6. 前端 Vite dev server

前端通过 `vite.config.ts` 中的 `/mix-api` 代理访问混合标注后端，代理时剥离
`/mix-api` 前缀，例如：

```
浏览器  /mix-api/api/projects
        -> http://127.0.0.1:<MIX_BACKEND_PORT>/api/projects
```

后端端口通过环境变量 `MIX_BACKEND_PORT` 传给前端，不得在前端硬编码主机名或端口。
混合标注后端再通过 `OCR_WORKER_URL` 调用 Worker，Worker 通过 `MINERU_API_URL`
调用 MinerU。各服务端口被占用时应自动顺延，并以 `start.bat` 打印的实际地址为准。

## 生产部署

主仓库的 Docker 镜像**不包含**本模块。生产环境需要：

1. 额外提供混合标注后端、OCR Worker、MinerU API 三个进程（或三个独立容器），
   并挂载本模块的 `models/`、`backend/data/`、`ocr_worker/data/`；
2. 在反向代理（Nginx / Caddy / Traefik 等）上把 `/mix-api/` 转发到混合标注后端，
   转发时去掉 `/mix-api` 前缀，保持与开发环境 Vite 代理一致的行为；
3. 保证 `OCR_WORKER_URL`、`MINERU_API_URL` 指向实际可达的内部地址；
4. 为 `backend/data/` 与 `ocr_worker/data/` 配置持久化卷；
5. 模型目录较大，建议构建镜像时挂载宿主机目录或使用独立数据卷，避免打进镜像。

## 数据与版本控制

以下目录**不进入 git**（已由仓库根 `.gitignore` 排除）：

- `mixed_annotation/models/` — 约 2.16 GB 离线模型缓存；
- `mixed_annotation/backend/data/` — 项目索引、原始文件、Markdown 与标注；
- `mixed_annotation/ocr_worker/data/` — OCR 任务临时目录与 MinerU API 输出。

复制或迁移本模块时请整体复制上述目录；重新 clone 仓库后需要单独获取模型缓存。
