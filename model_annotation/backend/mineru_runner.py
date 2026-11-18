import argparse
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


def str2bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MinerU runtime wrapper with quality-oriented overrides")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--backend", default="", help="Resolved MinerU backend")
    parser.add_argument("--language", default="", help="Resolved MinerU language")
    parser.add_argument("--parse-method", default="auto", help="MinerU parse method: auto|ocr|txt")
    parser.add_argument("--formula", default="false", help="Enable formula parsing")
    parser.add_argument("--table", default="true", help="Enable table parsing")
    parser.add_argument("--high-accuracy", default="true", help="Enable quality-first runtime tuning")
    return parser


def _wrap_with_dpi(func: Callable[..., Any], dpi: int) -> Callable[..., Any]:
    def wrapper(*args, **kwargs):
        kwargs.setdefault("dpi", dpi)
        return func(*args, **kwargs)

    return wrapper


def _patch_pdf_render_dpi(dpi: int) -> None:
    import mineru.utils.pdf_image_tools as pdf_image_tools

    pdf_image_tools.DEFAULT_PDF_IMAGE_DPI = dpi
    pdf_image_tools.pdf_page_to_image = _wrap_with_dpi(pdf_image_tools.pdf_page_to_image, dpi)
    pdf_image_tools.load_images_from_pdf_core = _wrap_with_dpi(pdf_image_tools.load_images_from_pdf_core, dpi)
    pdf_image_tools.load_images_from_pdf_doc = _wrap_with_dpi(pdf_image_tools.load_images_from_pdf_doc, dpi)
    pdf_image_tools._load_images_from_pdf_bytes_range = _wrap_with_dpi(
        pdf_image_tools._load_images_from_pdf_bytes_range,
        dpi,
    )

    for module_name in (
        "mineru.backend.pipeline.pipeline_analyze",
        "mineru.backend.hybrid.hybrid_analyze",
        "mineru.backend.vlm.vlm_analyze",
    ):
        module = sys.modules.get(module_name)
        if isinstance(module, ModuleType) and hasattr(module, "load_images_from_pdf_doc"):
            setattr(module, "load_images_from_pdf_doc", _wrap_with_dpi(module.load_images_from_pdf_doc, dpi))


