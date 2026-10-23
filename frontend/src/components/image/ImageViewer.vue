<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { getImageUrl, getLabelColor, type BoxItem } from '../../composables/useImageProject'

const props = withDefaults(
  defineProps<{
    imageName: string | null
    boxes: BoxItem[]
    drawingEnabled: boolean
    currentLabel: string
    /** 项目标签顺序，用于按标签下标分配框颜色。 */
    labels?: string[]
    canPrev?: boolean
    canNext?: boolean
    positionLabel?: string
    emptyHint?: string
  }>(),
  {
    labels: () => [],
    canPrev: false,
    canNext: false,
    positionLabel: '',
    emptyHint: '暂无图片',
  },
)

const emit = defineEmits<{
  (event: 'box-created', box: BoxItem): void
  (event: 'prev'): void
  (event: 'next'): void
}>()

const stageRef = ref<HTMLDivElement | null>(null)
const imageRef = ref<HTMLImageElement | null>(null)

/** 图片加载、容器尺寸变化时递增，驱动覆盖层重新测量。 */
const layoutVersion = ref(0)

const drawing = ref(false)
const drawingBox = ref<BoxItem | null>(null)
const activePointerId = ref<number | null>(null)

const imageUrl = computed(() => (props.imageName ? getImageUrl(props.imageName) : ''))
const canDraw = computed(
  () => props.drawingEnabled && Boolean(props.currentLabel) && Boolean(props.imageName),
)

interface LayoutMetrics {
  offsetX: number
  offsetY: number
  scaleX: number
  scaleY: number
  naturalWidth: number
  naturalHeight: number
}

/**
 * 小图在画布中按比例放大到接近占满舞台（最多 6×），
 * 大图仍由 max-width/max-height 约束，不再二次放大。
 * 缩放通过 transform 实现，getBoundingClientRect 会包含缩放，
 * 因此框坐标换算与覆盖层定位仍然成立。
 */
const imageScale = computed<number>(() => {
  void layoutVersion.value

  const stage = stageRef.value
  const image = imageRef.value
  if (!stage || !image) return 1

  const naturalWidth = image.naturalWidth
  const naturalHeight = image.naturalHeight
  const baseWidth = image.offsetWidth
  const baseHeight = image.offsetHeight
  if (!naturalWidth || !naturalHeight || !baseWidth || !baseHeight) return 1

  const padding = 48
  const availableWidth = Math.max(0, stage.clientWidth - padding)
  const availableHeight = Math.max(0, stage.clientHeight - padding)
  if (!availableWidth || !availableHeight) return 1

  const fit = Math.min(availableWidth / baseWidth, availableHeight / baseHeight)
  if (!Number.isFinite(fit)) return 1
  return Math.min(6, Math.max(1, fit))
})

/**
 * object-fit: contain 的图片在容器内会居中留白，
 * 覆盖层需要同时考虑图片相对容器的偏移与缩放比例。
 */
const metrics = computed<LayoutMetrics | null>(() => {
  void layoutVersion.value
  // transform 缩放会改变图片的实际矩形，指标需要跟随缩放值重新计算
  void imageScale.value

  const stage = stageRef.value
  const image = imageRef.value
  if (!stage || !image) return null

  const stageRect = stage.getBoundingClientRect()
  const imageRect = image.getBoundingClientRect()
  const naturalWidth = image.naturalWidth
  const naturalHeight = image.naturalHeight

  if (imageRect.width <= 0 || imageRect.height <= 0) return null
  if (!Number.isFinite(naturalWidth) || !Number.isFinite(naturalHeight)) return null
  if (naturalWidth <= 0 || naturalHeight <= 0) return null

  return {
    // 绝对定位子元素以 padding box 为基准，需要扣除原容器的 1px 边框
    offsetX: imageRect.left - stageRect.left - stage.clientLeft,
    offsetY: imageRect.top - stageRect.top - stage.clientTop,
    scaleX: imageRect.width / naturalWidth,
    scaleY: imageRect.height / naturalHeight,
    naturalWidth,
    naturalHeight,
  }
})

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

