"""预下载 PP-StructureV3 模型，用于离线部署。

用法：
    python download_models.py
    python download_models.py --no-formula
    python download_models.py --image sample.png   # 额外做一次完整推理冒烟

模型默认缓存到 ``ocr_worker/models/paddlex``，可通过环境变量
``PADDLE_PDX_CACHE_HOME`` 覆盖。该变量由 config.py 在导入 paddleocr 前设置。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from config import PADDLE_CACHE_DIR

import engine


def main() -> int:
    parser = argparse.ArgumentParser(description="预下载 PaddleOCR PP-StructureV3 模型")
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="不下载表格识别子产线（默认下载）",
    )
    parser.add_argument(
        "--no-formula",
        action="store_true",
        help="不下载公式识别子产线（生产环境默认关闭公式，可减小体积）",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="可选：下载后对指定图片执行一次推理验证",
    )
    args = parser.parse_args()

    enable_table = not args.no_table
    enable_formula = not args.no_formula
    print(f"模型缓存目录: {PADDLE_CACHE_DIR}")
    print(f"下载配置: table={enable_table}, formula={enable_formula}")

    try:
        pipeline = engine.get_pipeline(enable_table, enable_formula)
    except Exception as exc:
        print(f"模型初始化/下载失败: {exc}", file=sys.stderr)
        print(
            "请确认已安装 paddlepaddle 与 paddleocr[doc-parser]，并检查网络。",
            file=sys.stderr,
        )
        return 1

    print("PP-StructureV3 模型已就绪。")
    warnings = engine.get_warnings()
    for warning in warnings:
        print(f"警告: {warning}")

    if args.image is not None:
        image = args.image.expanduser().resolve()
        if not image.is_file():
            print(f"冒烟图片不存在: {image}", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory(prefix="ppocr-smoke-") as temp_dir:
            images_dir = Path(temp_dir) / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            try:
                markdown, _ = engine.process_image(
                    pipeline, image, images_dir, page_number=1
                )
            except Exception as exc:
                print(f"推理冒烟失败: {exc}", file=sys.stderr)
                return 1
            print(f"推理成功，Markdown 长度: {len(markdown)} 字符")
            print(markdown[:1000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
