"""OCR Worker 的 HTTP 客户端。

该模块只负责协议转换和错误归一化，不持有任何文件系统状态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from config import (
    MAX_RESULT_ZIP_BYTES,
    OCR_CONNECT_TIMEOUT,
    OCR_DOWNLOAD_TIMEOUT,
    OCR_HEALTH_TIMEOUT,
    OCR_REGION_TIMEOUT,
    OCR_STATUS_TIMEOUT,
    OCR_SUBMIT_TIMEOUT,
    OCR_WORKER_URL,
)


class OcrWorkerError(RuntimeError):
    """OCR Worker 请求失败。"""


class OcrWorkerBusy(OcrWorkerError):
    """Worker 存活但正忙于推理，本轮查询未在超时内返回。"""


def _worker_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
    except ValueError:
        pass
    text = response.text.strip()
    return text[:300] if text else response.reason_phrase


def _timeout(read_timeout: float, *, connect: float = OCR_CONNECT_TIMEOUT) -> httpx.Timeout:
    return httpx.Timeout(read_timeout, connect=connect, write=read_timeout, pool=connect)


async def worker_available() -> bool:
    """探测 OCR Worker 是否具备接收新任务的能力；异常一律视为不可用。

    规则：
    - HTTP 非 200 或连接异常 → False；
    - 200 但响应不是 JSON → True（兼容旧版 Worker）；
    - ``mineru_mode == "api"`` 时要求 ``mineru_api_available`` 为 true；
      其他模式要求 ``mineru_available`` 或 ``mineru_api_available`` 任一为 true。
    """

    try:
        async with httpx.AsyncClient(
            base_url=OCR_WORKER_URL,
            timeout=_timeout(OCR_HEALTH_TIMEOUT, connect=OCR_HEALTH_TIMEOUT),
            trust_env=False,
        ) as client:
            response = await client.get("/health")
    except Exception:
        # 包含 httpx.InvalidURL 等非 HTTPError 异常；探测绝不向外抛。
        return False

    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return True
    if not isinstance(payload, dict):
        return True

    api_ready = payload.get("mineru_api_available") is True
    local_ready = payload.get("mineru_available") is True
    mode = str(payload.get("mineru_mode") or "").strip().lower()
    if mode == "api":
        return api_ready
    return local_ready or api_ready


async def submit_convert(
    source_path: Path,
    filename: str,
    content_type: str,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    parse_method: str = "auto",
) -> str:
    """提交转换任务，返回 Worker 的 task_id。"""

    try:
        with source_path.open("rb") as handle:
            files = {"file": (filename, handle, content_type)}
            data = {
                "enable_table": "true" if enable_table else "false",
                "enable_formula": "true" if enable_formula else "false",
                "dpi": str(dpi),
                "parse_method": (parse_method or "auto").strip() or "auto",
            }
            async with httpx.AsyncClient(
                base_url=OCR_WORKER_URL,
                timeout=_timeout(OCR_SUBMIT_TIMEOUT),
                trust_env=False,
            ) as client:
                response = await client.post("/convert", files=files, data=data)
    except (httpx.HTTPError, OSError) as exc:
        raise OcrWorkerError(f"无法连接 OCR Worker：{exc}") from exc

    if response.status_code >= 400:
        raise OcrWorkerError(
            f"OCR Worker 拒绝任务（HTTP {response.status_code}）：{_worker_detail(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OcrWorkerError("OCR Worker 返回了非 JSON 响应") from exc
    task_id = payload.get("task_id") if isinstance(payload, dict) else None
    if not isinstance(task_id, str) or not task_id:
        raise OcrWorkerError("OCR Worker 未返回 task_id")
    return task_id


async def get_task(task_id: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            base_url=OCR_WORKER_URL,
            timeout=_timeout(OCR_STATUS_TIMEOUT),
            trust_env=False,
        ) as client:
            response = await client.get(f"/tasks/{task_id}")
    except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as exc:
        # Paddle 推理期间 Worker 的 HTTP 线程可能长时间拿不到 GIL，
        # 读超时只说明它在忙，不能当作故障计数。
        raise OcrWorkerBusy(f"查询 OCR 任务超时：{exc}") from exc
    except httpx.HTTPError as exc:
        raise OcrWorkerError(f"查询 OCR 任务失败：{exc}") from exc

    if response.status_code == 404:
        raise OcrWorkerError("OCR 任务不存在（Worker 可能已重启）")
    if response.status_code >= 400:
        raise OcrWorkerError(
            f"查询 OCR 任务失败（HTTP {response.status_code}）：{_worker_detail(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OcrWorkerError("OCR Worker 返回了非 JSON 状态") from exc
    if not isinstance(payload, dict):
        raise OcrWorkerError("OCR Worker 状态格式不正确")
    return payload


async def recognize_region(
    content: bytes,
    *,
    filename: str = "region.png",
    content_type: str = "image/png",
) -> dict[str, Any]:
    """调用 Worker 的小图 OCR，返回 ``{lines: [{text, score, top, left}]}``。

    小图 OCR 是图表标题自动预填的“锦上添花”，失败由调用方降级为手动填写。
    """

    files = {"file": (filename, content, content_type)}
    try:
        async with httpx.AsyncClient(
            base_url=OCR_WORKER_URL,
            timeout=_timeout(OCR_REGION_TIMEOUT),
            trust_env=False,
        ) as client:
            response = await client.post("/ocr/region", files=files)
    except (httpx.HTTPError, OSError) as exc:
        raise OcrWorkerError(f"无法连接 OCR Worker：{exc}") from exc

    if response.status_code >= 400:
        raise OcrWorkerError(
            f"OCR Worker 识别失败（HTTP {response.status_code}）：{_worker_detail(response)}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise OcrWorkerError("OCR Worker 返回了非 JSON 响应") from exc
    if not isinstance(payload, dict):
        raise OcrWorkerError("OCR Worker 返回格式不正确")
    return payload


async def download_result(task_id: str, destination: Path) -> None:
    """流式下载结果 ZIP，先写 .part 再原子替换。"""

    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(destination.name + ".part")
    try:
        async with httpx.AsyncClient(
            base_url=OCR_WORKER_URL,
            timeout=_timeout(OCR_DOWNLOAD_TIMEOUT),
            trust_env=False,
        ) as client:
            async with client.stream("GET", f"/tasks/{task_id}/result.zip") as response:
                if response.status_code == 404:
                    raise OcrWorkerError("OCR 结果不存在")
                if response.status_code >= 400:
                    await response.aread()
                    raise OcrWorkerError(
                        "下载 OCR 结果失败"
                        f"（HTTP {response.status_code}）：{_worker_detail(response)}"
                    )
                total = 0
                with part_path.open("wb") as handle:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_RESULT_ZIP_BYTES:
                            raise OcrWorkerError("OCR 结果 ZIP 超过大小限制")
                        handle.write(chunk)
        if not part_path.is_file() or part_path.stat().st_size == 0:
            raise OcrWorkerError("OCR 结果 ZIP 为空")
        part_path.replace(destination)
    except OcrWorkerError:
        part_path.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, OSError) as exc:
        part_path.unlink(missing_ok=True)
        raise OcrWorkerError(f"下载 OCR 结果失败：{exc}") from exc
