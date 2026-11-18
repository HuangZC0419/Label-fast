"""PaddleOCR PP-StructureV3 引擎封装。

PaddleOCR 仅在首次真正转换时导入，避免 Worker 启动即加载数百 MB 模型。
同一时刻只保留一套与当前表格/公式开关匹配的 pipeline，降低 CPU 环境内存占用。
"""

from __future__ import annotations

import gc
import inspect
import logging
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any

from config import FAST_MODE, PADDLE_CACHE_DIR

logger = logging.getLogger(__name__)

_pipeline: Any | None = None
_pipeline_key: tuple[bool, bool] | None = None
_pipeline_warnings: list[str] = []
_pipeline_lock = threading.RLock()


def _pipeline_kwargs(enable_table: bool, enable_formula: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "device": "cpu",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "use_seal_recognition": False,
        "use_table_recognition": bool(enable_table),
        "use_formula_recognition": bool(enable_formula),
    }
    if FAST_MODE:
        kwargs.update(
            {
                "layout_detection_model_name": "PP-DocLayout-S",
                "text_detection_model_name": "PP-OCRv5_mobile_det",
                "text_recognition_model_name": "PP-OCRv5_mobile_rec",
            }
        )
    return kwargs


def _create_pipeline(enable_table: bool, enable_formula: bool) -> tuple[Any, list[str]]:
    PADDLE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from paddleocr import PPStructureV3
    except Exception as exc:  # ImportError 之外也可能是 paddle 动态库加载失败
        raise RuntimeError(
            "无法导入 paddleocr，请先安装 OCR Worker 依赖并确认 PaddlePaddle 可用"
        ) from exc

    desired = _pipeline_kwargs(enable_table, enable_formula)
    warnings: list[str] = []
    try:
        signature = inspect.signature(PPStructureV3.__init__)
        parameters = signature.parameters
        accepts_kwargs = any(
            param.kind is inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        )
        if not accepts_kwargs:
            unsupported = [key for key in desired if key not in parameters]
            for key in unsupported:
                warnings.append(f"当前 PaddleOCR 版本不支持参数 {key}，已使用默认值")
                desired.pop(key)
    except (TypeError, ValueError):
        # 无法读取签名时直接尝试官方参数，出错由构造函数抛出。
        pass

    logger.info(
        "初始化 PP-StructureV3：table=%s formula=%s fast=%s cache=%s",
        enable_table,
        enable_formula,
        FAST_MODE,
        PADDLE_CACHE_DIR,
    )
    try:
        pipeline = PPStructureV3(**desired)
    except (TypeError, ValueError) as exc:
        # 版本差异兜底：仅移除明确报错中的未知参数，保留真实初始化错误。
        text = str(exc)
        lowered = text.lower()
        unknown_marker = any(
            marker in lowered
            for marker in ("unexpected keyword", "invalid keyword", "unknown argument")
        )
        removed: list[str] = []
        if unknown_marker:
            for key in list(desired):
                if key in text:
                    warnings.append(
                        f"当前 PaddleOCR 版本不支持参数 {key}，已使用默认值"
                    )
                    desired.pop(key)
                    removed.append(key)
        if not removed:
            raise
        pipeline = PPStructureV3(**desired)
    return pipeline, warnings