def _patch_small_text_runtime(
    *,
    min_confidence: float,
    min_width: int,
    span_contrast_threshold: float,
    limited_min_width: int,
) -> None:
    import cv2
    import numpy as np

    import mineru.backend.hybrid.hybrid_model_output_to_middle_json as hybrid_middle_json
    import mineru.backend.pipeline.batch_analyze as pipeline_batch_analyze
    import mineru.backend.pipeline.model_json_to_middle_json as pipeline_middle_json
    import mineru.model.ocr.pytorch_paddle as pytorch_paddle
    import mineru.utils.ocr_utils as ocr_utils
    import mineru.utils.span_pre_proc as span_pre_proc
    from mineru.utils.pdf_image_tools import get_crop_img

    def enhance_small_text_crop(image: Any, *, aggressive: bool = False) -> Any:
        if image is None or getattr(image, "size", 0) == 0:
            return image

        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        height, width = image.shape[:2]
        is_tiny = height <= 32 or width <= 120 or (height * width) <= 7000

        border = 4 if is_tiny else 2
        image = cv2.copyMakeBorder(
            image,
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=[255, 255, 255],
        )

        target_height = 80 if aggressive else 64
        target_width = 224 if aggressive else 160
        scale = max(
            1.0,
            target_height / max(image.shape[0], 1),
            target_width / max(image.shape[1], 1),
        )
        scale = min(scale, 4.0 if aggressive else 3.2)
        if scale > 1.05:
            image = cv2.resize(
                image,
                (max(1, int(round(image.shape[1] * scale))), max(1, int(round(image.shape[0] * scale)))),
                interpolation=cv2.INTER_CUBIC,
            )

        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0 if aggressive else 2.4, tileGridSize=(8, 8))
        l_channel = clahe.apply(l_channel)
        image = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)

        blurred = cv2.GaussianBlur(image, (0, 0), 0.8 if aggressive else 0.6)
        image = cv2.addWeighted(image, 1.45 if aggressive else 1.28, blurred, -0.45 if aggressive else -0.28, 0)

        return np.clip(image, 0, 255).astype(np.uint8)

    original_crop = ocr_utils.get_rotate_crop_image_for_text_rec
    if not getattr(original_crop, "_mineru_small_text_patched", False):
        def patched_crop(img, points):
            crop = original_crop(img, points)
            return enhance_small_text_crop(crop)

        patched_crop._mineru_small_text_patched = True
        ocr_utils.get_rotate_crop_image_for_text_rec = patched_crop
        pytorch_paddle.get_rotate_crop_image_for_text_rec = patched_crop
        pipeline_batch_analyze.get_rotate_crop_image_for_text_rec = patched_crop

    original_rotate_vertical = ocr_utils.rotate_vertical_crop_if_needed
    if not getattr(original_rotate_vertical, "_mineru_small_text_patched", False):
        def patched_rotate_vertical(crop_img, rotate_ratio=ocr_utils.TEXT_REC_ROTATE_RATIO):
            crop_img = original_rotate_vertical(crop_img, rotate_ratio=rotate_ratio)
            return enhance_small_text_crop(crop_img)

        patched_rotate_vertical._mineru_small_text_patched = True
        ocr_utils.rotate_vertical_crop_if_needed = patched_rotate_vertical
        pipeline_middle_json.rotate_vertical_crop_if_needed = patched_rotate_vertical
        hybrid_middle_json.rotate_vertical_crop_if_needed = patched_rotate_vertical

    original_prepare_post_ocr_spans = span_pre_proc._prepare_post_ocr_spans
    if not getattr(original_prepare_post_ocr_spans, "_mineru_small_text_patched", False):
        def patched_prepare_post_ocr_spans(need_ocr_spans, spans, pil_img, scale):
            if len(need_ocr_spans) == 0:
                return spans

            for span in need_ocr_spans:
                span_pil_img = get_crop_img(span["bbox"], pil_img, scale)
                span_img = cv2.cvtColor(np.array(span_pil_img), cv2.COLOR_RGB2BGR)

                raw_contrast = span_pre_proc.calculate_contrast(span_img, img_mode="bgr")
                height, width = span_img.shape[:2]
                is_tiny = height <= 28 or width <= 112 or (height * width) <= 6000
                enhanced_img = enhance_small_text_crop(
                    span_img,
                    aggressive=is_tiny or raw_contrast < (span_contrast_threshold + 0.05),
                )
                enhanced_contrast = span_pre_proc.calculate_contrast(enhanced_img, img_mode="bgr")

                if not is_tiny and max(raw_contrast, enhanced_contrast) <= span_contrast_threshold:
                    if span in spans:
                        spans.remove(span)
                    continue

                span["content"] = ""
                span["score"] = 1.0
                span["np_img"] = enhanced_img

            return spans

        patched_prepare_post_ocr_spans._mineru_small_text_patched = True
        span_pre_proc._prepare_post_ocr_spans = patched_prepare_post_ocr_spans

    ocr_utils.OcrConfidence.min_confidence = min(ocr_utils.OcrConfidence.min_confidence, min_confidence)
    ocr_utils.OcrConfidence.min_width = min(ocr_utils.OcrConfidence.min_width, min_width)

    original_init = pytorch_paddle.PytorchPaddleOCR.__init__
    if not getattr(original_init, "_mineru_small_text_init_patched", False):
        def patched_init(self, *args, **kwargs):
            kwargs["limited_min_width"] = max(int(kwargs.get("limited_min_width", 16)), limited_min_width)
            return original_init(self, *args, **kwargs)

        patched_init._mineru_small_text_init_patched = True
        pytorch_paddle.PytorchPaddleOCR.__init__ = patched_init


def _patch_ocr_runtime(
    *,
    det_db_box_thresh: float,
    det_db_unclip_ratio: float,
    det_limit_side_len: int,
    drop_score: float,
) -> None:
    from mineru.model.ocr import pytorch_paddle

    original_init = pytorch_paddle.PytorchPaddleOCR.__init__
    if getattr(original_init, "_mineru_quality_patched", False):
        return

    def patched_init(self, *args, **kwargs):
        kwargs["det_db_box_thresh"] = min(float(kwargs.get("det_db_box_thresh", 0.3)), det_db_box_thresh)
        kwargs["det_db_unclip_ratio"] = max(float(kwargs.get("det_db_unclip_ratio", 1.8)), det_db_unclip_ratio)
        kwargs["det_limit_side_len"] = max(int(kwargs.get("det_limit_side_len", 960)), det_limit_side_len)
        kwargs["drop_score"] = min(float(kwargs.get("drop_score", 0.5)), drop_score)
        return original_init(self, *args, **kwargs)

    patched_init._mineru_quality_patched = True
    pytorch_paddle.PytorchPaddleOCR.__init__ = patched_init