// transform 缩放应用后，getBoundingClientRect 才会反映新的显示尺寸；
// 等 DOM 更新完成后再触发一次测量，保证框覆盖层与缩放后的图片对齐。
watch(imageScale, async () => {
  await nextTick()
  layoutVersion.value += 1
})

function boxStyle(box: BoxItem, useMinSize = false): Record<string, string> {
  const layout = metrics.value
  if (!layout) return { display: 'none' }

  const leftOnImage = Math.min(box.x1, box.x2)
  const topOnImage = Math.min(box.y1, box.y2)
  const widthOnImage = Math.abs(box.x2 - box.x1)
  const heightOnImage = Math.abs(box.y2 - box.y1)

  const left = layout.offsetX + leftOnImage * layout.scaleX
  const top = layout.offsetY + topOnImage * layout.scaleY
  const width = widthOnImage * layout.scaleX
  const height = heightOnImage * layout.scaleY
  const color = getLabelColor(box.label, props.labels)

  return {
    left: `${left}px`,
    top: `${top}px`,
    width: `${useMinSize ? Math.max(1, width) : width}px`,
    height: `${useMinSize ? Math.max(1, height) : height}px`,
    borderColor: color,
    backgroundColor: `${color}20`,
    color,
  }
}

let layoutFrame = 0

/** 合并同一帧内的多次尺寸变化，避免重复布局计算。 */
function scheduleLayoutUpdate(): void {
  if (layoutFrame) return
  layoutFrame = window.requestAnimationFrame(() => {
    layoutFrame = 0
    layoutVersion.value += 1
  })
}

function handleImageLoad(): void {
  layoutVersion.value += 1
}

function pointerToImagePixels(
  event: PointerEvent,
  requireInside = false,
): { x: number; y: number } | null {
  const image = imageRef.value
  if (!image) return null

  const rect = image.getBoundingClientRect()
  const naturalWidth = image.naturalWidth
  const naturalHeight = image.naturalHeight
  if (rect.width <= 0 || rect.height <= 0 || !naturalWidth || !naturalHeight) return null

  const inside =
    event.clientX >= rect.left &&
    event.clientX <= rect.right &&
    event.clientY >= rect.top &&
    event.clientY <= rect.bottom

  if (requireInside && !inside) return null

  const x = ((clamp(event.clientX, rect.left, rect.right) - rect.left) * naturalWidth) / rect.width
  const y = ((clamp(event.clientY, rect.top, rect.bottom) - rect.top) * naturalHeight) / rect.height

  return {
    x: clamp(x, 0, naturalWidth),
    y: clamp(y, 0, naturalHeight),
  }
}

function releasePointerCapture(pointerId: number | null): void {
  const stage = stageRef.value
  if (!stage || pointerId === null) return
  try {
    if (stage.hasPointerCapture(pointerId)) {
      stage.releasePointerCapture(pointerId)
    }
  } catch {
    // 指针已释放时忽略异常。
  }
}

function cancelDrawing(): void {
  releasePointerCapture(activePointerId.value)
  drawing.value = false
  drawingBox.value = null
  activePointerId.value = null
}

function handlePointerDown(event: PointerEvent): void {
  if (!canDraw.value || drawing.value) return
  if (event.pointerType === 'mouse' && event.button !== 0) return

  const point = pointerToImagePixels(event, true)
  if (!point) return

  event.preventDefault()

  drawing.value = true
  activePointerId.value = event.pointerId
  drawingBox.value = {
    x1: point.x,
    y1: point.y,
    x2: point.x,
    y2: point.y,
    label: props.currentLabel,
  }

  const stage = stageRef.value
  if (stage) {
    try {
      stage.setPointerCapture(event.pointerId)
    } catch {
      // 部分浏览器不支持在 pointerdown 时捕获，忽略即可。
    }
  }
}

function handlePointerMove(event: PointerEvent): void {
  if (!drawing.value || !drawingBox.value) return
  if (activePointerId.value !== null && event.pointerId !== activePointerId.value) return

  const point = pointerToImagePixels(event)
  if (!point) return

  drawingBox.value = {
    ...drawingBox.value,
    x2: point.x,
    y2: point.y,
  }
}

