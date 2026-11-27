<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ConversionOptions, ConversionParseMethod } from '../../types'

/**
 * 「重新 OCR」参数弹窗。
 *
 * 针对单个文件重新识别：默认给出一组偏高的推荐值（300 DPI + 表格识别 + 自动解析），
 * 并在每个选项旁解释什么场景该调高、什么场景该关掉，避免用户盲调。
 * 提交由父组件执行，弹窗只维护草稿。
 */

const props = withDefaults(
  defineProps<{
    open: boolean
    fileName: string
    pageCount?: number
    busy?: boolean
    error?: string
  }>(),
  {
    pageCount: 0,
    busy: false,
    error: '',
  },
)

const emit = defineEmits<{
  close: []
  submit: [options: ConversionOptions]
}>()

interface DpiChoice {
  value: number
  title: string
  tag?: string
  hint: string
}

const DPI_CHOICES: DpiChoice[] = [
  {
    value: 200,
    title: '标准',
    hint: '速度均衡；小字号或扫描件可能略糊。',
  },
  {
    value: 300,
    title: '高精度',
    tag: '推荐',
    hint: '标准文档、扫描件、表格密集页的稳妥选择，耗时约增加 50%。',
  },
  {
    value: 400,
    title: '极高',
    hint: '字号很小或扫描质量差时使用；最慢，也更占内存。',
  },
]

interface ParseChoice {
  value: ConversionParseMethod
  title: string
  tag?: string
  hint: string
}

const PARSE_CHOICES: ParseChoice[] = [
  {
    value: 'auto',
    title: '自动判断',
    tag: '推荐',
    hint: '正常走 PDF 文本层；检测到文字层乱码时自动整页 OCR。',
  },
  {
    value: 'ocr',
    title: '强制 OCR',
    hint: '每页转成图片再识别，最稳但慢 1–2 倍；适合乱码、错字多、文字层不可靠的 PDF。',
  },
  {
    value: 'txt',
    title: '仅文本层',
    hint: '最快；只适合文字层正常且清晰的 PDF，坏编码的 PDF 仍会乱码。',
  },
]

/** 推荐值：偏高但不过分，绝大多数标准文档一次就能识别好。 */
const RECOMMENDED: ConversionOptions = {
  enable_table: true,
  enable_formula: false,
  dpi: 300,
  parse_method: 'auto',
}

const draft = ref<ConversionOptions>({ ...RECOMMENDED })

watch(
  () => props.open,
  (open) => {
    // 每次打开都回到推荐值，避免沿用上一次的临时试错参数。
    if (open) draft.value = { ...RECOMMENDED }
  },
)

const canSubmit = computed(() => !props.busy)

function chooseDpi(value: number): void {
  if (props.busy) return
  draft.value.dpi = value
}

function chooseParse(value: ConversionParseMethod): void {
  if (props.busy) return
  draft.value.parse_method = value
}

function applyPreset(kind: 'recommended' | 'force'): void {
  if (props.busy) return
  draft.value =
    kind === 'force'
      ? { ...RECOMMENDED, parse_method: 'ocr' }
      : { ...RECOMMENDED }
}

function submit(): void {
  if (!canSubmit.value) return
  emit('submit', { ...draft.value })
}

