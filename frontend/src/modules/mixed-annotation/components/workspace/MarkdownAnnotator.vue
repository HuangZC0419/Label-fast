<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AnnotationRecord, AnnotationSpan, BlockInfo } from '../../types'
import {
  hexToRgba,
  labelColor,
  relationColor,
  useMarkdownAnnotation,
} from '../../composables/useMarkdownAnnotation'
import {
  buildTextMap,
  createRangeFromOffsets,
  renderMarkdown,
} from '../../utils/markdown'
import { renderBlocks, type RenderedBlock } from '../../utils/blocks'
import {
  buildPageAnchors,
  type ScrollAnchor,
  type ScrollInfo,
} from '../../utils/scrollSync'
import {
  effectiveShortcuts,
  formatShortcutCompact,
} from '../../utils/shortcuts'
import '../../styles/markdown.css'

/**
 * 渲染后 Markdown 标注画布。
 *
 * 结构分两层：
 * - 数据/选区/快捷键/CSS Highlight 由 useMarkdownAnnotation 管理；
 * - 关系曲线与兼容高亮依赖真实布局，因此在本组件中基于 Range + getClientRects 测量。
 * 这样切换文件或撤销标注时，数据层保持单一事实来源，布局层只做“投影”。
 */

interface RelationVisual {
  index: number
  type: string
  color: string
  path: string
  labelX: number
  labelY: number
  fromId: number
  toId: number
}

interface FallbackRect {
  key: string
  left: number
  top: number
  width: number
  height: number
  background: string
  selected: boolean
  linked: boolean
}

/** 实体标签名叠加层的显示范围：全部 / 仅当前关注 / 隐藏。 */
type SpanLabelMode = 'all' | 'focus' | 'off'

/**
 * 一枚标签名胶囊的布局结果。
 * 坐标与 relationVisuals / fallbackRects 一致，都是相对 .md-stage 的左上角。
 */
interface SpanLabelVisual {
  key: string
  spanId: number
  label: string
  /** 悬停说明：同一范围存在多个标签时列出全部标签。 */
  title: string
  color: string
  left: number
  top: number
  maxWidth: number
  /** true 表示胶囊右边缘对齐锚点（靠近正文右边界时向左生长） */
  alignEnd: boolean
  selected: boolean
  linked: boolean
  missing: boolean
}

/** 标签名胶囊占用矩形，用于后续候选位置避让。 */
interface SpanLabelBox {
  left: number
  right: number
  top: number
  bottom: number
}

const props = withDefaults(
  defineProps<{
    fileId: string
    markdown: string
    labels: string[]
    relationTypes: string[]
    /** 后端权威切块；为空时回退为整篇 Markdown 渲染。 */
    blocks?: BlockInfo[]
    annotations?: AnnotationRecord | null
    /** 项目级自定义快捷键覆盖项；缺省表示全部沿用默认 1–9。 */
    shortcuts?: Record<string, string>
    loading?: boolean
    /** 编辑模式下画布仍挂载但隐藏，此时屏蔽标注快捷键。 */
    active?: boolean
  }>(),
  {
    blocks: () => [],
    annotations: null,
    shortcuts: () => ({}),
    loading: false,
    active: true,
  },
)

const emit = defineEmits<{
  /** 用户滚动时上报 0..1 的纵向滚动比例，用于与 PDF 预览联动。 */
  'scroll-state': [ratio: number]
  /** 标注数据发生用户侧变化，父组件据此触发自动保存。 */
  change: []
  /** 请求打开项目级快捷键设置弹窗（由父级透传到视图层）。 */
  'edit-shortcuts': []
}>()

const annotation = useMarkdownAnnotation({
  labels: () => props.labels,
  relationTypes: () => props.relationTypes,
  shortcuts: () => props.shortcuts,
  isActive: () => props.active,
})

const {
  canonicalText,
  spans,
  relations,
  paragraphs,
  hasAnnotations,
  canUndo,
  pendingSelection,
  pendingRelation,
  selectedSpanId,
  selectedRelationIndex,
  selectedRelation,
  linkedSpanIds,
  highlightSupported,
  getSpan,
  getSpanText,
  setPendingSelectionFromRange,
  applyLabel,
  applyRelation,
  selectSpanAtPoint,
  selectSpanById,
  selectRelation,
  setLinkedSpans,
  cancelPendingSelection,
  cancelPendingRelation,
  deleteSelected,
  undo,
} = annotation

const scrollRef = ref<HTMLDivElement | null>(null)
const stageRef = ref<HTMLDivElement | null>(null)
const bodyRef = ref<HTMLDivElement | null>(null)

const renderedHtml = ref('')
const renderedBlocks = ref<RenderedBlock[]>([])
const renderError = ref('')
const localNotice = ref('')
const hoveredRelation = ref<number | null>(null)
const relationVisuals = ref<RelationVisual[]>([])
const fallbackRects = ref<FallbackRect[]>([])
const overlayWidth = ref(1)
const overlayHeight = ref(1)

/* ============================================================
   实体标签名叠加层
   ============================================================ */

/*
 * 为什么需要这一层：正文高亮只有底色（CSS Custom Highlight API 不能注入文字），
 * 项目里有 40–50 个实体标签而调色板只有 6 色，颜色重复后用户无法回头辨认。
 * 因此在每处高亮的首行上方叠加一枚「标签名胶囊」，颜色仍沿用字典 chip 的底色。
 */
const SPAN_LABEL_MODE_STORAGE_KEY = 'labelfast.spanLabelMode'

const spanLabelModes: { value: SpanLabelMode; label: string; title: string }[] = [
  { value: 'all', label: '全部', title: '每个实体上方都显示标签名' },
  { value: 'focus', label: '仅选中', title: '只显示当前选中/关联实体的标签名' },
  { value: 'off', label: '隐藏', title: '不显示标签名，仅保留底色' },
]

const spanLabelMode = ref<SpanLabelMode>('all')
const spanLabelVisuals = ref<SpanLabelVisual[]>([])

function isSpanLabelMode(value: unknown): value is SpanLabelMode {
  return spanLabelModes.some((option) => option.value === value)
}

function setSpanLabelMode(mode: SpanLabelMode): void {
  spanLabelMode.value = mode
}

function restoreSpanLabelMode(): void {
  try {
    const stored = window.localStorage.getItem(SPAN_LABEL_MODE_STORAGE_KEY)
    // 白名单校验：历史版本或手工改动留下的脏值一律回落到默认「全部」。
    if (isSpanLabelMode(stored)) spanLabelMode.value = stored
  } catch {
    // 隐私模式 / 存储被禁用时读不到，保持默认值即可。
  }
}

let renderToken = 0
/** 文档加载期间抑制标注变更事件，避免把“载入”误判成“用户编辑”。 */
let changeSuppressed = false
let measureFrame = 0
let noticeTimer: ReturnType<typeof setTimeout> | null = null
let resizeObserver: ResizeObserver | null = null
/** 滚动比例上报的 rAF 句柄，避免每帧多次 emit。 */
let scrollRaf = 0
/** 程序化滚动的抑制标志：setScrollRatio 后的下一帧前不再上报自身滚动。 */
let ignoringScroll = false
let suppressRaf = 0

const isEmpty = computed(() => !props.markdown.trim() && renderedBlocks.value.length === 0)
const hasBlocks = computed(() => renderedBlocks.value.length > 0)
/** 标注总数：只统计实体与关系，避免继续暗示“段落级标注”模型。 */
const annotationCount = computed(() => spans.value.length + relations.value.length)
const pendingText = computed(() => truncate(pendingSelection.value?.text ?? '', 24))
const selectedSpan = computed(() =>
  selectedSpanId.value === null ? null : getSpan(selectedSpanId.value),
)
const selectedSpanText = computed(() =>
  selectedSpanId.value === null ? '' : truncate(getSpanText(selectedSpanId.value), 24),
)
/** 选中实体的标签名：状态栏必须能直接看到，否则标签丢失时无从判断原因。 */
const selectedSpanLabel = computed(() => selectedSpan.value?.label ?? '')
/**
 * 选中实体的标签是否已不在项目字典中。
 * 这类标签在画布上只能显示为字典外灰色，必须额外用文字与警示色说明。
 */
const selectedSpanLabelMissing = computed(
  () =>
    selectedSpan.value !== null &&
    selectedSpanLabel.value !== '' &&
    !props.labels.includes(selectedSpanLabel.value),
)
/** 缺失标签提示只在“实体选中”这一分支生效，待标注/待选关系时不应抢注意力。 */
const showMissingLabelWarning = computed(
  () =>
    !pendingSelection.value &&
    !pendingRelation.value &&
    selectedSpanLabelMissing.value,
)
/**
 * 当前文档中引用了字典外标签的实体数量。
 * 只做只读统计，不改变标注数据结构，也不依赖后端新增字段。
 */
const missingSpanCount = computed(() => {
  const known = new Set(props.labels)
  let count = 0
  for (const span of spans.value) {
    if (!known.has(span.label)) count += 1
  }
  return count
})
const pendingRelationText = computed(() => {
  const pair = pendingRelation.value
  if (!pair) return ''
  return `${truncate(getSpanText(pair.fromId), 16)} → ${truncate(getSpanText(pair.toId), 16)}`
})
const selectedRelationText = computed(() => {
  const relation = selectedRelation.value
  if (!relation) return ''
  return `${truncate(getSpanText(relation.fromId), 16)} → ${truncate(getSpanText(relation.toId), 16)}`
})

