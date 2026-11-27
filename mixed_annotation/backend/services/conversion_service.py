"""OCR 转换编排。

职责：
1. 生成一次转换的令牌并清理旧结果；
2. 后台提交 Worker、轮询进度、同步到 meta.json；
3. 校验并解压结果 ZIP，原子替换 Markdown 目录。

转换令牌是并发安全的核心：用户重新转换后，旧协程的任何后续写入都会
因令牌不匹配而被丢弃。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from config import (
    ALLOWED_UPLOADS,
    DEFAULT_DPI,
    DEFAULT_ENABLE_FORMULA,
    DEFAULT_ENABLE_TABLE,
    MAX_EXTRACTED_RESULT_BYTES,
    OCR_MAX_CONSECUTIVE_POLL_ERRORS,
    OCR_POLL_INTERVAL,
    OCR_QUEUE_TASK_TIMEOUT,
    OCR_TASK_TIMEOUT,
)
from errors import NotFoundError, ServiceError
from services import ocr_client
from services.ocr_client import OcrWorkerBusy, OcrWorkerError
from storage import (
    clear_results,
    file_dir,
    get_file,
    markdown_dir,
    source_path,
    update_file,
    update_file_if_token,
    update_file_if_token_and_status,
)
from utils import ensure_within

logger = logging.getLogger(__name__)

# 只有这些中间态允许被失败/退回操作改写；completed 等终态必须保持不变。
_FAILABLE_STATUSES = frozenset({"converting", "uploaded"})

_tasks: set[asyncio.Task[Any]] = set()
_file_locks: dict[str, asyncio.Lock] = {}


def _lock_for(file_id: str) -> asyncio.Lock:
    lock = _file_locks.get(file_id)
    if lock is None:
        lock = asyncio.Lock()
        _file_locks[file_id] = lock
    return lock


def _bounded_progress(value: Any) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def _short(value: Any, limit: int = 1000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:limit]


def _error_text(*values: Any) -> str:
    for value in values:
        text = _short(value)
        if text:
            return text
    return "OCR 转换失败"


def _short_token(token: str) -> str:
    """缩短转换令牌，避免 staging/backup 路径触发 Windows MAX_PATH。

    MinerU 输出的图片名是 64 位哈希；如果 staging 目录再包含完整 UUID
    （``.markdown-staging-<36 位>``），解压目标很容易超过 260 字符。
    这里保留 16 位十六进制（64 bit），既足够区分并发转换，又能显著缩短路径。
    """

    compact = str(token or "").replace("-", "")
    return compact[:16] or "temp"


async def _fail_if_current(file_id: str, token: str, message: str) -> None:
    """仅当令牌匹配且仍处于中间态时写 failed，避免覆盖已完成结果。

    写入同时清空 ``conversion_token``：终态不再持有并发令牌，后续任何
    陈旧协程都无法再改写该文件。
    """

    try:
        update_file_if_token_and_status(
            file_id,
            token,
            _FAILABLE_STATUSES,
            {
                "status": "failed",
                "stage": "转换失败",
                "message": message,
                "error": message,
                "conversion_token": "",
            },
        )
    except NotFoundError:
        # 文件或项目已被删除，无需回写失败状态。
        return
    except Exception:
        logger.exception("回写转换失败状态失败：file_id=%s", file_id)


def _requeue_if_current(file_id: str, token: str) -> None:
    """把被取消的排队转换退回 uploaded，等待服务重启后继续。

    通过令牌与状态双重校验避免旧任务覆盖用户新发起的转换或终态；
    ``queue_seq`` 保持不变，因此重新排队不会打乱夜间导入顺序。
    """

    try:
        update_file_if_token_and_status(
            file_id,
            token,
            _FAILABLE_STATUSES,
            {
                "status": "uploaded",
                "progress": 0,
                "stage": "转换已暂停，等待重新排队",
                "message": "",
                "error": "",
                "task_id": "",
                "conversion_token": "",
            },
        )
    except NotFoundError:
        return
    except Exception:
        logger.exception("回写重新排队状态失败：file_id=%s", file_id)


# Windows 设备名（忽略大小写，按第一个点前的基名判断），解压到磁盘会
# 触发设备写入或异常，必须整体拒绝。
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
)


def _validate_zip_member_part(part: str) -> None:
    """校验单个路径片段，覆盖 Windows 特有的盘符、数据流与设备名。"""

    if part in {"", ".", ".."}:
        raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")
    # 盘符（C:）与 NTFS 备用数据流（file.txt:ads）都含冒号；POSIX 路径中
    # 冒号合法，但该 ZIP 只面向 Windows 部署，统一拒绝。
    if ":" in part:
        raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")
    # Windows 会静默去掉末尾的空格和点，可能导致实际落盘路径与校验路径不一致。
    if part.endswith((" ", ".")):
        raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")
    if part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")


def _extract_result_zip(zip_path: Path, destination: Path) -> None:
    """安全解压 Worker 结果，拒绝路径穿越、符号链接与超大内容。"""

    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=False)

    declared_total = 0
    actual_total = 0
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > 100_000:
            raise ServiceError(500, "OCR 结果 ZIP 条目过多")
        for info in members:
            raw_name = info.filename.replace("\\", "/")
            if not raw_name or raw_name.endswith("/"):
                continue
            if "\x00" in raw_name:
                raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")
            path = PurePosixPath(raw_name)
            if path.is_absolute():
                raise ServiceError(500, "OCR 结果 ZIP 包含非法路径")
            # 用原始分段校验，确保 "a//b" 这类空片段也会被拒绝
            # （PurePosixPath 会静默合并连续斜杠）。
            for part in raw_name.split("/"):
                _validate_zip_member_part(part)

            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ServiceError(500, "OCR 结果 ZIP 不允许符号链接")

            declared_total += info.file_size
            if declared_total > MAX_EXTRACTED_RESULT_BYTES:
                raise ServiceError(500, "OCR 结果解压后超过大小限制")

            # ensure_within 内部用 resolve() 做真实路径校验，同时返回解析后的
            # 目标路径：即使解压目录内混入符号链接，也无法逃逸出 destination。
            try:
                target = ensure_within(
                    destination, destination.joinpath(*path.parts)
                )
            except ValueError as exc:
                raise ServiceError(500, "OCR 结果 ZIP 包含非法路径") from exc

            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(info) as source, target.open("wb") as sink:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    actual_total += len(chunk)
                    if (
                        written > MAX_EXTRACTED_RESULT_BYTES
                        or actual_total > MAX_EXTRACTED_RESULT_BYTES
                    ):
                        raise ServiceError(500, "OCR 结果解压后超过大小限制")
                    sink.write(chunk)

    if not (destination / "result.md").is_file():
        raise ServiceError(500, "OCR 结果 ZIP 中缺少 result.md")
    (destination / "images").mkdir(parents=True, exist_ok=True)


def _swap_markdown_dir(file_meta: dict[str, Any], staging: Path, token: str) -> None:
    """用 staging 原子替换活动 markdown 目录，失败时尽量恢复旧目录。"""

    live = markdown_dir(file_meta)
    backup = file_dir(file_meta) / f".bak-{_short_token(token)}"
    backup_exists = False
    if live.exists():
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        os.replace(live, backup)
        backup_exists = True
    try:
        live.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, live)
    except BaseException:
        if backup_exists and not live.exists():
            os.replace(backup, live)
        raise
    if backup_exists:
        shutil.rmtree(backup, ignore_errors=True)


async def _install_downloaded_result(
    file_id: str,
    token: str,
    zip_path: Path,
    page_count: int,
) -> bool:
    lock = _lock_for(file_id)
    async with lock:
        try:
            meta = get_file(file_id)
        except NotFoundError:
            return False
        if meta.get("conversion_token") != token:
            return False
        staging = file_dir(meta) / f".stg-{_short_token(token)}"
        try:
            await asyncio.to_thread(_extract_result_zip, zip_path, staging)
            _swap_markdown_dir(meta, staging, token)
            updated = update_file_if_token(
                file_id,
                token,
                {
                    "status": "completed",
                    "progress": 100,
                    "stage": "转换完成",
                    "message": "",
                    "error": "",
                    "page_count": int(page_count or 0),
                    # 终态不再持有转换令牌，防止陈旧协程覆盖结果。
                    "conversion_token": "",
                    # 成功后清空队列重试计数，不影响后续手动重新转换。
                    "queue_retry_count": 0,
                },
            )
            return updated is not None
        except Exception:
            logger.exception("解压 OCR 结果失败：file_id=%s", file_id)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)


async def _run_conversion(
    file_id: str,
    token: str,
    worker_options: dict[str, Any],
    worker_filename: str,
    worker_content_type: str,
    *,
    requeue_on_cancel: bool = False,
    timeout_seconds: float | None = None,
) -> None:
    """执行一次转换。

    ``requeue_on_cancel`` 默认 False：立即转换被取消时标记失败（保持原有行为）。
    夜间队列传入 True：被取消时退回 uploaded，服务重启后可自动续跑。
    ``timeout_seconds`` 为本次转换的截止时间；None 时使用普通转换的
    ``OCR_TASK_TIMEOUT``，夜间队列传入更短的 ``OCR_QUEUE_TASK_TIMEOUT``。
    """
    loop = asyncio.get_running_loop()
    timeout = OCR_TASK_TIMEOUT if timeout_seconds is None else timeout_seconds
    deadline = loop.time() + max(0.0, timeout)
    zip_path: Path | None = None

    try:
        try:
            meta = get_file(file_id)
        except NotFoundError:
            return
        if meta.get("conversion_token") != token:
            return
        source = source_path(meta)
        if not source.is_file():
            await _fail_if_current(file_id, token, "源文件不存在，请重新上传")
            return

        try:
            worker_task_id = await ocr_client.submit_convert(
                source,
                worker_filename,
                worker_content_type,
                enable_table=bool(worker_options["enable_table"]),
                enable_formula=bool(worker_options["enable_formula"]),
                dpi=int(worker_options["dpi"]),
                parse_method=str(worker_options.get("parse_method") or "auto"),
            )
        except OcrWorkerError as exc:
            await _fail_if_current(file_id, token, _short(exc))
            return

        if update_file_if_token(
            file_id,
            token,
            {
                "status": "converting",
                "progress": 1,
                "stage": "等待 OCR Worker",
                "message": "",
                "error": "",
                "task_id": worker_task_id,
            },
        ) is None:
            return

        consecutive_errors = 0
        last_signature: tuple[Any, ...] | None = None

        while True:
            if loop.time() > deadline:
                await _fail_if_current(file_id, token, "转换超时，请重试")
                return
            await asyncio.sleep(max(0.2, OCR_POLL_INTERVAL))

            try:
                status_payload = await ocr_client.get_task(worker_task_id)
                consecutive_errors = 0
            except OcrWorkerBusy:
                # 大页面推理可能让 Worker 数分钟无法响应状态查询，
                # 这期间继续等待即可，整体时长由本次 timeout_seconds 兜底：
                # 队列路径传入 OCR_QUEUE_TASK_TIMEOUT，普通转换使用
                # OCR_TASK_TIMEOUT。
                update_file_if_token(
                    file_id,
                    token,
                    {"message": "OCR Worker 正在处理，等待响应…"},
                )
                continue
            except OcrWorkerError as exc:
                consecutive_errors += 1
                if consecutive_errors >= OCR_MAX_CONSECUTIVE_POLL_ERRORS:
                    await _fail_if_current(file_id, token, _short(exc))
                    return
                update_file_if_token(
                    file_id,
                    token,
                    {"message": "与 OCR Worker 通信中断，正在重试…"},
                )
                continue

            try:
                current = get_file(file_id)
            except NotFoundError:
                return
            if current.get("conversion_token") != token:
                return
            if current.get("task_id") not in {"", worker_task_id}:
                return

            status = _short(status_payload.get("status")).lower()
            progress = _bounded_progress(status_payload.get("progress"))
            stage = _short(status_payload.get("stage"), 200)
            message = _short(status_payload.get("message"), 1000)
            error = _short(status_payload.get("error"), 1000)
            try:
                page_count = max(0, int(status_payload.get("page_count") or 0))
            except (TypeError, ValueError):
                page_count = 0

            if status in {"completed", "success", "succeeded"}:
                if zip_path is None:
                    fd, temp_name = tempfile.mkstemp(
                        prefix="lfm-ocr-result-", suffix=".zip"
                    )
                    os.close(fd)
                    zip_path = Path(temp_name)
                update_file_if_token(
                    file_id,
                    token,
                    {
                        "status": "converting",
                        "progress": max(min(progress, 99), 95),
                        "stage": "下载转换结果",
                        "message": "",
                        "page_count": page_count,
                    },
                )
                try:
                    await ocr_client.download_result(worker_task_id, zip_path)
                    installed = await _install_downloaded_result(
                        file_id, token, zip_path, page_count
                    )
                except Exception as exc:
                    logger.exception("获取 OCR 结果失败：file_id=%s", file_id)
                    await _fail_if_current(
                        file_id, token, f"获取 OCR 结果失败：{_short(exc)}"
                    )
                    return
                if installed:
                    logger.info("OCR 转换完成：file_id=%s", file_id)
                return

            if status in {"failed", "error", "cancelled", "canceled"}:
                await _fail_if_current(
                    file_id, token, _error_text(error, message, "OCR 转换失败")
                )
                return

            if status in {"queued", "pending"}:
                mapped_status = "converting"
                mapped_stage = stage or "排队中"
                mapped_progress = max(progress, 0)
            else:
                mapped_status = "converting"
                mapped_stage = stage or "转换中"
                mapped_progress = max(progress, 0)

            signature = (
                mapped_status,
                mapped_progress,
                mapped_stage,
                message,
                page_count,
            )
            if signature != last_signature:
                updated = update_file_if_token(
                    file_id,
                    token,
                    {
                        "status": mapped_status,
                        "progress": mapped_progress,
                        "stage": mapped_stage,
                        "message": message,
                        "error": "",
                        "page_count": page_count,
                    },
                )
                if updated is None:
                    return
                last_signature = signature
    except asyncio.CancelledError:
        if requeue_on_cancel:
            _requeue_if_current(file_id, token)
        else:
            await _fail_if_current(file_id, token, "转换中断，请重试")
        raise
    except Exception:
        logger.exception("转换协程异常：file_id=%s", file_id)
        await _fail_if_current(file_id, token, "转换发生内部错误，请重试")
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)


async def start_conversion(
    file_id: str,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    reset_results: bool,
    filename: str,
    content_type: str,
    parse_method: str = "auto",
) -> dict[str, Any]:
    """启动一次转换，返回最新的文件元数据。"""

    lock = _lock_for(file_id)
    async with lock:
        meta = get_file(file_id)
        if reset_results:
            clear_results(file_id, clear_annotations=True)

        token = str(uuid.uuid4())
        method = (parse_method or "auto").strip().lower() or "auto"
        updated = update_file(
            file_id,
            {
                "status": "converting",
                "progress": 0,
                "stage": "正在提交 OCR 任务",
                "message": "",
                "error": "",
                "task_id": "",
                "conversion_token": token,
                "page_count": 0,
                "enable_table": bool(enable_table),
                "enable_formula": bool(enable_formula),
                "dpi": int(dpi),
                "parse_method": method,
            },
        )
        task = asyncio.create_task(
            _run_conversion(
                file_id,
                token,
                {
                    "enable_table": enable_table,
                    "enable_formula": enable_formula,
                    "dpi": dpi,
                    "parse_method": method,
                },
                filename,
                content_type,
            ),
            name=f"ocr-convert-{file_id}",
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        # meta 变量只用于确保文件仍在；返回值用 update_file 的结果。
        _ = meta
        return updated


async def run_queued_conversion(file_id: str) -> bool:
    """执行一个排队中的文件转换，返回是否真正启动。

    与 ``start_conversion`` 的差异：
    - 只处理 ``status == "uploaded"`` 的文件，避免与用户重新转换竞争；
    - 只在“认领 + 置为 converting”这段临界区内持有文件锁，随后释放；
      ``_run_conversion`` / ``_install_downloaded_result`` 内部会再次获取
      同一把锁，外层长时间持有会导致死锁；
    - 被取消时把文件退回队列（``requeue_on_cancel=True``），服务重启后继续。
    """

    try:
        meta = get_file(file_id)
    except NotFoundError:
        return False
    if meta.get("status") != "uploaded":
        return False

    extension = f".{meta.get('source_ext', '')}"
    media_type = ALLOWED_UPLOADS.get(
        extension, ("image", "application/octet-stream")
    )[1]
    enable_table = bool(meta.get("enable_table", DEFAULT_ENABLE_TABLE))
    enable_formula = bool(meta.get("enable_formula", DEFAULT_ENABLE_FORMULA))
    try:
        dpi = int(meta.get("dpi", DEFAULT_DPI))
    except (TypeError, ValueError):
        dpi = DEFAULT_DPI
    parse_method = str(meta.get("parse_method") or "auto").strip().lower() or "auto"
    worker_options = {
        "enable_table": enable_table,
        "enable_formula": enable_formula,
        "dpi": dpi,
        "parse_method": parse_method,
    }
    worker_filename = str(meta.get("source_filename") or "source")

    lock = _lock_for(file_id)
    async with lock:
        # 二次确认：排队期间文件可能已被删除或被用户手动重新转换。
        try:
            current = get_file(file_id)
        except NotFoundError:
            return False
        if current.get("status") != "uploaded":
            return False
        token = str(uuid.uuid4())
        update_file(
            file_id,
            {
                "status": "converting",
                "progress": 0,
                "stage": "排队开始",
                "message": "",
                "error": "",
                "task_id": "",
                "conversion_token": token,
                # 上一次中断可能留下部分页码，重新排队时清零。
                "page_count": 0,
                "enable_table": enable_table,
                "enable_formula": enable_formula,
                "dpi": dpi,
                "parse_method": parse_method,
            },
        )

    # 关键：转换期间不持有文件锁，由 _run_conversion 内部按需加锁。
    try:
        await _run_conversion(
            file_id,
            token,
            worker_options,
            worker_filename,
            media_type,
            requeue_on_cancel=True,
            # 队列使用更短的单文件超时，避免卡死任务阻塞整夜。
            timeout_seconds=OCR_QUEUE_TASK_TIMEOUT,
        )
    except asyncio.CancelledError:
        # 兜底：若取消发生在 _run_conversion 真正开始之前，内部处理器来不及
        # 退回队列。令牌已被内部清空时这里是无操作，不会重复写状态。
        _requeue_if_current(file_id, token)
        raise
    return True


async def shutdown_conversion_tasks() -> None:
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _tasks.clear()
    _file_locks.clear()
    logger.info("转换后台任务已停止")


def active_conversion_count() -> int:
    return len(_tasks)
