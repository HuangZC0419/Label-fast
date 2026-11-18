def _entity_key(ent):
    """返回 (start_offset, end_offset, label) 元组，用于严格匹配"""
    return (ent["start_offset"], ent["end_offset"], ent["label"])


def _boundary_key(ent):
    """返回 (start_offset, end_offset) 元组，用于边界匹配"""
    return (ent["start_offset"], ent["end_offset"])


def _compute_metrics(tp, fp, fn):
    """根据 tp/fp/fn 计算 precision, recall, f1"""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def compute_entity_metrics(y_true, y_pred):
    """严格匹配 (边界+标签)，返回 {"precision", "recall", "f1", "tp", "fp", "fn"}"""
    true_keys = set(_entity_key(e) for e in y_true)
    pred_keys = set(_entity_key(e) for e in y_pred)

    tp = len(true_keys & pred_keys)
    fp = len(pred_keys - true_keys)
    fn = len(true_keys - pred_keys)

    metrics = _compute_metrics(tp, fp, fn)
    metrics["tp"] = tp
    metrics["fp"] = fp
    metrics["fn"] = fn
    return metrics


def compute_boundary_metrics(y_true, y_pred):
    """边界匹配 (标签宽容)，返回 {"precision", "recall", "f1"}"""
    true_keys = set(_boundary_key(e) for e in y_true)
    pred_keys = set(_boundary_key(e) for e in y_pred)

    tp = len(true_keys & pred_keys)
    fp = len(pred_keys - true_keys)
    fn = len(true_keys - pred_keys)

    return _compute_metrics(tp, fp, fn)


def compute_per_class_metrics(y_true, y_pred, labels=None):
    """每类 Entity F1 + macro_avg

    Args:
        y_true: 真实实体列表
        y_pred: 预测实体列表
        labels: 要评估的标签列表。若为 None，则从 y_true + y_pred 中自动收集。

    Returns:
        {"per_class": {label: {"precision", "recall", "f1", "tp", "fp", "fn"}}, "macro_avg": {"precision", "recall", "f1"}}
    """
    if labels is None:
        labels = sorted(set(e["label"] for e in y_true + y_pred))

    per_class = {}
    all_tp = all_fp = all_fn = 0

    for label in labels:
        true_for_label = [e for e in y_true if e["label"] == label]
        pred_for_label = [e for e in y_pred if e["label"] == label]
        metrics = compute_entity_metrics(true_for_label, pred_for_label)
        per_class[label] = metrics
        all_tp += metrics["tp"]
        all_fp += metrics["fp"]
        all_fn += metrics["fn"]

    macro_precision = (
        sum(m["precision"] for m in per_class.values()) / len(per_class)
        if per_class
        else 0.0
    )
    macro_recall = (
        sum(m["recall"] for m in per_class.values()) / len(per_class)
        if per_class
        else 0.0
    )
    macro_f1 = (
        sum(m["f1"] for m in per_class.values()) / len(per_class)
        if per_class
        else 0.0
    )

    return {
        "per_class": per_class,
        "macro_avg": {
            "precision": macro_precision,
            "recall": macro_recall,
            "f1": macro_f1,
        },
    }
