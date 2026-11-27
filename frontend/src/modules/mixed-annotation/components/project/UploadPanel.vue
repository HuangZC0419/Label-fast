<script setup lang="ts">
import { computed, ref } from 'vue'
import type { BatchSummary, ImportProgress } from '../../types'

const props = defineProps<{
  uploading: boolean
  disabled: boolean
  importing: boolean
  importProgress: ImportProgress | null
  batchSummary?: BatchSummary
  /**
   * 嵌入模式：被 ImportDialog 复用时，弹窗自己负责标题与外壳，
   * 面板层不再重复渲染「导入 Import / PDF · PNG · JPG」头部与外边框。
   * 拖拽、目录扫描、文件选择、进度与队列统计逻辑完全一致，不做分支。
   */
  embedded?: boolean
}>()

const emit = defineEmits<{
  upload: [file: File]
  'upload-batch': [files: File[]]
  invalid: [message: string]
  /** 目录扫描是异步的，父组件需要据此锁定项目切换。 */
  'scanning-change': [active: boolean]
}>()

const ACCEPTED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']

const fileInput = ref<HTMLInputElement | null>(null)
const folderInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
/** 拖入文件夹后读取目录项期间为 true，避免重复触发。 */
const scanning = ref(false)
let dragDepth = 0

const busy = computed(
  () => props.uploading || props.importing || scanning.value,
)
const blocked = computed(() => props.disabled || busy.value)

const dropTitle = computed(() => {
  if (scanning.value) return '正在读取文件夹…'
  if (props.importing) return '正在导入文件夹…'
  if (props.uploading) return '正在上传…'
  return '拖拽 PDF / 图片 / 文件夹到此处'
})

const dropHint = computed(() => {
  if (scanning.value) return '正在扫描文件夹内容，请稍候'
  if (props.importing) return '逐个上传，提交后由后端排队识别'
  if (props.uploading) return '正在创建转换任务，请稍候'
  return '或点击选择文件 · 支持整个文件夹拖入'
})

const progressPercent = computed(() => {
  const progress = props.importProgress
  if (!progress || progress.total <= 0) return 0
  return Math.round((progress.done / progress.total) * 100)
})

const progressIndex = computed(() => {
  const progress = props.importProgress
  if (!progress) return 0
  return progress.current
    ? Math.min(progress.done + 1, progress.total)
    : progress.done
})

const showBatchSummary = computed(() => {
  const summary = props.batchSummary
  if (!summary) return false
  return (
    props.importing ||
    summary.queued > 0 ||
    summary.converting > 0 ||
    summary.failed > 0
  )
})

function isAccepted(file: File): boolean {
  const lower = file.name.toLowerCase()
  return ACCEPTED_EXTENSIONS.some((extension) => lower.endsWith(extension))
}

/** 按文件夹内相对路径排序；没有相对路径时退回文件名。 */
function compareByPath(a: File, b: File): number {
  return (a.webkitRelativePath || a.name).localeCompare(
    b.webkitRelativePath || b.name,
    undefined,
    { numeric: true, sensitivity: 'base' },
  )
}

function supportedSorted(input: Iterable<File>): File[] {
  return Array.from(input).filter(isAccepted).sort(compareByPath)
}

function acceptFile(file: File): void {
  if (!isAccepted(file)) {
    emit('invalid', '仅支持 PDF、PNG、JPG 文件。')
    return
  }
  emit('upload', file)
}

function openPicker(): void {
  if (blocked.value) return
  fileInput.value?.click()
}

function openFolderPicker(): void {
  if (blocked.value) return
  folderInput.value?.click()
}

function onInputChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) acceptFile(file)
  // 允许再次选择同一个文件。
  input.value = ''
}

function onFolderChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const selected = supportedSorted(input.files ?? [])
  input.value = ''

  if (selected.length === 0) {
    emit('invalid', '文件夹中没有找到支持的 PDF、PNG、JPG 文件。')
    return
  }
  emit('upload-batch', selected)
}

/* ------------------------------------------------------------------ */
/* 拖拽：目录递归收集                                                  */
/* ------------------------------------------------------------------ */

function readAllEntries(
  reader: FileSystemDirectoryReader,
): Promise<FileSystemEntry[]> {
  const entries: FileSystemEntry[] = []
  return new Promise((resolve) => {
    const readBatch = (): void => {
      // readEntries 单次只返回一批，必须循环调用直到返回空数组。
      reader.readEntries(
        (batch) => {
          if (batch.length === 0) {
            resolve(entries)
            return
          }
          entries.push(...batch)
          readBatch()
        },
        () => resolve(entries),
      )
    }
    readBatch()
  })
}

async function collectEntryFiles(entry: FileSystemEntry): Promise<File[]> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry
    const file = await new Promise<File | null>((resolve) => {
      fileEntry.file(
        (result) => resolve(result),
        () => resolve(null),
      )
    })
    return file ? [file] : []
  }

  if (entry.isDirectory) {
    const directory = entry as FileSystemDirectoryEntry
    const children = await readAllEntries(directory.createReader())
    const nested = await Promise.all(children.map((child) => collectEntryFiles(child)))
    return nested.flat()
  }

  return []
}

