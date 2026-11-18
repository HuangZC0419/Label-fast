<script setup lang="ts">
withDefaults(
  defineProps<{
    /** Instrument Serif 英文短句。 */
    title: string
    /** 中文提示。 */
    message: string
    /** 侧栏等受限空间使用的紧凑模式。 */
    compact?: boolean
  }>(),
  { compact: false },
)
</script>

<template>
  <div class="mx-empty-state" :class="{ 'is-compact': compact }">
    <svg
      class="mx-empty-state-icon"
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      stroke-width="1.2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M12 7.5h17l7 7v26H12z" />
      <path d="M29 7.5v7h7" />
      <path d="M17.5 22h13M17.5 27.5h13M17.5 33h8" />
      <circle cx="34.5" cy="35.5" r="4.5" />
    </svg>
    <p class="empty-state-title">{{ title }}</p>
    <p class="empty-state-message">{{ message }}</p>
    <slot />
  </div>
</template>
