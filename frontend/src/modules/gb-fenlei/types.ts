/** 与后端 API 严格对应的数据类型。 */

export interface DialogColumn {
  key: string;
  label: string;
  mono?: boolean;
  align?: "left" | "right";
  width?: string;
  wrap?: boolean;
}

export type DialogCell = string | number | null | undefined;
export type DialogRow = Record<string, DialogCell>;

export interface FileInfo {
  name: string;
  size: number;
  sheet: string;
}

export interface ColumnNames {
  code: string;
  name: string;
  system: string;
  profession: string;
}

export interface CategoryEntry {
  row: number | string;
  code: string;
  name: string;
  system: string;
  excluded: boolean;
}

export interface CategorySystem {
  system: string;
  count: number;
}

export interface CategoryGroup {
  profession: string;
  system: string;
  systems: CategorySystem[];
  count: number;
  trainable_count: number;
  excluded_count: number;
  entries: CategoryEntry[];
}

export interface ConflictDetail {
  row: number | string;
  profession: string;
  system: string;
}

export interface ConflictGroup {
  code: string;
  name: string;
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  detail: ConflictDetail[];
}

export interface DuplicateGroup {
  code: string;
  name: string;
  profession: string;
  system: string;
  count: number;
  rows: Array<number | string>;
}

export interface SameNameDiffCode {
  name: string;
  codes: string[];
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  same_profession: boolean;
  severity: "info" | "warning";
}

export interface SameCodeDiffName {
  code: string;
  names: string[];
  count: number;
  rows: Array<number | string>;
  professions: string[];
  systems: string[];
  same_profession: boolean;
  severity: "info" | "warning";
}

export interface ProfessionMultiSystem {
  profession: string;
  systems: CategorySystem[];
}

export interface MissingField {
  count: number;
  rows: Array<number | string>;
}

export interface ReferenceQuality {
  conflicts: ConflictGroup[];
  conflict_group_count: number;
  conflict_row_count: number;
  duplicates: DuplicateGroup[];
  same_name_different_code: SameNameDiffCode[];
  same_code_different_name: SameCodeDiffName[];
  profession_multiple_systems: ProfessionMultiSystem[];
  missing: {
    name: MissingField;
    profession: MissingField;
    system: MissingField;
    code: MissingField;
  };
}

/** 分类依据词表：单个专业下的一个特征词。 */
export interface KeywordItem {
  term: string;
  support: number | null;
  purity: number | null;
  weight: number;
  /** 统计引擎给出的对数几率；旧版词表可能没有该字段。 */
  log_odds?: number;
  /** 统计引擎返回 "statistical"；旧版本可能返回 "mined" / "curated"。 */
  source: "statistical" | "mined" | "curated" | string;
  examples: string[];
}

/** 分类依据词表：按专业/系统聚合的特征词报告。 */
export interface KeywordReport {
  profession: string;
  system: string;
  keywords: KeywordItem[];
  top_examples: string[];
  /** 该类别在参照表中的可用样本数。 */
  class_support: number;
  /** 样本量不足时的提示，例如 "类别样本量不足 10 条"；样本充足时为空。 */
  warning?: string;
}

export interface ReferenceAnalysis {
  reference_id: string;
  file: FileInfo;
  columns: ColumnNames;
  raw_rows: number;
  usable_rows: number;
  training_rows: number;
  excluded_rows: number;
  training_category_count: number;
  categories: CategoryGroup[];
  quality: ReferenceQuality;
  keyword_report: KeywordReport[];
}

export interface PendingReport {
  type: string;
  code: string;
  name: string;
  count: number;
  detail: string;
  action: string;
}

export type PendingStatus = "auto" | "manual";

export interface PendingItem {
  index: number;
  code: string;
  name: string;
  units: string[];
  unit_counts: Record<string, number>;
  count: number;
  source_rows: Array<number | string>;
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
}

