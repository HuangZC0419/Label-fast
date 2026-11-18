<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConversionOptions, Project, ProjectSettingsPayload } from '../../types'

/**
 * 项目设置弹窗：新建时只填名称；编辑时可同时调整名称与文档转换参数。
 *
 * 实体标签/关系类型已移到左侧栏字典卡片，由独立的保存链路维护，
 * 弹窗只负责名称与转换参数。
 *
 * 刻意不使用 <Teleport>：面板内的 `.field` / `.mx-input` / `.check` / `.mx-btn`
 * 样式都依赖 `.mx-root` 祖先作用域，就地渲染可保证样式与主题令牌不丢失。
 * 组件不持有配置源，只维护草稿；父组件提交成功后再关闭弹窗。
 */
const props = defineProps<{
  open: boolean
  mode: 'create' | 'edit'
  project: Project | null
  options: ConversionOptions
  busy: boolean
  /** 保存失败时在弹窗内就地展示，避免被遮罩后的全局提示吞没。 */
  error?: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
  submit: [payload: ProjectSettingsPayload]
}>()

const DPI_OPTIONS = [150, 200, 250, 300] as const

const name = ref('')
const optionsDraft = ref<ConversionOptions>({ ...props.options })

const dialogRef = ref<HTMLElement | null>(null)
const nameInputRef = ref<HTMLInputElement | null>(null)
let restoreFocus: HTMLElement | null = null

const canSubmit = computed(() => name.value.trim().length > 0 && !props.busy)
const title = computed(() => (props.mode === 'create' ? '新建项目' : '项目设置'))
const submitLabel = computed(() => (props.mode === 'create' ? '创建项目' : '保存'))

function resetForm(): void {
  // 新建态清空名称；编辑态回填当前项目名称。转换参数始终跟随父组件传入值。
  name.value = props.mode === 'edit' ? (props.project?.name ?? '') : ''
  optionsDraft.value = { ...props.options }
}

const FOCUSABLE =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      if (restoreFocus?.isConnected) restoreFocus.focus()
      restoreFocus = null
      return
    }
    resetForm()
    restoreFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    nameInputRef.value?.focus()
    nameInputRef.value?.select()
  },
)

function close(): void {
  if (!props.busy) emit('update:open', false)
}

function submit(): void {
  if (!canSubmit.value) return
  emit('submit', {
    name: name.value.trim(),
    options: { ...optionsDraft.value },
  })
}

function onKeydown(event: KeyboardEvent): void {
  if (!props.open) return

  if (event.key === 'Escape') {
    close()
    return
  }

  // 弹窗打开期间屏蔽全局 Ctrl+S，避免在背景触发保存。
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    return
  }

  if (event.key !== 'Tab' || !dialogRef.value) return
  const focusable = dialogRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)
  if (focusable.length === 0) {
    event.preventDefault()
    dialogRef.value.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

// 捕获阶段监听：不依赖与工作区全局快捷键的注册顺序。
onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown, true))
</script>

<template>
  <div v-if="open" class="mx-modal-backdrop" @click.self="close">
    <section
      ref="dialogRef"
      class="mx-modal psd-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="psd-title"
      tabindex="-1"
    >
      <header class="psd-head">
        <h2 id="psd-title" class="psd-title">{{ title }}</h2>
        <button
          type="button"
          class="psd-close"
          aria-label="关闭"
          :disabled="busy"
          @click="close"
        >
          ×
        </button>
      </header>

      <div class="psd-body">
        <section class="psd-section">
          <h3 class="psd-section-title">项目信息</h3>
          <label class="field">
            <span class="field-label">名称</span>
            <input
              ref="nameInputRef"
              v-model="name"
              class="mx-input"
              type="text"
              maxlength="80"
              placeholder="例如：零件工艺标注"
              :disabled="busy"
            />
          </label>
        </section>

        <section v-if="mode === 'edit'" class="psd-section">
          <h3 class="psd-section-title">转换参数</h3>
          <div class="psd-options">
            <label class="check">
              <input v-model="optionsDraft.enable_table" type="checkbox" :disabled="busy" />
              表格识别
            </label>
            <label class="check">
              <input v-model="optionsDraft.enable_formula" type="checkbox" :disabled="busy" />
              公式识别
            </label>
            <label class="psd-dpi">
              <span class="psd-dpi-label">DPI</span>
              <select v-model.number="optionsDraft.dpi" class="mx-input" :disabled="busy">
                <option v-for="dpi in DPI_OPTIONS" :key="dpi" :value="dpi">{{ dpi }}</option>
              </select>
            </label>
          </div>
          <p class="field-hint">公式识别在 CPU 下较慢，可按需开启；DPI 越高越清晰，也更耗时。</p>
        </section>
      </div>

      <p v-if="error" class="psd-error" role="alert">{{ error }}</p>

      <footer class="psd-actions">
        <button type="button" class="mx-btn btn-ghost" :disabled="busy" @click="close">
          取消
        </button>
        <button
          type="button"
          class="mx-btn mx-btn-primary"
          :disabled="!canSubmit"
          @click="submit"
        >
          {{ busy ? '保存中…' : submitLabel }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.psd-dialog {
  width: min(440px, 100%);
}

.psd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 16px 18px 10px;
}

.psd-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}

.psd-close {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-4);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}

.psd-close:hover:not(:disabled) {
  background: var(--surface-sunken);
  color: var(--ink-2);
}

.psd-close:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.psd-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 6px 18px 16px;
}

.psd-section {
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-width: 0;
}

.psd-section + .psd-section {
  padding-top: 16px;
  border-top: 1px dashed var(--line);
}

.psd-section-title {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--ink-4);
}

.psd-options {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.psd-dpi {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.psd-dpi-label {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.psd-dpi select.mx-input {
  width: 88px;
}

.psd-error {
  margin: 0;
  padding: 8px 18px;
  border-top: 1px solid rgba(181, 64, 58, .2);
  background: var(--danger-bg);
  color: var(--danger);
  font-size: 11.5px;
  line-height: 1.5;
}

.psd-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 18px 16px;
  border-top: 1px solid var(--line);
}
</style>
