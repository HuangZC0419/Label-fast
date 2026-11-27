<script setup lang="ts">
import type { MixedFile } from '../../types'
import ConversionProgress from './ConversionProgress.vue'
import EmptyState from '../common/EmptyState.vue'

defineProps<{
  files: MixedFile[]
  selectedId: string | null
  loading: boolean
  retryingId: string | null
  /** 批量导入/目录扫描期间锁定刷新、删除、重试，避免并发覆盖文件列表。 */
  busy: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
  remove: [file: MixedFile]
  retry: [file: MixedFile]
  refresh: []
}>()
</script>

<template>
  <section class="panel file-panel">
    <header class="panel-head">
      <h2 class="panel-title">
        Files <span class="panel-title-cn">文件</span>
        <span class="panel-count">{{ files.length }}</span>
      </h2>
      <button
        type="button"
        class="mx-btn mx-btn-icon"
        title="刷新文件列表"
        :disabled="loading || busy"
        @click="emit('refresh')"
      >
        <svg
          class="file-refresh-icon"
          :class="{ 'is-spinning': loading }"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M13 8a5 5 0 1 1-1.5-3.5" />
          <path d="M13 2.5V5h-2.5" />
        </svg>
      </button>
    </header>

    <div class="file-scroll">
      <p v-if="loading && files.length === 0" class="file-loading">正在读取文件…</p>

      <!-- 上传入口已移到顶栏「导入数据」，空状态必须指路，否则用户会继续在侧栏找上传。 -->
      <EmptyState
        v-else-if="files.length === 0"
        compact
        title="Nothing filed yet"
        message="点击顶部「导入数据」上传 PDF 或图片"
      />

      <div
        v-for="(file, index) in files"
        :key="file.id"
        class="file-item"
        :class="{ 'is-selected': selectedId === file.id }"
        role="option"
        :aria-selected="selectedId === file.id"
        tabindex="0"
        @click="emit('select', file.id)"
        @keydown.enter.prevent="emit('select', file.id)"
        @keydown.space.prevent="emit('select', file.id)"
      >
        <span class="file-kind" :class="{ 'is-image': file.source_type !== 'pdf' }">
          {{ index + 1 }}
        </span>

        <div class="file-body">
          <div class="file-top">
            <span class="file-name" :title="file.name">{{ file.name }}</span>
            <div class="file-actions" @click.stop>
              <button
                v-if="file.status === 'failed'"
                type="button"
                class="mx-btn mx-btn-icon file-action"
                title="重新转换"
                :disabled="busy || retryingId === file.id"
                @click="emit('retry', file)"
              >
                <span
                  v-if="retryingId === file.id"
                  class="spinner spinner-sm"
                  aria-hidden="true"
                />
                <svg
                  v-else
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.4"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path d="M13 8a5 5 0 1 1-1.5-3.5" />
                  <path d="M13 2.5V5h-2.5" />
                </svg>
              </button>
              <button
                type="button"
                class="mx-btn mx-btn-icon file-action is-danger"
                title="删除文件"
                :disabled="busy"
                @click="emit('remove', file)"
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
                  <path d="M3 4.5h10" />
                  <path d="M6.5 4.5V3h3v1.5" />
                  <path d="M4.5 4.5 5 13h6l.5-8.5" />
                </svg>
              </button>
            </div>
          </div>

          <div v-if="file.status === 'completed'" class="file-meta">
            <span class="file-status">
              <span class="file-status-dot" aria-hidden="true" />
              已完成
            </span>
            <span v-if="file.page_count > 0" class="file-pages">
              {{ file.page_count }} 页
            </span>
            <span
              class="file-annot"
              :class="file.has_annotations ? 'is-done' : 'is-pending'"
            >
              {{ file.has_annotations ? '已标注' : '未标注' }}
            </span>
          </div>

          <ConversionProgress
            v-else
            :status="file.status"
            :progress="file.progress"
            :stage="file.stage"
            :message="file.message"
            :error="file.error"
            compact
          />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.file-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.file-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  font-weight: 500;
  line-height: 1.4;
  color: var(--success);
  white-space: nowrap;
}

.file-status-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
}

.file-annot {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 9.5px;
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
}

.file-annot::before {
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
}

.file-annot.is-done {
  background: var(--success-bg, #eaf4ee);
  color: var(--success);
}

.file-annot.is-pending {
  background: var(--surface-sunken);
  color: var(--ink-4);
}
</style>