function close(): void {
  if (props.busy) return
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
    <div v-if="open" class="rc-backdrop" @mousedown.self="close">
      <section
        class="rc-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rc-title"
      >
        <header class="rc-head">
          <div class="rc-head-copy">
            <span class="rc-eyebrow">Re-OCR</span>
            <h2 id="rc-title" class="rc-title">重新 OCR 识别</h2>
            <p class="rc-subtitle" :title="fileName">
              {{ fileName }}
              <span v-if="pageCount > 0">· {{ pageCount }} 页</span>
            </p>
          </div>
          <button
            type="button"
            class="rc-close"
            aria-label="关闭"
            :disabled="busy"
            @click="close"
          >
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <div class="rc-body">
          <div class="rc-recommend">
            <div class="rc-recommend-copy">
              <strong>已预填推荐的高精度配置</strong>
              <p>300 DPI + 表格识别 + 自动解析，适合大多数标准文档；识别仍差时可再试「强制 OCR」。</p>
            </div>
            <div class="rc-recommend-actions">
              <button type="button" class="rc-mini-btn" :disabled="busy" @click="applyPreset('recommended')">
                恢复推荐值
              </button>
              <button type="button" class="rc-mini-btn rc-mini-btn--strong" :disabled="busy" @click="applyPreset('force')">
                强制 OCR（最稳）
              </button>
            </div>
          </div>

          <fieldset class="rc-section">
            <legend class="rc-section-title">识别精度</legend>
            <div class="rc-dpi-row">
              <button
                v-for="choice in DPI_CHOICES"
                :key="choice.value"
                type="button"
                class="rc-dpi-btn"
                :class="{ 'is-active': draft.dpi === choice.value }"
                :aria-pressed="draft.dpi === choice.value"
                :disabled="busy"
                @click="chooseDpi(choice.value)"
              >
                <span class="rc-dpi-value">{{ choice.value }} DPI</span>
                <span class="rc-dpi-title">
                  {{ choice.title }}
                  <em v-if="choice.tag" class="rc-tag">{{ choice.tag }}</em>
                </span>
              </button>
            </div>
            <p class="rc-hint">
              {{ DPI_CHOICES.find((choice) => choice.value === draft.dpi)?.hint }}
            </p>
          </fieldset>

          <fieldset class="rc-section">
            <legend class="rc-section-title">解析方式</legend>
            <div class="rc-parse-list">
              <button
                v-for="choice in PARSE_CHOICES"
                :key="choice.value"
                type="button"
                class="rc-parse-btn"
                :class="{ 'is-active': draft.parse_method === choice.value }"
                :aria-pressed="draft.parse_method === choice.value"
                :disabled="busy"
                @click="chooseParse(choice.value)"
              >
                <span class="rc-radio" aria-hidden="true"></span>
                <span class="rc-parse-copy">
                  <span class="rc-parse-title">
                    {{ choice.title }}
                    <em v-if="choice.tag" class="rc-tag">{{ choice.tag }}</em>
                  </span>
                  <span class="rc-parse-hint">{{ choice.hint }}</span>
                </span>
              </button>
            </div>
          </fieldset>

          <fieldset class="rc-section">
            <legend class="rc-section-title">识别内容</legend>
            <label class="rc-switch">
              <input v-model="draft.enable_table" type="checkbox" :disabled="busy" />
              <span class="rc-switch-copy">
                <strong>表格识别</strong>
                <span>文档里有表格时开启；关闭会更快，但表格可能被识别成普通文本。</span>
              </span>
            </label>
            <label class="rc-switch">
              <input v-model="draft.enable_formula" type="checkbox" :disabled="busy" />
              <span class="rc-switch-copy">
                <strong>公式识别</strong>
                <span>仅含数学公式的文档才需要；CPU 下会明显变慢。</span>
              </span>
            </label>
          </fieldset>

          <p class="rc-warning">
            重新 OCR 会重新生成该文件的 Markdown、段落块与图表记录，并
            <strong>清空已有的实体/关系标注和图表截图</strong>，且无法恢复。
          </p>
          <p v-if="error" class="rc-error" role="alert">{{ error }}</p>
        </div>

        <footer class="rc-foot">
          <button type="button" class="rc-btn" :disabled="busy" @click="close">取消</button>
          <button
            type="button"
            class="rc-btn rc-btn--primary"
            :disabled="!canSubmit"
            @click="submit"
          >
            {{ busy ? '提交中…' : '开始重新 OCR' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.rc-backdrop {
  --rc-surface: var(--surface, #fffdf9);
  --rc-raised: var(--surface-raised, #fff);
  --rc-sunken: var(--surface-sunken, #f2eee6);
  --rc-paper: var(--paper, #f6f3ec);
  --rc-ink: var(--ink, #17181b);
  --rc-ink-2: var(--ink-2, #3e4147);
  --rc-ink-3: var(--ink-3, #6e727a);
  --rc-ink-4: var(--ink-4, #9a9da3);
  --rc-line: var(--line, #e2dccf);
  --rc-line-strong: var(--line-strong, #d2caba);
  --rc-signal: var(--signal, #e4572e);
  --rc-signal-deep: var(--signal-deep, #c44722);
  --rc-signal-soft: var(--signal-soft, #fbe8e1);
  --rc-signal-ink: var(--signal-ink, #8e2f14);
  --rc-warning: var(--warning, #a9761e);
  --rc-warning-bg: var(--warning-bg, #faf2e1);
  --rc-mono: var(--font-mono, 'Geist Mono', ui-monospace, Consolas, monospace);
  --rc-ease: var(--ease-out, cubic-bezier(0.22, 1, 0.36, 1));

  position: fixed;
  inset: 0;
  z-index: 130;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 22, 25, 0.42);
  backdrop-filter: blur(5px);
  -webkit-backdrop-filter: blur(5px);
  animation: rc-fade 160ms var(--rc-ease) both;
}

.rc-dialog {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: min(90vh, 780px);
  overflow: hidden;
  border: 1px solid var(--rc-line);
  border-radius: 20px;
  background: var(--rc-surface);
  box-shadow: 0 28px 60px -24px rgba(35, 29, 19, 0.35);
  animation: rc-rise 200ms var(--rc-ease) both;
}

.rc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  padding: 18px 22px 14px;
  border-bottom: 1px solid var(--rc-line);
}

.rc-head-copy {
  min-width: 0;
}

.rc-eyebrow {
  display: block;
  margin-bottom: 3px;
  font-family: var(--rc-mono);
  font-size: 9.5px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--rc-ink-3);
}

.rc-title {
  margin: 0;
  font-family: var(--font-display, 'Instrument Serif', Georgia, serif);
  font-size: 26px;
  font-weight: 400;
  line-height: 1.15;
  color: var(--rc-ink);
}

.rc-subtitle {
  margin: 5px 0 0;
  overflow: hidden;
  color: var(--rc-ink-3);
  font-size: 11.5px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.rc-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border: 1px solid var(--rc-line);
  border-radius: 8px;
  background: var(--rc-raised);
  color: var(--rc-ink-3);
  cursor: pointer;
}

.rc-close:hover:not(:disabled) {
  border-color: var(--rc-line-strong);
  color: var(--rc-ink);
}

.rc-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
  padding: 16px 22px 18px;
  overflow-y: auto;
}

.rc-recommend {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid rgba(228, 87, 46, 0.24);
  border-radius: 12px;
  background: linear-gradient(135deg, var(--rc-signal-soft), rgba(251, 232, 225, 0.35));
}

.rc-recommend-copy strong {
  display: block;
  margin-bottom: 3px;
  color: var(--rc-signal-ink);
  font-size: 12px;
  font-weight: 650;
}

.rc-recommend-copy p {
  margin: 0;
  color: var(--rc-ink-3);
  font-size: 11px;
  line-height: 1.55;
}

.rc-recommend-actions {
  display: flex;
  flex-shrink: 0;
  gap: 7px;
}

.rc-mini-btn {
  height: 28px;
  padding: 0 9px;
  border: 1px solid rgba(228, 87, 46, 0.4);
  border-radius: 7px;
  background: var(--rc-raised);
  color: var(--rc-signal-ink);
  font-family: inherit;
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.rc-mini-btn:hover:not(:disabled) {
  border-color: var(--rc-signal);
}

.rc-mini-btn--strong {
  background: var(--rc-signal-deep);
  border-color: transparent;
  color: #fffdf9;
}

.rc-mini-btn--strong:hover:not(:disabled) {
  background: var(--rc-signal);
}

.rc-mini-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.rc-section {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.rc-section-title {
  padding: 0;
  margin-bottom: 8px;
  color: var(--rc-ink-2);
  font-size: 11px;
  font-weight: 650;
}

.rc-dpi-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.rc-dpi-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 9px 11px;
  border: 1px solid var(--rc-line);
  border-radius: 10px;
  background: var(--rc-raised);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms var(--rc-ease),
    background-color 160ms var(--rc-ease);
}

.rc-dpi-btn:hover:not(:disabled) {
  border-color: var(--rc-line-strong);
}

.rc-dpi-btn.is-active {
  border-color: var(--rc-signal);
  background: var(--rc-signal-soft);
  box-shadow: 0 0 0 1px rgba(228, 87, 46, 0.25);
}

.rc-dpi-value {
  color: var(--rc-ink);
  font-family: var(--rc-mono);
  font-size: 12.5px;
  font-weight: 650;
}

.rc-dpi-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--rc-ink-3);
  font-size: 10.5px;
}

.rc-tag {
  padding: 1px 5px;
  border-radius: 999px;
  background: var(--rc-signal);
  color: #fffdf9;
  font-size: 8.5px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.rc-hint {
  margin: 7px 0 0;
  color: var(--rc-ink-3);
  font-size: 10.5px;
  line-height: 1.55;
}

.rc-parse-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.rc-parse-btn {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 9px 11px;
  border: 1px solid var(--rc-line);
  border-radius: 10px;
  background: var(--rc-raised);
  text-align: left;
  cursor: pointer;
  transition:
    border-color 160ms var(--rc-ease),
    background-color 160ms var(--rc-ease);
}

.rc-parse-btn:hover:not(:disabled) {
  border-color: var(--rc-line-strong);
}

.rc-parse-btn.is-active {
  border-color: var(--rc-signal);
  background: var(--rc-signal-soft);
}

.rc-radio {
  flex-shrink: 0;
  width: 13px;
  height: 13px;
  margin-top: 2px;
  border: 1.5px solid var(--rc-line-strong);
  border-radius: 50%;
  background: var(--rc-surface);
}

.rc-parse-btn.is-active .rc-radio {
  border-color: var(--rc-signal-deep);
  box-shadow: inset 0 0 0 3px var(--rc-surface);
  background: var(--rc-signal-deep);
}

.rc-parse-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.rc-parse-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--rc-ink);
  font-size: 11.5px;
  font-weight: 600;
}

.rc-parse-hint {
  color: var(--rc-ink-3);
  font-size: 10.5px;
  line-height: 1.5;
}

.rc-switch {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 7px 0;
  cursor: pointer;
}

.rc-switch input {
  margin-top: 2px;
  accent-color: var(--rc-signal-deep);
}

.rc-switch-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rc-switch-copy strong {
  color: var(--rc-ink);
  font-size: 11.5px;
  font-weight: 600;
}

.rc-switch-copy span {
  color: var(--rc-ink-3);
  font-size: 10.5px;
  line-height: 1.5;
}

.rc-warning {
  margin: 0;
  padding: 9px 11px;
  border: 1px solid rgba(169, 118, 30, 0.28);
  border-radius: 9px;
  background: var(--rc-warning-bg);
  color: #7a5716;
  font-size: 10.5px;
  line-height: 1.6;
}

.rc-error {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid rgba(181, 64, 58, 0.24);
  border-radius: 8px;
  background: rgba(250, 236, 234, 0.9);
  color: #b5403a;
  font-size: 11px;
}

.rc-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
  padding: 12px 22px 16px;
  border-top: 1px solid var(--rc-line);
}

.rc-btn {
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--rc-line);
  border-radius: 8px;
  background: var(--rc-raised);
  color: var(--rc-ink-2);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
}

.rc-btn:hover:not(:disabled) {
  border-color: var(--rc-line-strong);
  background: var(--rc-surface);
}

.rc-btn--primary {
  border-color: transparent;
  background: var(--rc-signal-deep);
  color: #fffdf9;
  font-weight: 600;
}

.rc-btn--primary:hover:not(:disabled) {
  background: var(--rc-signal);
  border-color: transparent;
}

.rc-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@keyframes rc-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes rc-rise {
  from {
    opacity: 0;
    transform: translateY(8px) scale(0.99);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (max-width: 720px) {
  .rc-backdrop {
    padding: 12px;
  }

  .rc-dpi-row {
    grid-template-columns: 1fr;
  }

  .rc-recommend {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
