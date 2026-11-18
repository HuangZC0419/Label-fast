<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { AnnotationRecord, BlockInfo } from '../../types'
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

const props = withDefaults(
  defineProps<{
    fileId: string
    markdown: string
    labels: string[]
    relationTypes: string[]
    /** 后端权威切块；为空时回退为整篇 Markdown 渲染。 */
    blocks?: BlockInfo[]
    annotations?: AnnotationRecord | null
    loading?: boolean
    /** 编辑模式下画布仍挂载但隐藏，此时屏蔽标注快捷键。 */
    active?: boolean
  }>(),
  {
    blocks: () => [],
    annotations: null,
    loading: false,
    active: true,
  },
)

const emit = defineEmits<{
  /** 用户滚动时上报 0..1 的纵向滚动比例，用于与 PDF 预览联动。 */
  'scroll-state': [ratio: number]
  /** 标注数据发生用户侧变化，父组件据此触发自动保存。 */
  change: []
}>()

const annotation = useMarkdownAnnotation({
  labels: () => props.labels,
  relationTypes: () => props.relationTypes,
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
   关系曲线与兼容高亮测量
   ============================================================ */

function scheduleMeasure(): void {
  if (measureFrame) return
  measureFrame = requestAnimationFrame(() => {
    measureFrame = 0
    measureLayout()
  })
}

function measureLayout(): void {
  const stage = stageRef.value
  const map = annotation.textMap.value
  if (!stage || !map) {
    relationVisuals.value = []
    fallbackRects.value = []
    return
  }

  const stageRect = stage.getBoundingClientRect()
  if (stageRect.width <= 0 || stageRect.height <= 0) {
    // 组件被 v-show 隐藏时无法测量；重新显示后由父组件调用 refreshLayout。
    relationVisuals.value = []
    fallbackRects.value = []
    return
  }

  overlayWidth.value = Math.max(1, Math.ceil(stageRect.width))
  overlayHeight.value = Math.max(1, Math.ceil(stage.scrollHeight || stageRect.height))

  relationVisuals.value = buildRelationVisuals(map, stageRect)
  fallbackRects.value = highlightSupported.value
    ? []
    : buildFallbackRects(map, stageRect)
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

onMounted(() => {
  window.addEventListener('resize', scheduleMeasure)
  bodyRef.value?.addEventListener('load', handleImageLoad, true)
  bodyRef.value?.addEventListener('error', handleImageLoad, true)
  scrollRef.value?.addEventListener('scroll', scheduleMeasure, { passive: true })

  if (typeof ResizeObserver !== 'undefined' && stageRef.value) {
    resizeObserver = new ResizeObserver(scheduleMeasure)
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
  window.removeEventListener('resize', scheduleMeasure)
  bodyRef.value?.removeEventListener('load', handleImageLoad, true)
  bodyRef.value?.removeEventListener('error', handleImageLoad, true)
  scrollRef.value?.removeEventListener('scroll', scheduleMeasure)
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
  setScrollRatio,
  getScrollRatio,
})
</script>

<template>
  <div class="markdown-annotator">
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
          <slot name="mode-toggle" />
        </div>
      </div>

      <div class="chip-columns">
        <div class="chip-column">
          <div class="chip-head">
            <h3 class="chip-title">实体标签</h3>
            <span class="chip-hint">快捷键 1–9</span>
          </div>
          <div class="chip-row">
            <button
              v-for="(label, index) in labels"
              :key="label"
              type="button"
              class="mx-label-chip"
              :class="{ 'is-armed': Boolean(pendingSelection) }"
              :style="labelChipStyle(label)"
              :title="pendingSelection ? `应用标签：${label}` : '先在正文中选中文本'"
              @click="handleLabelClick(label)"
            >
              <span v-if="index < 9" class="chip-key">{{ index + 1 }}</span>
              <span>{{ label }}</span>
            </button>
            <span v-if="labels.length === 0" class="chip-empty">项目未配置实体标签</span>
          </div>
        </div>

        <div class="chip-column chip-column--relation">
          <div class="chip-head">
            <h3 class="chip-title">关系类型</h3>
            <span class="chip-hint">Ctrl + 1–9</span>
          </div>
          <div class="chip-row">
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
            <span v-if="relationTypes.length === 0" class="chip-empty">项目未配置关系类型</span>
          </div>
        </div>
      </div>

      <div
        class="inline-bar"
        :class="{ 'is-pending': Boolean(pendingSelection || pendingRelation) }"
        role="status"
        aria-live="polite"
      >
        <template v-if="pendingSelection">
          <span class="mx-status-dot" aria-hidden="true"></span>
          <span class="inline-text">
            已选中「{{ pendingText }}」· 点击实体标签或按 <kbd>1–9</kbd> 应用
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
          <span class="mx-status-dot" aria-hidden="true"></span>
          <span class="inline-text">
            实体「{{ selectedSpanText }}」· 再点一个实体建立关系 · <kbd>Delete</kbd> 删除
          </span>
          <button type="button" class="inline-action inline-action--danger" @click="handleDeleteSelected">
            删除实体
          </button>
        </template>

        <template v-else-if="localNotice">
          <span class="mx-status-dot status-dot--muted" aria-hidden="true"></span>
          <span class="inline-text">{{ localNotice }}</span>
        </template>

        <template v-else>
          <span class="mx-status-dot status-dot--muted" aria-hidden="true"></span>
          <span class="inline-text">
            选中正文文本添加实体；依次点击两个实体后选择关系。Delete 删除，Ctrl+Z 撤销。
          </span>
        </template>
      </div>
    </section>

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
.annotation-tools {
  flex-shrink: 0;
  padding: 12px 16px 10px;
  border: 1px solid var(--lf-line);
  border-radius: 16px;
  background: var(--lf-surface);
  box-shadow: var(--lf-shadow-xs);
}

.tools-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 10px;
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

.kbd-hint {
  font-family: var(--lf-mono);
  font-size: 9px;
  color: var(--lf-ink-4);
}

.chip-columns {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
  gap: 16px;
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
  margin-bottom: 7px;
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

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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

.chip-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--lf-ink-2);
  font-family: var(--lf-mono);
  font-size: 9px;
  line-height: 1.3;
}

.chip-key--light {
  background: rgba(255, 255, 255, 0.16);
  color: rgba(255, 253, 249, 0.86);
}

.chip-empty {
  align-self: center;
  font-size: 10.5px;
  color: var(--lf-ink-3);
}

/* 内联提示条：不使用弹窗 */
.inline-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 31px;
  margin-top: 10px;
  padding: 7px 10px;
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

.relation-layer {
  position: absolute;
  inset: 0;
  z-index: 2;
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
  z-index: 3;
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
