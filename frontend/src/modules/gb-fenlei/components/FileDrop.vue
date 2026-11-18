<script setup lang="ts">
import { computed, ref } from "vue";

import { formatFileSize } from "../format";

const props = withDefaults(
  defineProps<{
    label: string;
    hint: string;
    file: File | null;
    busy?: boolean;
    accept?: string;
  }>(),
  {
    busy: false,
    accept: ".xlsx,.xlsm",
  },
);

const emit = defineEmits<{
  select: [file: File];
  clear: [];
}>();

const input = ref<HTMLInputElement | null>(null);
const dragging = ref(false);
const localError = ref("");

const allowed = computed(() =>
  props.accept
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean),
);

function isAllowed(file: File): boolean {
  const name = file.name.toLowerCase();
  return allowed.value.some((suffix) => name.endsWith(suffix));
}

function openPicker(): void {
  if (props.busy) return;
  input.value?.click();
}

function assign(file: File): void {
  if (!isAllowed(file)) {
    localError.value = `仅支持 ${props.accept} 格式的 Excel 文件`;
    return;
  }
  localError.value = "";
  emit("select", file);
}

function onPick(event: Event): void {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (file) assign(file);
  target.value = "";
}

function onDrop(event: DragEvent): void {
  event.preventDefault();
  dragging.value = false;
  if (props.busy) return;
  const file = event.dataTransfer?.files?.[0];
  if (file) assign(file);
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    openPicker();
  }
}
</script>

<template>
  <div class="file-drop-block">
    <input
      ref="input"
      class="sr-only"
      type="file"
      :accept="accept"
      tabindex="-1"
      @change="onPick"
    />

    <div
      class="file-drop"
      :class="{ 'is-filled': file, 'is-over': dragging, 'is-busy': busy }"
      role="button"
      tabindex="0"
      :aria-disabled="busy"
      @click="openPicker"
      @keydown="onKey"
      @dragover.prevent="dragging = !busy"
      @dragleave="dragging = false"
      @drop="onDrop"
    >
      <svg class="file-drop-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M6 2.75h7.1L19 8.65V21.25H6z"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linejoin="round"
        />
        <path
          d="M13 2.9V8.7h5.8M9 12.4h6M9 15.8h6"
          fill="none"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
        />
      </svg>

      <div v-if="file" class="file-drop-selected">
        <span class="file-drop-name">{{ file.name }}</span>
        <span class="file-drop-meta">
          {{ formatFileSize(file.size) }} · 已选择
        </span>
      </div>
      <div v-else class="file-drop-empty">
        <span class="file-drop-label">{{ label }}</span>
        <span class="file-drop-hint">{{ hint }}</span>
      </div>

      <button
        v-if="file"
        class="file-drop-clear"
        type="button"
        aria-label="移除文件"
        :disabled="busy"
        @click.stop="emit('clear')"
      >
        重新选择
      </button>
    </div>

    <p v-if="localError" class="form-error" role="alert">{{ localError }}</p>
  </div>
</template>