const relationMarkers = computed(() =>
  relationVisuals.value.map((visual) => ({
    id: `lf-arrow-${visual.index}`,
    color: visual.color,
  })),
)

/**
 * 「仅选中」模式下没有选中实体、也没有关系关联时，画布上一枚标签名都不会出现。
 * 用一条弱提示解释这次「静默」，避免用户误以为标签名功能失效而退回看颜色。
 */
const spanLabelFocusHint = computed(
  () =>
    spanLabelMode.value === 'focus' &&
    selectedSpanId.value === null &&
    linkedSpanIds.value.length === 0,
)

/**
 * 标签的有效快捷键：`{标签: 组合键}`。
 * 前 9 个标签默认 1–9，项目覆盖项优先；第 10 个之后未自定义则没有徽标。
 */
const labelShortcuts = computed(() =>
  effectiveShortcuts(props.labels, props.shortcuts),
)

function shortcutBadge(label: string): string {
  return formatShortcutCompact(labelShortcuts.value[label] ?? '')
}

/* ============================================================
   字典栏：单行横向滚动 + 展开全部
   ============================================================ */

/** 超过该数量时提供「展开全部 / 收起」切换，避免折叠态把标签藏住。 */
const CHIP_EXPAND_THRESHOLD = 9

/**
 * 实体标签 / 关系类型的展开态，默认 false。
 *
 * 默认单行横向滚动：标签多时（截图项目 24 / 35 个）不会把顶栏撑成多行，
 * 从而把 Markdown 正文区压扁；需要总览时用户可主动展开换行。
 * 只影响布局，不改变标签点击、快捷键与选中态。
 */
const labelsExpanded = ref(false)
const relationsExpanded = ref(false)

const labelsOverflow = computed(() => props.labels.length > CHIP_EXPAND_THRESHOLD)
const relationsOverflow = computed(
  () => props.relationTypes.length > CHIP_EXPAND_THRESHOLD,
)

function toggleLabelsExpanded(): void {
  if (!labelsOverflow.value) return
  labelsExpanded.value = !labelsExpanded.value
}

function toggleRelationsExpanded(): void {
  if (!relationsOverflow.value) return
  relationsExpanded.value = !relationsExpanded.value
}

/*
 * 数量回落到阈值以内时收起展开态。
 * 否则「展开全部」按钮会随数量消失，而列表仍停在换行态，用户无法再收回去。
 */
watch(
  () => props.labels.length,
  (count) => {
    if (count <= CHIP_EXPAND_THRESHOLD) labelsExpanded.value = false
  },
)
watch(
  () => props.relationTypes.length,
  (count) => {
    if (count <= CHIP_EXPAND_THRESHOLD) relationsExpanded.value = false
  },
)

/* ============================================================
   渲染：Markdown → 清洗 HTML → canonical text 映射
   ============================================================ */

async function renderDocument(): Promise<void> {
  const token = ++renderToken
  renderError.value = ''

  try {
    const sourceBlocks = props.blocks ?? []
    if (sourceBlocks.length > 0) {
      // 后端块为权威来源：逐块渲染，canonical text 由统一容器测量。
      renderedBlocks.value = renderBlocks(sourceBlocks, props.fileId)
      renderedHtml.value = ''
    } else {
      // 兼容路径：blocks 接口不可用或尚未切块时，保持整篇渲染。
      renderedBlocks.value = []
      renderedHtml.value = renderMarkdown(props.markdown, { fileId: props.fileId })
    }

    await nextTick()
    if (token !== renderToken) return

    const body = bodyRef.value
    if (!body) return
    const map = buildTextMap(body)
    annotation.setDocument(body, map)
    const blockIds =
      sourceBlocks.length > 0
        ? new Set(sourceBlocks.map((block) => block.id))
        : undefined
    changeSuppressed = true
    try {
      annotation.loadAnnotations(props.annotations, blockIds)
      await nextTick()
    } finally {
      // 渲染异常或 token 过期时也必须复位，否则标注变更事件会被永久抑制。
      if (token === renderToken) changeSuppressed = false
    }
    if (token !== renderToken) return
    scheduleMeasure()
  } catch (error) {
    renderError.value = error instanceof Error ? error.message : String(error)
  }
}

watch(
  () => [props.fileId, props.markdown, props.blocks, props.annotations] as const,
  () => {
    void renderDocument()
  },
  { immediate: true, flush: 'post' },
)

/* ============================================================
   选区与点击
   ============================================================ */

function handleMouseUp(event: MouseEvent): void {
  if (event.button !== 0) return
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return

  const range = selection.getRangeAt(0)
  if (setPendingSelectionFromRange(range)) {
    localNotice.value = ''
    hoveredRelation.value = null
    setLinkedSpans([])
  }
}

function handleCanvasClick(event: MouseEvent): void {
  const selection = window.getSelection()
  if (selection && selection.rangeCount > 0 && !selection.isCollapsed) {
    // 选完文本后的 click 不应触发链接跳转，也不应把刚建立的待选区清掉。
    event.preventDefault()
    return
  }

  const target = event.target as HTMLElement | null
  if (target?.closest('button')) return
  if (target?.closest('a')) return
  if (target?.closest('img')) return

  const hit = selectSpanAtPoint(event.clientX, event.clientY)
  if (hit) {
    localNotice.value = ''
    hoveredRelation.value = null
  }
}

/* ============================================================
   快捷操作
   ============================================================ */

/**
 * 点击标签名胶囊 → 选中该处实体。
 *
 * 胶囊位于正文行间，如果继续让事件穿透，点到的是上一行文字甚至空白，
 * 会选中相邻实体、让用户以为「点一下标签就变了」。这里直接用胶囊对应的
 * spanId 选中，保证点哪枚胶囊就选中哪处标注（同一范围有多个标签时选最新一条）。
 */
function handleSpanChipClick(spanId: number): void {
  localNotice.value = ''
  hoveredRelation.value = null
  setLinkedSpans([])
  selectSpanById(spanId)
}

function handleLabelClick(label: string): void {
  if (!pendingSelection.value) {
    showNotice('请先在正文中选中文本，再应用实体标签')
    return
  }
  localNotice.value = ''
  applyLabel(label)
}

function handleRelationClick(type: string): void {
  if (!pendingRelation.value) {
    showNotice('请先依次点击两个已标注实体，再选择关系类型')
    return
  }
  localNotice.value = ''
  applyRelation(type)
}

function handleDeleteSelected(): void {
  deleteSelected()
  localNotice.value = ''
}

function handleRelationEnter(index: number): void {
  hoveredRelation.value = index
  const visual = relationVisuals.value.find((item) => item.index === index)
  if (visual) setLinkedSpans([visual.fromId, visual.toId])
}

function handleRelationLeave(): void {
  hoveredRelation.value = null
  setLinkedSpans([])
}

function handleRelationSelect(index: number): void {
  hoveredRelation.value = null
  setLinkedSpans([])
  selectRelation(index)
}

function showNotice(message: string): void {
  localNotice.value = message
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => {
    localNotice.value = ''
    noticeTimer = null
  }, 2600)
}

