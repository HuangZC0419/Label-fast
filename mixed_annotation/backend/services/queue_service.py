"""夜间持久串行 OCR 队列。

设计要点：

1. 队列状态完全落在各文件的 meta.json（``status == "uploaded"``），
   进程重启后重新扫描即可恢复，不依赖内存队列；
2. 默认并发 1，按 ``(queue_seq, created_at, id)`` 全局串行处理，
   跨项目同样遵守该顺序；
3. 内存中维护待处理 id 列表：只有列表耗尽时才扫描一次磁盘，避免每个
   文件都全量遍历项目目录；扫描在线程池执行，不阻塞事件循环；
4. 空队列时等待事件唤醒，最长约 10 秒重新扫描一次，兜底外部写入；
5. worker 必须运行在 FastAPI lifespan 的同一事件循环内。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections import deque

import storage
from errors import NotFoundError
from services import conversion_service, ocr_client

logger = logging.getLogger(__name__)

# 空队列时的兜底扫描间隔（秒），防止漏掉未调用 wake() 的外部写入。
# 扫描在线程池中执行，间隔放长可显著降低空闲时的磁盘压力。
_SCAN_INTERVAL_SECONDS = 10.0
# 并发数环境变量；本次产品需求默认严格串行。
_CONCURRENCY_ENV = "MIX_CONVERSION_CONCURRENCY"
_DEFAULT_CONCURRENCY = 1
# OCR 服务不可用时的退避时间；夜间批量导入不能因 Worker 崩溃烧掉整批文件。
_WORKER_RETRY_ENV = "MIX_QUEUE_WORKER_RETRY_SECONDS"
_DEFAULT_WORKER_RETRY_SECONDS = 30.0
# 单个文件因 OCR 服务不可用的最大自动重试次数，防止持续 5xx 的坏文件占住队首。
_MAX_RETRIES_ENV = "MIX_QUEUE_MAX_RETRIES"
_DEFAULT_MAX_RETRIES = 3

# 连接/通信类错误：与具体文件无关，可安全重试。
_RETRYABLE_MARKERS = (
    "无法连接 OCR Worker",
    "与 OCR Worker 通信中断",
    "OCR 任务不存在",  # Worker 可能已重启
    "OCR 结果不存在",  # Worker 重启后结果丢失
    "OCR Worker 返回了非 JSON 响应",
    "OCR Worker 未返回",
    "查询 OCR 任务失败",
    "查询 OCR 任务超时",
    "下载 OCR 结果失败",
)
# 任意错误文本中的 HTTP 状态码：5xx 属于服务故障可重试；4xx 是文件/
# 请求本身有问题，重试只会永久占住队首（任务/结果丢失的 404 除外）。
_HTTP_STATUS_PATTERN = re.compile(r"HTTP\s+(\d{3})", re.IGNORECASE)
# 4xx 中唯一可重试的两类：Worker 重启导致任务/结果丢失。
_RETRYABLE_NOT_FOUND_MARKERS = ("OCR 任务不存在", "OCR 结果不存在")


class _QueueState:
    """一次 ``start()`` / ``stop()`` 周期内的队列运行时状态。"""

    def __init__(self, concurrency: int) -> None:
        self.concurrency = concurrency
        self.wakeup = asyncio.Event()
        self.claim_lock = asyncio.Lock()
        # 已在内存中认领、尚未处理完的文件，避免并发 worker 重复取同一个文件。
        self.claimed: set[str] = set()
        # 本次启动内不再重复认领的文件（损坏记录或已非 uploaded）。
        self.skipped: set[str] = set()
        # 一次扫描得到的待处理 id（按 queue_seq 升序）；耗尽后才重新扫描。
        self.pending: deque[str] = deque()
        self.workers: list[asyncio.Task[None]] = []
        self.stopping = False


_state: _QueueState | None = None
# start() 之前调用 wake() 时暂存唤醒，启动后立即扫描一次。
_wake_pending = False


def _queue_concurrency() -> int:
    """读取并发配置；非法值回退为串行，绝不因配置错误导致队列不可用。"""

    raw = os.getenv(_CONCURRENCY_ENV, str(_DEFAULT_CONCURRENCY)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("%s 取值非法（%s），回退为串行", _CONCURRENCY_ENV, raw)
        return _DEFAULT_CONCURRENCY
    if value < 1:
        logger.warning("%s 必须 >= 1（当前 %s），回退为串行", _CONCURRENCY_ENV, value)
        return _DEFAULT_CONCURRENCY
    return value


def _worker_retry_seconds() -> float:
    """读取 Worker 不可用时的退避时间，非法值回退默认。"""

    raw = os.getenv(
        _WORKER_RETRY_ENV, str(_DEFAULT_WORKER_RETRY_SECONDS)
    ).strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("%s 取值非法（%s），回退默认值", _WORKER_RETRY_ENV, raw)
        return _DEFAULT_WORKER_RETRY_SECONDS
    # 过低会导致忙轮询，保留最小间隔。
    return max(0.05, value)


def _queue_max_retries() -> int:
    """读取单文件最大自动重试次数；非法值回退默认，最小 1。"""

    raw = os.getenv(_MAX_RETRIES_ENV, str(_DEFAULT_MAX_RETRIES)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("%s 取值非法（%s），回退默认值", _MAX_RETRIES_ENV, raw)
        return _DEFAULT_MAX_RETRIES
    return max(1, value)


def _retry_count(meta: dict) -> int:
    try:
        return max(0, int(meta.get("queue_retry_count") or 0))
    except (TypeError, ValueError):
        return 0


def _is_worker_failure(text: str) -> bool:
    """判断失败文本是否属于可重试的 OCR 服务不可用。

    - 先解析文本中任意位置的 ``HTTP n``：n >= 500 可重试；
    - n < 500 只有明确“OCR 任务不存在 / OCR 结果不存在”可重试，
      其余 4xx（尤其查询任务的 401/403）一律不可重试，即使 detail
      中出现连接类文案；
    - 完全没有状态码时再匹配连接/通信类标记。
    """

    match = _HTTP_STATUS_PATTERN.search(text)
    if match is not None:
        try:
            status = int(match.group(1))
        except ValueError:  # pragma: no cover - 正则已限定三位数字
            return False
        if status >= 500:
            return True
        return any(marker in text for marker in _RETRYABLE_NOT_FOUND_MARKERS)
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def _requeue_worker_failure(file_id: str) -> bool:
    """转换因 OCR 服务不可用而失败时，把文件退回 uploaded 等待重试。

    通过转换令牌校验，避免覆盖用户在转换期间新发起的转换。
    """

    try:
        meta = storage.get_file(file_id)
    except NotFoundError:
        return False
    except Exception:
        logger.exception("读取转换结果失败：file_id=%s", file_id)
        return False

    if meta.get("status") != "failed":
        return False
    text = f"{meta.get('error') or ''} {meta.get('message') or ''}"
    if not _is_worker_failure(text):
        return False
    # 失败路径现在会清空令牌；空令牌仍可退回，但写入时继续用令牌做
    # 乐观校验——若期间用户发起了新转换（令牌非空），更新会被拒绝。
    token = str(meta.get("conversion_token") or "")

    retry_count = _retry_count(meta)
    max_retries = _queue_max_retries()
    if retry_count >= max_retries:
        # 达到上限：保留 failed，明确提示用户手动重试，让队列继续下一个文件。
        logger.warning(
            "OCR 服务多次不可用，暂停该文件（已重试 %s 次）：file_id=%s",
            retry_count,
            file_id,
        )
        try:
            storage.update_file_if_token(
                file_id,
                token,
                {
                    "status": "failed",
                    "stage": "OCR 服务多次不可用，已暂停该文件，请稍后手动重试",
                    "message": "OCR 服务多次不可用，已暂停该文件，请稍后手动重试",
                    "error": "OCR 服务多次不可用，已暂停该文件，请稍后手动重试",
                },
            )
        except NotFoundError:
            return False
        except Exception:
            logger.exception("标记文件暂停失败：file_id=%s", file_id)
        return False

    try:
        updated = storage.update_file_if_token(
            file_id,
            token,
            {
                "status": "uploaded",
                "progress": 0,
                "stage": "OCR 服务不可用，稍后重试",
                "message": "",
                "error": "",
                "task_id": "",
                "conversion_token": "",
                "queue_retry_count": retry_count + 1,
            },
        )
    except NotFoundError:
        return False
    except Exception:
        logger.exception("回写重新排队状态失败：file_id=%s", file_id)
        return False
    return updated is not None


def _fail_internal_if_converting(file_id: str) -> None:
    """转换协程抛出未预期异常时，把仍在 converting 的文件标记为失败。

    否则文件会永久停留在“转换中”，既不重试也不提示用户。写入前同样
    校验状态与令牌，避免覆盖并发完成的终态。
    """

    try:
        meta = storage.get_file(file_id)
    except NotFoundError:
        return
    except Exception:
        logger.exception("读取转换异常文件失败：file_id=%s", file_id)
        return
    if meta.get("status") != "converting":
        return
    token = str(meta.get("conversion_token") or "")
    if not token:
        return
    message = "转换发生内部错误，请重试"
    try:
        storage.update_file_if_token_and_status(
            file_id,
            token,
            frozenset({"converting"}),
            {
                "status": "failed",
                "stage": "转换失败",
                "message": message,
                "error": message,
                "task_id": "",
                "conversion_token": "",
            },
        )
    except NotFoundError:
        return
    except Exception:
        logger.exception("回写内部错误失败状态失败：file_id=%s", file_id)


def wake() -> None:
    """通知队列有新工作；可在同一事件循环内同步调用。

    队列空闲时立即唤醒并重新扫描；批次进行中不会打断当前 ``pending``
    顺序——新入队文件要等当前批次耗尽后再处理，保证 queue_seq 升序。
    """

    global _wake_pending
    state = _state
    if state is None or state.stopping:
        _wake_pending = True
        return
    state.wakeup.set()


async def start() -> None:
    """启动队列 worker；重复调用是幂等的。"""

    global _state, _wake_pending
    if _state is not None:
        return

    concurrency = _queue_concurrency()
    state = _QueueState(concurrency)
    _state = state
    if _wake_pending:
        state.wakeup.set()
        _wake_pending = False

    for index in range(concurrency):
        state.workers.append(
            asyncio.create_task(
                _worker_loop(state, index), name=f"ocr-queue-{index}"
            )
        )
    logger.info("OCR 夜间队列已启动，并发数：%s", concurrency)


async def stop() -> None:
    """取消所有 worker 并等待退出；未启动时为空操作。"""

    global _state
    state = _state
    if state is None:
        return

    _state = None
    state.stopping = True
    # 先唤醒再取消，避免 worker 阻塞在事件等待中错过取消信号。
    state.wakeup.set()
    for task in state.workers:
        task.cancel()
    if state.workers:
        await asyncio.gather(*state.workers, return_exceptions=True)
    state.workers.clear()
    state.claimed.clear()
    state.skipped.clear()
    state.pending.clear()
    logger.info("OCR 夜间队列已停止")


async def _worker_loop(state: _QueueState, index: int) -> None:
    """单个 worker：认领 → 探测 Worker → 转换 → 释放，循环直到被取消。"""

    try:
        while not state.stopping:
            file_id = await _claim_next(state)
            if file_id is None:
                await _wait_for_work(state)
                continue
            try:
                # OCR 服务整体不可用时暂停队列，文件保持 uploaded，
                # 绝不能连续把整批文件标成 failed。探测本身抛异常同样
                # 按不可用处理，避免异常杀死 worker 导致队列静默停摆。
                try:
                    available = await ocr_client.worker_available()
                except Exception:
                    logger.exception(
                        "OCR Worker 可用性探测异常，按不可用处理：file_id=%s",
                        file_id,
                    )
                    available = False
                if not available:
                    retry = _worker_retry_seconds()
                    logger.warning(
                        "OCR 服务不可用，%.1f 秒后重试，文件保持排队：file_id=%s",
                        retry,
                        file_id,
                    )
                    # 放回队首再退避：Worker 恢复后仍从原队首继续，
                    # 避免故障期间把批次顺序轮转掉。
                    state.pending.appendleft(file_id)
                    await _wait_for_worker()
                    continue

                try:
                    started = await conversion_service.run_queued_conversion(
                        file_id
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # 单个文件失败不停止队列；先把仍处于 converting 的
                    # 记录标成 failed，避免前端永久显示“转换中”，
                    # 本次启动内也不再重复认领，防止损坏记录在队首空转。
                    logger.exception("夜间队列转换异常：file_id=%s", file_id)
                    _fail_internal_if_converting(file_id)
                    state.skipped.add(file_id)
                    continue

                if not started:
                    # 文件在排队期间被删除或被用户重新转换，本次启动跳过。
                    state.skipped.add(file_id)
                    continue

                if _requeue_worker_failure(file_id):
                    retry = _worker_retry_seconds()
                    logger.warning(
                        "OCR 服务在转换中不可用，文件已退回队列，"
                        "%.1f 秒后重试：file_id=%s",
                        retry,
                        file_id,
                    )
                    # 重试优先于批次中的后续文件，避免等整批耗尽后才重试。
                    state.pending.appendleft(file_id)
                    await _wait_for_worker()
            finally:
                state.claimed.discard(file_id)
    except asyncio.CancelledError:
        logger.info("OCR 夜间队列 worker %s 退出", index)
        raise


async def _claim_next(state: _QueueState) -> str | None:
    """从待处理列表认领下一个文件；列表耗尽时扫描一次磁盘。

    返回 ``None`` 表示当前没有任务。扫描放在线程池执行，避免全量遍历
    项目目录时阻塞 uvicorn 事件循环。
    """

    async with state.claim_lock:
        while True:
            while state.pending:
                file_id = state.pending.popleft()
                if file_id in state.claimed or file_id in state.skipped:
                    continue
                state.claimed.add(file_id)
                return file_id

            # 列表为空：重新扫描一次，按导入顺序填充。
            try:
                metas = await asyncio.to_thread(storage.list_queued_files)
            except Exception:
                logger.exception("扫描待转换文件失败")
                return None
            for meta in metas:
                raw_id = meta.get("id")
                if not isinstance(raw_id, str) or not raw_id:
                    continue
                if raw_id in state.claimed or raw_id in state.skipped:
                    continue
                # 新入队文件 queue_seq 更大，自然排在当前批次之后。
                state.pending.append(raw_id)
            if not state.pending:
                return None


async def _wait_for_work(state: _QueueState) -> None:
    """空队列时等待唤醒；超时（默认 10 秒）后重新扫描一次。"""

    try:
        await asyncio.wait_for(
            state.wakeup.wait(), timeout=_SCAN_INTERVAL_SECONDS
        )
    except asyncio.TimeoutError:
        pass
    finally:
        state.wakeup.clear()


async def _wait_for_worker() -> None:
    """OCR 服务不可用时的退避等待；stop() 取消 worker 即可立即打断。"""

    await asyncio.sleep(_worker_retry_seconds())
