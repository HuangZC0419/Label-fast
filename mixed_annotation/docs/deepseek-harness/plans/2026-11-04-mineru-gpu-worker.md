# MinerU GPU OCR Worker 实现计划

> **For agentic workers:** 按任务逐项实现；本轮不提交 git。

**Goal:** 让 数据标注与分类工具 的 OCR Worker 默认使用本地 MinerU GPU 引擎，保留 PaddleOCR CPU 回退，Worker HTTP 与 `result.zip` 契约不变。

**关键事实（已核查）:**
- MinerU 环境：`E:\Anaconda\envs\MinerUv2\python.exe`，Python 3.12，`torch 2.5.1+cu121`，`get_device() == "cuda"`，显卡 RTX 4090 D。
- MinerU 项目入口：`H:\Git\1CF_win11\MinerU\backend\mineru_runner.py`，用 `mineru.cli.common.do_parse`，输出 `<stem>/ocr/<stem>.md`、`images/`、`<stem>_content_list.json`、`<stem>_middle.json`。
- content_list 项含 `type/text/bbox/page_idx/table_body/img_path`；middle.json 的 `pdf_info[].page_size` 为 `[width,height]`。
- 现有 Worker 在 CF 环境（Python 3.9 + PaddleOCR）运行；不要改主后端/前端。

---

## Task 1: 移植 runner

**Files:** 新建 `ocr_worker/mineru_runner.py`

- 复制 `H:\Git\1CF_win11\MinerU\backend\mineru_runner.py`。
- 保留 `apply_quality_overrides`、`configure_model_source`、`do_parse` 参数。
- 新增 `--device` 参数：若非空，设置 `os.environ["MINERU_DEVICE_MODE"]=device`。
- 在启动日志中打印 `backend/parse_method/device/high_accuracy`。
- 不修改 MinerU 项目原文件。

## Task 2: 新增 mineru_engine

**Files:** 新建 `ocr_worker/mineru_engine.py`

公开函数：

```python
def mineru_available() -> tuple[bool, str]
def select_engine(override: str | None = None) -> str  # "mineru" | "paddle"
def convert_with_mineru(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback,
) -> ConversionResult
def build_pages_from_content_list(markdown: str, content_list: list[dict], middle: dict) -> dict
```

要求：
- 子进程命令：`[MINERU_PYTHON, MINERU_RUNNER, "--input", source, "--output", task_dir/"mineru_out", "--backend", MINERU_BACKEND, "--language", MINERU_LANGUAGE, "--parse-method", MINERU_PARSE_METHOD, "--formula", ..., "--table", ..., "--high-accuracy", ...]`
- 环境：`MINERU_DEVICE_MODE`（若配置）、`PYTHONIOENCODING=utf-8`、`PYTHONNOUSERSITE=1`、`MINERU_MODEL_SOURCE`（若配置）。
- 流式读取 stdout/stderr，按关键字推进进度：layout 20、ocr 45、table 65、formula 75、markdown 90；无关键字时按已用时间缓慢推进，最高 90；完成 100。
- 超时：`MINERU_TIMEOUT_SECONDS`（默认 3600），超时 terminate/kill 并报错。
- 失败时抛出 RuntimeError，带最后 2000 字符日志。
- 输出发现：递归找第一个 `*.md`、同级 `images/`、`*_content_list.json`、`*_middle.json`。
- 归一化到 `task_dir/out/`：
  - `result.md` = MinerU markdown
  - `images/` = 复制 MinerU images 目录内容（保持文件名，Markdown 引用 `images/...`）
  - `pages.json` = `build_pages_from_content_list(...)` 生成
  - 返回 `ConversionResult(page_count, markdown_chars, elapsed_seconds, warnings, engine="mineru")`
- `build_pages_from_content_list`：
  - 逐项按顺序在 markdown 中查找 marker：text→`text`，image→`img_path`，table→`table_body` 或 `img_path`，equation→`text`；先精确查找，失败时取前 30 字/去空白再查找；找不到跳过。
  - 记录每页第一个命中位置，生成每页 `{page,start,end,width,height,continuation:false,empty}`；下一页起点作为上一页 end；末页 end=len(markdown)。
  - 命中率过低（<30%）时按页数均分 markdown 长度兜底。
  - 页面尺寸取 middle.json `pdf_info[page_idx].page_size`，缺失为 0。
