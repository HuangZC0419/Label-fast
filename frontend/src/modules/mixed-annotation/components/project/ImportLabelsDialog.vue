<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  fetchLabelCatalog,
  type LabelCatalogEntry,
} from '../../api/client'

/**
 * 从其他项目导入实体标签。
 *
 * 打开时汇总所有项目（排除当前项目）的实体标签与引用次数，用户勾选后通过
 * 现有字典增量保存链路写入当前项目；已存在于当前字典的标签只展示、不可选。
 */

const props = withDefaults(
  defineProps<{
    open: boolean
    projectId: string
    existingLabels: string[]
  }>(),
  {
    existingLabels: () => [],
  },
)

const emit = defineEmits<{
  close: []
  submit: [labels: string[]]
}>()

const loading = ref(false)
const loadError = ref('')
const entries = ref<LabelCatalogEntry[]>([])
const selected = ref<Set<string>>(new Set())
const keyword = ref('')

const existingSet = computed(() => new Set(props.existingLabels))

const filtered = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  if (!term) return entries.value
  return entries.value.filter((entry) =>
    entry.label.toLowerCase().includes(term),
  )
})

const importable = computed(() =>
  filtered.value.filter((entry) => !existingSet.value.has(entry.label)),
)

const selectedCount = computed(() => selected.value.size)
const allSelected = computed(
  () =>
    importable.value.length > 0 &&
    importable.value.every((entry) => selected.value.has(entry.label)),
)

async function loadCatalog(): Promise<void> {
  loading.value = true
  loadError.value = ''
  entries.value = []
  selected.value = new Set()
  keyword.value = ''
  try {
    entries.value = await fetchLabelCatalog(props.projectId)
  } catch (error) {
    loadError.value =
      error instanceof Error && error.message
        ? error.message
        : '加载其他项目的标签失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) void loadCatalog()
  },
  { immediate: true },
)

function toggle(label: string): void {
  if (existingSet.value.has(label)) return
  const next = new Set(selected.value)
  if (next.has(label)) next.delete(label)
  else next.add(label)
  selected.value = next
}

function toggleAll(): void {
  if (allSelected.value) {
    selected.value = new Set()
    return
  }
  selected.value = new Set(importable.value.map((entry) => entry.label))
}

function submit(): void {
  if (selectedCount.value === 0) return
  emit('submit', Array.from(selected.value))
}

function close(): void {
  emit('close')
}

