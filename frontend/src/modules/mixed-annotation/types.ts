/** 混合标注应用的前后端共享类型。 */

export type FileStatus = 'uploaded' | 'converting' | 'completed' | 'failed'

export interface Project {
  id: string
  name: string
  labels: string[]
  relation_types: string[]
  /**
   * 项目级自定义快捷键覆盖项（`{标签名: 组合键}`）。
   *
   * 只保存用户显式设置过的项；未覆盖的标签沿用「前 9 个标签 → 数字 1–9」
   * 的默认规则。老项目没有该字段，调用方一律按 `{}` 处理。
   */
  shortcuts?: Record<string, string>
  created_at: string
  updated_at: string
}

export interface MixedFile {
  id: string
  project_id: string
  name: string
  source_type: 'pdf' | 'image'
  status: FileStatus
  progress: number
  stage: string
  message: string
  error: string
  task_id: string
  page_count: number
  /** 是否已存在标注记录（实体/关系/段落或图表）。 */
  has_annotations?: boolean
  created_at: string
  updated_at: string
}

export interface AnnotationSpan {
  id: number
  start: number
  end: number
  label: string
  text: string
  /** 选区起始位置最近的块 ID，用于图谱建立“实体出现在段落”边。 */
  blockId?: string
}

export interface AnnotationRelation {
  fromId: number
  toId: number
  type: string
}

/** 后端 blocks.json 中的顶级块，偏移基于原始 result.md。 */
export interface BlockInfo {
  id: string
  index: number
  type: string
  markdown: string
  text: string
  start: number
  end: number
  page: number
  pageEnd: number
  sectionId: string
  sectionNumber: string
  sectionTitle: string
}

/** 逐页 Markdown 区间与页面尺寸。 */
export interface PageInfo {
  page: number
  width: number
  height: number
  start: number
  end: number
}

export interface BlocksPayload {
  version: number
  markdown_hash: string
  pages: PageInfo[]
  sections: unknown[]
  blocks: BlockInfo[]
}

/** 段落级标注：一个块最多一条记录。 */
export interface ParagraphAnnotation {
  blockId: string
  label: string
  note: string
}

/**
 * PDF 拖框截图记录（图表由独立接口维护，不随标注保存覆盖）。
 *
 * 图表只表达“这是图还是表 + 标题/备注 + 位置”，不再携带编号、
 * 标签或归属段落；叠加层展示的“图/表”由 kind 推导。
 */
export interface FigureAnnotation {
  id: string
  kind: 'figure' | 'table'
  caption: string
  note: string
  page: number
  bbox: number[]
  assetPath: string
}

/** 图表表单中可由用户编辑的字段（后端 PATCH 只接受 caption/note）。 */
export interface FigureDraftPayload {
  kind: FigureAnnotation['kind']
  caption: string
  note: string
}

/** 创建图表时随表单一起提交的定位信息。 */
export interface FigureCreatePayload extends FigureDraftPayload {
  page: number
  /** [x0, y0, x1, y1]，PDF 为 pt、图片为 px，左上原点。 */
  bbox: number[]
}

/** PdfPreview 拖框结束后抛给工作区的选区；previewUrl 仅用于弹窗预览。 */
export interface FigureRegionSelection {
  page: number
  bbox: number[]
  previewUrl?: string
}

export interface AnnotationRecord {
  text: string
  spans: AnnotationSpan[]
  relations: AnnotationRelation[]
  paragraphs?: ParagraphAnnotation[]
  figures?: FigureAnnotation[]
  updated_at?: string
}

export type ConversionParseMethod = 'auto' | 'txt' | 'ocr'

export interface ConversionOptions {
  enable_table: boolean
  enable_formula: boolean
  dpi: number
  /** auto：自动判断（坏文本层会自动 OCR）；txt：只用文本层；ocr：强制整页 OCR。 */
  parse_method: ConversionParseMethod
}

/**
 * 项目设置弹窗的提交载荷：名称与文档转换参数。
 * 实体标签/关系类型已移到左侧栏字典卡片，由独立的 PATCH 链路保存。
 */
export interface ProjectSettingsPayload {
  name: string
  options: ConversionOptions
}

/**
 * 字典卡片的增量保存载荷：只提交本次变化的值，由服务端做并集合并。
 *
 * 协作约定（与后端一致）：
 * - 标签/关系只能通过 add / remove 变更，服务端不会因为缺少某项而隐式删除；
 * - 同一值不得同时出现在 add 与 remove 中，调用方按“最后一次用户操作”保证互斥；
 * - 删除仍被标注引用的标签时，服务端返回 409，需用户确认后带 `force: true` 重发。
 */
export interface ProjectDictionaryPatch {
  labels_add?: string[]
  labels_remove?: string[]
  relation_types_add?: string[]
  relation_types_remove?: string[]
  /** 用户已确认删除在用标签：允许服务端删除仍被标注引用的标签。 */
  force?: boolean
}

/** 标签引用统计：`used` 为各标签被标注引用的条数，`missing` 为被引用但字典缺失的标签。 */
export interface ProjectLabelUsage {
  used: Record<string, number>
  missing: string[]
}

/* ------------------------------------------------------------------ */
/* 项目按文件序号区间拆分                                              */
/* ------------------------------------------------------------------ */

/**
 * 拆分分组：文件序号以左侧文件列表顺序为基准（1 基，`uploading` 已在后端排除）。
 * 行之间不允许重叠；未覆盖的文件留在源项目。
 */
export interface SplitGroup {
  name: string
  start: number
  end: number
}

/** 单个新项目的结果：完整项目对象 + 实际移入的文件。 */
export interface ProjectSplitResult {
  project: Project
  file_count: number
  file_ids: string[]
}

/** `POST /api/projects/{id}/split` 的响应。 */
export interface ProjectSplitResponse {
  projects: ProjectSplitResult[]
  source_project: Project
}

/* ------------------------------------------------------------------ */
/* 项目级自定义快捷键                                                  */
/* ------------------------------------------------------------------ */

/**
 * 快捷键增量保存载荷（复用 `PATCH /api/projects/{id}`）。
 *
 * 与字典一致采用增量语义：
 * - `shortcuts_set`：逐项覆盖，标签必须存在于当前项目字典；
 * - `shortcuts_unset`：删除覆盖项，回落到默认（前 9 个标签）或「无快捷键」。
 */
export interface ProjectShortcutsPatch {
  shortcuts_set?: Record<string, string>
  shortcuts_unset?: string[]
}

/** 文件夹批量导入时的上传进度快照。 */
export interface ImportProgress {
  /** 已处理（成功或失败）的文件数。 */
  done: number
  total: number
  /** 当前正在上传的文件名；全部处理完后为空字符串。 */
  current: string
}

/** 项目文件队列按后端状态汇总，用于上传面板展示串行识别进度。 */
export interface BatchSummary {
  queued: number
  converting: number
  completed: number
  failed: number
}

export interface ApiError {
  detail?: string
  message?: string
}