- 不导入 paddleocr；该模块必须能在 CF Python 3.9 下轻量导入。

## Task 3: 配置与引擎选择

**Files:** 修改 `ocr_worker/config.py`、`ocr_worker/convert.py`

config 增加：
```python
OCR_ENGINE = os.getenv("OCR_ENGINE", "auto").strip().lower()  # auto|mineru|paddle
MINERU_PYTHON = Path(os.getenv("MINERU_PYTHON", r"E:\Anaconda\envs\MinerUv2\python.exe"))
MINERU_RUNNER = Path(os.getenv("MINERU_RUNNER", str(Path(__file__).parent / "mineru_runner.py")))
MINERU_BACKEND = os.getenv("MINERU_BACKEND", "pipeline")
MINERU_LANGUAGE = os.getenv("MINERU_LANGUAGE", "ch")
MINERU_PARSE_METHOD = os.getenv("MINERU_PARSE_METHOD", "auto")
MINERU_DEVICE_MODE = os.getenv("MINERU_DEVICE_MODE", "")
MINERU_HIGH_ACCURACY = _env_flag("MINERU_HIGH_ACCURACY", False)
MINERU_TIMEOUT_SECONDS = int(os.getenv("MINERU_TIMEOUT_SECONDS", "3600"))
MINERU_MODEL_SOURCE = os.getenv("MINERU_MODEL_SOURCE", "")
```

convert.py：
- 现有 Paddle 流程改名为 `_convert_with_paddle(...)`。
- `convert_document(...)` 先 `select_engine()`：
  - `mineru` → 调用 MinerU；失败且模式为 `auto` 时记录 warning 并回退 Paddle。
  - `paddle` → 原流程。
  - `auto` 且 MinerU 文件不存在 → Paddle。
- `ConversionResult` 增加 `engine: str = "paddle"`（放在既有字段后，保持兼容）。

## Task 4: Worker API 与启动脚本

**Files:** 修改 `ocr_worker/app.py`、`start.bat`

app.py：
- `/health` 增加 `engine`（实际选择）、`mineru_available`、`mineru_python`、`mineru_runner`。
- `/convert` 增加可选 `engine: str = Form("")`，传入 options；`convert_document(engine=...)` 支持覆盖。
- 日志增加 engine 与耗时。

start.bat：
```bat
set "MINERU_PYTHON=E:\Anaconda\envs\MinerUv2\python.exe"
set "OCR_ENGINE=auto"
set "MINERU_DEVICE_MODE=cuda"
set "MINERU_BACKEND=pipeline"
set "MINERU_LANGUAGE=ch"
set "MINERU_PARSE_METHOD=auto"
set "MINERU_HIGH_ACCURACY=0"
set "MINERU_RUNNER=%~dp0ocr_worker\mineru_runner.py"
```
在 Worker 的 `start ... cmd /k` 命令内也设置这些变量；若 `%MINERU_PYTHON%` 不存在则 `OCR_ENGINE=paddle` 并打印提示。更新提示文字为“Win11 默认 MinerU GPU，失败回退 Paddle CPU”。

## Task 5: 测试与文档

**Files:** 新建 `ocr_worker/tests/test_mineru_pages.py`、`test_mineru_select.py`；修改 `README.md`、`docs/设计说明.md`

- 测试 pages 生成：3 页、表格/图片/text 混合、缺失 middle、命中率低兜底。
- 测试 select_engine：mode=paddle/mineru/auto + 文件存在/不存在（用 mock/patch）。
- 文档写清 MinerUv2 环境、环境变量、GPU/高精度开关、模型缓存与回退行为。

## 验证

```bash
cd ocr_worker && python -m unittest discover -s tests -v
cd backend && conda run -n CF python -m unittest discover -s tests -v
```

真实 GPU 转换（另做）：
- 用 `ocr_worker/mineru_engine.convert_with_mineru` 处理 `GBT+4423-2020.pdf`，确认 `result.md/images/pages.json`，记录耗时。
- 对比 `OCR_ENGINE=paddle` 的耗时（可选）。
