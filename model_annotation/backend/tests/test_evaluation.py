import sys
sys.path.insert(0, ".")
from evaluation import compute_entity_metrics, compute_boundary_metrics


def test_compute_entity_metrics_perfect():
    """完全正确的预测应得满分"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0


def test_compute_entity_metrics_boundary_error():
    """边界错误应降低分数"""
    y_true = [{"start_offset": 0, "end_offset": 4, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["f1"] < 1.0


def test_compute_boundary_metrics_label_mismatch():
    """边界正确但标签不同: Boundary F1 应高于 Entity F1"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [{"start_offset": 0, "end_offset": 3, "label": "工艺"}]
    entity = compute_entity_metrics(y_true, y_pred)
    boundary = compute_boundary_metrics(y_true, y_pred)
    assert boundary["f1"] >= entity["f1"]


def test_compute_entity_metrics_false_positive():
    """多预测的实体应降低 precision"""
    y_true = [{"start_offset": 0, "end_offset": 3, "label": "零件"}]
    y_pred = [
        {"start_offset": 0, "end_offset": 3, "label": "零件"},
        {"start_offset": 5, "end_offset": 8, "label": "工艺"},
    ]
    metrics = compute_entity_metrics(y_true, y_pred)
    assert metrics["precision"] < 1.0
    assert metrics["recall"] == 1.0