def apply_quality_overrides(high_accuracy: bool) -> None:
    if high_accuracy:
        render_dpi = 560
        det_db_box_thresh = 0.18
        det_db_unclip_ratio = 2.3
        det_limit_side_len = 1536
        drop_score = 0.28
        min_confidence = 0.36
        min_width = 2
        span_contrast_threshold = 0.12
        limited_min_width = 32
    else:
        render_dpi = 220
        det_db_box_thresh = 0.28
        det_db_unclip_ratio = 1.9
        det_limit_side_len = 1088
        drop_score = 0.45
        min_confidence = 0.5
        min_width = 3
        span_contrast_threshold = 0.17
        limited_min_width = 16

    os.environ.setdefault("MINERU_PROCESSING_WINDOW_SIZE", "48")
    _patch_pdf_render_dpi(render_dpi)
    _patch_ocr_runtime(
        det_db_box_thresh=det_db_box_thresh,
        det_db_unclip_ratio=det_db_unclip_ratio,
        det_limit_side_len=det_limit_side_len,
        drop_score=drop_score,
    )
    _patch_small_text_runtime(
        min_confidence=min_confidence,
        min_width=min_width,
        span_contrast_threshold=span_contrast_threshold,
        limited_min_width=limited_min_width,
    )
    print(
        "MinerU quality overrides active: "
        f"dpi={render_dpi}, det_db_box_thresh={det_db_box_thresh}, "
        f"det_db_unclip_ratio={det_db_unclip_ratio}, det_limit_side_len={det_limit_side_len}, "
        f"drop_score={drop_score}, min_confidence={min_confidence}, "
        f"min_width={min_width}, span_contrast_threshold={span_contrast_threshold}, "
        f"limited_min_width={limited_min_width}",
        flush=True,
    )


def configure_model_source() -> str:
    # Default to ModelScope in this wrapper to avoid HuggingFace SSL/certificate issues.
    model_source = os.getenv("MINERU_MODEL_SOURCE")
    if not model_source:
        model_source = "modelscope"
        os.environ["MINERU_MODEL_SOURCE"] = model_source
    return model_source


def resolve_effective_parse_method(parse_method: str, high_accuracy: bool) -> str:
    normalized = (parse_method or "auto").strip().lower()
    # In quality-first mode, prefer real OCR over PDF text-layer extraction.
    # This avoids broken standards PDFs losing digits, slashes and section markers.
    if high_accuracy and normalized == "auto":
        return "ocr"
    return normalized


def main() -> int:
    args = build_parser().parse_args()

    model_source = configure_model_source()

    from mineru.cli.common import do_parse, read_fn

    input_path = Path(args.input)
    output_dir = args.output
    backend = args.backend or "pipeline"
    language = args.language or ""
    formula_enable = str2bool(args.formula)
    table_enable = str2bool(args.table)
    high_accuracy = str2bool(args.high_accuracy)
    parse_method = resolve_effective_parse_method(args.parse_method, high_accuracy)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    apply_quality_overrides(high_accuracy)

    print(
        "Starting MinerU parse: "
        f"backend={backend}, parse_method={parse_method}, language={language or 'auto'}, "
        f"formula={formula_enable}, table={table_enable}, model_source={model_source}",
        flush=True,
    )

    do_parse(
        output_dir=output_dir,
        pdf_file_names=[input_path.stem],
        pdf_bytes_list=[read_fn(input_path)],
        p_lang_list=[language],
        backend=backend,
        parse_method=parse_method,
        formula_enable=formula_enable,
        table_enable=table_enable,
        f_draw_layout_bbox=True,
        f_draw_span_bbox=True,
        f_dump_md=True,
        f_dump_middle_json=True,
        f_dump_model_output=True,
        f_dump_orig_pdf=True,
        f_dump_content_list=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
