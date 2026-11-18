import sys
sys.path.insert(0, ".")
from data_cleaning import (
    get_template_prefix,
    remove_template_duplicates,
    split_guobiao_label,
    filter_short_entities,
    validate_annotations,
)


def test_remove_template_duplicates():
    """相似前缀的样本应被限制在 max_per_template 条以内"""
    examples = [
        {"text": "操作人员需严格按照车削工艺规范执行。", "entities": []},
        {"text": "操作人员需严格按照铣削工艺规范执行。", "entities": []},
        {"text": "操作人员需严格按照磨削工艺规范执行。", "entities": []},
        {"text": "供应商需提供弹簧钢的材质证明书。", "entities": []},
        {"text": "供应商需提供轴承钢的材质证明书。", "entities": []},
        {"text": "供应商需提供不锈钢的材质证明书。", "entities": []},
        {"text": "完全不同的句子内容。", "entities": []},
    ]
    result = remove_template_duplicates(examples, max_per_template=2)
    assert len(result) <= 5


def test_split_guobiao_label():
    """国标标签应根据书名号拆分为标准编号和标准全称"""
    examples = [
        {"text": "材料性能测试按照 GB/T 3190-2020 执行。", "entities": [
            {"start_offset": 9, "end_offset": 23, "label": "国标"}
        ]},
        {"text": "操作规范详见《GB/T 699-2015 优质碳素结构钢》。", "entities": [
            {"start_offset": 7, "end_offset": 20, "label": "国标"}
        ]},
    ]
    result = split_guobiao_label(examples)
    # 第一条: 无书名号 → 标准编号
    assert result[0]["entities"][0]["label"] == "标准编号"
    # 确认没有「国标」标签残留
    labels = {e["label"] for ex in result for e in ex.get("entities", [])}
    assert "国标" not in labels


def test_filter_short_entities():
    """1 字符实体应被过滤"""
    examples = [
        {"text": "该丝杠的加工精度要求较高。", "entities": [
            {"start_offset": 1, "end_offset": 2, "label": "零件"}
        ]},
        {"text": "该零件需进行珩磨处理。", "entities": [
            {"start_offset": 6, "end_offset": 8, "label": "工艺"}
        ]},
    ]
    result = filter_short_entities(examples, min_len=2)
    assert len(result[0]["entities"]) == 0
    assert len(result[1]["entities"]) == 1


def test_validate_annotations():
    """验证标注数据格式"""
    examples = [
        {"text": "正常样本", "entities": [{"start_offset": 0, "end_offset": 2, "label": "零件"}]},
        {"text": "异常样本", "entities": [{"start_offset": 0, "end_offset": 5, "label": "零件"}]},
        {"text": "", "entities": []},
    ]
    valid, issues = validate_annotations(examples)
    assert len(issues) > 0
    assert len(valid) == 1


# ---------- Bug 修复覆盖测试 ----------

def test_split_guobiao_label_adjacent_book_titles():
    """Bug1: 相邻书名号《A》《B》不应误匹配"""
    # 《标准A》《标准B》——实体"标准B"不应误匹配到标准A的《
    examples = [
        {"text": "参见《GB/T 1》《GB/T 2》规定。", "entities": [
            {"start_offset": 12, "end_offset": 17, "label": "国标"},   # GB/T 2
        ]},
    ]
    result = split_guobiao_label(examples)
    # 实体在第二个书名号内，应该被识别为"标准全称"
    assert result[0]["entities"][0]["label"] == "标准全称"


def test_validate_annotations_none_offsets():
    """Bug2: start_offset 或 end_offset 为 None 时不应崩溃"""
    examples = [
        {"text": "测试文本", "entities": [
            {"start_offset": None, "end_offset": 3, "label": "A"},
            {"start_offset": 0, "end_offset": None, "label": "B"},
            {"start_offset": 0, "end_offset": 2, "label": "C"},
        ]},
    ]
    valid, issues = validate_annotations(examples)
    # 前两个实体的 offset 为 None，应产生 2 条 issue
    # 第三个实体有效
    assert len(issues) == 1
    assert "start_offset 或 end_offset 为 None" in str(issues[0]["issues"])
    # 不应该崩溃


def test_filter_short_entities_missing_keys():
    """Bug3: 实体缺少 end_offset/start_offset 字段时不抛 KeyError"""
    examples = [
        {"text": "测试", "entities": [
            {"label": "A"},                          # 缺少两个字段
            {"start_offset": 0, "end_offset": 5, "label": "B"},
        ]},
    ]
    # 不应抛出 KeyError，对缺字段实体长度视为 0，被过滤掉
    result = filter_short_entities(examples, min_len=2)
    assert len(result[0]["entities"]) == 1  # 只有 B 保留


def test_get_template_prefix_empty_text():
    """Bug4: 空文本应返回 None，避免所有空文本共享 key ''"""
    # 空字符串
    assert get_template_prefix("") is None
    # 仅空格/换行
    assert get_template_prefix("   ") is None
    assert get_template_prefix("\n\n") is None
    assert get_template_prefix(" \n ") is None
    # 有效文本
    assert get_template_prefix("Hello World") == "HelloW"
    assert get_template_prefix("   abcdefg") == "abcdef"


def test_remove_template_duplicates_empty_text():
    """Bug4: 多个空文本不应被模板去重误合并"""
    examples = [
        {"text": "", "entities": []},
        {"text": "", "entities": []},
        {"text": "", "entities": []},
        {"text": "正常文本A", "entities": []},
        {"text": "正常文本B", "entities": []},
    ]
    # max_per_template=1，但空文本不参与去重，应全部保留
    result = remove_template_duplicates(examples, max_per_template=1)
    assert len(result) == 5  # 3 empty + 2 normal, 全部保留