/** 必须在 drop 事件同步阶段调用 webkitGetAsEntry，之后才能异步读取。 */
function collectDropEntries(transfer: DataTransfer): FileSystemEntry[] {
  const items = Array.from(transfer.items ?? [])
  const entries: FileSystemEntry[] = []

  for (const item of items) {
    if (item.kind !== 'file') continue
    if (typeof item.webkitGetAsEntry !== 'function') return []
    const entry = item.webkitGetAsEntry()
    if (entry) entries.push(entry)
  }

  return entries
}

async function importDroppedEntries(entries: FileSystemEntry[]): Promise<void> {
  scanning.value = true
  emit('scanning-change', true)
  try {
    const collected = (
      await Promise.all(entries.map((entry) => collectEntryFiles(entry)))
    ).flat()
    const supported = supportedSorted(collected)

    if (supported.length === 0) {
      emit('invalid', '拖入的文件夹中没有找到支持的 PDF、PNG、JPG 文件。')
      return
    }
    emit('upload-batch', supported)
  } catch {
    emit('invalid', '读取文件夹失败，请重试或改用“导入整个文件夹”。')
  } finally {
    scanning.value = false
    // 异常路径同样释放父组件的项目锁。
    emit('scanning-change', false)
  }
}

function handleDroppedFiles(list: FileList | null): void {
  const supported = supportedSorted(list ?? [])

  if (supported.length === 0) {
    emit(
      'invalid',
      list && list.length > 0
        ? '仅支持 PDF、PNG、JPG 文件。'
        : '未检测到可上传的文件。',
    )
    return
  }
  // 单文件保持原有上传行为；多文件按批量导入处理。
  if (supported.length === 1) {
    emit('upload', supported[0])
    return
  }
  emit('upload-batch', supported)
}

function onDragEnter(event: DragEvent): void {
  // 先阻止浏览器默认行为（打开文件/导航），再判断是否可接收。
  event.preventDefault()
  if (blocked.value) return
  dragDepth += 1
  dragging.value = true
}

function onDragOver(event: DragEvent): void {
  event.preventDefault()
  if (blocked.value) return
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(): void {
  if (blocked.value) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) dragging.value = false
}

function onDrop(event: DragEvent): void {
  event.preventDefault()
  if (blocked.value) return

  dragDepth = 0
  dragging.value = false

  const transfer = event.dataTransfer
  if (!transfer) return

  const entries = collectDropEntries(transfer)
  if (entries.some((entry) => entry.isDirectory)) {
    void importDroppedEntries(entries)
    return
  }

  // 没有目录项（或浏览器不支持 webkitGetAsEntry）时回退到 files。
  handleDroppedFiles(transfer.files)
}

</script>

