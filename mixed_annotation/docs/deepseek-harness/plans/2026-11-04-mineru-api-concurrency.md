# MinerU 常驻 API 与并发吞吐实现计划

**目标：** 把 Worker 从“每任务启动 MinerU 子进程”切换为“调用常驻 `mineru-api`”，模型只加载一次，Worker 支持 3 并发；保留子进程回退。

**实测依据（RTX 4090 D / 16 页国标 PDF）：**

| 模式 | 任务数 | 总耗时 | 吞吐 |
|---|---|---|---|
| 子进程单任务 | 1 | 44s | 0.023 jobs/s |
| 子进程 2 并发 | 2 | 66s | 0.030 jobs/s |
| 子进程 3 并发 | 3 | 99s | 0.030 jobs/s |
| 常驻 API 3 并发（预热后） | 3 | 25s | 0.12 jobs/s |
| 常驻 API 6 并发（预热后） | 6 | 46s | 0.13 jobs/s |

结论：默认 API 并发 3（延迟最低、吞吐已接近上限）；6 并发作为多系统重载选项。首次任务需要加载模型约 40s，之后 3 并发约 25s。

**API 契约（`mineru-api`，已实测）：**
- `GET /health` → `{"status":"healthy"}`
- `POST /tasks` multipart：
  - `files`：PDF/图片文件
  - `lang_list=ch`
  - `backend=pipeline`
  - `parse_method=auto`
  - `formula_enable=false`
  - `table_enable=true`
  - `return_md=true`
  - `return_middle_json=true`
  - `return_content_list=true`
  - `return_images=true`
  - `response_format_zip=true`
  - `return_original_file=false`
  - `start_page_id=0`
  - `end_page_id=99999`
- 返回 `{"task_id": "..."}`；`GET /tasks/{id}` 状态 `pending/processing/completed/failed`；`GET /tasks/{id}/result` 返回 ZIP（含 md、images、content_list、middle）。

**关键环境：**
- 服务：`E:\Anaconda\envs\MinerUv2\Scripts\mineru-api.exe`
- 端口：18000（避免与 8870/3200/5174 冲突）
- `MINERU_DEVICE_MODE=cuda`
- `MINERU_MODEL_SOURCE=modelscope`
- `HF_HUB_DISABLE_SYMLINKS=1`（避免首次并发 WinError 1314）
- `MINERU_API_MAX_CONCURRENT_REQUESTS=3`
- `MINERU_API_OUTPUT_ROOT=%LOCALAPPDATA%\LabelFastMixed\mineru_api_output`
- 当前已有一个测试 API 服务在 18000 运行（max=6，模型已预热），可直接用于联调；不要重复启动占用端口。

---

## Task 1: 配置

修改 `ocr_worker/config.py`：

```python
MINERU_MODE = os.getenv("MINERU_MODE", "auto").strip().lower()  # auto|api|subprocess
MINERU_API_URL = os.getenv("MINERU_API_URL", "http://127.0.0.1:18000").rstrip("/")
MINERU_API_TIMEOUT_SECONDS = int(os.getenv("MINERU_API_TIMEOUT_SECONDS", "3600"))
MINERU_API_POLL_SECONDS = float(os.getenv("MINERU_API_POLL_SECONDS", "1.0"))
MINERU_API_HEALTH_TIMEOUT_SECONDS = float(os.getenv("MINERU_API_HEALTH_TIMEOUT_SECONDS", "2.0"))
OCR_WORKER_CONCURRENCY = int(os.getenv("OCR_WORKER_CONCURRENCY", "0"))  # 0=auto
```

保留现有子进程配置。`requirements.txt` 增加 `httpx>=0.27`（CF 环境已有 0.28.1）。

## Task 2: mineru_engine 增加 API 传输

修改 `ocr_worker/mineru_engine.py`：

- `api_available() -> tuple[bool, str]`：GET `{MINERU_API_URL}/health`，2s 超时，缓存 2s；返回健康状态与原因。
- `mineru_ready() -> tuple[bool, str]`：子进程可用或 API 可用。
- `select_engine` 改用 `mineru_ready()`；显式 `mineru` 不可用仍返回 `mineru` 让转换报明确错误。
- `convert_with_mineru`：
  ```python
  mode = config.MINERU_MODE
  if mode != "subprocess" and api_available()[0]:
      try:
          return _convert_via_api(...)
      except Exception as exc:
          if mode == "api":
              raise
          logger.warning("MinerU API 失败，回退子进程：%s", exc)
  return _convert_via_subprocess(...)
  ```