function handleKeydown(event: KeyboardEvent): void {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="il-backdrop" @mousedown.self="close">
      <section
        class="il-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="il-title"
      >
        <header class="il-head">
          <div class="il-head-copy">
            <span class="il-eyebrow">Label Library</span>
            <h2 id="il-title" class="il-title">从其他项目导入标签</h2>
            <p class="il-subtitle">汇总所有项目使用过的实体标签，按引用次数排序。</p>
          </div>
          <button type="button" class="il-close" aria-label="关闭" @click="close">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <div class="il-toolbar">
          <input
            v-model="keyword"
            type="search"
            class="il-search"
            placeholder="搜索标签…"
            aria-label="搜索标签"
          />
          <button
            v-if="importable.length > 0"
            type="button"
            class="il-select-all"
            @click="toggleAll"
          >
            {{ allSelected ? '清除全选' : `全选可导入 ${importable.length} 个` }}
          </button>
        </div>

        <div class="il-body">
          <p v-if="loading" class="il-state">正在统计其他项目的标签…</p>
          <p v-else-if="loadError" class="il-state il-state--error" role="alert">
            {{ loadError }}
            <button type="button" class="il-retry" @click="loadCatalog">重试</button>
          </p>
          <p v-else-if="filtered.length === 0" class="il-state">
            {{ keyword.trim() ? '没有匹配的标签' : '其他项目还没有可导入的实体标签' }}
          </p>

          <ul v-else class="il-list">
            <li v-for="entry in filtered" :key="entry.label">
              <label
                class="il-item"
                :class="{
                  'is-existing': existingSet.has(entry.label),
                  'is-selected': selected.has(entry.label),
                }"
              >
                <input
                  type="checkbox"
                  :checked="selected.has(entry.label)"
                  :disabled="existingSet.has(entry.label)"
                  @change="toggle(entry.label)"
                />
                <span class="il-item-copy">
                  <span class="il-item-label">{{ entry.label }}</span>
                  <span class="il-item-meta">
                    {{ entry.usage_count }} 次标注引用 · {{ entry.project_count }} 个项目
                  </span>
                </span>
                <span v-if="existingSet.has(entry.label)" class="il-badge">
                  当前已有
                </span>
              </label>
            </li>
          </ul>
        </div>

        <footer class="il-foot">
          <span class="il-selected">已选 {{ selectedCount }} 个标签</span>
          <span class="il-spacer"></span>
          <button type="button" class="il-btn" @click="close">取消</button>
          <button
            type="button"
            class="il-btn il-btn--primary"
            :disabled="selectedCount === 0 || loading"
            @click="submit"
          >
            导入到当前项目
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.il-backdrop {
  --il-surface: var(--surface, #fffdf9);
  --il-raised: var(--surface-raised, #fff);
  --il-sunken: var(--surface-sunken, #f2eee6);
  --il-paper: var(--paper, #f6f3ec);
  --il-ink: var(--ink, #17181b);
  --il-ink-2: var(--ink-2, #3e4147);
  --il-ink-3: var(--ink-3, #6e727a);
  --il-ink-4: var(--ink-4, #9a9da3);
  --il-line: var(--line, #e2dccf);
  --il-line-strong: var(--line-strong, #d2caba);
  --il-signal: var(--signal, #e4572e);
  --il-signal-deep: var(--signal-deep, #c44722);
  --il-signal-soft: var(--signal-soft, #fbe8e1);
  --il-signal-ink: var(--signal-ink, #8e2f14);
  --il-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --il-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));

  position: fixed;
  inset: 0;
  z-index: 135;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 22, 25, 0.42);
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
}

.il-dialog {
  display: flex;
  flex-direction: column;
  width: min(620px, 100%);
  max-height: min(84vh, 700px);
  overflow: hidden;
  border: 1px solid var(--il-line);
  border-radius: 20px;
  background: var(--il-surface);
  box-shadow: 0 28px 60px -24px rgba(35, 29, 19, 0.35);
}

.il-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  padding: 18px 22px 12px;
  border-bottom: 1px solid var(--il-line);
}

.il-eyebrow {
  display: block;
  margin-bottom: 3px;
  font-family: var(--il-mono);
  font-size: 9.5px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--il-ink-3);
}

.il-title {
  margin: 0;
  font-family: var(--font-display, 'Instrument Serif', Georgia, serif);
  font-size: 24px;
  font-weight: 400;
  line-height: 1.2;
  color: var(--il-ink);
}

.il-subtitle {
  margin: 4px 0 0;
  color: var(--il-ink-3);
  font-size: 11px;
  line-height: 1.5;
}

.il-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: 1px solid var(--il-line);
  border-radius: 8px;
  background: var(--il-raised);
  color: var(--il-ink-3);
  cursor: pointer;
}

.il-close:hover {
  border-color: var(--il-line-strong);
  color: var(--il-ink);
}

.il-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  padding: 10px 22px;
  border-bottom: 1px solid var(--il-line);
}

.il-search {
  flex: 1;
  min-width: 0;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--il-line);
  border-radius: 8px;
  background: var(--il-raised);
  color: var(--il-ink);
  font-family: inherit;
  font-size: 11.5px;
  outline: none;
}

.il-search:focus {
  border-color: var(--il-signal);
  box-shadow: 0 0 0 2px var(--il-signal-soft);
}

.il-select-all {
  flex-shrink: 0;
  height: 30px;
  padding: 0 9px;
  border: 1px solid var(--il-line);
  border-radius: 8px;
  background: var(--il-raised);
  color: var(--il-ink-2);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.il-select-all:hover {
  border-color: var(--il-line-strong);
}

.il-body {
  flex: 1;
  min-height: 180px;
  overflow-y: auto;
  padding: 8px 14px 12px;
}

.il-state {
  margin: 24px 8px;
  color: var(--il-ink-3);
  font-size: 11.5px;
  text-align: center;
}

.il-state--error {
  color: #b5403a;
}

.il-retry {
  margin-left: 8px;
  padding: 0;
  border: none;
  background: transparent;
  color: var(--il-signal-ink);
  font-family: inherit;
  font-size: 11.5px;
  text-decoration: underline;
  cursor: pointer;
}

.il-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.il-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
}

.il-item:hover {
  background: var(--il-sunken);
}

.il-item.is-selected {
  background: var(--il-signal-soft);
}

.il-item.is-existing {
  cursor: not-allowed;
  opacity: 0.6;
}

.il-item input {
  margin-top: 2px;
  accent-color: var(--il-signal-deep);
}

.il-item-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.il-item-label {
  color: var(--il-ink);
  font-size: 12px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.il-item-meta {
  color: var(--il-ink-3);
  font-family: var(--il-mono);
  font-size: 9.5px;
  letter-spacing: 0.01em;
}

.il-badge {
  flex-shrink: 0;
  align-self: center;
  padding: 1px 6px;
  border: 1px solid var(--il-line-strong);
  border-radius: 999px;
  color: var(--il-ink-4);
  font-size: 9px;
  white-space: nowrap;
}

.il-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  padding: 12px 22px 16px;
  border-top: 1px solid var(--il-line);
}

.il-selected {
  color: var(--il-ink-3);
  font-size: 10.5px;
  white-space: nowrap;
}

.il-spacer {
  flex: 1;
}

.il-btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--il-line);
  border-radius: 8px;
  background: var(--il-raised);
  color: var(--il-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}

.il-btn:hover:not(:disabled) {
  border-color: var(--il-line-strong);
}

.il-btn--primary {
  border-color: transparent;
  background: var(--il-signal-deep);
  color: #fffdf9;
  font-weight: 600;
}

.il-btn--primary:hover:not(:disabled) {
  background: var(--il-signal);
}

.il-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (max-width: 720px) {
  .il-backdrop {
    padding: 12px;
  }

  .il-toolbar {
    flex-wrap: wrap;
  }

  .il-search {
    flex-basis: 100%;
  }
}
</style>
