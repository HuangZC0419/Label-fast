"""MinerU GPU 引擎适配器。

Worker 与 MinerU 都运行在项目唯一的 ``CFwin11`` 环境（Python 3.12 + CUDA +
PaddleOCR）；API/子进程都使用同一解释器与项目内 ``models\\`` 缓存。本模块只
依赖标准库（``httpx`` 延迟导入），保证可以轻量导入（不导入
``paddleocr`` / ``mineru`` / ``torch``）。

两种传输方式：

- **常驻 API（推荐）**：HTTP 调用独立运行的 ``mineru-api``，模型只加载一次，
  支持 Worker 多任务并发；
- **子进程（回退）**：调用 ``mineru_runner.py``，每次任务重新加载模型。

输出契约与 Paddle 流程保持一致：``task_dir/out/result.md``、``images/``、
``pages.json`` 以及 ``task_dir/result.zip``。
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import stat
import subprocess
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Optional

import config

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, Optional[int]], None]

_ENGINES = {"auto", "mineru", "paddle"}

# MinerU pipeline 日志关键字 -> 进度百分比。取所有命中的最大值，
# 保证进度只前进不后退。
_PROGRESS_KEYWORDS: tuple[tuple[str, int], ...] = (
    ("layout", 20),
    ("ocr", 45),
    ("table", 65),
    ("formula", 75),
    ("markdown", 90),
)

# 命中率低于该值时，说明 content_list 与 Markdown 对不上（例如 MinerU
# 版本变更导致 marker 形式变化），改用按页数均分的兜底映射。
_MIN_HIT_RATE = 0.30

# 失败时附带日志的最大长度。
_LOG_TAIL_CHARS = 2000

# ---------------------------------------------------------------------------
# 常驻 mineru-api 常量
# ---------------------------------------------------------------------------

_API_HEALTH_CACHE_SECONDS = 2.0
_API_COMPLETED_STATUSES = {"completed", "success", "succeeded", "done"}
_API_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}
_API_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# /health 探测结果缓存；避免健康检查与每个任务重复发起网络请求。
_api_health_lock = threading.Lock()
_api_health_cache: tuple[float, bool, str] | None = None


def _noop_progress(_: int, __: str, ___: int | None) -> None:
    return


# ---------------------------------------------------------------------------
# 引擎可用性与选择
# ---------------------------------------------------------------------------


def mineru_available() -> tuple[bool, str]:
    """检查 MinerU 子进程所需的 Python 与 runner 是否存在。"""

    python = config.MINERU_PYTHON
    runner = config.MINERU_RUNNER
    if not python.is_file():
        return False, f"MinerU Python 不存在：{python}"
    if not runner.is_file():
        return False, f"MinerU runner 不存在：{runner}"
    return True, "MinerU GPU 可用"


def _import_httpx():
    """延迟导入 httpx。

    Worker 测试环境不一定安装 httpx；延迟导入保证本模块在没有 httpx 时
    仍可导入，API 相关功能安全返回不可用。
    """

    try:
        import httpx  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "未安装 httpx，无法使用 MinerU 常驻 API（pip install 'httpx>=0.27'）"
        ) from exc
    return httpx


def _probe_api() -> tuple[bool, str]:
    """实际探测 ``MINERU_API_URL/health``，不读写缓存。"""

    try:
        httpx = _import_httpx()
    except RuntimeError as exc:
        return False, str(exc)

    url = f"{config.MINERU_API_URL}/health"
    try:
        with httpx.Client(
            timeout=config.MINERU_API_HEALTH_TIMEOUT_SECONDS
        ) as client:
            response = client.get(url)
    except Exception as exc:  # 连接拒绝、超时、代理错误等
        return False, f"MinerU API 不可达（{url}）：{exc}"

    if response.status_code != 200:
        return False, f"MinerU API 健康检查失败：HTTP {response.status_code}"
    return True, f"MinerU API 可用：{config.MINERU_API_URL}"


def api_available(force: bool = False) -> tuple[bool, str]:
    """返回常驻 `mineru-api` 是否可用及原因（结果缓存 2 秒）。

    ``force=True`` 跳过缓存。连接失败与未安装 httpx 都返回 ``False``，
    由调用方决定回退子进程还是直接报错。
    """

    global _api_health_cache

    now = time.monotonic()
    with _api_health_lock:
        cached = _api_health_cache
    if (
        not force
        and cached is not None
        and now - cached[0] < _API_HEALTH_CACHE_SECONDS
    ):
        return cached[1], cached[2]

    result = _probe_api()
    with _api_health_lock:
        _api_health_cache = (time.monotonic(), result[0], result[1])
    return result


def mineru_ready() -> tuple[bool, str]:
    """MinerU 是否可用：子进程就绪或常驻 API 健康。"""

    subprocess_ok, subprocess_reason = mineru_available()
    if subprocess_ok:
        return True, subprocess_reason
    api_ok, api_reason = api_available()
    if api_ok:
        return True, api_reason
    return False, f"{subprocess_reason}；{api_reason}"


def select_engine(override: str | None = None) -> str:
    """返回实际使用的引擎：``"mineru"`` 或 ``"paddle"``。

    - ``override`` 为显式请求（``/convert`` 的 ``engine`` 表单字段），
      非法值抛 ``ValueError``，由 API 层转成 400。
    - 未提供 ``override`` 时读取 ``OCR_ENGINE``；非法配置降级为 ``auto``，
      避免一个拼写错误让 Worker 无法启动。
    - 显式 ``mineru`` 不因文件缺失而静默降级：让转换失败并返回明确错误，
      避免用户以为在用 GPU。``auto`` 才自动回退 Paddle。
    """

    if override is not None and str(override).strip():
        mode = str(override).strip().lower()
        if mode not in _ENGINES:
            raise ValueError(
                f"不支持的 OCR 引擎：{override!r}（可选 auto/mineru/paddle）"
            )
    else:
        # None 或空字符串都表示“未指定”，使用 OCR_ENGINE 配置。
        mode = (config.OCR_ENGINE or "").strip().lower() or "auto"
        if mode not in _ENGINES:
            logger.warning(
                "OCR_ENGINE=%s 不合法，已按 auto 处理（可选 auto/mineru/paddle）",
                config.OCR_ENGINE,
            )
            mode = "auto"

    if mode == "paddle":
        return "paddle"

    available, reason = mineru_ready()
    if not available:
        logger.warning(
            "MinerU 不可用：%s；PaddleOCR 回退已禁用（中文项目路径限制）",
            reason,
        )
    # auto / mineru 都返回 mineru：不可用时由转换层给出明确错误，
    # 不再静默回退到无法读取中文路径的 PaddleOCR。
    return "mineru"


# ---------------------------------------------------------------------------
# content_list -> pages.json
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _page_count(content_list: list[dict], middle: dict) -> int:
    indexes = [
        int(item["page_idx"])
        for item in content_list
        if isinstance(item, dict) and isinstance(item.get("page_idx"), int)
    ]
    item_pages = max(indexes) + 1 if indexes else 0
    pdf_info = middle.get("pdf_info") if isinstance(middle, dict) else None
    middle_pages = len(pdf_info) if isinstance(pdf_info, list) else 0
    return max(item_pages, middle_pages, 1)


def _markers_for_item(item: dict) -> list[str]:
    """按优先级返回可用于在 Markdown 中定位该项的候选字符串。"""

    kind = str(item.get("type") or "").strip().lower()
    if kind in {"text", "equation"}:
        text = str(item.get("text") or "").strip()
        return [text] if text else []
    if kind == "image":
        path = str(item.get("img_path") or "").strip()
        return [path] if path else []
    if kind == "table":
        # MinerU 会把表格同时输出为 table_body（HTML）与裁剪图；不同版本
        # 的 Markdown 可能只保留其中一种引用，因此两个都尝试。
        candidates = [
            str(item.get("table_body") or "").strip(),
            str(item.get("img_path") or "").strip(),
        ]
        return [value for value in candidates if value]
    candidates = [
        str(item.get("text") or "").strip(),
        str(item.get("img_path") or "").strip(),
        str(item.get("table_body") or "").strip(),
    ]
    return [value for value in candidates if value]


def _find_marker(markdown: str, marker: str, start: int = 0) -> int:
    """在 Markdown 中从 ``start`` 起定位内容项。

    先精确匹配，再尝试去空白后的前缀。``start`` 取上一项命中位置，
    避免封面/页眉中重复出现的短文本把后续页面错误地拉回文档开头。
    """

    if not marker:
        return -1
    position = markdown.find(marker, max(0, start))
    if position >= 0:
        return position

    # 表格/公式等长文本在不同版本里可能被换行或空白重排，这里用前 30
    # 个字符的“折叠空白”变体兜底。
    collapsed = " ".join(marker.split())[:30]
    if collapsed:
        position = markdown.find(collapsed, max(0, start))
        if position >= 0:
            return position

    squeezed = "".join(marker.split())[:30]
    if squeezed and squeezed != collapsed:
        position = markdown.find(squeezed, max(0, start))
        if position >= 0:
            return position
    return -1


def _page_size(middle: dict, index: int) -> tuple[float, float]:
    pdf_info = middle.get("pdf_info") if isinstance(middle, dict) else None
    if not isinstance(pdf_info, list) or index >= len(pdf_info):
        return 0.0, 0.0
    entry = pdf_info[index]
    if not isinstance(entry, dict):
        return 0.0, 0.0
    size = entry.get("page_size")
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        return _to_float(size[0]), _to_float(size[1])
    if isinstance(size, dict):
        return _to_float(size.get("width")), _to_float(size.get("height"))
    return _to_float(entry.get("width")), _to_float(entry.get("height"))


def _equal_split_pages(markdown: str, page_count: int) -> list[dict]:
    """按页数均分 Markdown 长度；用于 content_list 定位失败时的兜底。"""

    total = len(markdown)
    base, remainder = divmod(total, page_count)
    pages: list[dict] = []
    cursor = 0
    for index in range(page_count):
        size = base + (1 if index < remainder else 0)
        start = cursor
        end = cursor + size
        cursor = end
        pages.append(
            {
                "page": index + 1,
                "start": start,
                "end": end,
                "width": 0.0,
                "height": 0.0,
                "continuation": False,
                "empty": end <= start,
            }
        )
    return pages


def build_pages_from_content_list(
    markdown: str, content_list: list[dict], middle: dict
) -> dict:
    """由 MinerU 的 content_list 生成 ``pages.json`` 载荷。

    content_list 按阅读顺序给出每个区块所属页码；在 Markdown 中按顺序
    查找这些区块的文本/图片引用，把首次命中位置作为该页起点。命中率
    过低时退化为按页数均分，保证前端页码与字符区间始终可用。
    """

    content_list = content_list if isinstance(content_list, list) else []
    middle = middle if isinstance(middle, dict) else {}
    total = len(markdown)
    page_count = _page_count(content_list, middle)

    items_by_page: list[list[dict]] = [[] for _ in range(page_count)]
    for item in content_list:
        if not isinstance(item, dict):
            continue
        raw_index = item.get("page_idx")
        if not isinstance(raw_index, int) or not 0 <= raw_index < page_count:
            continue
        items_by_page[raw_index].append(item)

    # 按页顺序、页内按 content_list 顺序查找，并把搜索起点推进到上次
    # 命中位置之后：MinerU 输出本身是顺序的，这样可以避免封面/页眉等
    # 重复短文本把后续页面的起点定位到文档开头。
    starts: list[int | None] = [None] * page_count
    cursor = 0
    for index in range(page_count):
        page_start: int | None = None
        for item in items_by_page[index]:
            position = -1
            for marker in _markers_for_item(item):
                position = _find_marker(markdown, marker, cursor)
                if position >= 0:
                    break
            if position < 0:
                continue
            if page_start is None:
                page_start = position
            cursor = position + 1
        starts[index] = page_start

    hit_count = sum(1 for value in starts if value is not None)
    hit_rate = hit_count / page_count if page_count else 0.0

    if hit_rate < _MIN_HIT_RATE:
        logger.info(
            "MinerU pages 定位命中率 %.0f%%（%s/%s 页），按页数均分兜底",
            hit_rate * 100,
            hit_count,
            page_count,
        )
        pages = _equal_split_pages(markdown, page_count)
        # 尺寸仍尽量从 middle.json 取，命中失败不影响页面尺寸。
        for index, page in enumerate(pages):
            page["width"], page["height"] = _page_size(middle, index)
        if pages:
            # content_list 的首个 marker 可能从偏移 >0 开始（BOM/空行），
            # 首页必须覆盖 Markdown 开头，否则首块会被判成“无页码”。
            pages[0]["start"] = 0
            pages[0]["empty"] = pages[0]["end"] <= 0
        return {"version": 1, "page_count": page_count, "pages": pages}

    known_positions = sorted(value for value in starts if value is not None)

    def _next_known(after: int) -> int:
        for position in known_positions:
            if position > after:
                return position
        return total

    pages = []
    previous_known: int | None = None
    for index in range(page_count):
        if starts[index] is not None:
            start = int(starts[index])  # type: ignore[arg-type]
            end = _next_known(start)
            previous_known = start
        elif index == 0:
            # 首页没有命中时，把 Markdown 开头到首个命中位置归入首页，
            # 避免出现“无主”区间。
            start, end = 0, (known_positions[0] if known_positions else 0)
        else:
            boundary = previous_known if previous_known is not None else 0
            start = end = boundary
        width, height = _page_size(middle, index)
        pages.append(
            {
                "page": index + 1,
                "start": start,
                "end": end,
                "width": width,
                "height": height,
                "continuation": False,
                "empty": end <= start,
            }
        )
    if pages:
        # 首页起点强制为 0：content_list 首个 marker 可能在 BOM/空行之后。
        pages[0]["start"] = 0
        pages[0]["empty"] = pages[0]["end"] <= 0
    return {"version": 1, "page_count": page_count, "pages": pages}


# ---------------------------------------------------------------------------
# 子进程调用
# ---------------------------------------------------------------------------


def _build_command(
    source_path: Path,
    output_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    high_accuracy: bool,
) -> list[str]:
    command = [
        str(config.MINERU_PYTHON),
        "-u",
        str(config.MINERU_RUNNER),
        "--input",
        str(source_path),
        "--output",
        str(output_dir),
        "--backend",
        config.MINERU_BACKEND,
        "--language",
        config.MINERU_LANGUAGE,
        "--parse-method",
        config.MINERU_PARSE_METHOD,
        "--formula",
        "true" if enable_formula else "false",
        "--table",
        "true" if enable_table else "false",
        "--high-accuracy",
        "true" if high_accuracy else "false",
    ]
    if config.MINERU_DEVICE_MODE:
        command.extend(["--device", config.MINERU_DEVICE_MODE])
    return command


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    if config.MINERU_DEVICE_MODE:
        env["MINERU_DEVICE_MODE"] = config.MINERU_DEVICE_MODE
    if config.MINERU_MODEL_SOURCE:
        env["MINERU_MODEL_SOURCE"] = config.MINERU_MODEL_SOURCE
    return env


def _pump(stream: Any, sink: "queue.Queue[str | None]") -> None:
    """读取子进程输出并放入队列；结束时放入 ``None`` 作为哨兵。"""

    try:
        for line in iter(stream.readline, ""):
            sink.put(line)
    except Exception:  # 流被关闭时忽略
        logger.debug("读取 MinerU 子进程输出失败", exc_info=True)
    finally:
        sink.put(None)
        try:
            stream.close()
        except Exception:
            pass


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception:
            logger.debug("无法终止 MinerU 子进程", exc_info=True)


def _run_mineru_subprocess(
    command: list[str],
    *,
    timeout: int,
    progress: ProgressCallback,
) -> str:
    """运行 MinerU 并流式上报进度；返回最后 2000 字符日志。"""

    logger.info("启动 MinerU 子进程：%s", " ".join(command))
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_build_env(),
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 MinerU 子进程：{exc}") from exc

    assert process.stdout is not None
    lines: "queue.Queue[str | None]" = queue.Queue()
    reader = threading.Thread(
        target=_pump, args=(process.stdout, lines), name="mineru-log", daemon=True
    )
    reader.start()

    current = 0
    started = time.monotonic()
    deadline = started + max(1, timeout)
    tail = ""

    def _advance(value: int, stage: str) -> None:
        nonlocal current
        value = max(0, min(100, value))
        if value > current:
            current = value
            progress(value, stage, None)

    _advance(5, "启动 MinerU GPU")

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise RuntimeError(
                    f"MinerU 转换超时（{timeout} 秒），已终止子进程。"
                    f"\n最后日志：\n{tail}"
                )
            try:
                line = lines.get(timeout=min(0.5, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    break
                # 没有关键字输出时按已用时间缓慢推进，最高 90。
                _advance(min(90, 10 + int(time.monotonic() - started)), "MinerU 处理中")
                continue

            if line is None:
                break
            tail = (tail + line)[-_LOG_TAIL_CHARS:]
            lowered = line.lower()
            for keyword, value in _PROGRESS_KEYWORDS:
                if keyword in lowered:
                    _advance(value, f"MinerU {keyword}")
                    break

        try:
            returncode = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            _stop_process(process)
            raise RuntimeError(
                f"MinerU 子进程在输出结束后仍未退出。\n最后日志：\n{tail}"
            )
    finally:
        _stop_process(process)
        reader.join(timeout=2)

    if returncode != 0:
        raise RuntimeError(
            f"MinerU 转换失败（退出码 {returncode}）。\n最后日志：\n{tail}"
        )
    return tail


# ---------------------------------------------------------------------------
# 输出发现与归一化
# ---------------------------------------------------------------------------


def _discover_outputs(output_dir: Path) -> tuple[Path, Path | None, Path | None]:
    markdown_files = sorted(
        path for path in output_dir.rglob("*.md") if path.is_file()
    )
    if not markdown_files:
        raise RuntimeError("MinerU 未生成任何 Markdown 文件")
    markdown_path = markdown_files[0]

    def _first(pattern: str) -> Path | None:
        candidates = sorted(
            path for path in output_dir.rglob(pattern) if path.is_file()
        )
        if not candidates:
            return None
        # 优先选择与 Markdown 同目录（或同树）的附件。
        candidates.sort(key=lambda path: (path.parent != markdown_path.parent, len(path.parts)))
        return candidates[0]

    return markdown_path, _first("*_content_list.json"), _first("*_middle.json")


def _read_json(path: Path | None, warnings: list[str], label: str) -> Any:
    if path is None:
        warnings.append(f"MinerU 未输出 {label}，相关页面信息已降级")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        warnings.append(f"读取 MinerU {label} 失败：{exc}")
        return {}


def _copy_images(source_dir: Path | None, target_dir: Path) -> int:
    """把 MinerU 的 images 目录复制到 ``out/images``（保持相对路径）。"""

    if source_dir is None or not source_dir.is_dir():
        return 0
    count = 0
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        count += 1
    return count


def build_api_form_data(enable_table: bool, enable_formula: bool) -> dict[str, str]:
    """构造 ``POST /tasks`` 的 multipart 表单字段（纯函数，便于单测）。"""

    return {
        "lang_list": config.MINERU_LANGUAGE,
        "backend": config.MINERU_BACKEND,
        "parse_method": config.MINERU_PARSE_METHOD,
        "formula_enable": "true" if enable_formula else "false",
        "table_enable": "true" if enable_table else "false",
        "return_md": "true",
        "return_middle_json": "true",
        "return_content_list": "true",
        "return_images": "true",
        "return_original_file": "false",
        "response_format_zip": "true",
        "start_page_id": "0",
        "end_page_id": "99999",
    }


def _json_object(response: Any) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("MinerU API 返回了非 JSON 响应") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MinerU API 返回格式异常（期望 JSON 对象）")
    return payload


def _raise_for_status(response: Any, action: str) -> None:
    try:
        response.raise_for_status()
    except Exception as exc:  # httpx.HTTPStatusError / 网络异常
        raise RuntimeError(f"{action}失败：{exc}") from exc


def _poll_api_task(
    client: Any,
    task_id: str,
    *,
    timeout: int,
    report: ProgressCallback,
    started: float,
) -> None:
    """轮询任务状态直到完成/失败/超时。

    API 未返回进度字段时按已用时间推进（10 → 最高 90），不会因缺少进度
    而卡住。
    """

    url = f"{config.MINERU_API_URL}/tasks/{task_id}"
    poll_seconds = max(0.05, float(config.MINERU_API_POLL_SECONDS))
    deadline = started + max(1, timeout)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"MinerU API 转换超时（{timeout} 秒），任务：{task_id}"
            )

        response = client.get(url)
        _raise_for_status(response, "查询 MinerU API 任务状态")
        payload = _json_object(response)
        status = str(payload.get("status") or "").strip().lower()

        elapsed = time.monotonic() - started
        report(min(90, 10 + int(elapsed)), "MinerU API 处理中", None)

        if status in _API_COMPLETED_STATUSES:
            return
        if status in _API_FAILED_STATUSES:
            error = str(
                payload.get("error")
                or payload.get("message")
                or "未知错误"
            ).strip()
            raise RuntimeError(f"MinerU API 任务失败：{error}")

        # pending / processing 或未知状态：继续等待，不依赖进度字段。
        sleep_seconds = min(
            poll_seconds, max(0.05, deadline - time.monotonic())
        )
        time.sleep(sleep_seconds)


def _safe_extract_zip(archive_path: Path, target_dir: Path) -> int:
    """安全解压 ZIP 到 ``target_dir``，返回文件数。

    拒绝 ``..``、绝对路径（POSIX / Windows 盘符 / UNC）与符号链接，防止
    ZIP Slip 把文件写到任务目录之外。
    """

    target = target_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    extracted = 0

    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if not name or info.is_dir():
                continue
            if "\x00" in name:
                raise RuntimeError(f"压缩包包含非法文件名：{name!r}")

            relative = PurePosixPath(name.replace("\\", "/"))
            windows_path = PureWindowsPath(name)
            if (
                relative.is_absolute()
                or windows_path.is_absolute()
                or windows_path.drive
                or ".." in relative.parts
            ):
                raise RuntimeError(f"压缩包包含非法路径：{name}")

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise RuntimeError(f"压缩包包含符号链接：{name}")

            destination = (target / Path(*relative.parts)).resolve()
            if destination != target and target not in destination.parents:
                raise RuntimeError(f"压缩包路径越界：{name}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted += 1

    return extracted


def _convert_via_api(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback | None = None,
) -> "ConversionResult":
    """通过常驻 `mineru-api` 转换文档并归一化结果。"""

    httpx = _import_httpx()
    report = progress or _noop_progress
    # 与 _poll_api_task 的 deadline 使用同一时钟（Windows 下 perf_counter 与
    # monotonic 的基准可能不同，混用会导致立即误判超时）。
    started = time.monotonic()
    mineru_out = task_dir / "mineru_out"
    shutil.rmtree(mineru_out, ignore_errors=True)
    mineru_out.mkdir(parents=True, exist_ok=True)

    timeout = max(1, int(config.MINERU_API_TIMEOUT_SECONDS))
    base_url = config.MINERU_API_URL.rstrip("/")
    media_type = _API_MEDIA_TYPES.get(
        source_path.suffix.lower(), "application/octet-stream"
    )

    report(5, "提交 MinerU API 任务", None)
    try:
        with httpx.Client(timeout=timeout) as client:
            with source_path.open("rb") as handle:
                files = [("files", (source_path.name, handle, media_type))]
                response = client.post(
                    f"{base_url}/tasks",
                    data=build_api_form_data(enable_table, enable_formula),
                    files=files,
                )
            _raise_for_status(response, "提交 MinerU API 任务")
            task_id = str(_json_object(response).get("task_id") or "").strip()
            if not task_id:
                raise RuntimeError("MinerU API 未返回 task_id")
            logger.info(
                "MinerU API 任务已提交：%s（%s，dpi=%s）",
                task_id,
                source_path.name,
                dpi,
            )

            _poll_api_task(
                client,
                task_id,
                timeout=timeout,
                report=report,
                started=started,
            )

            report(95, "下载 MinerU 结果", None)
            result_url = f"{base_url}/tasks/{task_id}/result"
            archive_path = mineru_out / "mineru_api_result.zip"
            with client.stream("GET", result_url) as result_response:
                _raise_for_status(result_response, "下载 MinerU API 结果")
                with archive_path.open("wb") as target:
                    for chunk in result_response.iter_bytes():
                        target.write(chunk)
    except Exception:
        # 失败时保留 mineru_out 便于排查，但避免残留不完整 ZIP 被误用。
        raise

    if archive_path.stat().st_size <= 0:
        raise RuntimeError("MinerU API 返回了空结果 ZIP")

    extracted = _safe_extract_zip(archive_path, mineru_out)
    logger.info(
        "MinerU API 结果已解压：任务=%s，文件=%s，ZIP=%s 字节",
        task_id,
        extracted,
        archive_path.stat().st_size,
    )

    return _finalize_outputs(
        source_path,
        task_dir,
        mineru_out,
        engine_name="mineru-api",
        started=started,
        report=report,
        high_accuracy=None,
    )


def _finalize_outputs(
    source_path: Path,
    task_dir: Path,
    mineru_out: Path,
    *,
    engine_name: str,
    started: float,
    report: ProgressCallback,
    high_accuracy: bool | None,
) -> "ConversionResult":
    """把 MinerU 中间产物归一化为 Worker 结果契约（API / 子进程共用）。"""

    markdown_path, content_list_path, middle_path = _discover_outputs(mineru_out)
    markdown = markdown_path.read_text(encoding="utf-8", errors="replace")

    warnings: list[str] = []
    content_list = _read_json(content_list_path, warnings, "content_list.json")
    if not isinstance(content_list, list):
        warnings.append("MinerU content_list 格式异常，页面映射已降级")
        content_list = []
    middle = _read_json(middle_path, warnings, "middle.json")
    if not isinstance(middle, dict):
        warnings.append("MinerU middle.json 格式异常，页面尺寸已降级")
        middle = {}

    images_source = markdown_path.parent / "images"
    if not images_source.is_dir() and markdown_path.parent.parent != mineru_out:
        # 少数版本把 Markdown 放在更深一层，图片目录与 Markdown 同级；
        # 仍然允许递归查找唯一的 images 目录。
        candidates = sorted(
            path for path in mineru_out.rglob("images") if path.is_dir()
        )
        images_source = candidates[0] if candidates else None

    output_dir = task_dir / "out"
    shutil.rmtree(output_dir, ignore_errors=True)
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.md").write_text(markdown, encoding="utf-8")

    image_count = _copy_images(images_source, images_dir)
    if image_count == 0:
        logger.info("MinerU 输出不包含图片，images/ 目录保持为空")

    pages_payload = build_pages_from_content_list(markdown, content_list, middle)

    # 懒导入，避免 mineru_engine -> convert -> engine 的模块级循环依赖，
    # 同时让本模块在测试中保持轻量。
    from convert import ConversionResult, build_result_zip, write_pages

    write_pages(output_dir, pages_payload["pages"])
    build_result_zip(output_dir, task_dir / "result.zip")

    # 中间产物只在失败时保留用于排查；成功后删除以节省磁盘。
    shutil.rmtree(mineru_out, ignore_errors=True)

    page_count = int(pages_payload["page_count"])
    elapsed = time.monotonic() - started
    report(100, "MinerU 完成", page_count)
    logger.info(
        "MinerU 转换完成（%s）：%s，页数=%s，图片=%s，Markdown=%s 字符，"
        "耗时=%.2fs，high_accuracy=%s",
        engine_name,
        source_path.name,
        page_count,
        image_count,
        len(markdown),
        elapsed,
        high_accuracy,
    )
    return ConversionResult(
        page_count=page_count,
        markdown_chars=len(markdown),
        elapsed_seconds=elapsed,
        warnings=warnings,
        engine=engine_name,
    )


def _convert_via_subprocess(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback | None = None,
) -> "ConversionResult":
    """用 CFwin11 内的 MinerU 子进程转换文档（每次任务重新加载模型）。"""

    report = progress or _noop_progress
    # 与 _finalize_outputs 的耗时统计保持同一时钟。
    started = time.monotonic()
    mineru_out = task_dir / "mineru_out"
    shutil.rmtree(mineru_out, ignore_errors=True)
    mineru_out.mkdir(parents=True, exist_ok=True)

    # dpi >= 300 时自动开启高精度（渲染 560 DPI + 更激进的 OCR 覆写）。
    high_accuracy = bool(config.MINERU_HIGH_ACCURACY) or int(dpi) >= 300

    command = _build_command(
        source_path,
        mineru_out,
        enable_table=enable_table,
        enable_formula=enable_formula,
        high_accuracy=high_accuracy,
    )
    report(3, "启动 MinerU GPU", None)
    _run_mineru_subprocess(
        command,
        timeout=int(config.MINERU_TIMEOUT_SECONDS),
        progress=report,
    )

    return _finalize_outputs(
        source_path,
        task_dir,
        mineru_out,
        engine_name="mineru",
        started=started,
        report=report,
        high_accuracy=high_accuracy,
    )


def convert_with_mineru(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback | None = None,
) -> "ConversionResult":
    """用 MinerU GPU 转换文档并归一化到 Worker 的结果契约。

    传输方式由 ``MINERU_MODE`` 决定：

    - ``subprocess``：直接使用子进程；
    - ``api``：只使用常驻 API，不可用或失败直接抛错；
    - ``auto``：API 可用时优先 API，失败后回退子进程。
    """

    report = progress or _noop_progress
    mode = (config.MINERU_MODE or "auto").strip().lower()
    if mode not in {"auto", "api", "subprocess"}:
        logger.warning(
            "MINERU_MODE=%s 不合法，已按 auto 处理（可选 auto/api/subprocess）",
            config.MINERU_MODE,
        )
        mode = "auto"

    kwargs = {
        "enable_table": enable_table,
        "enable_formula": enable_formula,
        "dpi": dpi,
        "progress": report,
    }

    if mode == "subprocess":
        return _convert_via_subprocess(source_path, task_dir, **kwargs)

    api_ok, api_reason = api_available()
    if not api_ok:
        if mode == "api":
            raise RuntimeError(f"MinerU API 不可用：{api_reason}")
        logger.info("MinerU API 不可用，使用子进程：%s", api_reason)
        return _convert_via_subprocess(source_path, task_dir, **kwargs)

    try:
        return _convert_via_api(source_path, task_dir, **kwargs)
    except Exception as exc:
        if mode == "api":
            raise
        logger.warning(
            "MinerU API 失败，回退子进程：%s", exc, exc_info=True
        )
        report(1, "MinerU API 失败，回退子进程", None)
        return _convert_via_subprocess(source_path, task_dir, **kwargs)
