<script setup lang="ts">
/**
 * 切分方式说明弹窗。
 * 从 React 版 HelpModal.tsx 迁移，文案与示例保持不变。
 */

interface HelpMethod {
  key: 'as_is' | 'paragraph' | 'sentence'
  icon: string
  title: string
  description: string
  example: string
  result: string
  useCases: string[]
}

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const methods: HelpMethod[] = [
  {
    key: 'as_is',
    icon: '📄',
    title: '原文模式',
    description: '整篇不切分，导入1条待标注对象',
    example: `在某航空结构件的制造过程中，加工任务由机加车间负责实施。操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对，确认该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。在正式加工前，张伟对所使用的立式加工中心进行了点检，确保设备状态满足精加工要求。

在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。该工序使用 Φ16 硬质合金立铣刀，切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。加工过程中，操作人员需持续观察切削状态，并根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。

完成粗加工后，零件进入半精加工与精加工工序。精加工工艺名称为“数控铣削精加工”，重点保证关键尺寸和表面质量。操作人员李强依据 GB/T 1804—2000《一般公差》对加工精度进行控制，并使用游标卡尺和高度尺进行尺寸检测。最终，经检验确认零件尺寸合格，表面粗糙度满足 Ra 1.6 μm 的设计要求，零件转入下一道装配工序。`,
    result: '✅ 1个标注对象：整篇文章作为一个整体进行标注',
    useCases: ['短文本标注', '完整文档分析', '整体情感分析'],
  },
  {
    key: 'paragraph',
    icon: '📝',
    title: '段落模式',
    description: '按空行分段，每段作为1条待标注对象',
    example: `段落 1
在某航空结构件的制造过程中，加工任务由机加车间负责实施。操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对，确认该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。在正式加工前，张伟对所使用的立式加工中心进行了点检，确保设备状态满足精加工要求。

段落 2
在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。该工序使用 Φ16 硬质合金立铣刀，切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。加工过程中，操作人员需持续观察切削状态，并根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。

段落 3
完成粗加工后，零件进入半精加工与精加工工序。精加工工艺名称为“数控铣削精加工”，重点保证关键尺寸和表面质量。操作人员李强依据 GB/T 1804—2000《一般公差》对加工精度进行控制，并使用游标卡尺和高度尺进行尺寸检测。最终，经检验确认零件尺寸合格，表面粗糙度满足 Ra 1.6 μm 的设计要求，零件转入下一道装配工序。`,
    result: `✅ 3个标注对象：
1. 第一段：在某航空结构件...精加工要求。
2. 第二段：在粗加工阶段...异常磨损。
3. 第三段：完成粗加工后...装配工序。`,
    useCases: ['段落主题提取', '分段情感分析', '内容结构化'],
  },
  {
    key: 'sentence',
    icon: '💬',
    title: '句子模式',
    description: '按句末标点和换行切分，每句作为1条待标注对象',
    example: `在某航空结构件的制造过程中，加工任务由机加车间负责实施。
操作人员张伟依据工艺规程文件，对零件图纸和技术要求进行了详细核对。
该零件材料为 7075-T6 铝合金，执行标准符合 GB/T 3190—2020《变形铝及铝合金化学成分》。
在正式加工前，张伟对所使用的立式加工中心进行了点检。
设备状态经确认后满足精加工要求。
在粗加工阶段，工艺名称为“数控铣削粗加工”，主要目的是去除大部分余量。
该工序使用 Φ16 硬质合金立铣刀。
切削参数按照工艺卡片执行，主轴转速设定为 6000 r/min，进给速度为 1200 mm/min。
加工过程中，操作人员需持续观察切削状态。
根据实际情况补充乳化切削液，以避免材料过热和刀具异常磨损。
...（后续句子）`,
    result: `✅ 多个标注对象：
1. 在某航空结构件的制造过程中...
2. 操作人员张伟依据工艺规程文件...
3. 该零件材料为 7075-T6 铝合金...
...`,
    useCases: ['句子级实体识别', '语法分析', '句子分类'],
  },
]

const stats = [
  { number: '1', label: '原文模式：适合短文本' },
  { number: '3-10', label: '段落模式：适合中等长度文本' },
  { number: '10+', label: '句子模式：适合详细分析' },
]

const tips = [
  '根据文本长度选择合适的切分方式，避免产生过多或过少的标注对象',
  '原文模式适合短文本，段落模式适合结构化文档，句子模式适合详细分析',
  '切分后的每个对象都会独立保存，可以分别进行标注和修改',
  '选择切分方式后，系统会自动预览切分结果，确认无误后再导入',
  '不同切分方式会影响标注效率，建议根据具体任务需求选择',
]

const quickStartSteps = [
  '拖拽或选择文本文件',
  '选择合适的切分方式',
  '预览切分结果',
  '开始标注工作',
]
</script>