export interface PendingPreview {
  index: number;
  code: string;
  name: string;
  units: string[];
  count: number;
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
}

export interface PendingAnalysis {
  pending_id: string;
  file: FileInfo & { header_row: number };
  columns: {
    code: string;
    name: string;
    unit: string;
  };
  raw_rows: number;
  unique_rows: number;
  group_count: number;
  auto_count: number;
  manual_count: number;
  multi_unit_count: number;
  exact_duplicate_rows: number;
  duplicate_rows: number;
  dedup_basis: string;
  missing_name_count: number;
  missing_name_rows: Array<number | string>;
  reports: PendingReport[];
  items: PendingItem[];
  preview: PendingPreview[];
}

/** 单条判定依据的结构化明细。 */
export interface EvidenceItem {
  type:
    | "keyword"
    | "similar"
    | "reference"
    | "model"
    | "term"
    | "nb"
    | "ensemble"
    | string;
  term?: string;
  name?: string;
  profession: string;
  weight?: number;
  similarity?: number;
  source?: string;
}

export interface ResultRow {
  index: number;
  code: string;
  name: string;
  system: string;
  profession: string;
  confidence: number;
  low_confidence: boolean;
  duplicate_count: number;
  source_rows: Array<number | string>;
  units: string[];
  status: PendingStatus;
  reason: string;
  needs_confirmation: boolean;
  evidence: string[];
  evidence_detail: EvidenceItem[];
  evidence_level:
    | "reference"
    | "ensemble"
    | "term"
    | "similar"
    | "nb"
    | "model"
    | "manual"
    | "rule";
  confidence_reason: string;
  needs_review: boolean;
  top3: Array<{
    profession: string;
    system: string;
    probability: number;
    score?: number;
  }>;
}

export interface ClassifyCategory {
  profession: string;
  system: string;
}

export interface ClassifySummary {
  raw_rows: number;
  unique_rows: number;
  group_count: number;
  auto_count: number;
  manual_count: number;
  multi_unit_count: number;
  low_confidence_count: number;
  threshold: number;
  dedup_basis: string;
}

export interface EvaluationReport {
  accuracy: number;
  macro_f1: number;
  per_class: Record<
    string,
    { precision: number; recall: number; f1: number; support: number }
  >;
  sample_count: number;
  method?: string;
  name_mode?: boolean;
  confusion_matrix?: Record<string, Record<string, number>>;
  calibration?: Array<{ bin: string; count: number; accuracy: number }>;
  by_level?: Record<string, { count: number; accuracy: number }>;
  /** 每个类别的参照表样本数，键为专业名称。 */
  class_support?: Record<string, number>;
  /** 样本量偏低等提示；为空表示没有警告。 */
  warnings?: string[];
  /** 三路统计信号的集成权重。 */
  weights?: { term: number; knn: number; nb: number };
  /** 权重搜索时返回的最高准确率。 */
  tuning_accuracy?: number;
  /** 分层折数。 */
  folds?: number;
  note?: string;
}

export interface ClassifyResponse {
  task_id: string;
  rows: ResultRow[];
  auto_rows: ResultRow[];
  manual_rows: ResultRow[];
  categories: ClassifyCategory[];
  columns: ColumnNames;
  summary: ClassifySummary;
  stats: {
    professions: Record<string, number>;
    systems: Record<string, number>;
    total: number;
  };
  conflicts: ConflictGroup[];
  mapping: Record<string, unknown>;
  warnings: string[];
  dedup_reports: PendingReport[];
  evaluation: EvaluationReport;
  keyword_report: KeywordReport[];
  /** 三路统计信号的集成权重（留一法在参照表上搜索得到）。 */
  ensemble_weights?: { term: number; knn: number; nb: number };
  /** 每个类别的参照表样本数，键为专业名称。 */
  class_support?: Record<string, number>;
}

export interface ExportResponse {
  path: string;
  download_url: string;
  filename: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  categories?: string[];
}
