<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  getLabelColor,
  type BoxItem,
  type StatusMessage,
} from '../../composables/useImageProject'

const props = defineProps<{
  labels: string[]
  currentLabel: string
  drawingEnabled: boolean
  boxes: BoxItem[]
  status: StatusMessage | null
  hasImage: boolean
  canExport: boolean
}>()

const emit = defineEmits<{
  (event: 'add-label', name: string): void
  (event: 'select-label', name: string): void
  (event: 'toggle-drawing'): void
  (event: 'remove-box', index: number): void
  (event: 'clear-boxes'): void
  (event: 'save-boxes'): void
  (event: 'export-zip'): void
}>()

const labelInput = ref('')

const currentLabelColor = computed(() => getLabelColor(props.currentLabel, props.labels))

function submitLabel(): void {
  const value = labelInput.value.trim()
  if (!value) return
  emit('add-label', value)
  labelInput.value = ''
}

// 低饱和标签色偏浅，选中态填充标签色后使用深墨文字，保证对比度可读。
function chipStyle(name: string): Record<string, string> {
  const selected = props.currentLabel === name
  const color = getLabelColor(name, props.labels)
  return {
    backgroundColor: selected ? color : 'var(--ip-surface-raised, #FFFFFF)',
    borderColor: selected ? color : 'var(--ip-line, #E2DCCF)',
    color: selected ? 'var(--ip-ink, #17181B)' : 'var(--ip-ink-2, #3E4147)',
  }
}

function keyBadgeStyle(name: string): Record<string, string> {
  const selected = props.currentLabel === name
  return {
    background: selected ? 'rgba(23, 24, 27, .14)' : 'var(--ip-sunken, #F2EEE6)',
    color: selected ? 'var(--ip-ink, #17181B)' : 'var(--ip-ink-3, #6E727A)',
  }
}
</script>

<template>
  <aside class="image-panel image-panel-box">
    <header class="image-panel-head">
      <div class="image-panel-heading">
        <span class="image-panel-eyebrow">Box Annotation</span>
        <h2 class="image-panel-title">框选标注</h2>
      </div>
      <span class="image-panel-sub">{{ boxes.length }} boxes</span>
    </header>

    <div class="image-panel-scroll">
      <p class="image-panel-hint">
        添加并选中标签后开启绘制，在图片上按住左键拖拽即可生成矩形框。
      </p>

      <div class="image-section-head">
        <span class="image-section-title">标签</span>
        <span class="image-section-count">{{ labels.length }}</span>
      </div>

      <!-- 新增标签 -->
      <div class="image-label-input">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
          <line x1="7" y1="7" x2="7.01" y2="7" />
        </svg>
        <input
          v-model="labelInput"
          type="text"
          placeholder="输入标签名，按 Enter 添加"
          aria-label="新标签名称"
          @keyup.enter="submitLabel"
        />
        <button
          type="button"
          class="image-label-add"
          title="添加标签"
          aria-label="添加标签"
          @click="submitLabel"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      <!-- 标签列表 -->
      <div v-if="labels.length > 0" class="image-label-chips">
        <button
          v-for="(name, index) in labels"
          :key="name"
          type="button"
          class="image-label-chip"
          :class="{ selected: currentLabel === name }"
          :style="chipStyle(name)"
          :title="`选择标签 ${name}`"
          @click="emit('select-label', name)"
        >
          <span
            class="image-label-dot"
            :style="{ backgroundColor: currentLabel === name ? 'rgba(23, 24, 27, .55)' : getLabelColor(name, labels) }"
            aria-hidden="true"
          />
          <span v-if="index < 10" class="image-label-key" :style="keyBadgeStyle(name)">
            {{ index === 9 ? 0 : index + 1 }}
          </span>
          {{ name }}
        </button>
      </div>
      <p v-else class="image-panel-empty">尚未定义标签，请先添加标签。</p>

      <div class="image-label-current">
        <span class="image-label-current-main">
          当前标签
          <span
            class="image-label-dot"
            :style="{ backgroundColor: currentLabel ? currentLabelColor : 'var(--ip-ink-4, #9A9DA3)' }"
            aria-hidden="true"
          />
          <strong>{{ currentLabel || '未选择' }}</strong>
        </span>
        <button
          type="button"
          class="image-btn image-btn-sm image-btn-ghost"
          :disabled="!hasImage || boxes.length === 0"
          @click="emit('clear-boxes')"
        >
          清空本图框
        </button>
      </div>

      <!-- 绘制开关 -->
      <button
        type="button"
        class="image-draw-toggle"
        :class="{ active: drawingEnabled }"
        :disabled="!hasImage || labels.length === 0"
        :aria-pressed="drawingEnabled"
        @click="emit('toggle-drawing')"
      >
        <span v-if="drawingEnabled" class="image-draw-dot" aria-hidden="true" />
        <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <line x1="12" y1="8" x2="12" y2="16" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
        {{ drawingEnabled ? '绘制中… 按 ESC 取消' : '开始框选标注' }}
      </button>

      <!-- 当前图片框列表 -->
      <div class="image-section-head">
        <span class="image-section-title">本图框</span>
        <span class="image-section-count">{{ boxes.length }}</span>
      </div>

      <div class="image-box-list">
        <p v-if="boxes.length === 0" class="image-panel-empty">
          当前图片暂无框标注，开启绘制后在图片上拖动即可。
        </p>
        <div v-for="(box, index) in boxes" :key="index" class="image-box-item">
          <span class="image-box-label">
            <span
              class="image-box-swatch"
              :style="{ backgroundColor: getLabelColor(box.label, labels) }"
              aria-hidden="true"
            />
            {{ box.label || '(未命名)' }}
          </span>
          <span class="image-box-coords">
            [{{ Math.round(box.x1) }}, {{ Math.round(box.y1) }}] – [{{
              Math.round(box.x2)
            }}, {{ Math.round(box.y2) }}]
          </span>
          <button
            type="button"
            class="image-box-remove"
            title="删除该框"
            @click="emit('remove-box', index)"
          >
            删除
          </button>
        </div>
      </div>
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
        @click="emit('save-boxes')"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
          <polyline points="17 21 17 13 7 13 7 21" />
          <polyline points="7 3 7 8 15 8" />
        </svg>
        保存当前图片框标注
        <span class="image-btn-hint">Space</span>
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
        打包导出框选标注 (ZIP)
      </button>

      <div class="image-shortcut-bar">
        <span><kbd class="image-kbd">A</kbd>/<kbd class="image-kbd">D</kbd> 切换</span>
        <span><kbd class="image-kbd">1-0</kbd> 选标签</span>
        <span><kbd class="image-kbd">Ctrl</kbd>+<kbd class="image-kbd">Enter</kbd> 保存</span>
      </div>
    </footer>
  </aside>
</template>
