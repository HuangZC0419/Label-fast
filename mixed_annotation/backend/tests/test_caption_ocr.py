"""图表标题自动预填的提取逻辑单测（纯函数，不依赖 OCR Worker）。"""

from __future__ import annotations

from services.caption_service import build_caption_result, extract_caption


def _lines(*texts: str, score: float = 0.95) -> list[dict]:
    return [{"text": text, "score": score} for text in texts]


def test_extract_common_caption() -> None:
    assert extract_caption(_lines("图3 液压系统原理图")) == "图3 液压系统原理图"
    assert extract_caption(_lines("图 3：液压系统原理图")) == "图3 液压系统原理图"
    assert extract_caption(_lines("表2 A-A方向D的减小值")) == "表2 A-A方向D的减小值"


def test_extract_attached_caption_without_separator() -> None:
    # 中文规范里最常见的紧凑写法：编号后直接接标题。
    assert extract_caption(_lines("图1单元面积示例")) == "图1 单元面积示例"
    assert extract_caption(_lines("表2A-A方向D的减小值")) == "表2 A-A方向D的减小值"


def test_extract_number_only_caption() -> None:
    assert extract_caption(_lines("图1")) == "图1"
    assert extract_caption(_lines("OCR 其他文字", "表 2")) == "表2"


def test_extract_section_numbers_and_full_width() -> None:
    assert extract_caption(_lines("图 1.2 零件图")) == "图1.2 零件图"
    assert extract_caption(_lines("图３ 液压系统")) == "图3 液压系统"


def test_ignore_body_references() -> None:
    # 没有分隔符的正文引用，以及「图3 所示…」都不应当作标题。
    assert extract_caption(_lines("图3所示结构应满足要求")) == ""
    assert extract_caption(_lines("如图3 所示，应满足要求")) == ""
    assert extract_caption(_lines("图3 中所列的数值")) == ""
    assert extract_caption(_lines("图3和图4的尺寸")) == ""
    assert extract_caption(_lines("图3为示意结构")) == ""


def test_remove_spaces_between_chinese_characters() -> None:
    assert extract_caption(_lines("图3 液 压 系 统")) == "图3 液压系统"


def test_join_caption_split_across_lines() -> None:
    # OCR 把「表 1」和标题拆成两行时，向后一行补标题。
    assert (
        extract_caption(_lines("表1", "软线拉力试验", "类型", "重物质量/kg"))
        == "表1 软线拉力试验"
    )
    # 下一行是表头时不能拿来当标题，只能保留编号。
    assert extract_caption(_lines("表1", "类型", "重物质量/kg")) == "表1"


def test_skip_low_confidence_lines() -> None:
    assert extract_caption(_lines("图3 液压系统", score=0.2)) == ""


def test_build_caption_result_shape() -> None:
    result = build_caption_result(
        {
            "lines": [
                {"text": "图 4 试验装置", "score": 0.9876, "top": 10, "left": 2},
                {"text": "其余说明", "score": 0.9, "top": 40, "left": 2},
            ]
        }
    )
    assert result["caption"] == "图4 试验装置"
    assert result["text"] == "图 4 试验装置\n其余说明"
    assert result["lines"] == [
        {"text": "图 4 试验装置", "score": 0.9876},
        {"text": "其余说明", "score": 0.9},
    ]
