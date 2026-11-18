import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_store import analyze_dataset_content, analyze_examples
from model_service import parse_jsonl_training_data


SAMPLE_CONTENT = """
{"text":"依据 GB/T3191-2019 执行","spans":[{"start":3,"end":16,"label":"标准条文"}]}
{"text":"螺纹精度需符合 GB/T196-203","spans":[{"start":6,"end":17,"label":"标准条文"},{"start":6,"end":17,"label":"数值信息"}]}
{"text":"没有任何标注的句子","spans":[]}
不可解析的行
""".strip()


ANNOTATION_CONTENT = "\n".join(
    [
        (
            '{"text":"依据 GB/T3191-2019 执行",'
            '"spans":[{"start":3,"end":16,"label":"标准条文"}],'
            '"annotations":[{"label":"标准条文"},{"label":"判定结论"}]}'
        ),
        (
            '{"text":"螺纹精度需符合 GB/T196-203",'
            '"spans":[{"start":6,"end":17,"label":"标准条文"},'
            '{"start":6,"end":17,"label":"数值信息"}],'
            '"annotations":[{"label":"标准条文"},{"label":"数值信息"},'
            '{"label":"判定结论"}]}'
        ),
    ]
)


def test_analyze_examples_counts():
    examples = parse_jsonl_training_data(SAMPLE_CONTENT)
    stats = analyze_examples(examples)
    assert stats["sample_count"] == 3
    assert stats["entity_count"] == 3
    assert stats["label_count"] == 2
    assert stats["label_counts"] == {"标准条文": 2, "数值信息": 1}
    assert stats["unlabeled_sample_count"] == 1
    assert stats["char_count"] == sum(len(e["text"]) for e in examples)
    assert stats["avg_text_length"] == round(stats["char_count"] / 3, 1)


def test_analyze_dataset_content_adds_annotation_only_labels():
    stats = analyze_dataset_content(ANNOTATION_CONTENT)
    assert stats["sample_count"] == 2
    # entity_count 仍只统计 span，不因 annotation 增加。
    assert stats["entity_count"] == 3
    # 判定结论只存在于 annotations，应补齐；标准条文/数值信息已有 span，不重复计数。
    assert stats["label_counts"] == {
        "判定结论": 2,
        "标准条文": 2,
        "数值信息": 1,
    }
    assert stats["label_count"] == 3


def test_analyze_dataset_content_falls_back_to_rule_id():
    content = '{"text":"判定合格","spans":[],"annotations":[{"rule_id":"decisions"}]}'
    stats = analyze_dataset_content(content)
    assert stats["label_counts"] == {"decisions": 1}
    assert stats["label_count"] == 1


def test_parse_jsonl_skips_span_without_label():
    content = (
        '{"text":"abcdef","spans":['
        '{"start":0,"end":2},'
        '{"start":1,"end":3,"label":"L"}]}'
    )
    examples = parse_jsonl_training_data(content)
    assert examples == [
        {
            "text": "abcdef",
            "entities": [{"start_offset": 1, "end_offset": 3, "label": "L"}],
        }
    ]


def test_parse_jsonl_accepts_bom():
    content = chr(0xFEFF) + '{"text":"abc","spans":[{"start":0,"end":1,"label":"L"}]}'
    examples = parse_jsonl_training_data(content)
    assert len(examples) == 1
    assert examples[0]["text"] == "abc"
    assert examples[0]["entities"] == [
        {"start_offset": 0, "end_offset": 1, "label": "L"}
    ]


def test_parse_jsonl_skips_invalid_span_bounds_and_fields():
    content = (
        '{"text":"abc","spans":['
        '{"start":-1,"end":2,"label":"L"},'
        '{"start":2,"end":2,"label":"L"},'
        '{"start":0,"end":4,"label":"L"},'
        '{"start":"x","end":2,"label":"L"},'
        '{"start":0,"end":2,"label":""},'
        '"not-a-dict",'
        '{"start":0,"end":1,"label":"OK"}]}'
    )
    examples = parse_jsonl_training_data(content)
    assert examples[0]["entities"] == [
        {"start_offset": 0, "end_offset": 1, "label": "OK"}
    ]


def test_parse_jsonl_validates_entities_and_labels():
    entity_content = (
        '{"text":"abcd","entities":['
        '{"start_offset":0,"end_offset":2,"label":"A"},'
        '{"start_offset":3,"end_offset":9,"label":"B"},'
        '{"start_offset":"bad","end_offset":2,"label":"C"}]}'
    )
    assert parse_jsonl_training_data(entity_content)[0]["entities"] == [
        {"start_offset": 0, "end_offset": 2, "label": "A"}
    ]

    label_content = '{"text":"abcd","labels":[[0,2,"A"],[1],[2,4,""],[3,9,"B"]]}'
    assert parse_jsonl_training_data(label_content)[0]["entities"] == [
        {"start_offset": 0, "end_offset": 2, "label": "A"}
    ]


def test_parse_jsonl_ignores_non_object_lines():
    content = "[]\n5\nnull\n" + '{"text":"abc","spans":[]}'
    examples = parse_jsonl_training_data(content)
    assert examples == [{"text": "abc", "entities": []}]


def test_analyze_examples_empty():
    stats = analyze_examples([])
    assert stats["sample_count"] == 0
    assert stats["entity_count"] == 0
    assert stats["label_count"] == 0
    assert stats["label_counts"] == {}
    assert stats["avg_text_length"] == 0


def test_save_dataset_persists_original_content_and_annotation_stats(
    tmp_path, monkeypatch
):
    import dataset_store

    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    meta = dataset_store.save_dataset(ANNOTATION_CONTENT, "inline.jsonl")

    data_path = tmp_path / f"{meta['dataset_id']}.jsonl"
    assert data_path.read_text(encoding="utf-8") == ANNOTATION_CONTENT
    assert not list(tmp_path.glob("*.tmp"))
    assert meta["label_counts"]["判定结论"] == 2
    assert meta["label_count"] == 3


def test_list_datasets_skips_non_dict_and_corrupt_meta(tmp_path, monkeypatch):
    import dataset_store

    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    (tmp_path / "aaaaaaaaaaaa.meta.json").write_text("[]", encoding="utf-8")
    (tmp_path / "bbbbbbbbbbbb.meta.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "cccccccccccc.meta.json").write_text("null", encoding="utf-8")

    assert dataset_store.list_datasets() == []


def test_get_dataset_corrupt_meta_raises_file_not_found(tmp_path, monkeypatch):
    import dataset_store

    monkeypatch.setattr(dataset_store, "DATASET_BASE", str(tmp_path))
    dataset_id = "a" * 12
    (tmp_path / f"{dataset_id}.meta.json").write_text("{bad", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        dataset_store.get_dataset(dataset_id)