<template>
  <div v-if="open" class="modal-overlay" @click="emit('close')">
    <div
      class="modal-content-large"
      role="dialog"
      aria-modal="true"
      aria-label="切分方式详细说明"
      @click.stop
    >
      <div class="modal-header-large">
        <div class="modal-heading-large">
          <span class="modal-eyebrow">Splitting Methods / Guide</span>
          <h2 class="modal-title-large">切分方式详细说明</h2>
        </div>
        <button type="button" class="modal-close-btn" aria-label="关闭" @click="emit('close')">
          ×
        </button>
      </div>

      <div class="modal-body-large">
        <section class="help-section">
          <div class="section-head">
            <span class="section-index">01</span>
            <h3 class="section-title">切分方式对比</h3>
          </div>

          <article v-for="(method, index) in methods" :key="method.key" class="help-method">
            <div class="method-header">
              <span class="method-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="method-heading">
                <div class="method-title">{{ method.title }}</div>
                <div class="method-description">{{ method.description }}</div>
              </div>
            </div>

            <div class="example-section">
              <div class="example-block">
                <div class="example-title">输入示例</div>
                <div class="example-content">{{ method.example }}</div>
              </div>

              <div class="example-block">
                <div class="example-title">切分结果</div>
                <div class="example-result">{{ method.result }}</div>
              </div>

              <div class="example-block">
                <div class="example-title">适用场景</div>
                <div class="method-use-cases">
                  <span v-for="useCase in method.useCases" :key="useCase" class="method-use-case">
                    {{ useCase }}
                  </span>
                </div>
              </div>
            </div>
          </article>
        </section>

        <section class="help-section">
          <div class="section-head">
            <span class="section-index">02</span>
            <h3 class="section-title">使用建议</h3>
          </div>
          <div class="usage-stats">
            <div v-for="stat in stats" :key="stat.label" class="stat-item">
              <span class="stat-number">{{ stat.number }}</span>
              <div class="stat-label">{{ stat.label }}</div>
            </div>
          </div>
        </section>

        <section class="tips-section">
          <div class="tips-title">使用技巧</div>
          <ul class="tips-list">
            <li v-for="tip in tips" :key="tip">{{ tip }}</li>
          </ul>
        </section>

        <section class="quick-start-panel">
          <div class="quick-start-title">快速开始</div>
          <ol class="quick-start-steps">
            <li v-for="(step, index) in quickStartSteps" :key="step">
              <span class="step-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="step-label">{{ step }}</span>
            </li>
          </ol>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============================================================
   Ink & Signal — 切分方式说明弹窗
   ============================================================ */
