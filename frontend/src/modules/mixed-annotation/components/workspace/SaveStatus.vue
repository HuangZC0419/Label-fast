<script setup lang="ts">
import { computed } from 'vue'

export type SaveState = 'saved' | 'saving' | 'pending' | 'error'

/**
 * 内容面板里的自动保存状态提示。
 * 只做展示，不提供保存按钮；失败时 title 展示具体错误。
 */
const props = defineProps<{
  state: SaveState
  error?: string
}>()

const label = computed(() => {
  switch (props.state) {
    case 'saving':
      return '保存中…'
    case 'pending':
      return '待保存'
    case 'error':
      return '保存失败'
    default:
      return '已保存'
  }
})
</script>

<template>
  <span
    class="save-status"
    :class="`is-${state}`"
    :title="state === 'error' && error ? error : label"
    role="status"
    aria-live="polite"
  >
    <span class="save-status-dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.save-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 500;
  line-height: 1.5;
  white-space: nowrap;
}

.save-status-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.save-status.is-saved {
  background: var(--success-bg, #eaf4ee);
  color: var(--success);
}

.save-status.is-saving {
  background: var(--warning-bg, #faf2e1);
  color: var(--warning);
}

.save-status.is-saving .save-status-dot {
  animation: save-pulse 1s ease-in-out infinite;
}

.save-status.is-pending {
  background: var(--surface-sunken);
  color: var(--ink-3);
}

.save-status.is-error {
  background: var(--danger-bg, #faecea);
  color: var(--danger);
}

@keyframes save-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: .35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .save-status.is-saving .save-status-dot {
    animation: none;
  }
}
</style>
