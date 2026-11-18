<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import type { DialogColumn, DialogRow } from "../types";

const props = withDefaults(
  defineProps<{
    open: boolean;
    title: string;
    description?: string;
    columns: DialogColumn[];
    rows: DialogRow[];
    badge?: string;
    searchPlaceholder?: string;
    emptyText?: string;
    pageSize?: number;
  }>(),
  {
    description: "",
    badge: "",
    searchPlaceholder: "搜索",
    emptyText: "没有符合条件的数据。",
    pageSize: 50,
  },
);

const emit = defineEmits<{
  close: [];
}>();

const query = ref("");
const page = ref(1);
const size = ref(props.pageSize);
const closeButton = ref<HTMLButtonElement | null>(null);
let previousFocus: HTMLElement | null = null;

const filteredRows = computed(() => {
  const keyword = query.value.trim().toLowerCase();
  if (!keyword) return props.rows;
  return props.rows.filter((row) =>
    props.columns.some((column) => {
      const value = row[column.key];
      return String(value ?? "").toLowerCase().includes(keyword);
    }),
  );
});

const pageCount = computed(() =>
  Math.max(1, Math.ceil(filteredRows.value.length / size.value)),
);

const pageRows = computed(() => {
  const start = (page.value - 1) * size.value;
  return filteredRows.value.slice(start, start + size.value);
});

const pageNumbers = computed(() => {
  const total = pageCount.value;
  if (total <= 7) {
    return Array.from({ length: total }, (_item, index) => index + 1);
  }
  const start = Math.max(1, Math.min(page.value - 3, total - 6));
  return Array.from({ length: 7 }, (_item, index) => start + index);
});

const rangeText = computed(() => {
  if (!filteredRows.value.length) return "0 条";
  const start = (page.value - 1) * size.value + 1;
  const end = Math.min(page.value * size.value, filteredRows.value.length);
  return `${start}–${end} / ${filteredRows.value.length}`;
});

function setScrollLock(locked: boolean): void {
  document.body.style.overflow = locked ? "hidden" : "";
  const host = document.querySelector<HTMLElement>(".gb-module .content");
  if (host) host.style.overflow = locked ? "hidden" : "";
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      query.value = "";
      page.value = 1;
      size.value = props.pageSize;
      previousFocus = document.activeElement as HTMLElement | null;
      setScrollLock(true);
      void nextTick(() => closeButton.value?.focus());
    } else {
      setScrollLock(false);
      previousFocus?.focus?.();
      previousFocus = null;
    }
  },
);

watch([query, size], () => {
  page.value = 1;
});

watch(pageCount, (count) => {
  if (page.value > count) page.value = count;
});

function close(): void {
  emit("close");
}

function goPage(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value);
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape" && props.open) {
    event.preventDefault();
    close();
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKeydown);
  if (props.open) setScrollLock(false);
});
</script>

<template>
  <Teleport to="body" disabled>
    <div
      v-if="open"
      class="dialog-backdrop"
      @click.self="close"
    >
      <section
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="data-dialog-title"
      >
        <header class="dialog-head">
          <div class="dialog-heading">
            <div class="dialog-title-row">
              <h2 id="data-dialog-title" class="dialog-title">{{ title }}</h2>
              <span v-if="badge" class="tag">{{ badge }}</span>
            </div>
            <p v-if="description" class="dialog-desc">{{ description }}</p>
          </div>
          <button
            ref="closeButton"
            class="dialog-close"
            type="button"
            aria-label="关闭"
            @click="close"
          >
            ×
          </button>
        </header>

        <div class="dialog-toolbar">
          <input
            v-model="query"
            class="gb-input dialog-search"
            type="search"
            :placeholder="searchPlaceholder"
            aria-label="搜索当前明细"
          />
          <span class="dialog-count">
            共 {{ filteredRows.length }} 条
            <template v-if="filteredRows.length !== rows.length">
              （全部 {{ rows.length }} 条）
            </template>
          </span>
          <span class="toolbar-range mono">{{ rangeText }}</span>
        </div>

        <div class="dialog-body">
          <table class="data-table dialog-table">
            <thead>
              <tr>
                <th
                  v-for="column in columns"
                  :key="column.key"
                  scope="col"
                  :class="`col-${column.key}`"
                  :style="{
                    width: column.width,
                    textAlign: column.align === 'right' ? 'right' : 'left',
                  }"
                >
                  {{ column.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in pageRows" :key="`${page}-${index}`">
                <td
                  v-for="column in columns"
                  :key="column.key"
                  :class="[
                    `col-${column.key}`,
                    {
                      'cell-mono': column.mono,
                      'cell-wrap': column.wrap,
                    },
                  ]"
                  :style="{
                    textAlign: column.align === 'right' ? 'right' : 'left',
                  }"
                >
                  {{ row[column.key] ?? "—" }}
                </td>
              </tr>
              <tr v-if="!pageRows.length">
                <td :colspan="columns.length" class="table-empty">
                  {{ emptyText }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <footer class="dialog-foot">
          <label class="dialog-size">
            每页
            <select v-model.number="size" class="select select-small">
              <option :value="20">20</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
              <option :value="200">200</option>
            </select>
            条
          </label>

          <div class="dialog-pagination">
            <button
              class="gb-btn btn-small btn-secondary"
              type="button"
              :disabled="page <= 1"
              @click="goPage(page - 1)"
            >
              上一页
            </button>
            <button
              v-for="number in pageNumbers"
              :key="number"
              class="page-number"
              :class="{ active: number === page }"
              type="button"
              @click="goPage(number)"
            >
              {{ number }}
            </button>
            <button
              class="gb-btn btn-small btn-secondary"
              type="button"
              :disabled="page >= pageCount"
              @click="goPage(page + 1)"
            >
              下一页
            </button>
          </div>

          <span class="dialog-page mono">第 {{ page }} / {{ pageCount }} 页</span>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