.modal-overlay {
  --tf-paper-deep: var(--paper-deep, #EFEBE2);
  --tf-raised: var(--surface-raised, #FFFFFF);
  --tf-sunken: var(--surface-sunken, #F2EEE6);
  --tf-ink: var(--ink, #17181B);
  --tf-ink-2: var(--ink-2, #3E4147);
  --tf-ink-3: var(--ink-3, #6E727A);
  --tf-ink-4: var(--ink-4, #9A9DA3);
  --tf-line: var(--line, #E2DCCF);
  --tf-line-strong: var(--line-strong, #D2CABA);
  --tf-signal: var(--signal, #E4572E);
  --tf-signal-deep: var(--signal-deep, #C44722);
  --tf-signal-soft: var(--signal-soft, #FBE8E1);
  --tf-signal-ink: var(--signal-ink, #8E2F14);
  --tf-success: var(--success, #2F7D5B);
  --tf-success-bg: var(--success-bg, #EAF4EE);
  --tf-mono: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
  --tf-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --tf-ease: var(--ease-out, cubic-bezier(.22,.61,.36,1));
  --tf-shadow-lg: var(--shadow-lg, 0 32px 80px -32px rgba(23,24,27,.3));

  position: fixed;
  inset: 0;
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 22, 25, .38);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  animation: hp-fade 180ms var(--tf-ease) both;
}

.modal-content-large {
  display: flex;
  flex-direction: column;
  width: min(900px, 100%);
  max-width: 900px;
  max-height: calc(100vh - 48px);
  overflow: hidden;
  border: 1px solid var(--tf-line);
  border-radius: 22px;
  background: var(--tf-raised);
  box-shadow: var(--tf-shadow-lg);
  animation: hp-pop 200ms var(--tf-ease) both;
}

/* 头部 */
.modal-header-large {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-shrink: 0;
  padding: 22px 26px 16px;
  border-bottom: 1px solid var(--tf-line);
  background: var(--tf-raised);
}
.modal-heading-large {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.modal-eyebrow {
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 13px;
  line-height: 1.2;
  color: var(--tf-ink-3);
}
.modal-title-large {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  letter-spacing: .01em;
  color: var(--tf-ink);
}

.modal-close-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 9px;
  border: 1px solid var(--tf-line);
  background: transparent;
  color: var(--tf-ink-3);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 180ms var(--tf-ease),
    color 180ms var(--tf-ease),
    border-color 180ms var(--tf-ease);
}
.modal-close-btn:hover {
  background: var(--tf-sunken);
  border-color: var(--tf-line);
  color: var(--tf-ink);
}

.modal-body-large {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 26px 30px;
  scrollbar-width: thin;
}

/* 分区标题：编号 + 中文 */
.help-section { margin-bottom: 22px; }
.section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}
.section-index {
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .06em;
  color: var(--tf-signal-deep);
  font-variant-numeric: tabular-nums;
}
.section-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .03em;
  color: var(--tf-ink);
}

/* 方法卡：细线卡片，无彩色底 */
.help-method {
  padding: 16px 18px;
  margin-bottom: 10px;
  border: 1px solid var(--tf-line);
  border-radius: 14px;
  background: var(--tf-raised);
  transition:
    border-color 200ms var(--tf-ease),
    box-shadow 200ms var(--tf-ease);
}
.help-method:hover {
  border-color: var(--tf-line-strong);
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(23,24,27,.05));
}
.method-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.method-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  border-radius: 9px;
  background: var(--tf-signal-soft);
  color: var(--tf-signal-ink);
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .04em;
  font-variant-numeric: tabular-nums;
}
.method-heading {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.method-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--tf-ink);
}
.method-description {
  font-size: 11.5px;
  color: var(--tf-ink-3);
}

.example-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--tf-line);
}
.example-block {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.example-title {
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
}
.example-content {
  max-height: 200px;
  overflow-y: auto;
  padding: 10px 12px;
  border-left: 2px solid var(--tf-line-strong);
  border-radius: 0 6px 6px 0;
  background: var(--tf-paper-deep);
  color: var(--tf-ink-3);
  font-family: var(--tf-mono);
  font-size: 11px;
  line-height: 1.65;
  white-space: pre-wrap;
  scrollbar-width: thin;
}
.example-result {
  padding: 10px 12px;
  border-left: 2px solid var(--tf-success);
  border-radius: 0 6px 6px 0;
  background: var(--tf-success-bg);
  color: #245C46;
  font-size: 11.5px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.method-use-cases {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 2px;
}
.method-use-case {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid var(--tf-line);
  border-radius: 6px;
  background: var(--tf-sunken);
  color: var(--tf-ink-3);
  font-size: 10.5px;
  line-height: 1.5;
}

/* 使用建议 */
.usage-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.stat-item {
  padding: 14px 16px;
  border: 1px solid var(--tf-line);
  border-radius: 12px;
  background: var(--tf-raised);
  text-align: left;
}
.stat-number {
  display: block;
  font-family: var(--tf-mono);
  font-size: 20px;
  font-weight: 500;
  letter-spacing: .02em;
  color: var(--tf-signal-deep);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}
.stat-label {
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--tf-ink-3);
}

/* 使用技巧 */
.tips-section {
  padding: 16px 18px;
  margin-bottom: 22px;
  border: 1px solid var(--tf-line);
  border-radius: 14px;
  background: var(--tf-paper-deep);
}
.tips-title {
  margin-bottom: 10px;
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
}
.tips-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.tips-list li {
  position: relative;
  padding-left: 16px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--tf-ink-2);
}
.tips-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: .62em;
  width: 5px;
  height: 1px;
  background: var(--tf-signal);
}

/* 快速开始 */
.quick-start-panel {
  padding: 16px 18px;
  border: 1px solid var(--tf-line);
  border-radius: 14px;
  background: var(--tf-raised);
}
.quick-start-title {
  margin-bottom: 10px;
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
}
.quick-start-steps {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 8px;
  padding: 0;
  margin: 0;
}
.quick-start-steps li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--tf-line);
  border-radius: 9px;
  background: var(--tf-sunken);
}
.step-index {
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  color: var(--tf-signal-deep);
  font-variant-numeric: tabular-nums;
}
.step-label {
  font-size: 11.5px;
  color: var(--tf-ink-2);
}

.modal-overlay :focus-visible {
  outline: 2px solid var(--tf-signal);
  outline-offset: 2px;
}

@keyframes hp-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes hp-pop {
  from { opacity: 0; transform: scale(.985); }
  to { opacity: 1; transform: scale(1); }
}

@media (max-width: 640px) {
  .modal-overlay { padding: 14px; }
  .modal-header-large { padding: 18px 18px 14px; }
  .modal-body-large { padding: 18px 18px 24px; }
  .help-method { padding: 14px; }
  .quick-start-steps { grid-template-columns: minmax(0, 1fr); }
}

@media (prefers-reduced-motion: reduce) {
  .modal-overlay,
  .modal-content-large,
  .modal-content-large * {
    animation-duration: .001ms !important;
    transition-duration: .001ms !important;
  }
}
</style>