function finishDrawing(): void {
  const box = drawingBox.value
  cancelDrawing()
  if (!box || !props.imageName) return

  // 宽或高不足 3 自然像素视为误触（与原实现一致）。
  if (Math.abs(box.x2 - box.x1) < 3 || Math.abs(box.y2 - box.y1) < 3) return

  emit('box-created', { ...box })
}

function handlePointerUp(event: PointerEvent): void {
  if (!drawing.value) return
  if (activePointerId.value !== null && event.pointerId !== activePointerId.value) return

  const point = pointerToImagePixels(event)
  if (point && drawingBox.value) {
    drawingBox.value = {
      ...drawingBox.value,
      x2: point.x,
      y2: point.y,
    }
  }

  finishDrawing()
}

function handlePointerCancel(event: PointerEvent): void {
  if (!drawing.value) return
  if (activePointerId.value !== null && event.pointerId !== activePointerId.value) return
  cancelDrawing()
}

watch(
  () => props.imageName,
  () => {
    cancelDrawing()
    scheduleLayoutUpdate()
  },
)

watch(
  () => props.drawingEnabled,
  (enabled) => {
    if (!enabled) cancelDrawing()
  },
)

watch(
  () => props.currentLabel,
  (label) => {
    if (!label) cancelDrawing()
  },
)

let resizeObserver: ResizeObserver | null = null

onMounted(() => {
  window.addEventListener('resize', scheduleLayoutUpdate)
  if (typeof ResizeObserver !== 'undefined' && stageRef.value) {
    resizeObserver = new ResizeObserver(scheduleLayoutUpdate)
    resizeObserver.observe(stageRef.value)
  }
  scheduleLayoutUpdate()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', scheduleLayoutUpdate)
  resizeObserver?.disconnect()
  resizeObserver = null
  if (layoutFrame) {
    window.cancelAnimationFrame(layoutFrame)
    layoutFrame = 0
  }
  cancelDrawing()
})
</script>

<template>
  <section class="image-viewer">
    <div
      ref="stageRef"
      class="image-stage"
      :class="{ 'can-draw': canDraw }"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerCancel"
    >
      <img
        v-if="imageName"
        :key="imageName"
        ref="imageRef"
        :src="imageUrl"
        :alt="imageName"
        draggable="false"
        :style="imageScale > 1.02 ? { transform: `scale(${imageScale})` } : undefined"
        @load="handleImageLoad"
        @dragstart.prevent
      />

      <span v-if="imageName && imageScale > 1.02" class="image-zoom-badge">
        FIT {{ imageScale.toFixed(1) }}×
      </span>

      <template v-if="imageName">
        <div
          v-for="(box, index) in boxes"
          :key="`box-${index}`"
          class="image-box"
          :style="boxStyle(box)"
        >
          <span class="image-box-dot tl" />
          <span class="image-box-dot tr" />
          <span class="image-box-dot bl" />
          <span class="image-box-dot br" />
        </div>

        <div
          v-if="drawing && drawingBox"
          class="image-box image-box-drawing"
          :style="boxStyle(drawingBox, true)"
        >
          <span class="image-box-dot tl" />
          <span class="image-box-dot tr" />
          <span class="image-box-dot bl" />
          <span class="image-box-dot br" />
        </div>
      </template>

      <div v-else class="image-empty">
        <div class="image-empty-icon" aria-hidden="true">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2.5" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
        </div>
        <p class="image-empty-en">Nothing on the canvas</p>
        <p class="image-empty-text">{{ emptyHint }}</p>
      </div>
    </div>

    <footer class="image-viewer-footer">
      <button
        type="button"
        class="image-btn"
        :disabled="!canPrev"
        aria-label="上一张图片"
        @click="emit('prev')"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="15 18 9 12 15 6" />
        </svg>
        上一张
      </button>

      <div class="image-viewer-meta">
        <span class="image-viewer-name" :title="imageName ?? ''">{{ imageName || '未选择图片' }}</span>
        <span v-if="positionLabel" class="image-viewer-position">{{ positionLabel }}</span>
      </div>

      <button
        type="button"
        class="image-btn"
        :disabled="!canNext"
        aria-label="下一张图片"
        @click="emit('next')"
      >
        下一张
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
    </footer>
  </section>
</template>
