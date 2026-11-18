<script setup lang="ts">
import { computed } from 'vue'
import type { FileStatus } from '../../types'

const props = withDefaults(
  defineProps<{
    status: FileStatus
    progress?: number
    stage?: string
    message?: string
    error?: string
    compact?: boolean
  }>(),
  {
    progress: 0,
    stage: '',
    message: '',
    error: '',
    compact: false,
  },
)

const STATUS_LABELS: Record<FileStatus, string> = {
  uploaded: '排队中',
  converting: '转换中',
  completed: '已完成',
  failed: '转换失败',
}

const percentage = computed(() => {
  const raw = props.progress
  // 兼容 0–1 与 0–100 两种上报方式。
  const scaled = raw > 0 && raw <= 1 ? raw * 100 : raw
  return Math.min(100, Math.max(0, Math.round(scaled)))
})

const isIndeterminate = computed(
  () => props.status === 'uploaded' || (props.status === 'converting' && percentage.value === 0),
)

const isRunning = computed(
  () => props.status === 'uploaded' || props.status === 'converting',
)

const detailText = computed(() => {
  if (props.status === 'failed') return props.error
  if (props.status === 'converting') return props.stage || props.message
  return ''
})
</script>

<template>
  <div class="conversion" :class="[`is-${status}`, { 'is-compact': compact }]">
    <div class="conversion-meta">
      <span class="conversion-dot" aria-hidden="true" />
      <span class="conversion-label">{{ STATUS_LABELS[status] }}</span>
      <span v-if="status === 'converting' && !isIndeterminate" class="conversion-percent">
        {{ percentage }}%
      </span>
    </div>

    <div
      v-if="isRunning"
      class="progress-track"
      :class="{ 'is-indeterminate': isIndeterminate }"
      role="progressbar"
      :aria-valuemin="0"
      :aria-valuemax="100"
      :aria-valuenow="isIndeterminate ? undefined : percentage"
      :aria-label="STATUS_LABELS[status]"
    >
      <div
        class="progress-fill"
        :style="isIndeterminate ? undefined : { width: `${percentage}%` }"
      />
    </div>

    <p v-if="detailText" class="conversion-detail" :title="detailText">
      {{ detailText }}
    </p>
  </div>
</template>
