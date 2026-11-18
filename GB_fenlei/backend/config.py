# -*- coding: utf-8 -*-
"""应用常量：Excel 列别名、证据参数与纯统计集成参数。"""

from pathlib import Path
from typing import Dict, Tuple

APP_VERSION = "3.0.0"

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "输出"
DEFAULT_REFERENCE = DATA_DIR / "分类好国标.xlsx"

DEFAULT_THRESHOLD = 0.70
MAX_TASKS = 8

REFERENCE_SHEET = "标准分类总表"
MAPPING_SHEET = "专业与系统映射"

# 列名别名。读取时按字段取第一个非空值，避免列顺序变化影响结果。
COLUMN_ALIASES: Dict[str, Tuple[str, ...]] = {
    "code": ("标准号", "国标号", "标准编号", "标准代号", "标准号/编号", "标准编码"),
    "name": ("标准名称", "国标名称", "名称", "标准中文名称", "中文名称", "标准名"),
    "profession": (
        "选用专业名称",
        "使用专业名称",
        "专业名称",
        "选用专业",
        "使用专业",
        "专业",
    ),
    "system": (
        "选用系统名称",
        "使用系统名称",
        "系统名称",
        "选用系统",
        "使用系统",
        "系统",
    ),
    "unit": ("主营单位", "所属单位", "使用单位", "单位"),
}

# ---------------------------------------------------------------------------
# 证据分级引擎参数
# ---------------------------------------------------------------------------

REVIEW_THRESHOLD = DEFAULT_THRESHOLD  # 复核阈值复用分类阈值，避免两处常量漂移。
MAX_CONFIDENCE = 0.95
CONFLICT_DOMINANCE = 0.55
NEIGHBOR_CONFLICT_SIMILARITY = 0.5

KNN_TOP_K = 5
KNN_MIN_SIMILARITY = 0.20

MINING_MIN_SUPPORT = 2
MINING_MIN_PURITY = 0.80
MINING_MAX_TERMS_PER_CLASS = 80
MINING_LONG_TERM_LENGTH = 5

# ---------------------------------------------------------------------------
# 纯统计集成参数
# ---------------------------------------------------------------------------

TERM_SMOOTHING = 0.5
NB_ALPHA = 1.0
NB_SIZES = (2, 3)
LOW_SUPPORT_THRESHOLD = 10
ENSEMBLE_WEIGHT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
# 归一化后每路信号的最小权重。防止调参把某一路信号压到 0，
# 从而丢掉它在外部回归集上的纠错能力。
ENSEMBLE_MIN_WEIGHT = 0.10
ENSEMBLE_STRONG_SCORE = 8.0
