<script setup lang="ts">
import { computed } from 'vue'

/**
 * 工作区模式左右切换开关。
 * 外框与工具栏里的 PDF 预览按钮保持同一套容器样式；
 * 内部两个文案：左＝文本标注模式，右＝文本修改模式，滑块左右切换。
 */
const props = defineProps<{
  mode: 'annotate' | 'edit'
  disabled?: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

const title = computed(() =>
  props.mode === 'annotate'
    ? '当前：文本标注模式，点击切换到文本修改模式'
    : '当前：文本修改模式，点击切换到文本标注模式',
)
</script>

<template>
  <button
    type="button"
    class="mode-switch"
    :class="`is-${mode}`"
    role="switch"
    :aria-checked="mode === 'edit'"
    :aria-label="title"
    :title="title"
    :disabled="disabled"
    @click="emit('toggle')"
  >
    <span class="mode-switch-track">
      <span class="mode-switch-thumb" aria-hidden="true" />
      <span class="mode-switch-label is-annotate">文本标注模式</span>
      <span class="mode-switch-label is-edit">文本修改模式</span>
    </span>
  </button>
</template>

<style scoped>
.mode-switch {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 3px;
  border: 1px solid var(--mw-line);
  border-radius: 9px;
  background: var(--mw-surface);
  cursor: pointer;
  transition:
    border-color 180ms var(--mw-ease),
    background-color 180ms var(--mw-ease),
    opacity 180ms var(--mw-ease);
}

.mode-switch:hover:not(:disabled) {
  border-color: var(--mw-line-strong);
  background: var(--mw-raised);
}

.mode-switch:disabled {
  opacity: .42;
  cursor: not-allowed;
}

.mode-switch-track {
  position: relative;
  display: inline-grid;
  grid-template-columns: 1fr 1fr;
  align-items: center;
  height: 24px;
}

.mode-switch-thumb {
  position: absolute;
  top: 0;
  left: 0;
  width: 50%;
  height: 100%;
  border-radius: 6px;
  transition:
    transform 200ms var(--mw-ease),
    background-color 200ms var(--mw-ease);
}

.mode-switch.is-annotate .mode-switch-thumb {
  transform: translateX(0);
  background: var(--mw-signal-soft);
  box-shadow: inset 0 0 0 1px rgba(228, 87, 46, .2);
}

.mode-switch.is-edit .mode-switch-thumb {
  transform: translateX(100%);
  background: var(--mw-ink);
}

.mode-switch-label {
  position: relative;
  z-index: 1;
  padding: 0 8px;
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1;
  text-align: center;
  white-space: nowrap;
  color: var(--mw-ink-3);
  transition: color 180ms var(--mw-ease);
}

.mode-switch.is-annotate .mode-switch-label.is-annotate {
  color: var(--mw-signal-ink);
  font-weight: 600;
}

.mode-switch.is-edit .mode-switch-label.is-edit {
  color: #FFFDF9;
  font-weight: 600;
}

@media (prefers-reduced-motion: reduce) {
  .mode-switch,
  .mode-switch-thumb,
  .mode-switch-label {
    transition: none;
  }
}
</style>
