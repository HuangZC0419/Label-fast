"""区域截图的小型 OCR（RapidOCR / ONNXRuntime）。

定位：
- 只做「文字检测 + 识别」，不跑版面分析，专门用于图表截图里找「图 3 XXXX」这类标题；
- 模型随 ``rapidocr-onnxruntime`` 包内置，离线可用，不依赖 MinerU / Paddle；
- 与主转换流程互不影响：主转换用 MinerU，本模块只服务截图弹窗的标题预填。
"""

from __future__ import annotations

import threading
from io import BytesIO
from typing import Any

_engine: Any | None = None
_engine_lock = threading.Lock()
# CPU 推理串行执行：同一时刻只跑一个小图，避免并发占满核心。
_infer_lock = threading.Lock()

# 小图放大倍数上限：截图里的标题往往只有 12–16px，
# 放大到 2 倍能明显提升「图/表」这类低矮文字的可检出率，同时耗时仍只有几十毫秒。
_MAX_UPSCALE = 2.0
_MAX_PREPARED_EDGE = 1800
_UPSCALE_BELOW_EDGE = 1000


def _prepare_image(image_bytes: bytes) -> Any:
    """解码 + 白色留白 + 适度放大。

    - 标题常贴着框选边缘，四周留出少量白边能避免检测框被裁掉；
    - 小图（最长边 < 1000）放大 2 倍，提升小字号文字的识别率；
    - 用 PIL 解码，避免 OpenCV imread 读不了中文路径。
    """

    from PIL import Image

    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    width, height = image.size
    pad = max(8, round(min(width, height) * 0.06))

    prepared = Image.new("RGB", (width + pad * 2, height + pad * 2), (255, 255, 255))
    prepared.paste(image, (pad, pad))

    longest = max(prepared.size)
    if longest < _UPSCALE_BELOW_EDGE:
        scale = min(_MAX_UPSCALE, _MAX_PREPARED_EDGE / longest)
        if scale > 1.05:
            prepared = prepared.resize(
                (round(prepared.width * scale), round(prepared.height * scale)),
                Image.LANCZOS,
            )
    return prepared


def _get_engine() -> Any:
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except Exception as exc:  # ImportError 也可能是 onnxruntime 动态库问题
                raise RuntimeError(
                    "无法导入 rapidocr-onnxruntime，请安装 OCR 小图识别依赖"
                ) from exc
            # 针对“宽而扁”的截图区域做速度优化：
            # - det_limit_type=max：不再把短边放大到 736（宽表格会因此放大近 9 倍，单次 1s+）；
            # - use_cls=False：图表标题都是水平文字，省掉方向分类模型；
            # - 限制线程数，避免和 MinerU / 后端抢满 CPU。
            _engine = RapidOCR(
                use_cls=False,
                det_limit_side_len=960,
                det_limit_type="max",
                intra_op_num_threads=4,
                inter_op_num_threads=1,
            )
        return _engine


def pipeline_loaded() -> bool:
    """引擎是否已加载，供 /health 观察。"""

    return _engine is not None


def recognize(image_bytes: bytes) -> list[dict[str, Any]]:
    """识别图片文字，返回按阅读顺序（先上后下、先左后右）排序的行。

    入参用字节：OpenCV 的 ``imread`` 读不了中文路径，
    这里用 PIL 从字节解码并做留白/放大预处理，再交给 RapidOCR。
    """

    if not image_bytes:
        return []

    engine = _get_engine()
    try:
        prepared = _prepare_image(image_bytes)
    except Exception as exc:
        raise RuntimeError("截图解码失败，无法识别文字") from exc

    with _infer_lock:
        result, _elapse = engine(prepared)

    lines: list[dict[str, Any]] = []
    for item in result or []:
        try:
            box, text, score = item
        except (TypeError, ValueError):
            continue
        normalized = str(text or "").strip()
        if not normalized:
            continue
        try:
            points = [(float(point[0]), float(point[1])) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        if not points:
            continue
        top = sum(point[1] for point in points) / len(points)
        left = min(point[0] for point in points)
        lines.append(
            {
                "text": normalized,
                "score": round(float(score), 4),
                "top": round(top, 1),
                "left": round(left, 1),
            }
        )

    lines.sort(key=lambda line: (line["top"], line["left"]))
    return lines
