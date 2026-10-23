<script setup lang="ts">
import type { StatusMessage } from '../../composables/useImageProject'

defineProps<{
  userContent: string
  assistantContent: string
  status: StatusMessage | null
  hasImage: boolean
  canExport: boolean
}>()

const emit = defineEmits<{
  (event: 'update:userContent', value: string): void
  (event: 'update:assistantContent', value: string): void
  (event: 'save'): void
  (event: 'skip'): void
  (event: 'export-zip'): void
}>()

function handleUserInput(event: Event): void {
  emit('update:userContent', (event.target as HTMLTextAreaElement).value)
}

function handleAssistantInput(event: Event): void {
  emit('update:assistantContent', (event.target as HTMLTextAreaElement).value)
}
</script>

<template>
  <aside class="image-panel image-panel-qa">
    <header class="image-panel-head">
      <div class="image-panel-heading">
        <span class="image-panel-eyebrow">QA Annotation</span>
        <h2 class="image-panel-title">大模型问答标注</h2>
      </div>
      <span class="image-panel-sub">Ctrl + Enter</span>
    </header>

    <div class="image-panel-scroll">
      <label class="image-qa-field">
        <span class="image-qa-label">
          <span class="image-qa-label-en">User Input</span>
          <span class="image-qa-label-cn">用户指令</span>
        </span>
        <span class="image-textarea-wrap">
          <textarea
            class="image-textarea"
            rows="4"
            placeholder="例如：详细描述这张图片。"
            :value="userContent"
            @input="handleUserInput"
          />
          <span class="image-char-count">{{ userContent.length }}</span>
        </span>
      </label>

      <label class="image-qa-field image-qa-grow">
        <span class="image-qa-label">
          <span class="image-qa-label-en">Assistant Output</span>
          <span class="image-qa-label-cn">助手回答</span>
        </span>
        <span class="image-textarea-wrap">
          <textarea
            class="image-textarea image-textarea-lg"
            placeholder="填写模型预期的回答…"
            :value="assistantContent"
            @input="handleAssistantInput"
          />
          <span class="image-char-count">{{ assistantContent.length }}</span>
        </span>
      </label>

      <p class="image-panel-hint">
        已有问答会自动回填；助手回答为空时不会保存该图片记录。
      </p>
    </div>

    <footer class="image-panel-footer">
      <div
        v-if="status"
        class="image-panel-status"
        :class="status.type === 'success' ? 'success' : 'error'"
        role="status"
        aria-live="polite"
      >
        {{ status.msg }}
      </div>

      <button
        type="button"
        class="image-btn image-btn-primary image-btn-block"
        :disabled="!hasImage"
        @click="emit('save')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
          <polyline points="17 21 17 13 7 13 7 21" />
          <polyline points="7 3 7 8 15 8" />
        </svg>
        保存并下一张
        <span class="image-btn-hint">Ctrl+Enter</span>
      </button>

      <button
        type="button"
        class="image-btn image-btn-block"
        :disabled="!hasImage"
        @click="emit('skip')"
      >
        跳过 (不保存)
      </button>

      <button
        type="button"
        class="image-btn image-btn-accent image-btn-block"
        :disabled="!canExport"
        @click="emit('export-zip')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        打包导出问答标注 (ZIP)
      </button>

      <div class="image-shortcut-bar">
        <span><kbd class="image-kbd">A</kbd>/<kbd class="image-kbd">D</kbd> 切换</span>
        <span><kbd class="image-kbd">Space</kbd> 保存并下一张</span>
      </div>
    </footer>
  </aside>
</template>