def get_pipeline(enable_table: bool, enable_formula: bool) -> Any:
    """按开关获取 pipeline；开关变化时释放旧实例。"""

    global _pipeline, _pipeline_key, _pipeline_warnings
    key = (bool(enable_table), bool(enable_formula))
    with _pipeline_lock:
        if _pipeline is not None and _pipeline_key == key:
            return _pipeline
        if _pipeline is not None:
            close = getattr(_pipeline, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("关闭旧 PP-StructureV3 pipeline 失败", exc_info=True)
            _pipeline = None
            _pipeline_key = None
            gc.collect()
        pipeline, warnings = _create_pipeline(*key)
        _pipeline = pipeline
        _pipeline_key = key
        _pipeline_warnings = warnings
        return pipeline


def get_warnings() -> list[str]:
    with _pipeline_lock:
        return list(_pipeline_warnings)


def pipeline_loaded() -> bool:
    return _pipeline is not None


def _image_suffix(key: str) -> str:
    suffix = Path(str(key)).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def _save_image(image: Any, destination: Path, suffix: str) -> bool:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(image, (bytes, bytearray)):
            destination.write_bytes(bytes(image))
            return True
        if not hasattr(image, "save"):
            return False
        if suffix == ".jpg" and getattr(image, "mode", "RGB") not in {"RGB", "L"}:
            image = image.convert("RGB")
        fmt = {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".webp": "WEBP",
            ".bmp": "BMP",
            ".gif": "GIF",
        }.get(suffix, "PNG")
        image.save(destination, format=fmt)
        return True
    except Exception:
        logger.warning("保存 Markdown 图片失败：%s", destination, exc_info=True)
        return False


def _replace_image_references(text: str, old_key: str, new_relpath: str) -> str:
    variants = {
        old_key,
        old_key.replace("\\", "/"),
        old_key.lstrip("./"),
        f"./{old_key.lstrip('./')}",
    }
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            text = text.replace(variant, new_relpath)
    return text


def _materialize_markdown_images(
    markdown_text: str,
    markdown_images: Any,
    images_dir: Path,
    page_number: int,
    counter_start: int,
) -> tuple[str, int]:
    counter = counter_start
    if not isinstance(markdown_images, dict):
        return markdown_text, counter

    for key, image in markdown_images.items():
        key_text = str(key)
        suffix = _image_suffix(key_text)
        filename = f"p{page_number:04d}_{counter:03d}{suffix}"
        target = images_dir / filename
        if not _save_image(image, target, suffix):
            continue
        counter += 1
        markdown_text = _replace_image_references(
            markdown_text, key_text, f"images/{filename}"
        )
    return markdown_text, counter


def _fallback_save_to_markdown(
    result: Any,
    images_dir: Path,
    page_number: int,
    counter_start: int,
) -> tuple[str, int]:
    """兼容旧版本：使用 result.save_to_markdown 的输出。"""

    counter = counter_start
    save_to_markdown = getattr(result, "save_to_markdown", None)
    if not callable(save_to_markdown):
        return "", counter

    temp_dir = images_dir.parent / f".fallback-{page_number:04d}-{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        save_to_markdown(save_path=str(temp_dir))
        markdown_files = sorted(temp_dir.rglob("*.md"))
        if not markdown_files:
            return "", counter

        replacements: list[tuple[str, str]] = []
        for asset in sorted(temp_dir.rglob("*")):
            if not asset.is_file() or asset.suffix.lower() == ".md":
                continue
            suffix = _image_suffix(asset.name)
            filename = f"p{page_number:04d}_{counter:03d}{suffix}"
            target = images_dir / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset, target)
            counter += 1
            new_relative = f"images/{filename}"
            replacements.append(
                (asset.relative_to(temp_dir).as_posix(), new_relative)
            )
            replacements.append((asset.name, new_relative))

        chunks: list[str] = []
        for md_file in markdown_files:
            text = md_file.read_text(encoding="utf-8", errors="replace")
            for old_value, new_value in replacements:
                text = _replace_image_references(text, old_value, new_value)
            chunks.append(text.strip())
        return "\n\n".join(chunk for chunk in chunks if chunk), counter
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def process_image(
    pipeline: Any,
    image_path: Path,
    images_dir: Path,
    page_number: int,
) -> tuple[str, tuple[bool, bool] | None]:
    """识别单页图片，返回 Markdown 和页延续标记。"""

    output = pipeline.predict(input=str(image_path))
    if output is None:
        return "", None
    try:
        results = list(output)
    except TypeError:
        results = [output]

    chunks: list[str] = []
    continuation: tuple[bool, bool] | None = None
    counter = 1

    for result in results:
        md_info: Any = None
        try:
            md_info = getattr(result, "markdown", None)
        except Exception:
            logger.warning("读取 result.markdown 失败", exc_info=True)

        text = ""
        if isinstance(md_info, dict):
            raw_text = md_info.get("markdown_texts", "")
            if isinstance(raw_text, list):
                text = "\n".join(str(item) for item in raw_text)
            else:
                text = str(raw_text or "")
            text, counter = _materialize_markdown_images(
                text,
                md_info.get("markdown_images", {}),
                images_dir,
                page_number,
                counter,
            )
            flags = md_info.get("page_continuation_flags")
            if continuation is None and isinstance(flags, (tuple, list)) and len(flags) == 2:
                continuation = (bool(flags[0]), bool(flags[1]))

        if not text.strip():
            fallback_text, counter = _fallback_save_to_markdown(
                result, images_dir, page_number, counter
            )
            text = fallback_text

        if text.strip():
            chunks.append(text.strip())

    return "\n\n".join(chunks), continuation