function truncate(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}…` : normalized
}

function labelChipStyle(label: string): Record<string, string> {
  return { background: labelColor(label, props.labels) }
}

function relationChipStyle(type: string): Record<string, string> {
  return { background: relationColor(type, props.relationTypes) }
}

/* ============================================================
   关系曲线、标签名胶囊与兼容高亮测量
   ============================================================ */

/*
 * 叠加层（关系曲线 / 标签名胶囊）的坐标全部相对 .md-stage，滚动不改变它们；
 * 因此不为 scroll 注册测量监听：窗口尺寸、容器尺寸、图片加载、字体就绪
 * 以及数据变更才是真正需要重测的时机，全都已有独立触发路径。
 */
function scheduleMeasure(): void {
  if (measureFrame) return
  measureFrame = requestAnimationFrame(() => {
    measureFrame = 0
    measureLayout()
  })
}

function measureLayout(): void {
  // 排版变化（字体、图片、窗口尺寸、块内容）都会让页首偏移失效。
  scrollAnchorsCache = null
  const stage = stageRef.value
  const map = annotation.textMap.value
  if (!stage || !map) {
    relationVisuals.value = []
    fallbackRects.value = []
    spanLabelVisuals.value = []
    return
  }

  const stageRect = stage.getBoundingClientRect()
  if (stageRect.width <= 0 || stageRect.height <= 0) {
    // 组件被 v-show 隐藏时无法测量；重新显示后由父组件调用 refreshLayout。
    relationVisuals.value = []
    fallbackRects.value = []
    spanLabelVisuals.value = []
    return
  }

  overlayWidth.value = Math.max(1, Math.ceil(stageRect.width))
  overlayHeight.value = Math.max(1, Math.ceil(stage.scrollHeight || stageRect.height))

  relationVisuals.value = buildRelationVisuals(map, stageRect)
  fallbackRects.value = highlightSupported.value
    ? []
    : buildFallbackRects(map, stageRect)
  spanLabelVisuals.value =
    spanLabelMode.value === 'off' ? [] : buildSpanLabelVisuals(map, stageRect)
}

function buildRelationVisuals(
  map: NonNullable<typeof annotation.textMap.value>,
  stageRect: DOMRect,
): RelationVisual[] {
  const visuals: RelationVisual[] = []

  relations.value.forEach((relation, index) => {
    const from = getSpan(relation.fromId)
    const to = getSpan(relation.toId)
    if (!from || !to) return

    const fromRange = createRangeFromOffsets(map, from.start, from.end)
    const toRange = createRangeFromOffsets(map, to.start, to.end)
    if (!fromRange || !toRange) return

    const fromRects = validClientRects(fromRange)
    const toRects = validClientRects(toRange)
    if (fromRects.length === 0 || toRects.length === 0) return

    // 规范要求：起点取 Range 的最后一枚矩形，终点取第一枚矩形。
    const source = fromRects[fromRects.length - 1]
    const target = toRects[0]
    const x1 = source.right - stageRect.left
    const y1 = source.top - stageRect.top - 2
    const x2 = target.left - stageRect.left
    const y2 = target.top - stageRect.top - 2

    const horizontalGap = Math.abs(x2 - x1)
    const arcHeight = Math.max(22, Math.min(72, 20 + horizontalGap * 0.06))
    const top = Math.min(y1, y2)
    const controlY = Math.max(8, top - arcHeight)
    const controlOffset = (x2 - x1) * 0.28
    const path = `M ${x1} ${y1} C ${x1 + controlOffset} ${controlY}, ${x2 - controlOffset} ${controlY}, ${x2} ${y2}`

    visuals.push({
      index,
      type: relation.type,
      color: relationColor(relation.type, props.relationTypes),
      path,
      labelX: (x1 + x2) / 2,
      labelY: Math.max(12, controlY - 6),
      fromId: relation.fromId,
      toId: relation.toId,
    })
  })

  return visuals
}

function buildFallbackRects(
  map: NonNullable<typeof annotation.textMap.value>,
  stageRect: DOMRect,
): FallbackRect[] {
  const result: FallbackRect[] = []
  const selected = selectedRelation.value
  const linkedIds = new Set(linkedSpanIds.value)
  if (selected) {
    linkedIds.add(selected.fromId)
    linkedIds.add(selected.toId)
  }

  spans.value.forEach((span) => {
    const range = createRangeFromOffsets(map, span.start, span.end)
    if (!range) return
    const color = labelColor(span.label, props.labels)
    const isSelected = selectedSpanId.value === span.id
    const isLinked = linkedIds.has(span.id)
    const background = hexToRgba(color, isSelected ? 0.44 : 0.3)

    validClientRects(range).forEach((rect, rectIndex) => {
      result.push({
        key: `${span.id}-${rectIndex}`,
        left: rect.left - stageRect.left,
        top: rect.top - stageRect.top,
        width: rect.width,
        height: rect.height,
        background,
        selected: isSelected,
        linked: isLinked,
      })
    })
  })

  return result
}

function validClientRects(range: Range): DOMRect[] {
  return Array.from(range.getClientRects()).filter(
    (rect) => rect.width > 0.5 && rect.height > 0.5,
  )
}

/*
 * 胶囊高度 14px：正文行高 28.8px，相邻两行字形之间只有约 11px 空白。
 * 高度再大就会明显盖住上一行正文，再小则 10.5px 中文难以辨认。
 */
const SPAN_LABEL_CHIP_HEIGHT = 14
/** 相邻胶囊之间的最小留白，避免不同实体的标签名贴在一起难以分辨。 */
const SPAN_LABEL_GAP = 3
/** 胶囊最大宽度：过宽会横跨正文，过窄则中文标签被 ellipsis 吃掉。 */
const SPAN_LABEL_MAX_WIDTH = 200

/**
 * 估算胶囊宽度：碰撞检测用保守上界即可，宁可多留白也不要误判可放置。
 * 中文字形在 10.5px 字号下约 10.5px 宽，拉丁字符约 6.3px；
 * 早期按统一 7.2px 估算会让「普通螺纹公差带」这类标签被无谓截断。
 */
function estimateSpanLabelWidth(label: string): number {
  let width = 10
  for (const char of label) {
    width += /[\u2e80-\u9fff\uff00-\uffef\u3000-\u303f]/.test(char) ? 10.5 : 6.3
  }
  // CSS 里还有 letter-spacing: 0.01em（10.5px 字号约 0.1px/字符），漏算会让长标签被无谓截断。
  width += label.length * 0.1
  return Math.min(SPAN_LABEL_MAX_WIDTH, Math.max(22, width))
}

function buildSpanLabelVisuals(
  map: NonNullable<typeof annotation.textMap.value>,
  stageRect: DOMRect,
): SpanLabelVisual[] {
  const stageWidth = stageRect.width
  const stageHeight = stageRect.height
  const linkedIds = new Set(linkedSpanIds.value)
  // linkedSpanIds 已覆盖关系悬停/选中的两端；再并一次是防御性兜底，与兼容高亮层保持一致。
  const currentRelation = selectedRelation.value
  if (currentRelation) {
    linkedIds.add(currentRelation.fromId)
    linkedIds.add(currentRelation.toId)
  }

  /*
   * 同一段文本可能被标注过多次：历史数据里既有完全重复的记录（同范围 + 同标签），
   * 也有多人给同一段文本打了不同标签。一个文本范围只画一枚胶囊，
   * 文字显示「最新标签 +N」，title 里列出全部标签；点击选中最新那条。
   * 这样不会再出现同一段文字上叠出两三枚名字的观感，也不会隐瞒冲突。
   */
  const groupsByRange = new Map<string, AnnotationSpan[]>()
  for (const span of spans.value) {
    const key = `${span.start}:${span.end}`
    const list = groupsByRange.get(key) ?? []
    list.push(span)
    groupsByRange.set(key, list)
  }

  const groups = Array.from(groupsByRange, ([key, list]) => {
    list.sort((left, right) => left.id - right.id)
    return { key, list, start: list[0].start, end: list[0].end }
  }).sort((left, right) => left.start - right.start || left.end - right.end)

  const occupied: SpanLabelBox[] = []
  const visuals: SpanLabelVisual[] = []

  for (const group of groups) {
    const isSelected = group.list.some((span) => span.id === selectedSpanId.value)
    const isLinked = group.list.some((span) => linkedIds.has(span.id))
    // 聚焦模式只保留当前选中与关系关联的实体，其余靠底色表达。
    if (spanLabelMode.value === 'focus' && !isSelected && !isLinked) continue

    const range = createRangeFromOffsets(map, group.start, group.end)
    if (!range) continue
    const rects = validClientRects(range)
    if (rects.length === 0) continue

    // 最新记录（id 最大）代表这段文本当前的标签，也作为点击选中的目标。
    const latest = group.list[group.list.length - 1]
    const uniqueLabels = Array.from(new Set(group.list.map((span) => span.label)))
    const extraLabelCount = uniqueLabels.length - 1
    const displayLabel =
      extraLabelCount > 0 ? `${latest.label} +${extraLabelCount}` : latest.label
    const title =
      extraLabelCount > 0
        ? `该处标注了 ${uniqueLabels.length} 个标签：${uniqueLabels.join('、')}（点击选中最新标签「${latest.label}」）`
        : latest.label

    // 多行实体只在首行上方出一枚胶囊，否则会出现一长串重复标签名。
    const first = rects[0]
    // 舞台过窄时先压窄胶囊上限，避免兜底位置越过右边界被卡片裁掉。
    const maxWidth = Math.min(
      estimateSpanLabelWidth(displayLabel),
      Math.max(22, stageWidth - 4),
    )
    let top = Math.max(0, first.top - stageRect.top - SPAN_LABEL_CHIP_HEIGHT - 1)
    const anchorLeft = first.left - stageRect.left

    // 候选位置：行首左侧 → 同一行起点向右紧邻 → 右对齐向左生长。
    const inlineLeft = findSpanLabelInlineLeft(
      anchorLeft,
      top,
      maxWidth,
      occupied,
      stageWidth,
    )
    const candidates: { left: number; alignEnd: boolean }[] = [
      { left: anchorLeft, alignEnd: false },
      ...(inlineLeft !== null && inlineLeft > anchorLeft
        ? [{ left: inlineLeft, alignEnd: false }]
        : []),
      { left: anchorLeft, alignEnd: true },
    ]

    let chosen: { left: number; alignEnd: boolean } | null = null
    for (const candidate of candidates) {
      if (isSpanLabelPlaceable(candidate, top, maxWidth, stageWidth, stageHeight, occupied)) {
        chosen = candidate
        break
      }
    }
    if (!chosen) {
      /*
       * 兜底：密集/嵌套实体（中文 NER 里「普通螺纹公差带」与「螺纹」常常同起点）
       * 可能找不到完全不冲突的位置。此时宁可轻微压住文字，也不隐藏标签名。
       * 但同一位置的嵌套实体若直接复用 (left, top)，后渲染的会把先渲染的整枚盖住，
       * 因此先向上错开一层，保证两枚至少各露出大半。
       */
      const maxLeft = Math.max(2, stageWidth - maxWidth - 2)
      chosen = { left: Math.min(Math.max(2, anchorLeft), maxLeft), alignEnd: false }
      if (
        !isSpanLabelPlaceable(chosen, top, maxWidth, stageWidth, stageHeight, occupied)
      ) {
        top = Math.max(0, top - SPAN_LABEL_CHIP_HEIGHT - 2)
      }
    }

    const box = spanLabelBox(chosen, top, maxWidth)
    occupied.push({
      left: box.left - SPAN_LABEL_GAP,
      right: box.right + SPAN_LABEL_GAP,
      top: box.top - SPAN_LABEL_GAP,
      bottom: box.bottom + SPAN_LABEL_GAP,
    })

    visuals.push({
      key: group.key,
      spanId: latest.id,
      label: displayLabel,
      title,
      color: labelColor(latest.label, props.labels),
      left: chosen.left,
      top,
      maxWidth,
      alignEnd: chosen.alignEnd,
      selected: isSelected,
      linked: isLinked,
      missing: uniqueLabels.some((label) => !props.labels.includes(label)),
    })
  }

  return visuals
}

/**
 * 从 anchorLeft 开始向右找第一个不与已放胶囊重叠的位置。
 * 同一行起点上的多个实体（嵌套、同起点）因此会紧挨着排成「标签串」，
 * 而不是第二个被推到整行末尾——后者看起来像凭空多出来一枚标签。
 */
function findSpanLabelInlineLeft(
  anchorLeft: number,
  top: number,
  maxWidth: number,
  occupied: SpanLabelBox[],
  stageWidth: number,
): number | null {
  let left = Math.max(0, anchorLeft)
  for (let step = 0; step <= occupied.length; step += 1) {
    const box = spanLabelBox({ left, alignEnd: false }, top, maxWidth)
    if (box.right > stageWidth) return null
    const hit = occupied.find(
      (taken) =>
        box.left < taken.right &&
        box.right > taken.left &&
        box.top < taken.bottom &&
        box.bottom > taken.top,
    )
    if (!hit) return left
    left = hit.right + SPAN_LABEL_GAP
  }
  return null
}

function spanLabelBox(
  position: { left: number; alignEnd: boolean },
  top: number,
  maxWidth: number,
): SpanLabelBox {
  return {
    left: position.alignEnd ? position.left - maxWidth : position.left,
    right: position.alignEnd ? position.left : position.left + maxWidth,
    top,
    bottom: top + SPAN_LABEL_CHIP_HEIGHT,
  }
}

function isSpanLabelPlaceable(
  position: { left: number; alignEnd: boolean },
  top: number,
  maxWidth: number,
  stageWidth: number,
  stageHeight: number,
  occupied: SpanLabelBox[],
): boolean {
  const box = spanLabelBox(position, top, maxWidth)
  // 必须完全落在 stage 内，否则会被正文卡片裁掉或盖到卡片边框上。
  if (box.left < 0 || box.right > stageWidth) return false
  if (box.top < 0 || box.bottom > stageHeight) return false
  return !occupied.some(
    (taken) =>
      box.left < taken.right &&
      box.right > taken.left &&
      box.top < taken.bottom &&
      box.bottom > taken.top,
  )
}

watch(
  [spans, relations, selectedSpanId, selectedRelationIndex, linkedSpanIds, highlightSupported],
  () => scheduleMeasure(),
  { flush: 'post' },
)

watch(
  () => props.labels.slice(),
  () => scheduleMeasure(),
  { flush: 'post' },
)

watch(
  () => props.relationTypes.slice(),
  () => scheduleMeasure(),
  { flush: 'post' },
)

watch(relations, () => {
  hoveredRelation.value = null
  setLinkedSpans([])
})

/*
 * 标签名显示模式：写回本地偏好，并立刻重算布局。
 * 不重算的话，切到「隐藏」后旧胶囊会一直留在屏幕上，直到下次滚动才消失。
 */
watch(spanLabelMode, (mode) => {
  try {
    window.localStorage.setItem(SPAN_LABEL_MODE_STORAGE_KEY, mode)
  } catch {
    // 写入失败只影响下次打开时的默认值，本次会话的显示效果不受影响。
  }
  scheduleMeasure()
})

/**
 * 标注数据的用户侧变更 → 通知父组件自动保存。
 * 文档加载由 `changeSuppressed` 抑制；非激活（编辑模式）时不产生变更。
 */
watch(
  [spans, relations, paragraphs],
  () => {
    if (!props.active || changeSuppressed) return
    emit('change')
  },
  { deep: true, flush: 'post' },
)

watch(
  () => props.active,
  (active) => {
    if (active) {
      scheduleMeasure()
      return
    }
    annotation.clearTransientState()
    hoveredRelation.value = null
  },
)

function handleImageLoad(): void {
  scheduleMeasure()
}

/* 视口/容器尺寸变化：排版会变，胶囊与曲线必须一起重测。 */
function handleLayoutChange(): void {
  scheduleMeasure()
}

onMounted(() => {
  // 先恢复显示模式偏好，再做首次测量，避免首帧先画出默认模式的胶囊再闪一次。
  restoreSpanLabelMode()

  window.addEventListener('resize', handleLayoutChange)
  bodyRef.value?.addEventListener('load', handleImageLoad, true)
  bodyRef.value?.addEventListener('error', handleImageLoad, true)

  if (typeof ResizeObserver !== 'undefined' && stageRef.value) {
    resizeObserver = new ResizeObserver(handleLayoutChange)
    resizeObserver.observe(stageRef.value)
  }

  if ('fonts' in document) {
    document.fonts.ready.then(() => scheduleMeasure()).catch(() => undefined)
  }

  scheduleMeasure()
})

onBeforeUnmount(() => {
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = null
  if (measureFrame) cancelAnimationFrame(measureFrame)
  measureFrame = 0
  if (scrollRaf) cancelAnimationFrame(scrollRaf)
  scrollRaf = 0
  if (suppressRaf) cancelAnimationFrame(suppressRaf)
  suppressRaf = 0
  ignoringScroll = false
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', handleLayoutChange)
  bodyRef.value?.removeEventListener('load', handleImageLoad, true)
  bodyRef.value?.removeEventListener('error', handleImageLoad, true)
})

async function refreshLayout(): Promise<void> {
  await nextTick()
  scheduleMeasure()
}

/* ============================================================
   滚动同步（与 PDF 预览联动）
   ============================================================ */

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(1, Math.max(0, value))
}

function scrollRatioOf(element: HTMLElement): number {
  // 分母至少为 1，避免不可滚动时除以 0。
  return clampRatio(element.scrollTop / Math.max(1, element.scrollHeight - element.clientHeight))
}

/**
 * 程序化滚动后屏蔽自身 scroll 事件。
 *
 * 标志在下一帧的 rAF 回调里清除；scroll 事件在同一帧的渲染步骤中先于
 * rAF 回调派发，因此事件处理器读取到的仍是 true，可可靠跳过回传，
 * 避免 Markdown ↔ PDF 的 A→B→A 回环。
 */
function suppressOwnScroll(): void {
  ignoringScroll = true
  if (suppressRaf) cancelAnimationFrame(suppressRaf)
  suppressRaf = requestAnimationFrame(() => {
    suppressRaf = 0
    ignoringScroll = false
  })
}

function handleScroll(): void {
  const element = scrollRef.value
  if (!element) return
  const programmatic = ignoringScroll
  if (scrollRaf) return
  scrollRaf = requestAnimationFrame(() => {
    scrollRaf = 0
    if (programmatic) return
    emit('scroll-state', scrollRatioOf(element))
  })
}

/** 外部（MixedWorkspace）按比例设置滚动位置。 */
function setScrollRatio(ratio: number): void {
  const element = scrollRef.value
  if (!element) return
  const max = element.scrollHeight - element.clientHeight
  if (max <= 0) return
  const target = clampRatio(ratio) * max
  if (Math.abs(target - element.scrollTop) < 1) return
  suppressOwnScroll()
  element.scrollTop = target
}

/** 页首锚点缓存：布局/内容变化时失效，滚动时只做纯计算。 */
let scrollAnchorsCache: {
  pageCount: number
  scrollHeight: number
  anchors: ScrollAnchor[]
} | null = null

function getScrollInfo(pageCount?: number): ScrollInfo | null {
  const element = scrollRef.value
  const body = bodyRef.value
  if (!element || !body) return null

  const blocks = renderedBlocks.value
  const maxBlockPage = blocks.reduce(
    (max, item) =>
      Math.max(max, Number(item.block.pageEnd) || Number(item.block.page) || 1),
    0,
  )
  const total = pageCount && pageCount > 0 ? pageCount : maxBlockPage
  if (!total) return null

  const cached =
    scrollAnchorsCache &&
    scrollAnchorsCache.pageCount === total &&
    scrollAnchorsCache.scrollHeight === element.scrollHeight
      ? scrollAnchorsCache
      : null

  if (cached) {
    return {
      scrollTop: element.scrollTop,
      scrollHeight: element.scrollHeight,
      viewportHeight: element.clientHeight,
      pageCount: total,
      anchors: cached.anchors,
    }
  }

  const elementByBlock = new Map<string, HTMLElement>()
  body.querySelectorAll<HTMLElement>('[data-block-id]').forEach((node) => {
    const id = node.dataset.blockId
    if (id) elementByBlock.set(id, node)
  })

  const scrollRect = element.getBoundingClientRect()
  const pageTops = new Map<number, number>()

  for (const item of blocks) {
    const block = item.block
    const node = elementByBlock.get(block.id)
    if (!node) continue
    const rect = node.getBoundingClientRect()
    const top = rect.top - scrollRect.top + element.scrollTop
    const startPage = Math.max(1, Number(block.page) || 1)
    const endPage = Math.max(startPage, Number(block.pageEnd) || startPage)
    // 一个段落跨多页时，按页均分它的高度，避免多页共用同一个锚点。
    const span = Math.max(1, endPage - startPage + 1)
    for (let page = startPage; page <= Math.min(endPage, total); page += 1) {
      const pageTop = top + ((page - startPage) / span) * rect.height
      const existing = pageTops.get(page)
      if (existing === undefined || pageTop < existing) pageTops.set(page, pageTop)
    }
  }

  const anchors = buildPageAnchors(pageTops, total, element.scrollHeight)
  if (anchors.length < 2) return null

  scrollAnchorsCache = {
    pageCount: total,
    scrollHeight: element.scrollHeight,
    anchors,
  }

  return {
    scrollTop: element.scrollTop,
    scrollHeight: element.scrollHeight,
    viewportHeight: element.clientHeight,
    pageCount: total,
    anchors,
  }
}

/** 外部（MixedWorkspace）按绝对滚动偏移对齐，供按页同步使用。 */
function scrollToPosition(top: number): void {
  const element = scrollRef.value
  if (!element) return
  const max = element.scrollHeight - element.clientHeight
  const target = Math.min(max, Math.max(0, top))
  if (Math.abs(target - element.scrollTop) < 1) return
  suppressOwnScroll()
  element.scrollTop = target
}

function getScrollRatio(): number {
  const element = scrollRef.value
  return element ? scrollRatioOf(element) : 0
}

defineExpose({
  getPayload: annotation.getPayload,
  getCanonicalText: () => annotation.canonicalText.value,
  hasAnnotations: () => annotation.hasAnnotations.value,
  clearAnnotations: annotation.clearAnnotations,
  refreshLayout,
  getScrollInfo,
  scrollToPosition,
  setScrollRatio,
  getScrollRatio,
})
</script>

<template>
  <div class="markdown-annotator">
    <!--
      工具区传送到工作区顶部的整宽挂载点（MixedWorkspace 的 #mw-annotation-bar），
      让实体标签/关系类型/状态条横跨文本与 PDF，正文与 PDF 从同一高度开始。
      Teleport 子树保留本组件的 scope 属性，原有 .annotation-tools 等样式继续生效。
    -->
    <Teleport to="#mw-annotation-bar">
      <section class="annotation-tools" aria-label="实体与关系快捷操作">
        <div class="tools-head">
          <div class="tools-stats">
            <span class="stats-eyebrow">Annotation</span>
            <span class="stats-item">{{ canonicalText.length }} 字</span>
            <span class="stats-divider" aria-hidden="true">·</span>
            <span class="stats-item">{{ annotationCount }} 标注</span>
            <span class="stats-divider" aria-hidden="true">·</span>
            <span class="stats-item">{{ spans.length }} 实体</span>
            <span class="stats-divider" aria-hidden="true">·</span>
            <span class="stats-item">{{ relations.length }} 关系</span>
            <span
              v-if="!highlightSupported && spans.length > 0"
              class="compat-badge"
              title="当前浏览器不支持 CSS Custom Highlight API，已启用兼容高亮层"
            >
              兼容高亮
            </span>
            <span
              v-if="missingSpanCount > 0"
              class="stats-missing"
              title="这些实体引用的标签已不在项目字典中，可在左侧「字典缺失」处恢复"
            >
              {{ missingSpanCount }} 处缺失标签
            </span>
            <span v-if="spanLabelFocusHint" class="stats-hint">
              标签名「仅选中」：点选实体后显示
            </span>
            <slot name="save-status" />
          </div>
          <div class="tools-actions">
            <button
              type="button"
              class="mx-btn btn-quiet mx-btn-sm"
              :disabled="!canUndo"
              title="撤销（Ctrl + Z）"
              @click="undo"
            >
              撤销
              <span class="kbd-hint">Ctrl Z</span>
            </button>
            <!--
              标签名显示方式：紧邻操作按钮组，用户调整“正文上到底显示哪些名字”时
              视线不用离开工具条；三段式比下拉更少一次点击。
            -->
            <div class="span-label-mode" role="group" aria-label="实体标签名显示方式">
              <span class="span-label-mode-label" aria-hidden="true">标签名</span>
              <button
                v-for="option in spanLabelModes"
                :key="option.value"
                type="button"
                class="span-label-mode-btn"
                :class="{ 'is-active': spanLabelMode === option.value }"
                :aria-pressed="spanLabelMode === option.value"
                :title="option.title"
                @click="setSpanLabelMode(option.value)"
              >
                {{ option.label }}
              </button>
            </div>
            <!--
              快捷键入口：用户看着 chip 上的徽标想改键时，视线正在工具条上，
              入口就放在这里（与左侧字典卡片头部的按钮互为同一动作），
              不必再回头去侧栏找。
            -->
            <button
              type="button"
              class="shortcut-entry-btn"
              title="快捷键设置：为标签录制/修改快捷键"
              @click="emit('edit-shortcuts')"
            >
              <svg
                class="shortcut-entry-icon"
                viewBox="0 0 16 16"
                fill="none"
                stroke="currentColor"
                stroke-width="1.3"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
                focusable="false"
              >
                <rect x="1.8" y="4.2" width="12.4" height="7.6" rx="1.6" />
                <path d="M4.2 6.6h.01M6.4 6.6h.01M8.6 6.6h.01M10.8 6.6h.01M4.2 8.8h.01M11.8 8.8h.01" />
                <path d="M6 9.4h4" />
              </svg>
              快捷键设置
            </button>
            <slot name="mode-toggle" />
          </div>
        </div>

        <!--
          关系列只在项目配置了关系类型时出现：没有关系类型时整列隐藏，
          实体标签占满整宽，单行能多显示几个 chip，也少一层视觉噪音。
        -->
        <div class="chip-columns" :class="{ 'is-single': relationTypes.length === 0 }">
          <div class="chip-column">
            <div class="chip-head">
              <h3 class="chip-title">实体标签</h3>
              <span class="chip-hint">快捷键 1–9 · 可自定义</span>
              <button
                v-if="labelsOverflow"
                type="button"
                class="chip-expand-btn"
                :aria-expanded="labelsExpanded"
                aria-controls="annotator-label-chips"
                :title="labelsExpanded ? '收起为单行' : '展开显示全部标签'"
                @click="toggleLabelsExpanded"
              >
                {{ labelsExpanded ? '收起' : `展开全部 ${labels.length} 个` }}
              </button>
            </div>
            <div
              id="annotator-label-chips"
              class="chip-row"
              :class="{ 'is-expanded': labelsExpanded }"
            >
              <button
                v-for="label in labels"
                :key="label"
                type="button"
                class="mx-label-chip"
                :class="{ 'is-armed': Boolean(pendingSelection) }"
                :style="labelChipStyle(label)"
                :title="
                  shortcutBadge(label)
                    ? `${pendingSelection ? '应用标签' : '先在正文中选中文本'}：${label}（快捷键 ${shortcutBadge(label)}）`
                    : `${pendingSelection ? '应用标签' : '先在正文中选中文本'}：${label}`
                "
                @click="handleLabelClick(label)"
              >
                <span
                  v-if="shortcutBadge(label)"
                  class="chip-key"
                  :class="{ 'is-combo': shortcutBadge(label).length > 1 }"
                  aria-hidden="true"
                >{{ shortcutBadge(label) }}</span>
                <span>{{ label }}</span>
              </button>
              <span v-if="labels.length === 0" class="chip-empty">项目未配置实体标签</span>
            </div>
          </div>

          <div v-if="relationTypes.length > 0" class="chip-column chip-column--relation">
            <div class="chip-head">
              <h3 class="chip-title">关系类型</h3>
              <span class="chip-hint">Ctrl + 1–9</span>
              <button
                v-if="relationsOverflow"
                type="button"
                class="chip-expand-btn"
                :aria-expanded="relationsExpanded"
                aria-controls="annotator-relation-chips"
                :title="relationsExpanded ? '收起为单行' : '展开显示全部关系类型'"
                @click="toggleRelationsExpanded"
              >
                {{ relationsExpanded ? '收起' : `展开全部 ${relationTypes.length} 个` }}
              </button>
            </div>
            <div
              id="annotator-relation-chips"
              class="chip-row"
              :class="{ 'is-expanded': relationsExpanded }"
            >
              <button
                v-for="(type, index) in relationTypes"
                :key="type"
                type="button"
                class="mx-label-chip relation-chip"
                :class="{ 'is-armed': Boolean(pendingRelation) }"
                :style="relationChipStyle(type)"
                :title="pendingRelation ? `应用关系：${type}` : '先依次点击两个实体'"
                @click="handleRelationClick(type)"
              >
                <span v-if="index < 9" class="chip-key chip-key--light">{{ index + 1 }}</span>
                <span>{{ type }}</span>
              </button>
            </div>
          </div>
        </div>

        <!--
          状态条只在“真的有状态”时出现：无待定选区/选中项/提示时整条不渲染，
          空闲状态下不再白白占掉约 40px 的正文高度。
        -->
        <div
          v-if="
            pendingSelection ||
            pendingRelation ||
            selectedRelation ||
            selectedSpan ||
            localNotice
          "
          class="inline-bar"
          :class="{
            'is-pending': Boolean(pendingSelection || pendingRelation),
            'is-warning': showMissingLabelWarning,
          }"
          role="status"
          aria-live="polite"
        >
          <template v-if="pendingSelection">
            <span class="mx-status-dot" aria-hidden="true"></span>
            <span class="inline-text">
              已选中「{{ pendingText }}」· 点击实体标签或按标签上的快捷键应用
            </span>
            <button type="button" class="inline-action" @click="cancelPendingSelection">取消</button>
          </template>

          <template v-else-if="pendingRelation">
            <span class="mx-status-dot" aria-hidden="true"></span>
            <span class="inline-text">
              已连接 {{ pendingRelationText }} · 点击关系类型或按
              <kbd>Ctrl</kbd> + <kbd>1–9</kbd> 应用
            </span>
            <button type="button" class="inline-action" @click="cancelPendingRelation">取消</button>
          </template>

          <template v-else-if="selectedRelation">
            <span class="mx-status-dot status-dot--relation" aria-hidden="true"></span>
            <span class="inline-text">
              关系「{{ selectedRelation.type }}」· {{ selectedRelationText }} ·
              <kbd>Delete</kbd> 删除
            </span>
            <button type="button" class="inline-action inline-action--danger" @click="handleDeleteSelected">
              删除关系
            </button>
          </template>

          <template v-else-if="selectedSpan">
            <span
              class="mx-status-dot"
              :class="{ 'status-dot--warning': selectedSpanLabelMissing }"
              aria-hidden="true"
            ></span>
            <span class="inline-text">
              实体「{{ selectedSpanText }}」· 标签「{{ selectedSpanLabel }}」· 再点一个实体建立关系 ·
              <kbd>Delete</kbd> 删除<span v-if="selectedSpanLabelMissing" class="inline-missing">（字典缺失，可在左侧恢复）</span>
            </span>
            <button type="button" class="inline-action inline-action--danger" @click="handleDeleteSelected">
              删除实体
            </button>
          </template>

          <template v-else-if="localNotice">
            <span class="mx-status-dot status-dot--muted" aria-hidden="true"></span>
            <span class="inline-text">{{ localNotice }}</span>
          </template>
        </div>
      </section>
    </Teleport>

    <div ref="scrollRef" class="annotator-scroll" @scroll.passive="handleScroll">
      <article class="md-paper">
        <header class="paper-head">
          <div class="paper-eyebrow">
            <span>Rendered Markdown</span>
            <span class="paper-sep" aria-hidden="true">/</span>
            <span class="paper-meta">{{ canonicalText.length }} 字</span>
          </div>
          <span v-if="hasAnnotations" class="paper-saved">已加载标注</span>
          <span v-else class="paper-saved paper-saved--muted">尚未标注</span>
        </header>

        <div ref="stageRef" class="md-stage">
          <div
            ref="bodyRef"
            class="markdown-content"
            :aria-busy="loading"
            @mouseup="handleMouseUp"
            @click="handleCanvasClick"
          >
            <template v-if="hasBlocks">
              <!--
                逐块渲染保留 data-block-id 作为“选区起始块”定位锚点，
                但不再提供任何逐段标签入口：选区跨块时只生成一个 span。
              -->
              <section
                v-for="item in renderedBlocks"
                :key="item.block.id"
                class="md-block"
                :data-block-id="item.block.id"
              >
                <div class="md-block-body" v-html="item.html"></div>
              </section>
            </template>
            <div v-else class="md-block-body" v-html="renderedHtml"></div>
          </div>

          <!--
            实体标签名叠加层：只做视觉投影，aria-hidden + pointer-events:none，
            不参与命中测试，因此不会挡住正文的选区拖拽、点击与链接。
          -->
          <div
            v-if="spanLabelVisuals.length > 0"
            class="span-label-layer"
            aria-hidden="true"
          >
            <span
              v-for="chip in spanLabelVisuals"
              :key="chip.key"
              class="span-label-chip"
              :class="{
                'is-selected': chip.selected,
                'is-linked': chip.linked,
                'is-missing': chip.missing,
                'is-end': chip.alignEnd,
              }"
              :style="{
                left: `${chip.left}px`,
                top: `${chip.top}px`,
                maxWidth: `${chip.maxWidth}px`,
                background: chip.color,
              }"
              :title="chip.title"
              @click.stop="handleSpanChipClick(chip.spanId)"
            >{{ chip.label }}</span>
          </div>

          <div
            v-if="!highlightSupported && fallbackRects.length > 0"
            class="fallback-highlight-layer"
            aria-hidden="true"
          >
            <span
              v-for="rect in fallbackRects"
              :key="rect.key"
              class="fallback-highlight"
              :class="{ 'is-selected': rect.selected, 'is-linked': rect.linked }"
              :style="{
                left: `${rect.left}px`,
                top: `${rect.top}px`,
                width: `${rect.width}px`,
                height: `${rect.height}px`,
                background: rect.background,
              }"
            ></span>
          </div>

          <svg
            v-if="relationVisuals.length > 0"
            class="relation-layer"
            :viewBox="`0 0 ${overlayWidth} ${overlayHeight}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="实体关系曲线"
          >
            <defs>
              <marker
                v-for="marker in relationMarkers"
                :id="marker.id"
                :key="marker.id"
                markerWidth="6"
                markerHeight="6"
                refX="5.2"
                refY="3"
                orient="auto"
              >
                <path d="M0,0 L6,3 L0,6 Z" :fill="marker.color" />
              </marker>
            </defs>

            <g v-for="visual in relationVisuals" :key="visual.index" class="relation-group">
              <path
                class="relation-hit"
                :d="visual.path"
                fill="none"
                stroke="transparent"
                stroke-width="16"
                @mouseenter="handleRelationEnter(visual.index)"
                @mouseleave="handleRelationLeave"
                @click.stop="handleRelationSelect(visual.index)"
              />
              <path
                class="relation-path"
                :class="{
                  'is-selected': selectedRelationIndex === visual.index,
                  'is-hovered': hoveredRelation === visual.index,
                }"
                :d="visual.path"
                fill="none"
                :stroke="visual.color"
                :marker-end="`url(#lf-arrow-${visual.index})`"
              />
              <text
                class="relation-label"
                :class="{ 'is-selected': selectedRelationIndex === visual.index }"
                :x="visual.labelX"
                :y="visual.labelY"
                text-anchor="middle"
                :fill="visual.color"
              >
                {{ visual.type }}
              </text>
            </g>
          </svg>

          <div v-if="renderError" class="canvas-state canvas-state--error">
            <strong>Markdown 渲染失败</strong>
            <span>{{ renderError }}</span>
          </div>

          <div v-else-if="isEmpty" class="canvas-state">
            <strong>Markdown 内容为空</strong>
            <span>可在「编辑 Markdown」模式中补充内容后回来标注。</span>
          </div>

          <div v-if="loading" class="canvas-state canvas-state--loading" aria-live="polite">
            <span class="loading-pulse" aria-hidden="true"></span>
            <span>正在加载文档与标注…</span>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.markdown-annotator {
  --lf-paper: var(--paper, #f6f3ec);
  --lf-paper-deep: var(--paper-deep, #efebe2);
  --lf-surface: var(--surface, #fffdf9);
  --lf-raised: var(--surface-raised, #fff);
  --lf-sunken: var(--surface-sunken, #f2eee6);
  --lf-ink: var(--ink, #17181b);
  --lf-ink-2: var(--ink-2, #3e4147);
  --lf-ink-3: var(--ink-3, #6e727a);
  --lf-ink-4: var(--ink-4, #9a9da3);
  --lf-line: var(--line, #e2dccf);
  --lf-line-strong: var(--line-strong, #d2caba);
  --lf-signal: var(--signal, #e4572e);
  --lf-signal-deep: var(--signal-deep, #c44722);
  --lf-signal-soft: var(--signal-soft, #fbe8e1);
  --lf-signal-ink: var(--signal-ink, #8e2f14);
  --lf-success: var(--success, #2f7d5b);
  --lf-danger: var(--danger, #b5403a);
  --lf-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --lf-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --lf-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));
  --lf-shadow-xs: var(--shadow-xs, 0 1px 2px rgba(35, 29, 19, 0.05));
  --lf-shadow: var(--shadow, 0 18px 44px -28px rgba(35, 29, 19, 0.22));

  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  gap: 12px;
}

/* ------------------------------------------------------------
   快捷操作卡片
   ------------------------------------------------------------ */
/*
 * 卡片现在由 Teleport 放到工作区顶部的整宽顶栏里。
 * 默认单行紧凑：减少上下留白，尽量把纵向空间留给正文；
 * 横向留白与外层栏（16px）保持一致，避免出现“卡片里一层、卡片外一层”的双层大留白。
 */
.annotation-tools {
  flex-shrink: 0;
  min-width: 0;
  /* 顶部/底部各 8px：整条工具区高度控制在约 100px，把纵向空间留给正文。 */
  padding: 8px 14px;
  border: 1px solid var(--lf-line);
  border-radius: 14px;
  background: var(--lf-surface);
  box-shadow: var(--lf-shadow-xs);
}

.tools-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 6px;
}

.tools-stats {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 7px;
  min-width: 0;
}

.tools-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.stats-eyebrow {
  margin-right: 3px;
  font-family: var(--lf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--lf-ink-3);
}

.stats-item {
  font-family: var(--lf-mono);
  font-size: 10.5px;
  color: var(--lf-ink-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.stats-divider {
  color: var(--lf-line-strong);
}

.compat-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border: 1px solid rgba(169, 118, 30, 0.25);
  border-radius: 999px;
  background: var(--warning-bg, #faf2e1);
  color: var(--warning, #a9761e);
  font-size: 9.5px;
  white-space: nowrap;
}

/* 字典缺失警示徽标：用警示色 + 实心边框，避免与“灰色即无关”混淆。 */
.stats-missing {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  border: 1px solid rgba(169, 118, 30, 0.45);
  border-radius: 999px;
  background: var(--warning-bg, #faf2e1);
  color: var(--warning, #a9761e);
  font-family: var(--lf-mono);
  font-size: 9.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

/* 「仅选中」空态的解释性提示：只做弱提醒，不抢缺失标签警示的注意力。 */
.stats-hint {
  padding: 1px 6px;
  border: 1px dashed var(--lf-line-strong);
  border-radius: 999px;
  color: var(--lf-ink-3);
  font-family: var(--lf-mono);
  font-size: 9.5px;
  white-space: nowrap;
}

.mx-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  height: 29px;
  padding: 0 10px;
  border: 1px solid var(--lf-line);
  border-radius: 8px;
  background: var(--lf-surface);
  color: var(--lf-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 180ms var(--lf-ease),
    border-color 180ms var(--lf-ease),
    color 180ms var(--lf-ease),
    transform 180ms var(--lf-ease);
}

.mx-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--lf-line-strong);
  background: var(--lf-raised);
}

.mx-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.btn-quiet {
  border-color: transparent;
  background: transparent;
  color: var(--lf-ink-3);
}

.btn-quiet:hover:not(:disabled) {
  border-color: transparent;
  background: var(--lf-paper-deep);
  color: var(--lf-ink);
}

.mx-btn-sm {
  height: 27px;
  padding: 0 9px;
  font-size: 11px;
}

/*
 * 标签名显示方式：与 27px 高的按钮组同排，内部也是 27px 高，
 * 视觉上是一枚「带前缀文字的分段开关」，而不是三个独立按钮。
 */
.span-label-mode {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
  min-height: 27px;
}

.span-label-mode-label {
  margin-right: 1px;
  font-family: var(--lf-mono);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--lf-ink-3);
  white-space: nowrap;
}

.span-label-mode-label::after {
  content: '：';
  color: var(--lf-ink-4);
}

.span-label-mode-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 27px;
  padding: 0 8px;
  border: 1px solid var(--lf-line);
  border-radius: 7px;
  background: var(--lf-surface);
  color: var(--lf-ink-3);
  font-family: inherit;
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 180ms var(--lf-ease),
    border-color 180ms var(--lf-ease),
    color 180ms var(--lf-ease);
}

.span-label-mode-btn:hover {
  border-color: var(--lf-line-strong);
  color: var(--lf-ink);
}

.span-label-mode-btn.is-active {
  border-color: rgba(228, 87, 46, 0.35);
  background: var(--lf-signal-soft);
  color: var(--lf-signal-ink);
  font-weight: 600;
}

.span-label-mode-btn:focus-visible {
  outline: none;
  border-color: var(--lf-signal);
  box-shadow: 0 0 0 3px rgba(228, 87, 46, 0.22);
}

/*
 * 工具条「快捷键设置」入口：与左侧字典卡片头部同一套 accent 胶囊语言，
 * 但工具条本身高 27px 的按钮组，这里对齐到 27px 保证同排不参差。
 */
.shortcut-entry-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 27px;
  padding: 0 9px;
  border: 1px solid rgba(228, 87, 46, 0.35);
  border-radius: 8px;
  background: var(--lf-signal-soft);
  color: var(--lf-signal-ink);
  font-family: inherit;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 180ms var(--lf-ease),
    border-color 180ms var(--lf-ease),
    color 180ms var(--lf-ease),
    box-shadow 180ms var(--lf-ease);
}

.shortcut-entry-icon {
  width: 12px;
  height: 12px;
  flex: 0 0 auto;
}

.shortcut-entry-btn:hover {
  border-color: var(--lf-signal);
  background: #F7DACF;
  color: var(--lf-signal-deep);
  box-shadow: 0 6px 14px -12px rgba(228, 87, 46, 0.6);
}

.shortcut-entry-btn:focus-visible {
  outline: none;
  border-color: var(--lf-signal);
  box-shadow: 0 0 0 3px rgba(228, 87, 46, 0.22);
}

.kbd-hint {
  font-family: var(--lf-mono);
  font-size: 9px;
  color: var(--lf-ink-4);
}

.chip-columns {
  display: grid;
  /* 实体标签占主要宽度（整宽顶栏下可容纳更多 chip），关系列保持可读的最小宽度。 */
  grid-template-columns: minmax(0, 1fr) minmax(200px, 260px);
  gap: 16px;
}

/* 项目没有关系类型：整列隐藏，实体标签独占整宽。 */
.chip-columns.is-single {
  grid-template-columns: minmax(0, 1fr);
  gap: 0;
}

.chip-columns.is-single .chip-column {
  padding-right: 0;
}

.chip-column {
  min-width: 0;
  padding-right: 16px;
}

.chip-column--relation {
  padding-right: 0;
  padding-left: 16px;
  border-left: 1px solid var(--lf-line);
}

.chip-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}

.chip-title {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--lf-ink);
}

.chip-hint {
  font-family: var(--lf-mono);
  font-size: 9.5px;
  letter-spacing: 0.03em;
  color: var(--lf-ink-3);
}

/* 展开全部 / 收起：只在超出阈值时出现，贴右侧，不挤占标题与快捷键提示。 */
.chip-expand-btn {
  flex-shrink: 0;
  align-self: center;
  margin-left: auto;
  padding: 0 2px;
  border: 0;
  background: transparent;
  color: var(--lf-signal-deep);
  font-family: inherit;
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.chip-expand-btn:hover {
  color: var(--lf-ink);
}

/*
 * 默认单行横向滚动：标签多时不会把顶栏撑成多行。
 * padding-bottom 留 2px，避免 chip 的 hover 阴影被滚动容器裁掉。
 */
.chip-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.chip-row::-webkit-scrollbar {
  height: 5px;
}

.chip-row::-webkit-scrollbar-track {
  background: transparent;
}

.chip-row::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(23, 24, 27, 0.16);
}

.chip-row::-webkit-scrollbar-thumb:hover {
  background: rgba(23, 24, 27, 0.3);
}

/* 展开态才换行，完整展示所有标签。 */
.chip-row.is-expanded {
  flex-wrap: wrap;
  overflow: visible;
  padding-bottom: 0;
}

/* chip 自身不参与拉伸/收缩，保证横向滚动时宽度稳定。 */
.chip-row > .mx-label-chip,
.chip-row > .chip-empty {
  flex: 0 0 auto;
}

.mx-label-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 27px;
  padding: 4px 9px;
  border: 1px solid rgba(23, 24, 27, 0.18);
  border-radius: 7px;
  color: var(--lf-ink);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.25;
  cursor: pointer;
  user-select: none;
  opacity: 0.78;
  transition:
    opacity 200ms var(--lf-ease),
    transform 200ms var(--lf-ease),
    box-shadow 200ms var(--lf-ease),
    border-color 200ms var(--lf-ease);
}

.mx-label-chip:hover {
  transform: translateY(-1px);
  border-color: rgba(23, 24, 27, 0.38);
  box-shadow: var(--lf-shadow-xs);
  opacity: 1;
}

.mx-label-chip:active {
  transform: scale(0.985);
}

/* 已有待标注选区时，标签 chip 需要足够醒目，避免用户误以为选中无效。 */
.mx-label-chip.is-armed {
  opacity: 1;
  border-color: rgba(228, 87, 46, 0.55);
  box-shadow:
    0 0 0 2px rgba(228, 87, 46, 0.16),
    var(--lf-shadow-xs);
}

.relation-chip {
  color: #fffdf9;
  border-color: rgba(23, 24, 27, 0.22);
}

.relation-chip:hover {
  border-color: rgba(23, 24, 27, 0.5);
}

/*
 * 快捷键徽标：原来半透明白在浅色 chip 上几乎看不清，
 * 改为接近实白的底 + 细描边 + 600 字重，保证「数字键」本身成为可读信息。
 */
.chip-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  padding: 1px 4px;
  border: 1px solid rgba(23, 24, 27, 0.1);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.92);
  color: var(--lf-ink-2);
  font-family: var(--lf-mono);
  font-size: 9px;
  font-weight: 600;
  line-height: 1.3;
}

/* 关系 chip 是深色底，白描边 + 半透明白保留层级但不再发灰。 */
.chip-key--light {
  border-color: rgba(255, 253, 249, 0.3);
  background: rgba(255, 255, 255, 0.22);
  color: rgba(255, 253, 249, 0.95);
}

/*
 * 自定义组合键可能很长（Alt+Shift+P、Ctrl+Alt+Shift+K），
 * 徽标限宽省略，保证 chip 不因快捷键长度而变形。
 * 底色用 signal-soft 与默认数字键区分：长组合键更醒目，但尺寸不超出 chip。
 */
.chip-key.is-combo {
  max-width: 84px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-color: rgba(228, 87, 46, 0.28);
  background: var(--lf-signal-soft);
  color: var(--lf-signal-ink);
  letter-spacing: -0.02em;
}

.chip-empty {
  align-self: center;
  font-size: 10.5px;
  color: var(--lf-ink-3);
}

/* 内联提示条：不使用弹窗；仅在有待定选区/选中项/提示时渲染。 */
.inline-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  margin-top: 8px;
  padding: 6px 10px;
  border: 1px solid var(--lf-line);
  border-radius: 9px;
  background: var(--lf-sunken);
  color: var(--lf-ink-3);
  font-size: 11px;
  line-height: 1.55;
}

.inline-bar.is-pending {
  border-color: rgba(228, 87, 46, 0.32);
  background: var(--lf-signal-soft);
  color: var(--lf-signal-ink);
}

/* 选中实体的标签已不在字典：整条提示改用警示色，不只靠灰色高亮传达。 */
.inline-bar.is-warning {
  border-color: rgba(169, 118, 30, 0.45);
  background: var(--warning-bg, #faf2e1);
  color: #7d5710;
}

.inline-missing {
  margin-left: 2px;
  font-weight: 600;
  color: var(--warning, #a9761e);
}

.inline-text {
  min-width: 0;
  flex: 1;
}

.inline-bar kbd {
  display: inline-block;
  padding: 0 4px;
  border: 1px solid var(--lf-line-strong);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.48);
  color: var(--lf-ink-2);
  font-family: var(--lf-mono);
  font-size: 9px;
  line-height: 1.5;
}

.mx-status-dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--lf-signal);
}

.status-dot--relation {
  background: var(--lf-signal-deep);
}

.status-dot--muted {
  background: var(--lf-ink-4);
}

.status-dot--warning {
  background: var(--warning, #a9761e);
}

.inline-action {
  flex-shrink: 0;
  padding: 2px 4px;
  border: none;
  background: transparent;
  color: var(--lf-signal-ink);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 500;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.inline-action:hover {
  color: var(--lf-ink);
}

.inline-action--danger {
  color: var(--lf-danger);
}

/* ------------------------------------------------------------
   画布
   ------------------------------------------------------------ */
.annotator-scroll {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0 2px 24px;
}

.md-paper {
  position: relative;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--lf-line);
  border-radius: 22px;
  background: var(--lf-raised);
  box-shadow: var(--lf-shadow);
  animation: lf-canvas-in 300ms var(--lf-ease) both;
}

.paper-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px clamp(20px, 3vw, 46px) 12px;
  border-bottom: 1px solid var(--lf-line);
}

.paper-eyebrow {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--lf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--lf-ink-3);
}

.paper-sep {
  color: var(--lf-line-strong);
}

.paper-meta {
  letter-spacing: 0.05em;
  font-variant-numeric: tabular-nums;
}

.paper-saved {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--success-bg, #eaf4ee);
  color: var(--lf-success);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.paper-saved--muted {
  background: var(--lf-sunken);
  color: var(--lf-ink-4);
}

.md-stage {
  position: relative;
}

/* ------------------------------------------------------------
   逐块渲染
   ------------------------------------------------------------ */
.md-block {
  position: relative;
}

.markdown-content > .md-block:first-child .md-block-body > :first-child,
.markdown-content > .md-block-body > :first-child {
  margin-top: 0 !important;
}

.markdown-content > .md-block:last-child .md-block-body > :last-child,
.markdown-content > .md-block-body > :last-child {
  margin-bottom: 0 !important;
}

.fallback-highlight-layer {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

.fallback-highlight {
  position: absolute;
  border-radius: 4px;
  mix-blend-mode: multiply;
  pointer-events: none;
  transition: background-color 180ms var(--lf-ease);
}

.fallback-highlight.is-linked {
  box-shadow: inset 0 0 0 1px rgba(196, 71, 34, 0.28);
}

.fallback-highlight.is-selected {
  box-shadow: inset 0 0 0 2px var(--lf-signal-deep);
}

/*
 * 实体标签名叠加层。
 * 层级在正文（z-index:1）之上、关系曲线（z-index:3）之下：
 * 曲线跨行穿行时不能被胶囊切断，而胶囊本身绝不能吃事件。
 */
.span-label-layer {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}

.span-label-chip {
  position: absolute;
  display: inline-flex;
  align-items: center;
  height: 14px;
  padding: 0 4px;
  border-radius: 4px;
  border: 1px solid rgba(35, 29, 19, 0.16);
  /*
   * 行间空白只有约 11px，胶囊必然压住上一行字底 2–3px。
   * 纸色只放在上缘：既把胶囊与上一行文字隔开，又不会在本行高亮底带上切出白色缺口。
   */
  box-shadow:
    0 -1.5px 0 0 var(--lf-paper),
    0 2px 6px -3px rgba(35, 29, 19, 0.4);
  color: #2c2b27;
  /* 中文标签没有等宽需求：等宽字体族无中文字形，10px 下会回落到系统字造成笔画粘连。 */
  font-family: 'Geist', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1;
  letter-spacing: 0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 1;
  /* 胶囊可点击选中对应实体；层级本身仍是 pointer-events:none，只有胶囊吃事件。 */
  pointer-events: auto;
  cursor: pointer;
}

/* 悬停反馈：点之前就能确认它是可点击的控件，而不是纯装饰。 */
.span-label-chip:hover {
  border-color: rgba(35, 29, 19, 0.38);
  box-shadow:
    0 -1.5px 0 0 var(--lf-paper),
    0 0 0 1px rgba(35, 29, 19, 0.18),
    0 3px 8px -4px rgba(35, 29, 19, 0.5);
}

/* 靠近右边界时改为向左生长：left 是锚点，用 transform 让右边缘贴合。 */
.span-label-chip.is-end {
  transform: translateX(-100%);
}

.span-label-chip.is-linked {
  border-color: rgba(196, 71, 34, 0.45);
}

.span-label-chip.is-selected {
  z-index: 1;
  border-color: var(--lf-signal-deep);
  box-shadow:
    0 -1.5px 0 0 var(--lf-paper),
    0 0 0 1.5px rgba(196, 71, 34, 0.55),
    0 3px 8px -4px rgba(35, 29, 19, 0.5);
}

/* 字典缺失标签用虚线 + 深警示字色：与调色板里的灰色标签明确区分（灰底上仍要达到可读对比度）。 */
.span-label-chip.is-missing {
  border-style: dashed;
  border-color: rgba(120, 82, 12, 0.9);
  color: #33260a;
}

/*
 * 窄屏正文会降到 14.5px / 1.8（行高约 26px，行间只剩约 9px）。
 * 此时把胶囊压到 13px / 9.5px，避免压掉上一行近一个字高。
 */
@media (max-width: 720px) {
  .span-label-chip {
    height: 13px;
    padding: 0 4px;
    font-size: 9.5px;
  }
}

.relation-layer {
  position: absolute;
  inset: 0;
  z-index: 3;
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
}

.relation-hit {
  pointer-events: stroke;
  cursor: pointer;
}

.relation-path {
  stroke-width: 1.6;
  opacity: 0.68;
  stroke-linecap: round;
  pointer-events: none;
  transition:
    stroke-width 180ms var(--lf-ease),
    opacity 180ms var(--lf-ease);
}

.relation-path.is-hovered {
  stroke-width: 2.4;
  opacity: 0.98;
}

.relation-path.is-selected {
  stroke-width: 2.8;
  opacity: 1;
}

.relation-label {
  font-family: var(--lf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.03em;
  paint-order: stroke;
  stroke: var(--lf-raised);
  stroke-width: 3px;
  stroke-linejoin: round;
  pointer-events: none;
  transition: font-weight 180ms var(--lf-ease);
}

.relation-label.is-selected {
  font-weight: 600;
}

.canvas-state {
  position: absolute;
  inset: 20px;
  z-index: 4;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 24px;
  border: 1px dashed var(--lf-line-strong);
  border-radius: 16px;
  background: rgba(255, 253, 249, 0.88);
  text-align: center;
  color: var(--lf-ink-3);
  font-size: 12px;
  line-height: 1.6;
  backdrop-filter: blur(4px);
}

.canvas-state strong {
  font-family: var(--lf-display);
  font-size: 22px;
  font-weight: 400;
  line-height: 1.2;
  color: var(--lf-ink-2);
}

.canvas-state--error {
  border-color: rgba(181, 64, 58, 0.25);
  background: rgba(250, 236, 234, 0.92);
  color: var(--lf-danger);
}

.canvas-state--loading {
  flex-direction: row;
  gap: 9px;
  inset: auto 20px 20px;
  min-height: 48px;
  background: var(--lf-ink);
  color: var(--paper, #f6f3ec);
  border: none;
  box-shadow: var(--lf-shadow);
}

.loading-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--lf-signal);
  animation: lf-pulse 1.2s ease-in-out infinite;
}

@keyframes lf-canvas-in {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes lf-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.82);
  }
}

@media (max-width: 900px) {
  .chip-columns {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .chip-column {
    padding-right: 0;
  }

  .chip-column--relation {
    padding-top: 12px;
    padding-left: 0;
    border-top: 1px solid var(--lf-line);
    border-left: none;
  }

  .md-paper {
    border-radius: 18px;
  }

  .inline-bar {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .inline-text {
    flex-basis: calc(100% - 16px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .md-paper,
  .loading-pulse {
    animation: none;
  }

  .mx-btn,
  .mx-label-chip,
  .inline-action,
  .relation-path,
  .fallback-highlight {
    transition: none;
  }
}
</style>