- `_convert_via_api`：
  - `httpx.Client(timeout=MINERU_API_TIMEOUT_SECONDS)`
  - 提交 `POST /tasks`，轮询 `GET /tasks/{id}`，状态失败时抛出 `error`。
  - 进度：5 启动 → 10 + 已用时间（最高 90）→ 95 下载 → 100。
  - `GET /tasks/{id}/result` 保存 ZIP；安全解压到 `task_dir/mineru_out`（拒绝 `..`/绝对路径/符号链接）。
  - 复用现有 `_discover_outputs`、`_read_json`、`_copy_images`、`build_pages_from_content_list`、`write_pages`、`build_result_zip`，归一化为 `out/result.md`、`out/images/`、`out/pages.json`、`result.zip`。
  - 返回 `ConversionResult(..., engine="mineru-api")`。
- 子进程逻辑改名为 `_convert_via_subprocess`，`engine="mineru"`。
- 新增纯函数 `build_api_form_data(enable_table, enable_formula)` 便于单测。
- 不要导入 paddleocr；httpx 延迟导入。

## Task 3: Worker 并发

修改 `ocr_worker/app.py`：

- `lifespan` 计算并发：
  ```python
  configured = config.OCR_WORKER_CONCURRENCY
  if configured > 0:
      concurrency = configured
  else:
      concurrency = 3 if mineru_engine.api_available()[0] else 1
  _semaphore = asyncio.Semaphore(max(1, concurrency))
  ```
  启动日志打印并发数与 MinerU 传输方式。
- `/health` 增加：`mineru_mode`、`mineru_api_available`、`mineru_api_url`、`worker_concurrency`。
- 其他任务流程不变；多个任务由 `_semaphore` 控制。

## Task 4: start.bat

修改 `start.bat`：

- 新增第 0 个窗口启动 MinerU API（在 Worker 之前）：
  ```bat
  set "MINERU_API_PYTHON=E:\Anaconda\envs\MinerUv2\Scripts\mineru-api.exe"
  set "MINERU_API_URL=http://127.0.0.1:18000"
  set "MINERU_API_OUTPUT_ROOT=%LOCALAPPDATA%\LabelFastMixed\mineru_api_output"
  set "MINERU_API_MAX_CONCURRENT_REQUESTS=3"
  set "MINERU_MODEL_SOURCE=modelscope"
  set "HF_HUB_DISABLE_SYMLINKS=1"
  set "MINERU_DEVICE_MODE=cuda"
  ```
  启动窗口，然后用 PowerShell 轮询 `/health` 最多 20s；失败则 `MINERU_MODE=subprocess`、`OCR_WORKER_CONCURRENCY=1`。
- Worker 窗口增加 `MINERU_MODE=auto`、`MINERU_API_URL=%MINERU_API_URL%`、`OCR_WORKER_CONCURRENCY=3`。
- 如果 API exe 不存在，跳过 API 窗口并回退子进程。
- 更新提示文字为“4 个窗口”、API 端口 18000、首次任务加载模型约 40s。
- 保留原有主后端/前端启动命令。

## Task 5: 测试与文档

- 更新 `ocr_worker/tests/test_mineru_select.py`：patch `mineru_ready`/`api_available`，覆盖 api/subprocess/auto。
- 新增 `ocr_worker/tests/test_mineru_api.py`：`build_api_form_data` 字段、安全解压拒绝路径穿越、状态失败抛错（用 mock）。
- 更新 `README.md`、`docs/设计说明.md`：常驻 API 架构、实测吞吐、并发开关、首次预热、`MINERU_MODE`、`MINERU_API_*`、6 并发选项、回退。
- 运行：
  ```bash
  cd ocr_worker && python -m unittest discover -s tests -v
  cd backend && conda run -n CF python -m unittest discover -s tests -v
  ```

## Task 6: 联调验证

使用已运行的 18000 API：
- 用 `MINERU_MODE=api` 调用 `mineru_engine.convert_with_mineru` 处理 `GBT+4423-2020.pdf`，确认 `result.md/images/pages.json` 与 `result.zip`。
- 3 个线程并发调用，确认总耗时接近 25s（模型已预热）、结果互不串扰。
- 检查 `/health` 的 api/worker_concurrency 字段。
- 报告真实耗时与输出。
