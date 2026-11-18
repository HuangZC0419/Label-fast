"""文档到 Markdown 的转换流程与结果打包。

转换入口按 ``OCR_ENGINE`` / 请求参数选择引擎：

- ``mineru``：调用 CFwin11 环境内的 MinerU 常驻 API（优先）或子进程；
- ``paddle``：已禁用（Paddle C++ 无法读取中文项目路径）；
- ``auto``：使用 MinerU；不可用时给出明确错误，不再回退 Paddle。

两个引擎产出同样的 ``out/result.md``、``out/images/``、``out/pages.json``
与 ``result.zip``，主后端与前端契约保持不变。
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import engine as paddle_engine
from page_layout import assemble_pages

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, Optional[int]], None]


@dataclass
class ConversionResult:
    page_count: int
    markdown_chars: int
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)
    engine: str = "paddle"


def _noop_progress(_: int, __: str, ___: int | None) -> None:
    return


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _image_size(path: Path) -> tuple[float, float]:
    """读取图片像素尺寸；失败时返回 (0, 0)，不阻断转换。"""

    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
        return float(width), float(height)
    except Exception:
        logger.warning("读取图片尺寸失败：%s", path, exc_info=True)
        return 0.0, 0.0


def write_pages(output_dir: Path, page_map: list[dict]) -> None:
    payload = {"version": 1, "page_count": len(page_map), "pages": page_map}
    _write_text(
        output_dir / "pages.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


# 兼容旧名称（仅模块内部使用，保留别名避免外部脚本失效）。
_write_pages = write_pages


def build_result_zip(output_dir: Path, result_zip: Path) -> None:
    temp_zip = result_zip.with_name(result_zip.name + ".part")
    temp_zip.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            temp_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            result_md = output_dir / "result.md"
            archive.write(result_md, "result.md")
            archive.write(output_dir / "pages.json", "pages.json")
            # 即使没有图片也保留 images/ 目录，保持结果契约稳定。
            archive.writestr("images/", b"")
            images_dir = output_dir / "images"
            if images_dir.is_dir():
                for path in sorted(images_dir.rglob("*")):
                    if path.is_file():
                        archive.write(
                            path,
                            f"images/{path.relative_to(images_dir).as_posix()}",
                        )
        temp_zip.replace(result_zip)
    except BaseException:
        temp_zip.unlink(missing_ok=True)
        raise


# 兼容旧名称。
_build_result_zip = build_result_zip


def _convert_with_paddle(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback | None = None,
) -> ConversionResult:
    """原有 PaddleOCR PP-StructureV3 流程（CPU）。"""

    report = progress or _noop_progress
    started = time.perf_counter()
    output_dir = task_dir / "out"
    images_dir = output_dir / "images"
    pages_dir = task_dir / ".pages"
    shutil.rmtree(output_dir, ignore_errors=True)
    shutil.rmtree(pages_dir, ignore_errors=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    extension = source_path.suffix.lower()
    is_pdf = extension == ".pdf"
    pages: list[dict] = []
    page_count = 0
    pipeline = None
    pdf_document = None

    try:
        if is_pdf:
            try:
                import fitz  # PyMuPDF
            except ImportError as exc:
                raise RuntimeError("缺少 PyMuPDF，请安装 pymupdf") from exc

            pdf_document = fitz.open(str(source_path))
            if pdf_document.needs_pass or pdf_document.is_encrypted:
                raise RuntimeError("PDF 已加密，当前不支持解析")
            page_count = int(pdf_document.page_count)
            if page_count <= 0:
                raise RuntimeError("PDF 没有可处理的页面")
        else:
            page_count = 1

        image_width, image_height = 0.0, 0.0
        if not is_pdf:
            image_width, image_height = _image_size(source_path)

        report(1, "加载 OCR 模型", page_count)
        pipeline = paddle_engine.get_pipeline(enable_table, enable_formula)
        report(5, "OCR 模型已加载", page_count)

        for index in range(page_count):
            page_number = index + 1
            if is_pdf:
                render_progress = 6 + int((2 * index) / (2 * page_count) * 88)
                report(render_progress, f"渲染第 {page_number}/{page_count} 页", page_count)
                page = pdf_document.load_page(index)
                page_width = float(page.rect.width)
                page_height = float(page.rect.height)
                pixmap = page.get_pixmap(
                    dpi=dpi, alpha=False, colorspace=fitz.csRGB
                )
                page_image = pages_dir / f"page_{page_number:04d}.png"
                pixmap.save(str(page_image))

                ocr_progress = 6 + int((2 * index + 1) / (2 * page_count) * 88)
                report(ocr_progress, f"OCR 第 {page_number}/{page_count} 页", page_count)
            else:
                page_image = source_path
                page_width = image_width
                page_height = image_height
                report(10, f"OCR 第 {page_number}/{page_count} 页", page_count)

            markdown_text, continuation = paddle_engine.process_image(
                pipeline, page_image, images_dir, page_number
            )
            page_info: dict = {
                "page": page_number,
                "width": page_width,
                "height": page_height,
                "markdown_texts": markdown_text,
            }
            if continuation is not None:
                page_info["page_continuation_flags"] = continuation
            page_info["markdown_images"] = {}
            pages.append(page_info)

            if is_pdf:
                page_image.unlink(missing_ok=True)

        report(94, "生成 Markdown", page_count)
        markdown, page_map = assemble_pages(pages)
        _write_text(output_dir / "result.md", markdown)
        write_pages(output_dir, page_map)

        report(98, "打包结果", page_count)
        build_result_zip(output_dir, task_dir / "result.zip")

        elapsed = time.perf_counter() - started
        logger.info(
            "Paddle 转换完成：%s，页数=%s，Markdown=%s 字符，耗时=%.2fs",
            source_path.name,
            page_count,
            len(markdown),
            elapsed,
        )
        return ConversionResult(
            page_count=page_count,
            markdown_chars=len(markdown),
            elapsed_seconds=elapsed,
            warnings=paddle_engine.get_warnings(),
            engine="paddle",
        )
    finally:
        if pdf_document is not None:
            try:
                pdf_document.close()
            except Exception:
                logger.debug("关闭 PDF 失败", exc_info=True)
        shutil.rmtree(pages_dir, ignore_errors=True)


def _requested_mode(engine_override: str | None) -> str:
    """返回本次请求的原始模式（auto/mineru/paddle），用于决定是否回退。"""

    import config

    if engine_override is not None and str(engine_override).strip():
        mode = str(engine_override).strip().lower()
    else:
        mode = (config.OCR_ENGINE or "auto").strip().lower() or "auto"
    # 非法配置按 select_engine 的降级规则处理，避免“看起来是 auto
    # 实际不回退”的不一致。
    return mode if mode in {"auto", "mineru", "paddle"} else "auto"


def convert_document(
    source_path: Path,
    task_dir: Path,
    *,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    progress: ProgressCallback | None = None,
    engine: str | None = None,
) -> ConversionResult:
    """转换 PDF 或图片，写出 ``out/result.md``、``out/pages.json``、
    ``out/images/`` 与 ``result.zip``。

    ``engine`` 为空时使用 ``OCR_ENGINE``；``auto`` 模式下 MinerU
    失败会回退 PaddleOCR，并在 ``warnings`` 中说明原因。
    """

    # 延迟导入：select_engine 只依赖 config，但保持模块级依赖轻量，
    # 便于在没有 MinerU 的部署环境（Docker/Win7）照常导入本模块。
    import mineru_engine

    report = progress or _noop_progress
    # 空字符串表示“未指定”，交给 OCR_ENGINE 决定；只有显式值才覆盖配置。
    override = (engine or "").strip() or None
    selected = mineru_engine.select_engine(override)

    if selected == "paddle":
        raise RuntimeError(
            "PaddleOCR 回退已禁用：项目位于中文路径，Paddle C++ 无法读取模型/图片路径；"
            "请使用 MinerU（OCR_ENGINE=mineru 或 auto）。"
        )

    return mineru_engine.convert_with_mineru(
        source_path,
        task_dir,
        enable_table=enable_table,
        enable_formula=enable_formula,
        dpi=dpi,
        progress=report,
    )
