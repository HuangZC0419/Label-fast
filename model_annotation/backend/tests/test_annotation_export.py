import json
import os
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.responses import Response

from main import (
    build_annotation_export_rows,
    build_export_content_disposition,
    collect_rule_spans_for_sentence,
    normalize_text_for_match,
)


SAMPLE_MD = (
    "某液压阀体采用606-T6铝合金棒料，采购标准严格执行《GB/T3191-2019铝及铝合金挤压棒材》。"
    "加工后重点检查OP20钻4×6.8通孔与OP30攻丝M8×125，螺纹精度需符合《GB/T196-203普通螺纹基本尺寸》的规定。"
    "所有尺寸经三坐标测量仪终检合格后，平面度误差不超过0.05mm。"
)


def _rows(rule_ids=None):
    return build_annotation_export_rows(
        markdown_text=SAMPLE_MD,
        task_id="task-123",
        file_name="测试文本.png",
        file_number=2,
        rule_ids=rule_ids or ["standards", "decisions", "limits", "numeric_facts"],
    )


def test_rows_have_exact_top_level_fields():
    rows = _rows()
    assert rows, "应至少导出一行"
    expected = {"file_name", "file_number", "task_id", "text", "annotations", "spans", "relations", "meta"}
    for row in rows:
        assert set(row.keys()) == expected
        assert row["file_name"] == "测试文本.png"
        assert row["file_number"] == 2
        assert row["task_id"] == "task-123"
        assert row["relations"] == []
        assert row["meta"]["export_format"] == "mineru-annotation-jsonl-v1"
        assert isinstance(row["meta"]["annotation_sources"], list)


def test_span_offsets_match_text():
    rows = _rows()
    found = False
    for row in rows:
        for span in row["spans"]:
            assert row["text"][span["start"]:span["end"]] == span["text"]
            found = True
    assert found, "应产生至少一个 span"


def test_decisions_is_annotation_only():
    rows = _rows(["decisions"])
    assert rows
    for row in rows:
        assert any(a["rule_id"] == "decisions" for a in row["annotations"])
        assert not any(s["rule_id"] == "decisions" for s in row["spans"])


def test_annotation_id_grouped_by_rule():
    rows = _rows(["standards", "decisions"])
    ids = [a["id"] for row in rows for a in row["annotations"]]
    assert any(i.startswith("standards:") for i in ids)
    if any(i.startswith("decisions:") for i in ids):
        # 规则按 standards → decisions 的顺序分配全局序号
        standards_nums = [int(i.split(":")[1]) for i in ids if i.startswith("standards:")]
        decisions_nums = [int(i.split(":")[1]) for i in ids if i.startswith("decisions:")]
        assert max(standards_nums) < min(decisions_nums)


def test_blank_and_noise_sentences_excluded():
    md = "# 标题\n\n第1章\n\n没有任何标注的普通句子内容。\n\n依据 GB/T 3191-2019 执行。"
    rows = build_annotation_export_rows(
        markdown_text=md,
        task_id="t",
        file_name="a.md",
        file_number=1,
        rule_ids=["standards"],
    )
    for row in rows:
        assert row["annotations"], "空标注行不应导出"
        assert not row["text"].startswith("#")


def test_export_jsonl_serializable():
    rows = _rows()
    text = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    assert text.count("\n") + 1 == len(rows)


def test_model_and_rule_spans_keep_sources(monkeypatch):
    import main

    sentence = "依据 GB/T 3191-2019 执行"
    target = "GB/T 3191-2019"
    start = sentence.index(target)
    entity = {
        "id": "标准号:0",
        "rule_id": "标准号",
        "rule_label": "标准号",
        "type": "标准号",
        # run_inference 的 label 字段存放实体文本，不是标签
        "label": target,
        "text": target,
        "confidence": 0.9,
        "start_offset": start,
        "end_offset": start + len(target),
        "sentence_index": 0,
        "sentence_original": sentence,
    }
    monkeypatch.setattr(main, "run_inference", lambda **kwargs: {"entities": [entity]})

    def build(threshold=0.5, rule_ids=("standards",)):
        return main.build_annotation_export_rows(
            markdown_text=sentence,
            task_id="t",
            file_name="a.md",
            file_number=1,
            rule_ids=list(rule_ids),
            model_id="fake-model",
            model_conf_threshold=threshold,
        )

    rows = build()
    assert len(rows) == 1
    row = rows[0]
    annotation_sources = {a["rule_id"]: a["sources"] for a in row["annotations"]}
    assert annotation_sources == {"standards": ["rule"], "标准号": ["model"]}
    span_labels = {(s["rule_id"], s["text"]) for s in row["spans"]}
    assert span_labels == {("standards", target), ("标准号", target)}
    assert row["meta"]["annotation_sources"] == ["model", "rule"]
    for span in row["spans"]:
        assert row["text"][span["start"]:span["end"]] == span["text"]

    # 置信度低于阈值时模型实体被丢弃，仅保留规则结果
    filtered_rows = build(threshold=0.95)
    assert len(filtered_rows) == 1
    assert {a["rule_id"] for a in filtered_rows[0]["annotations"]} == {"standards"}
    assert filtered_rows[0]["meta"]["annotation_sources"] == ["rule"]
    assert build(threshold=0.95, rule_ids=()) == []


def test_limits_owns_metric_spans_when_numeric_facts_enabled():
    sentence = "平面度误差不超过0.05mm，钻4×6.8通孔。"
    spans = collect_rule_spans_for_sentence(
        sentence,
        ["limits", "numeric_facts"],
        {"limits": "限值指标", "numeric_facts": "数值信息"},
    )

    metric_spans = [span for span in spans if span["text"] == "0.05mm"]
    assert len(metric_spans) == 1
    assert metric_spans[0]["rule_id"] == "limits"
    assert metric_spans[0]["label"] == "限值指标"

    # numeric_facts 仍保留真正的数值类实体，只是不再重复产出 metric。
    numeric_spans = [span for span in spans if span["rule_id"] == "numeric_facts"]
    assert numeric_spans
    assert all(span["text"] != "0.05mm" for span in numeric_spans)
    assert any(span["text"] == "4×6.8" for span in numeric_spans)


def test_normalize_text_for_match_reuses_model_service():
    from model_service import _normalize_text

    sample = "—–―－‘’“”\xa0　A"
    assert normalize_text_for_match(sample) == _normalize_text(sample)


def test_content_disposition_header_is_ascii_for_chinese_file_name():
    header = build_export_content_disposition("测试文本")
    assert header.isascii()
    header.encode("latin-1")  # Starlette 响应头按 latin-1 编码，不得抛异常
    assert 'filename="annotations.jsonl"' in header
    assert "filename*=UTF-8''" in header
    encoded_name = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded_name) == "测试文本_annotations.jsonl"

    # Response 构造时会按 latin-1 编码响应头，可复现此前的 UnicodeEncodeError
    response = Response(
        content="",
        media_type="application/x-ndjson",
        headers={"Content-Disposition": header},
    )
    assert response.headers["content-disposition"] == header
