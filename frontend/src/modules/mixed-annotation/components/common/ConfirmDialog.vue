<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * 通用危险操作确认弹窗。
 *
 * 与 ProjectSettingsDialog 一样不使用 <Teleport>，复用 `.mx-root` 下的
 * `.mx-btn` / `.mx-btn-danger` 主题样式。确认动作由父组件执行，成功后关闭弹窗；
 * 失败时保留弹窗，并通过 error 在弹窗内就地展示错误（不被遮罩压暗）。
 */
const props = defineProps<{
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
  busyLabel?: string
  /** 操作失败时在弹窗内就地展示，避免被遮罩后的全局提示吞没。 */
  error?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  confirm: []
}>()

const dialogRef = ref<HTMLElement | null>(null)
const cancelRef = ref<HTMLButtonElement | null>(null)
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
    // 危险操作默认聚焦「取消」，降低误触确认的概率。
    ;(cancelRef.value ?? dialogRef.value)?.focus()
  },
)

function close(): void {
  if (!props.busy) emit('update:open', false)
}

function confirm(): void {
  if (props.busy) return
  emit('confirm')
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  if (event.key === 'Escape') {
    close()
    return
  }

  // 弹窗打开期间屏蔽全局 Ctrl+S，避免在背景触发保存。
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    return
  }

  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)
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
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal cfm-dialog"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="cfm-title"
      aria-describedby="cfm-message"
      tabindex="-1"
    >
      <h2 id="cfm-title" class="cfm-title">{{ title }}</h2>
      <p id="cfm-message" class="cfm-message">{{ message }}</p>
      <p v-if="error" class="cfm-error" role="alert">{{ error }}</p>
      <div class="cfm-actions">
        <button
          ref="cancelRef"
          type="button"
          class="mx-btn btn-ghost"
          :disabled="busy"
          @click="close"
        >
          取消
        </button>
        <button
          type="button"
          class="mx-btn"
          :class="danger ? 'mx-btn-danger' : 'mx-btn-primary'"
          :disabled="busy"
          @click="confirm"
        >
          {{ busy ? (busyLabel ?? '处理中…') : (confirmLabel ?? '确认') }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.cfm-dialog {
  width: min(400px, 100%);
  padding: 18px 18px 16px;
}

.cfm-title {
  margin: 0 0 8px;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--ink);
}

.cfm-message {
  margin: 0;
  font-size: 12px;
  line-height: 1.65;
  color: var(--ink-3);
}

.cfm-error {
  margin: 12px 0 0;
  padding: 8px 10px;
  border: 1px solid rgba(181, 64, 58, .2);
  border-radius: var(--radius-sm);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11.5px;
  line-height: 1.5;
}

.cfm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 18px;
}
</style>