<template>
  <section class="panel upload-panel" :class="{ 'is-embedded': embedded }">
    <!-- 嵌入弹窗时头部由 ImportDialog 提供，避免出现两套「导入」标题。 -->
    <header v-if="!embedded" class="panel-head">
      <h2 class="panel-title">导入 <span class="panel-title-cn">Import</span></h2>
      <span class="panel-count">PDF · PNG · JPG</span>
    </header>

    <div class="panel-body">
      <div
        class="dropzone"
        :class="{ 'is-dragging': dragging, 'is-busy': busy, 'is-disabled': blocked }"
        role="button"
        tabindex="0"
        :aria-disabled="blocked"
        :aria-busy="busy"
        @click="openPicker"
        @keydown.enter.prevent="openPicker"
        @keydown.space.prevent="openPicker"
        @dragenter="onDragEnter"
        @dragover="onDragOver"
        @dragleave="onDragLeave"
        @drop="onDrop"
      >
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          tabindex="-1"
          @click.stop
          @change="onInputChange"
        />

        <svg
          class="dropzone-icon"
          viewBox="0 0 32 32"
          fill="none"
          stroke="currentColor"
          stroke-width="1.2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M16 21V6" />
          <path d="m10.5 11.5 5.5-5.5 5.5 5.5" />
          <path d="M6 19.5v5A1.5 1.5 0 0 0 7.5 26h17a1.5 1.5 0 0 0 1.5-1.5v-5" />
        </svg>

        <p class="dropzone-title">{{ dropTitle }}</p>
        <p class="dropzone-hint">{{ dropHint }}</p>
      </div>

      <!-- 目录选择：webkitdirectory 为非标准属性，用 v-bind 规避模板类型检查。 -->
      <input
        ref="folderInput"
        class="sr-only"
        type="file"
        accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
        multiple
        v-bind="{ webkitdirectory: true }"
        tabindex="-1"
        @click.stop
        @change="onFolderChange"
      />

      <div class="upload-actions">
        <button
          type="button"
          class="mx-btn upload-action-btn"
          :disabled="blocked"
          @click="openPicker"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M8 11V3" />
            <path d="m5 6 3-3 3 3" />
            <path d="M3 12.5h10" />
          </svg>
          选择文件
        </button>
        <button
          type="button"
          class="mx-btn upload-action-btn"
          :disabled="blocked"
          @click="openFolderPicker"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path
              d="M2 5.5A1.5 1.5 0 0 1 3.5 4h2.2l1.2 1.5h5.6A1.5 1.5 0 0 1 14 7v5a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12z"
            />
          </svg>
          {{ importing ? '正在导入…' : '选择文件夹' }}
        </button>
      </div>

      <div
        v-if="importing && importProgress"
        class="upload-progress"
        role="status"
        aria-live="polite"
      >
        <div class="upload-progress-line">
          <span class="upload-progress-label">正在上传 {{ progressIndex }}/{{ importProgress.total }}<template v-if="importProgress.current">：</template></span>
          <span
            v-if="importProgress.current"
            class="upload-progress-file"
            :title="importProgress.current"
          >
            {{ importProgress.current }}
          </span>
        </div>
        <div class="upload-progress-track" aria-hidden="true">
          <span
            class="upload-progress-fill"
            :style="{ width: `${progressPercent}%` }"
          />
        </div>
      </div>

      <div
        v-if="showBatchSummary && batchSummary"
        class="upload-summary"
        role="status"
        aria-live="polite"
      >
        <span class="upload-summary-title">项目队列</span>
        <span class="upload-summary-dot" aria-hidden="true">·</span>
        <span
          class="upload-summary-item"
          :class="{ 'is-active': batchSummary.queued > 0 }"
        >
          排队 <b class="upload-summary-value">{{ batchSummary.queued }}</b>
        </span>
        <span class="upload-summary-dot" aria-hidden="true">·</span>
        <span
          class="upload-summary-item"
          :class="{ 'is-active': batchSummary.converting > 0 }"
        >
          识别中 <b class="upload-summary-value">{{ batchSummary.converting }}</b>
        </span>
        <span class="upload-summary-dot" aria-hidden="true">·</span>
        <span
          class="upload-summary-item"
          :class="{ 'is-active': batchSummary.completed > 0 }"
        >
          已完成 <b class="upload-summary-value">{{ batchSummary.completed }}</b>
        </span>
        <span class="upload-summary-dot" aria-hidden="true">·</span>
        <span
          class="upload-summary-item"
          :class="{ 'is-failed': batchSummary.failed > 0 }"
        >
          失败 <b class="upload-summary-value">{{ batchSummary.failed }}</b>
        </span>
      </div>

      <p
        v-if="batchSummary && (batchSummary.queued > 0 || batchSummary.converting > 0)"
        class="field-hint"
      >
        若长时间停留在“排队”，请检查 OCR Worker / MinerU 是否正常运行；服务恢复后会自动继续。
      </p>

      <p class="field-hint">文件夹内按相对路径排序；同名文件会自动跳过。</p>
    </div>
  </section>
</template>

<style scoped>
.upload-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

/*
 * 嵌入模式：去掉 .panel 的底部分隔线/背景/内边距，交给弹窗统一控制留白。
 * 选择器加 .upload-panel 前缀以压过全局 .mx-root .panel 与 .panel-body。
 */
.upload-panel.is-embedded {
  border: 0;
  background: transparent;
  box-shadow: none;
}

.upload-panel.is-embedded .panel-body {
  padding: 0;
  gap: 12px;
}

/* 弹窗空间更充裕，拖拽区加高到约 170px，落点更好辨认，也不改变原有交互逻辑。 */
.upload-panel.is-embedded .dropzone {
  min-height: 170px;
  gap: 6px;
  padding: 18px 14px;
}

.upload-panel.is-embedded .dropzone-icon {
  width: 30px;
  height: 30px;
  margin-bottom: 4px;
}

.upload-panel.is-embedded .dropzone-title {
  font-size: 13px;
}

/* 选择器带上 .upload-actions 前缀，确保压过全局 .mx-root .mx-btn 的同名属性。 */
.upload-actions .upload-action-btn {
  flex: 1 1 0;
  min-width: 0;
  height: 32px;
  padding: 0 8px;
  font-size: 11.5px;
}

.upload-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--paper);
}

.upload-progress-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.upload-progress-label {
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  color: var(--ink-3);
}

.upload-progress-file {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-2);
}

.upload-progress-track {
  height: 3px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--surface-sunken);
}

.upload-progress-fill {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--signal);
  transition: width 180ms var(--ease-out);
}

.upload-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 3px 6px;
  font-size: 10.5px;
  line-height: 1.4;
  color: var(--ink-3);
}

.upload-summary-title {
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--ink-4);
}

.upload-summary-item {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
}

.upload-summary-value {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--ink-2);
}

.upload-summary-item.is-active .upload-summary-value {
  color: var(--signal-deep);
}

.upload-summary-item.is-failed .upload-summary-value {
  color: var(--danger);
}

.upload-summary-dot {
  color: var(--ink-4);
}
</style>
