<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { BatchSummary, ImportProgress } from '../../types'
import UploadPanel from './UploadPanel.vue'

/**
 * 导入弹窗：顶栏「导入数据」按钮的落地入口。
 *
 * 设计取舍：
 * - 上传能力**完全复用** UploadPanel（embedded 模式），这里只负责弹窗外壳，
 *   因此拖拽/目录扫描/文件选择/进度/队列统计只有一份实现，不会出现两套行为。
 * - 弹窗只做「发起导入」，不负责上传本身：上传由父组件持有，
 *   关闭窗口不会中断正在进行的上传与后台转换排队。
 * - 使用 `.mx-modal-backdrop` / `.mx-modal` 与 ConfirmDialog 保持同一套弹窗观感，
 *   并且同样不使用 <Teleport>，以继承 `.mx-root` 的主题令牌。
 * - 组件常驻挂载（v-show），弹窗关闭时 UploadPanel 仍在，目录扫描的
 *   `scanning-change` 不会因为卸载而丢失，父组件的项目锁能正确释放。
 */
const props = defineProps<{
  open: boolean
  /** 单文件上传进行中（父组件持有）。 */
  uploading: boolean
  /** 没有当前项目时禁用一切上传入口。 */
  disabled: boolean
  /** 批量导入（整目录）进行中。 */
  importing: boolean
  importProgress: ImportProgress | null
  batchSummary?: BatchSummary
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  upload: [file: File]
  'upload-batch': [files: File[]]
  invalid: [message: string]
  /** 目录扫描是异步的，父组件需要据此锁定项目切换。 */
  'scanning-change': [active: boolean]
}>()

const dialogRef = ref<HTMLElement | null>(null)
/** 弹窗关闭后把焦点还给打开它的「导入数据」按钮，避免焦点落回 body。 */
let restoreFocus: HTMLElement | null = null

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (restoreFocus?.isConnected) restoreFocus.focus()
      restoreFocus = null
      return
    }
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    // 焦点先落到弹窗容器（tabindex=-1）：读屏会先播报标题与说明，
    // 用户按 Tab 才进入「关闭 / 选择文件 / 选择文件夹」这些可交互项。
    dialogRef.value?.focus()
  },
)

/**
 * 关闭弹窗。
 * 上传/转换进行中同样允许关闭：上传任务由父组件继续，用户可以先回去标注。
 */
function close(): void {
  emit('update:open', false)
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  if (event.key === 'Escape') {
    // 捕获阶段先关弹窗：背景的菜单/标注快捷键不会再收到这次 Esc。
    event.preventDefault()
    close()
    return
  }

  // 弹窗打开期间屏蔽全局 Ctrl+S，避免在背景触发保存。
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    return
  }

  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = Array.from(
    dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE),
  ).filter((element) => element.offsetParent !== null)
  if (focusable.length === 0) {
    event.preventDefault()
    dialogRef.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (event.shiftKey && document.activeElement === dialogRef.value) {
    // 容器自身获得焦点时反向 Tab 也要留在弹窗内。
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-show="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal import-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="import-dialog-title"
      aria-describedby="import-dialog-desc"
      tabindex="-1"
    >
      <header class="import-head">
        <div class="import-head-text">
          <h2 id="import-dialog-title" class="import-title">导入数据</h2>
          <p id="import-dialog-desc" class="import-subtitle">
            上传 PDF / 图片，支持整个文件夹；转换完成后即可标注。
          </p>
        </div>
        <button
          type="button"
          class="import-close"
          aria-label="关闭导入窗口"
          title="关闭（Esc）"
          @click="close"
        >
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="m4.5 4.5 7 7M11.5 4.5l-7 7" />
          </svg>
        </button>
      </header>

      <!--
        上传面板以 embedded 模式嵌入：拖拽/文件夹扫描/进度/队列统计全部复用，
        弹窗内不再重复「导入 Import」面板头。
      -->
      <div class="import-body">
        <UploadPanel
          embedded
          :uploading="uploading"
          :disabled="disabled"
          :importing="importing"
          :import-progress="importProgress"
          :batch-summary="batchSummary"
          @upload="emit('upload', $event)"
          @upload-batch="emit('upload-batch', $event)"
          @scanning-change="emit('scanning-change', $event)"
          @invalid="emit('invalid', $event)"
        />
      </div>

      <footer class="import-foot">
        <p class="import-foot-hint">转换在后台排队，可关闭本窗口继续标注</p>
        <button type="button" class="mx-btn btn-ghost import-done" @click="close">
          关闭
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
/*
 * 选择器带上 .mx-root 与 .mx-modal 双重限定，确保压过全局 `.mx-root .mx-modal`
 * 的默认 440px 宽度（scoped 属性会再叠加一层特异性）。
 */
.mx-root .mx-modal.import-dialog {
  width: min(560px, 100%);
  max-height: min(86vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px 18px 14px;
}

.import-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-shrink: 0;
  margin-bottom: 14px;
}

.import-head-text {
  min-width: 0;
  flex: 1 1 auto;
}

.import-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: .01em;
  color: var(--ink);
}

.import-subtitle {
  margin: 4px 0 0;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--ink-3);
}

/* 右上角关闭：图标按钮，与弹窗边框保持 4px 的视觉安全距离。 */
.import-close {
  display: inline-grid;
  place-items: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  transition:
    background-color 160ms var(--ease-out),
    border-color 160ms var(--ease-out),
    color 160ms var(--ease-out);
}

.import-close svg {
  width: 14px;
  height: 14px;
}

.import-close:hover {
  border-color: var(--line);
  background: var(--surface-sunken);
  color: var(--ink);
}

.import-close:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--signal-soft);
}

/* 主体可滚动：进度与队列统计变高时不让底部按钮被推出视口。 */
.import-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
}

.import-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.import-foot-hint {
  margin: 0;
  min-width: 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--ink-4);
}

/* 底部「关闭」比全局 .mx-btn 矮 4px，选择器加 .mx-modal 前缀保证覆盖生效。 */
.mx-root .mx-modal .import-done {
  flex-shrink: 0;
  height: 30px;
}

.mx-root .mx-modal .import-done:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px var(--signal-soft);
}

@media (max-width: 640px) {
  .mx-root .mx-modal.import-dialog {
    padding: 14px 14px 12px;
  }

  /* 窄屏先让底部按钮完整可见，提示文案允许换行。 */
  .import-foot {
    flex-wrap: wrap;
  }
}
</style>

