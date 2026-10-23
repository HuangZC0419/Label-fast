<script setup lang="ts">
import { computed } from 'vue'
import HelpModal from '../components/text/HelpModal.vue'
import SettingsModal from '../components/text/SettingsModal.vue'
import { useTextAnnotation } from '../composables/useTextAnnotation'

/**
 * 文本标注页。
 * 布局：左侧项目/标签栏 + 工作台左列待标注对象 + 右侧文本画布。
 * 全局顶部栏（AppHeader）已提供品牌、用户与退出，本页不再重复。
 */

const {
  projectName,
  labelsInput,
  relationTypesInput,
  labels,
  relationTypes,
  palette,
  relPalette,
  projectList,
  pid,
  projectsLoading,
  projectLoading,
  savingProject,
  items,
  currentIndex,
  splitMode,
  uploadInfo,
  canPrev,
  canNext,
  relations,
  chars,
  spanRenderList,
  relationVisuals,
  containerRef,
  overlayHeight,
  fontSize,
  lineH,
  relStrokeWidth,
  relDashed,
  annotationStyle,
  pending,
  labelPickerOpen,
  relPickerOpen,
  pendingRel,
  hoverRelIdx,
  showSettings,
  splitHelpOpen,
  savingRecord,
  statusOf,
  statusTitle,
  setCharRef,
  spanSegmentStyle,
  spanLabelText,
  handleContainerMouseUp,
  handleContainerContextMenu,
  handleSpanMouseDown,
  handleSpanMouseUp,
  handleSpanClick,
  addSpan,
  cancelLabelPicker,
  addRelation,
  cancelRelPicker,
  handleRelationTypeChange,
  deleteRelation,
  selectItem,
  prevItem,
  nextItem,
  handleSkip,
  handleSaveOnly,
  handleSaveAndNext,
  handleDeleteCurrent,
  handleFilesSelected,
  handleDrop,
  handleConfigUpload,
  handleProjectSelect,
  handleSwitchProject,
  clearProject,
  deleteProject,
  exportZip,
  saveProject,
} = useTextAnnotation()

/** 两位编号，用于工具栏与文档 eyebrow 的编辑感排版 */
function formatIndex(value: number): string {
  return String(Math.max(value, 0)).padStart(2, '0')
}

/** 已完成文档数与进度，用于待标注对象面板底部进度条 */
const completedCount = computed(
  () => items.value.filter((_, index) => statusOf(index) === 'completed').length,
)
const progressPercent = computed(() =>
  items.value.length > 0 ? Math.round((completedCount.value / items.value.length) * 100) : 0,
)
</script>

<template>
  <div class="text-page">
    <!-- ================================================================
         左侧栏 — 项目配置 / 标签配置 / 待标注对象
         ================================================================ -->
    <aside class="sidebar">
      <!-- 模块 1：项目配置 -->
      <section class="sidebar-module">
        <div class="sidebar-module-title">
          <span class="module-heading">
            <span class="module-index">01</span>
            <span class="module-sep">/</span>
            <span class="module-name">项目</span>
          </span>
          <span class="sidebar-module-actions">
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="!pid || savingProject"
              @click="saveProject"
            >
              保存
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              title="一键打包 ZIP（含 JSON+JSONL+CSV）"
              :disabled="!pid"
              @click="exportZip"
            >
              打包导出
            </button>
          </span>
        </div>

        <div class="sidebar-module-body">
          <label class="sidebar-field">
            <span class="sidebar-field-label">当前项目</span>
            <select
              class="input"
              aria-label="选择项目"
              :value="pid ? String(pid) : ''"
              @change="handleProjectSelect"
            >
              <option value="">{{ projectsLoading ? '加载项目中…' : '选择已有项目...' }}</option>
              <option v-for="project in projectList" :key="project.id" :value="String(project.id)">
                {{ project.name }}
              </option>
            </select>
          </label>

          <div class="sidebar-divider"><span>或新建项目</span></div>

          <div class="project-create">
            <input v-model="projectName" class="input" placeholder="输入新项目名称" />
            <button
              type="button"
              class="btn btn-dark btn-sm full-width-btn"
              :disabled="!projectName.trim()"
              @click="handleSwitchProject"
            >
              {{ pid ? '切换 / 创建项目' : '创建新项目' }}
            </button>
          </div>

          <div v-if="pid" class="sidebar-status ok">当前项目: {{ projectName }}</div>
          <div v-else class="sidebar-status hint">请选择项目或输入名称创建</div>
          <div v-if="projectLoading" class="sidebar-status hint">正在加载项目数据…</div>

          <div class="danger-row">
            <button
              type="button"
              class="btn btn-danger btn-sm flex-1"
              :disabled="!pid || projectLoading"
              @click="clearProject"
            >
              清空数据
            </button>
            <button
              type="button"
              class="btn btn-danger btn-sm flex-1"
              :disabled="!pid || projectLoading"
              @click="deleteProject"
            >
              删除项目
            </button>
          </div>
        </div>
      </section>

      <!-- 模块 2：标签配置 -->
      <section class="sidebar-module">
        <div class="sidebar-module-title">
          <span class="module-heading">
            <span class="module-index">02</span>
            <span class="module-sep">/</span>
            <span class="module-name">标签</span>
          </span>
        </div>
        <div class="sidebar-module-body">
          <label class="sidebar-field">
            <span class="sidebar-field-label">实体标签</span>
            <input
              v-model="labelsInput"
              class="input"
              placeholder="逗号分隔，如: 人名, 地名, 组织"
            />
          </label>
          <label class="sidebar-field">
            <span class="sidebar-field-label">关系类型</span>
            <input
              v-model="relationTypesInput"
              class="input"
              placeholder="逗号分隔，如: 位于, 属于, 担任"
            />
          </label>

          <label class="config-upload">
            <span class="config-upload-icon" aria-hidden="true">
              <svg
                width="15"
                height="15"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <path d="M8 13h8M8 17h5" />
              </svg>
            </span>
            <span class="config-upload-copy">
              <span class="config-upload-title">从 TXT 导入配置</span>
              <span class="config-upload-hint">自动识别「标签」与「关系」分段</span>
            </span>
            <span class="config-upload-action" aria-hidden="true">选择</span>
            <input
              type="file"
              accept=".txt"
              class="input input-file"
              aria-label="从 TXT 文件导入标签与关系配置"
              @change="handleConfigUpload"
            />
          </label>
        </div>
      </section>

      <div class="sidebar-foot">
        <span class="sidebar-foot-eyebrow">Workspace</span>
        <p class="sidebar-foot-text">
          选中文本后按 <kbd>1–9</kbd> 选择实体标签，<kbd>Ctrl</kbd> + <kbd>1–9</kbd> 选择关系类型。
        </p>
        <div class="sidebar-foot-stats">
          <span><strong>{{ items.length }}</strong> 条语料</span>
          <span><strong>{{ labels.length }}</strong> 个标签</span>
          <span><strong>{{ relationTypes.length }}</strong> 种关系</span>
        </div>
      </div>

    </aside>

    <!-- 工作台左列：待标注对象 -->
    <section class="doc-panel" aria-label="待标注对象">
      <header class="doc-panel-head">
        <div class="doc-panel-heading">
          <span class="module-index">03</span>
          <span class="module-sep">/</span>
          <h2 class="doc-panel-title">待标注对象</h2>
        </div>
        <span class="doc-panel-count">{{ formatIndex(items.length) }}</span>
      </header>

      <div class="doc-panel-body">

          <div
            class="upload-bar upload-card"
            @dragover.prevent
            @drop.prevent="handleDrop"
          >
            <div class="upload-card-head">
              <span class="upload-icon" aria-hidden="true">
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
              </span>
              <span class="upload-copy">
                <strong>拖拽 .txt 到此处</strong>
                <span>支持多文件 · 单文件不超过 10 MB</span>
              </span>
            </div>

            <div class="upload-card-controls">
              <div class="segmentation-tabs" role="group" aria-label="切分方式">
                <button
                  type="button"
                  class="tab-item"
                  :class="{ active: splitMode === 'as_is' }"
                  :aria-pressed="splitMode === 'as_is'"
                  @click="splitMode = 'as_is'"
                >
                  原文
                </button>
                <button
                  type="button"
                  class="tab-item"
                  :class="{ active: splitMode === 'paragraph' }"
                  :aria-pressed="splitMode === 'paragraph'"
                  @click="splitMode = 'paragraph'"
                >
                  段落
                </button>
                <button
                  type="button"
                  class="tab-item"
                  :class="{ active: splitMode === 'sentence' }"
                  :aria-pressed="splitMode === 'sentence'"
                  @click="splitMode = 'sentence'"
                >
                  句子
                </button>
              </div>

              <div class="upload-card-actions">
                <button
                  type="button"
                  class="help-icon-btn upload-help-btn"
                  title="切分方式说明"
                  aria-label="切分方式说明"
                  @click="splitHelpOpen = true"
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <circle cx="12" cy="12" r="9" />
                    <path d="M9.6 9.2a2.6 2.6 0 1 1 3.6 2.4c-.8.35-1.2.9-1.2 1.9" />
                    <path d="M12 17h.01" />
                  </svg>
                </button>

                <label class="upload-bar-btn">
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                  >
                    <path
                      d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"
                    />
                  </svg>
                  选择文件
                  <input type="file" multiple accept=".txt" @change="handleFilesSelected" />
                </label>
              </div>
            </div>
          </div>

          <div v-if="uploadInfo" class="upload-info-text">{{ uploadInfo }}</div>

          <div class="doc-list" role="list" aria-label="待标注对象列表">
            <div v-if="items.length === 0" class="doc-list-empty">
              <span class="empty-glyph" aria-hidden="true">
                <svg
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <path d="M8 13h8M8 17h5" />
                </svg>
              </span>
              <p class="empty-en">Nothing to annotate</p>
              <p class="empty-zh">暂无待标注对象</p>
              <p class="empty-hint">导入 TXT 后，切分结果会显示在这里</p>
            </div>

            <template v-else>
              <div
                v-for="(item, index) in items"
                :key="index"
                class="list-item"
                :class="{ active: currentIndex === index }"
                :title="item"
                role="listitem"
                :aria-current="currentIndex === index ? 'true' : undefined"
                @click="selectItem(index)"
              >
                <span class="count-badge">{{ formatIndex(index + 1) }}</span>
                <span class="list-item-text">{{ item }}</span>
                <span
                  class="status-dot"
                  :class="statusOf(index)"
                  :title="statusTitle(statusOf(index))"
                ></span>
              </div>
            </template>
          </div>
      </div>

      <footer class="doc-panel-foot">
        <div class="doc-progress">
          <div class="doc-progress-label">
            <span>已完成</span>
            <span>{{ formatIndex(completedCount) }} / {{ formatIndex(items.length) }}</span>
          </div>
          <span class="doc-progress-bar"><span :style="{ width: `${progressPercent}%` }"></span></span>
        </div>
      </footer>
    </section>

    <!-- ================================================================
         右侧工作区
         ================================================================ -->
    <main class="workspace">
      <!-- 命令条 -->
      <div class="workspace-toolbar">
        <div class="workspace-toolbar-left">
          <div class="toolbar-nav">
            <button type="button" class="btn btn-quiet" :disabled="!canPrev" @click="prevItem">
              上一篇
            </button>
            <button type="button" class="btn btn-quiet" :disabled="!canNext" @click="nextItem">
              下一篇
            </button>
          </div>

          <span class="toolbar-divider" aria-hidden="true"></span>

          <div class="doc-counter">
            <span class="doc-counter-label">
              {{ currentIndex >= 0 ? '待标注对象' : '无待标注对象' }}
            </span>
            <span v-if="currentIndex >= 0" class="doc-counter-value">
              {{ formatIndex(currentIndex + 1) }}
              <span class="doc-counter-slash">/</span>
              {{ formatIndex(items.length) }}
            </span>
          </div>

          <button
            v-if="currentIndex >= 0 && items.length > 0"
            type="button"
            class="btn btn-danger btn-sm"
            @click="handleDeleteCurrent"
          >
            删除当前
          </button>
        </div>

        <div class="workspace-toolbar-actions">
          <button
            type="button"
            class="btn btn-quiet"
            :disabled="currentIndex < 0"
            @click="handleSkip"
          >
            跳过
          </button>

          <span class="toolbar-divider" aria-hidden="true"></span>

          <button
            type="button"
            class="btn btn-signal-soft"
            :disabled="currentIndex < 0 || savingRecord"
            @click="handleSaveOnly"
          >
            保存
            <span
              v-if="currentIndex >= 0 && statusOf(currentIndex) === 'completed'"
              class="saved-mark"
              aria-hidden="true"
            >✓</span>
          </button>
          <button
            type="button"
            class="btn btn-primary"
            :disabled="currentIndex < 0 || savingRecord"
            @click="handleSaveAndNext"
          >
            保存并下一篇
          </button>
          <button
            type="button"
            class="btn btn-quiet btn-settings"
            title="显示设置与快捷键"
            aria-label="显示设置与快捷键"
            @click="showSettings = true"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="3" />
              <path
                d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"
              />
            </svg>
            设置
          </button>
        </div>
      </div>

      <!-- 标签 / 关系快捷区 -->
      <div class="card shortcut-card">
        <div class="shortcut-grid">
          <div class="shortcut-column">
            <div class="shortcut-head">
              <h4 class="shortcut-title">实体标签</h4>
              <span class="shortcut-hint">快捷键 1–9</span>
            </div>
            <div class="chip-row">
              <button
                v-for="(label, index) in labels"
                :key="label"
                type="button"
                class="label-chip"
                :style="{ background: palette[label] }"
                @click="addSpan(label)"
              >
                <span v-if="index < 9" class="shortcut-index">{{ index + 1 }}</span>
                {{ label }}
              </button>
              <span v-if="labels.length === 0" class="chip-empty">请在左侧导入标签配置</span>
            </div>
          </div>

          <div class="shortcut-column shortcut-column--divider">
            <div class="shortcut-head">
              <h4 class="shortcut-title">关系类型</h4>
              <span class="shortcut-hint">Ctrl + 1–9</span>
            </div>
            <div class="chip-row">
              <button
                v-for="(type, index) in relationTypes"
                :key="type"
                type="button"
                class="label-chip relation-chip"
                :style="{ background: relPalette[type] }"
                @click="addRelation(type)"
              >
                <span v-if="index < 9" class="shortcut-index shortcut-index--light">
                  {{ index + 1 }}
                </span>
                {{ type }}
              </button>
              <span v-if="relationTypes.length === 0" class="chip-empty">请在左侧导入关系配置</span>
            </div>
          </div>
        </div>

        <div v-if="pending || pendingRel" class="inline-picker-hint" role="status" aria-live="polite">
          <span class="inline-hint-dot" aria-hidden="true"></span>
          <template v-if="pending">
            已选中文本 · 点击实体标签或按 <kbd>1–9</kbd> 应用
          </template>
          <template v-else>
            已连接两个实体 · 点击关系类型或按 <kbd>Ctrl</kbd> + <kbd>1–9</kbd> 应用
          </template>
          <button
            type="button"
            class="inline-hint-cancel"
            @click="pending ? cancelLabelPicker() : cancelRelPicker()"
          >
            取消
          </button>
        </div>

      </div>
      <!-- 文本编辑区（字符 span + 绝对定位高亮 + SVG 关系层） -->
      <div class="card annotation-card">
        <div class="document-eyebrow">
          <span class="eyebrow-brand">
            Document
            <span class="eyebrow-divider" aria-hidden="true">·</span>
            <span class="eyebrow-figures">
              {{ currentIndex >= 0 ? formatIndex(currentIndex + 1) : '—' }}
              <span class="eyebrow-slash">/</span>
              {{ formatIndex(items.length) }}
            </span>
          </span>
          <span class="eyebrow-meta">
            <span>{{ chars.length }} 字</span>
            <span class="eyebrow-divider" aria-hidden="true">·</span>
            <span>{{ currentIndex >= 0 ? statusTitle(statusOf(currentIndex)) : '未选择' }}</span>
          </span>
        </div>

        <div v-if="currentIndex < 0" class="canvas-empty">
          <span class="canvas-empty-glyph" aria-hidden="true">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6" />
              <path d="M8 13h8M8 17h5" />
            </svg>
          </span>
          <p class="canvas-empty-en">No document selected</p>
          <p class="canvas-empty-zh">从左侧导入或选择一段文本</p>
          <p class="canvas-empty-hint">支持拖拽 TXT，按原文、段落或句子切分后开始标注</p>
        </div>

        <div
          ref="containerRef"
          class="annotation-area"
          tabindex="0"
          :style="annotationStyle"
          @mouseup="handleContainerMouseUp"
          @contextmenu.prevent="handleContainerContextMenu"
        >
          <span
            v-for="(char, index) in chars"
            :key="index"
            :data-char-index="index"
            :ref="setCharRef"
          >{{ char }}</span>

          <template v-for="entry in spanRenderList" :key="entry.span.id">
            <div
              v-for="(segment, segmentIndex) in entry.segments"
              :key="`${entry.span.id}-${segmentIndex}`"
              class="span-highlight"
              :style="spanSegmentStyle(entry.span, segment)"
              @mousedown.prevent="handleSpanMouseDown(entry.span.id)"
              @mouseup.stop="handleSpanMouseUp(entry.span.id)"
              @click.stop="handleSpanClick(entry.span.id)"
            ></div>
          </template>

          <svg class="relation-layer" :style="{ height: overlayHeight > 0 ? `${overlayHeight}px` : '100%' }">
            <defs>
              <marker id="relation-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="#3E4147" />
              </marker>
            </defs>

            <g
              v-for="visual in relationVisuals"
              :key="visual.index"
              class="relation-group"
              @mouseenter="hoverRelIdx = visual.index"
              @mouseleave="hoverRelIdx = null"
              @mouseup.stop
            >
              <path
                :d="visual.path"
                :stroke="visual.color"
                fill="none"
                :stroke-width="visual.hovered ? relStrokeWidth + 1 : relStrokeWidth"
                marker-end="url(#relation-arrow)"
                :stroke-dasharray="relDashed ? '6 4' : undefined"
                :opacity="visual.hovered ? 1 : 0.7"
              />
              <text
                :x="visual.mx"
                :y="visual.labelY"
                :fill="visual.color"
                font-size="12"
                text-anchor="middle"
                :font-weight="visual.hovered ? 'bold' : 'normal'"
                class="relation-label"
              >
                {{ visual.type }}
              </text>
            </g>
          </svg>
        </div>
      </div>

    </main>

    <!-- 显示设置与快捷键 -->
    <SettingsModal
      :open="showSettings"
      :font-size="fontSize"
      :line-height="lineH"
      :rel-stroke-width="relStrokeWidth"
      :rel-dashed="relDashed"
      @close="showSettings = false"
      @update:font-size="fontSize = $event"
      @update:line-height="lineH = $event"
      @update:rel-stroke-width="relStrokeWidth = $event"
      @update:rel-dashed="relDashed = $event"
    />

    <!-- 切分方式说明 -->
    <HelpModal :open="splitHelpOpen" @close="splitHelpOpen = false" />
  </div>
</template>

<style scoped>
/* ============================================================
   Ink & Signal — 文本标注页
   暖纸画布 / 墨色文字 / 单一朱砂橙强调 / 细线分隔
   令牌全部带 fallback，兼容设计系统尚未注入的新变量
   ============================================================ */
.text-page {
  --tf-paper: var(--paper, #F6F3EC);
  --tf-paper-deep: var(--paper-deep, #EFEBE2);
  --tf-surface: var(--surface, #FFFDF9);
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
  --tf-warning: var(--warning, #A9761E);
  --tf-danger: var(--danger, #B5403A);
  --tf-danger-bg: var(--danger-bg, #FAECEA);
  --tf-mono: var(--font-mono, 'JetBrains Mono', 'Fira Code', monospace);
  --tf-display: var(--font-display, 'Instrument Serif', Georgia, serif);
  --tf-ease: var(--ease-out, cubic-bezier(.22,.61,.36,1));
  --tf-shadow-xs: var(--shadow-xs, 0 1px 2px rgba(23,24,27,.05));
  --tf-shadow: var(--shadow, 0 18px 44px -28px rgba(23,24,27,.22));
  --tf-shadow-lg: var(--shadow-lg, 0 32px 80px -32px rgba(23,24,27,.3));

  height: 100%;
  display: flex;
  min-height: 0;
  overflow: hidden;
  background: var(--tf-paper);
  color: var(--tf-ink);
}

.full-width-btn { width: 100%; }

/* ------------------------------------------------------------
   通用按钮：克制的暖色边框 / 1px 上浮 / 按压缩放
   ------------------------------------------------------------ */
.text-page .btn {
  height: 32px;
  padding: 0 12px;
  border-radius: 9px;
  border: 1px solid var(--tf-line);
  background: var(--tf-surface);
  color: var(--tf-ink-2);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 12.5px;
  font-weight: 500;
  line-height: 1;
  box-shadow: none;
  transition:
    transform 180ms var(--tf-ease),
    background-color 180ms var(--tf-ease),
    border-color 180ms var(--tf-ease),
    box-shadow 180ms var(--tf-ease),
    color 180ms var(--tf-ease);
}
.text-page .btn:hover:not(:disabled) {
  transform: translateY(-1px);
  background: var(--tf-raised);
  border-color: var(--tf-line-strong);
  box-shadow: var(--tf-shadow-xs);
}
.text-page .btn:active:not(:disabled) {
  transform: scale(.985);
}
.text-page .btn:disabled {
  opacity: .42;
  transform: none;
  box-shadow: none;
}
.text-page .btn-sm {
  height: 27px;
  padding: 0 10px;
  font-size: 11.5px;
  border-radius: 8px;
}
.text-page .btn-primary {
  background: var(--tf-signal-deep);
  border-color: transparent;
  color: #FFFDF9;
  font-weight: 600;
}
.text-page .btn-primary:hover:not(:disabled) {
  background: var(--tf-signal-ink);
  border-color: transparent;
  color: #FFFDF9;
}
.text-page .btn-dark {
  background: var(--tf-ink);
  border-color: transparent;
  color: var(--tf-surface);
  font-weight: 600;
}
.text-page .btn-dark:hover:not(:disabled) {
  background: #000;
  border-color: transparent;
  color: var(--tf-surface);
}
.text-page .btn-signal-soft {
  background: var(--tf-signal-soft);
  border-color: transparent;
  color: var(--tf-signal-ink);
  font-weight: 600;
}
.text-page .btn-signal-soft:hover:not(:disabled) {
  background: #F7DCD2;
  border-color: transparent;
  color: var(--tf-signal-ink);
}
.text-page .btn-ghost {
  background: transparent;
  border-color: var(--tf-line);
  color: var(--tf-ink-3);
}
.text-page .btn-ghost:hover:not(:disabled) {
  background: var(--tf-paper-deep);
  color: var(--tf-ink);
}
.text-page .btn-quiet {
  background: transparent;
  border-color: transparent;
  color: var(--tf-ink-3);
}
.text-page .btn-quiet:hover:not(:disabled) {
  background: var(--tf-paper-deep);
  border-color: transparent;
  color: var(--tf-ink);
}
.text-page .btn-danger {
  background: var(--tf-danger-bg);
  border-color: transparent;
  color: var(--tf-danger);
  font-weight: 500;
}
.text-page .btn-danger:hover:not(:disabled) {
  background: #F5DDD8;
  border-color: transparent;
  color: #93302B;
}
.text-page .btn:focus-visible,
.text-page .tab-item:focus-visible,
.text-page .label-chip:focus-visible,
.text-page .help-icon-btn:focus-visible,
.text-page .upload-bar-btn:focus-within,
.text-page .config-upload:focus-within,
.text-page .list-item:focus-visible {
  outline: 2px solid var(--tf-signal);
  outline-offset: 2px;
}

/* ------------------------------------------------------------
   左侧栏
   ------------------------------------------------------------ */
.sidebar {
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: var(--tf-surface);
  border-right: 1px solid var(--tf-line);
  animation: tf-fade 320ms var(--tf-ease) both;
}

.sidebar-module {
  border-bottom: 1px solid var(--tf-line);
  flex-shrink: 0;
}
.sidebar-module-grow {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-bottom: none;
}

/* 编号 + 小标题：编辑目录式模块标题 */
.sidebar-module-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 18px 20px 9px;
  background: transparent;
  text-transform: none;
  letter-spacing: normal;
  user-select: none;
}
.module-heading {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.module-index {
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .06em;
  color: var(--tf-ink-4);
  font-variant-numeric: tabular-nums;
}
.module-sep {
  font-family: var(--tf-mono);
  font-size: 10px;
  color: var(--tf-line-strong);
}
.module-name {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tf-ink);
}
.module-side {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.module-note {
  font-size: 10.5px;
  color: var(--tf-ink-3);
  letter-spacing: .02em;
  white-space: nowrap;
}
.sidebar-module-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.sidebar-module-badge {
  min-width: 22px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--tf-sunken);
  color: var(--tf-ink-3);
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  text-align: center;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}

.sidebar-module-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 3px 20px 18px;
}
.sidebar-module-flex {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-bottom: 16px;
}

/* 表单字段 */
.sidebar-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sidebar-field-label {
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: .03em;
  color: var(--tf-ink-3);
}

.text-page .input {
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--tf-line);
  background: var(--tf-raised);
  color: var(--tf-ink);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 12.5px;
  box-shadow: none;
  transition:
    border-color 180ms var(--tf-ease),
    box-shadow 180ms var(--tf-ease),
    background-color 180ms var(--tf-ease);
}
.text-page .input::placeholder { color: var(--tf-ink-4); }
.text-page .input:hover:not(:disabled):not(:focus) {
  border-color: var(--tf-line-strong);
}
.text-page .input:focus {
  border-color: var(--tf-signal);
  box-shadow: 0 0 0 3px var(--tf-signal-soft);
  outline: none;
}
.text-page select.input {
  padding-right: 28px;
  background-color: var(--tf-raised);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%236E727A' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 9px center;
  background-size: 12px 12px;
}

.project-create {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 2px 0;
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--tf-ink-4);
}
.sidebar-divider::before,
.sidebar-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--tf-line);
}

.sidebar-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 11.5px;
  font-weight: 400;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-status.ok {
  background: var(--tf-success-bg);
  color: var(--tf-success);
}
.sidebar-status.ok::before {
  content: '';
  width: 5px;
  height: 5px;
  flex-shrink: 0;
  border-radius: 50%;
  background: currentColor;
}
.sidebar-status.hint {
  background: var(--tf-sunken);
  color: var(--tf-ink-4);
}
.danger-row {
  display: flex;
  gap: 8px;
  margin-top: 2px;
}
.danger-row .btn { flex: 1; }

/* 配置导入：虚线卡片，与上传区保持同一语言 */
.config-upload {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 1px dashed var(--tf-line-strong);
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
  transition:
    border-color 180ms var(--tf-ease),
    background-color 180ms var(--tf-ease);
}
.config-upload:hover {
  border-color: var(--tf-signal);
  background: #FFFCF8;
}
.config-upload-icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--tf-sunken);
  color: var(--tf-ink-3);
}
.config-upload-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.config-upload-title {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--tf-ink-2);
}
.config-upload-hint {
  font-size: 10px;
  color: var(--tf-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.config-upload-action {
  flex-shrink: 0;
  font-size: 10.5px;
  color: var(--tf-signal-ink);
  letter-spacing: .02em;
}
.config-upload .input-file {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  padding: 0;
  cursor: pointer;
}

/* 上传卡片 */
.upload-card {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  padding: 11px 12px;
  border: 1px dashed var(--tf-line-strong);
  border-radius: 12px;
  background: var(--tf-raised);
  flex-shrink: 0;
  flex-wrap: nowrap;
  transition:
    border-color 200ms var(--tf-ease),
    background-color 200ms var(--tf-ease);
}
.upload-card:hover {
  border-color: var(--tf-signal);
  background: #FFFCF8;
}
.upload-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.upload-icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 9px;
  background: var(--tf-signal-soft);
  color: var(--tf-signal-deep);
}
.upload-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.upload-copy strong {
  font-size: 12px;
  font-weight: 600;
  color: var(--tf-ink);
  letter-spacing: .01em;
}
.upload-copy span {
  font-size: 10px;
  color: var(--tf-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.upload-card-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 8px;
}
.upload-card-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  flex-shrink: 0;
}
.upload-help-btn {
  padding: 4px;
  flex-shrink: 0;
  color: var(--tf-ink-4);
  border-radius: 6px;
}
.upload-help-btn:hover {
  color: var(--tf-ink);
  background: var(--tf-sunken);
  border-color: transparent;
}

/* 原文 / 段落 / 句子：紧凑 segmented control */
.segmentation-tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: var(--tf-sunken);
  flex-shrink: 0;
}
.tab-item {
  flex: 0 0 auto;
  padding: 5px 9px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--tf-ink-3);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: .01em;
  cursor: pointer;
  transition:
    background-color 180ms var(--tf-ease),
    color 180ms var(--tf-ease),
    box-shadow 180ms var(--tf-ease);
}
.tab-item:hover { color: var(--tf-ink); background: rgba(255,255,255,.55); }
.tab-item.active {
  background: var(--tf-raised);
  color: var(--tf-ink);
  font-weight: 600;
  box-shadow: var(--tf-shadow-xs);
}

.upload-bar-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border-radius: 7px;
  border: 1px solid transparent;
  background: var(--tf-signal-soft);
  color: var(--tf-signal-ink);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  cursor: pointer;
  transition:
    background-color 180ms var(--tf-ease),
    color 180ms var(--tf-ease),
    transform 180ms var(--tf-ease);
}
.upload-bar-btn:hover {
  background: var(--tf-signal-deep);
  color: #FFFDF9;
  transform: translateY(-1px);
}
.upload-bar-btn input[type="file"] {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.upload-info-text {
  padding: 0 2px;
  flex-shrink: 0;
  font-size: 10.5px;
  color: var(--tf-success);
}

/* 文档列表 */
.doc-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 2px 0;
  scrollbar-width: thin;
  scrollbar-color: var(--tf-line-strong) transparent;
}
.doc-list-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-height: 0;
  padding: 12px 12px;
  text-align: center;
  color: var(--tf-ink-4);
}
/* 全局空状态伪元素会再插入一句英文，这里统一由模板中的空状态文案承担 */
.doc-list-empty::before {
  content: none;
  display: none;
}
.empty-glyph {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-bottom: 2px;
  border: 1px solid var(--tf-line);
  border-radius: 50%;
  color: var(--tf-ink-4);
  opacity: .9;
}
.empty-en {
  margin: 0;
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 18px;
  line-height: 1.15;
  color: var(--tf-ink-3);
}
.empty-zh {
  margin: 0;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tf-ink-2);
}
.empty-hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.45;
  color: var(--tf-ink-3);
}
@media (max-height: 940px) {
  .empty-hint { display: none; }
}

/* 未选择文档时的画布空状态 */
.canvas-empty {
  position: absolute;
  inset: 56px 0 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 24px;
  text-align: center;
  pointer-events: none;
}
.canvas-empty-glyph {
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin-bottom: 8px;
  border: 1px solid var(--tf-line);
  border-radius: 50%;
  color: var(--tf-ink-4);
}
.canvas-empty-en {
  margin: 0;
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 28px;
  line-height: 1.15;
  color: var(--tf-ink-3);
}
.canvas-empty-zh {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tf-ink-2);
}
.canvas-empty-hint {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--tf-ink-3);
}
@media (max-height: 720px) {
  .canvas-empty-hint { display: none; }
}

.list-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px 9px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 13px;
  color: var(--tf-ink-2);
  cursor: pointer;
  transition:
    background-color 180ms var(--tf-ease),
    color 180ms var(--tf-ease);
}
.list-item:hover {
  background: var(--tf-paper-deep);
  border-color: transparent;
}
.list-item.active {
  background: var(--tf-signal-soft);
  color: var(--tf-ink);
}
.list-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 2px;
  background: var(--tf-signal);
}
.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: auto;
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: var(--tf-ink-4);
  font-family: var(--tf-mono);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .02em;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  transition: color 180ms var(--tf-ease);
}
.list-item.active .count-badge { color: var(--tf-signal-deep); }
.list-item-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--tf-ink-4);
  box-shadow: 0 0 0 3px rgba(154,157,163,.16);
  transition: background-color 180ms var(--tf-ease);
}
.status-dot.completed {
  background: var(--tf-success);
  box-shadow: 0 0 0 3px rgba(47,125,91,.15);
}
.status-dot.in_progress {
  background: var(--tf-warning);
  box-shadow: 0 0 0 3px rgba(169,118,30,.16);
}
.status-dot.pending {
  background: var(--tf-ink-4);
  box-shadow: 0 0 0 3px rgba(154,157,163,.16);
}

/* ------------------------------------------------------------
   右侧工作区
   ------------------------------------------------------------ */
.workspace {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  overflow-y: auto;
  background: var(--tf-paper);
  scrollbar-width: thin;
  scrollbar-color: var(--tf-line-strong) transparent;
}

/* 命令条：半透明暖纸底 + 1px 分隔，滚动时保持可操作 */
.workspace-toolbar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  min-height: 60px;
  padding: 12px clamp(18px, 3vw, 34px);
  background: rgba(246, 243, 236, .92);
  background: color-mix(in srgb, var(--tf-paper) 90%, transparent);
  border-bottom: 1px solid var(--tf-line);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  animation: tf-fade 300ms var(--tf-ease) both;
}
.workspace-toolbar-left,
.workspace-toolbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.toolbar-nav { display: inline-flex; gap: 4px; }
.toolbar-divider {
  width: 1px;
  height: 18px;
  flex-shrink: 0;
  background: var(--tf-line);
}
.doc-counter {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.doc-counter-label {
  font-size: 11px;
  letter-spacing: .03em;
  color: var(--tf-ink-3);
  white-space: nowrap;
}
.doc-counter-value {
  font-family: var(--tf-mono);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: .06em;
  color: var(--tf-ink);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.doc-counter-slash {
  margin: 0 2px;
  color: var(--tf-ink-4);
}
.saved-mark {
  margin-left: 1px;
  font-size: 11px;
  color: var(--tf-success);
  line-height: 1;
}
.btn-settings svg { color: var(--tf-ink-4); }
.btn-settings:hover svg { color: var(--tf-ink); }

/* 快捷区卡片 */
.shortcut-card {
  width: calc(100% - clamp(36px, 6vw, 68px));
  max-width: 1080px;
  margin: 20px auto 0;
  padding: 14px 20px;
  border: 1px solid var(--tf-line);
  border-radius: 14px;
  background: var(--tf-surface);
  box-shadow: var(--tf-shadow-xs);
  animation: tf-rise 380ms var(--tf-ease) both;
  animation-delay: 40ms;
}
.shortcut-grid {
  display: flex;
  align-items: stretch;
  gap: 0;
}
.shortcut-column {
  flex: 1;
  min-width: 0;
  padding: 1px 20px 1px 0;
}
.shortcut-column--divider {
  border-left: 1px solid var(--tf-line);
  padding-left: 20px;
  padding-right: 0;
}
.shortcut-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}
.shortcut-title {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .04em;
  color: var(--tf-ink);
}
.shortcut-hint {
  font-family: var(--tf-mono);
  font-size: 9.5px;
  letter-spacing: .04em;
  color: var(--tf-ink-3);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip-empty {
  font-size: 10.5px;
  color: var(--tf-ink-3);
}

/* 标签 chip：低饱和暖色 + 1px 墨色描边 */
.label-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid rgba(23,24,27,.2);
  box-shadow: none;
  color: var(--tf-ink);
  font-family: var(--font-sans, 'Geist', 'Inter', system-ui, sans-serif);
  font-size: 11.5px;
  font-weight: 500;
  line-height: 1.25;
  cursor: pointer;
  user-select: none;
  transition:
    transform 200ms var(--tf-ease),
    box-shadow 200ms var(--tf-ease),
    border-color 200ms var(--tf-ease);
}
.label-chip:hover {
  transform: translateY(-1px);
  border-color: rgba(23,24,27,.38);
  box-shadow: var(--tf-shadow-xs);
}
.label-chip:active { transform: scale(.985); }
.relation-chip {
  color: #FFFDF9;
  border-color: rgba(23,24,27,.24);
}
.relation-chip:hover { border-color: rgba(23,24,27,.5); }
.shortcut-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(255,255,255,.55);
  box-shadow: none;
  color: var(--tf-ink-2);
  font-family: var(--tf-mono);
  font-size: 9px;
  font-weight: 500;
  line-height: 1.3;
}
.shortcut-index--light {
  background: rgba(255,255,255,.16);
  color: rgba(255,253,249,.86);
}

/* 当前关系：细线行 + 衬线斜体箭头 */
.relation-manager {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--tf-line);
  display: flex;
  flex-direction: column;
  gap: 0;
}
.relation-manager-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 5px;
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .12em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
}
.relation-count {
  font-variant-numeric: tabular-nums;
  color: var(--tf-ink-3);
}
.relation-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 4px;
  border-radius: 0;
  border-bottom: 1px solid var(--tf-line);
  background: transparent;
}
.relation-row:last-child { border-bottom: none; }
.relation-route {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--tf-ink-2);
}
.relation-end {
  max-width: 11rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--tf-ink);
}
.relation-arrow {
  flex-shrink: 0;
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 16px;
  line-height: 1;
  color: var(--tf-signal-deep);
  font-weight: 400;
}
.relation-type-select {
  width: auto;
  min-width: 104px;
  max-width: 156px;
  height: 28px;
  padding: 0 24px 0 8px;
  font-size: 11px;
  border-radius: 7px;
  background-color: var(--tf-sunken);
  flex-shrink: 0;
}

/* ------------------------------------------------------------
   文本画布：居中纸张卡片
   ------------------------------------------------------------ */
.annotation-card {
  position: relative;
  width: calc(100% - clamp(36px, 6vw, 68px));
  max-width: 1080px;
  margin: 14px auto 44px;
  padding: 0;
  display: flex;
  flex-direction: column;
  flex: 1 0 auto;
  min-height: 420px;
  overflow: hidden;
  border: 1px solid var(--tf-line);
  border-radius: 22px;
  background: var(--tf-raised);
  box-shadow: var(--tf-shadow);
  animation: tf-rise 420ms var(--tf-ease) both;
  animation-delay: 80ms;
}

/* 文档 eyebrow：不参与字符测量，放在文本容器之外 */
.document-eyebrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  max-width: 72ch;
  margin: 0 auto;
  padding: 22px clamp(28px, 5vw, 64px) 12px;
  border-bottom: 1px solid var(--tf-line);
  font-family: var(--tf-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--tf-ink-3);
  font-variant-numeric: tabular-nums;
}
.eyebrow-brand {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
  white-space: nowrap;
}
.eyebrow-figures {
  color: var(--tf-ink-3);
  letter-spacing: .1em;
}
.eyebrow-slash {
  margin: 0 2px;
  color: var(--tf-ink-4);
}
.eyebrow-meta {
  display: inline-flex;
  align-items: baseline;
  gap: 7px;
  white-space: nowrap;
}
.eyebrow-divider { color: var(--tf-line-strong); }

/* 文本容器：覆盖内联内边距，保持字符 span 结构不变 */
.text-page .annotation-area {
  width: 100%;
  max-width: 72ch;
  margin: 0 auto;
  padding: 18px clamp(28px, 5vw, 64px) clamp(28px, 5vw, 64px) !important;
  background: transparent !important;
  color: var(--tf-ink-2);
  caret-color: var(--tf-signal);
  outline: none;
  scrollbar-width: thin;
}
.text-page .annotation-area:focus,
.text-page .annotation-area:focus-visible {
  /* 标注过程中不显示任何线框，保持干净的纸张画布 */
  outline: none !important;
  box-shadow: none !important;
  border-radius: 0;
}
.text-page .annotation-area::selection { background: rgba(228,87,46,.22); }
.text-page .annotation-area span::selection { background: rgba(228,87,46,.22); }

/* 高亮块：multiply 让文字保持清晰，透明感更接近 .3 */
.span-highlight {
  position: absolute;
  border-radius: 5px;
  mix-blend-mode: multiply;
  opacity: .62;
  cursor: pointer;
  outline-color: var(--tf-signal-deep) !important;
  outline-offset: 1px;
  transition:
    opacity 160ms var(--tf-ease),
    outline-color 160ms var(--tf-ease);
}
.span-highlight:hover { opacity: .82; }

/* 关系线层 */
.relation-layer {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  pointer-events: none;
  overflow: visible;
}
.relation-layer path { stroke-linecap: round; }
.relation-group {
  pointer-events: auto;
  cursor: pointer;
}
.relation-label {
  font-family: var(--tf-mono) !important;
  font-size: 10.5px !important;
  letter-spacing: .03em;
  paint-order: stroke;
  stroke: var(--tf-raised);
  stroke-width: 3px;
  stroke-linejoin: round;
  text-shadow: 0 1px 0 rgba(255,253,249,.9);
}

/* ------------------------------------------------------------
   选择浮层
   ------------------------------------------------------------ */
.picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 99;
  background: rgba(20,22,25,.38);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  pointer-events: none;
  animation: tf-fade 200ms var(--tf-ease) both;
}
.picker-card {
  position: fixed;
  inset: 0;
  width: min(440px, calc(100vw - 40px));
  max-width: 440px;
  height: fit-content;
  max-height: calc(100vh - 48px);
  margin: auto;
  padding: 22px;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px;
  overflow-y: auto;
  z-index: 100;
  transform: none;
  border: 1px solid var(--tf-line);
  border-radius: 22px;
  background: var(--tf-raised);
  box-shadow: var(--tf-shadow-lg);
  animation: tf-pop 220ms var(--tf-ease) both;
}
.picker-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  width: 100%;
  margin-bottom: 4px;
}
.picker-title {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: .01em;
  color: var(--tf-ink);
}
.picker-sub {
  font-family: var(--tf-display);
  font-style: italic;
  font-size: 13px;
  color: var(--tf-ink-3);
}
.picker-chip {
  font-size: 12px;
  padding: 6px 12px;
}
.picker-cancel {
  margin-left: auto;
  margin-top: 4px;
}

/* ------------------------------------------------------------
   动效与可见性
   ------------------------------------------------------------ */
@keyframes tf-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes tf-rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes tf-pop {
  from { opacity: 0; transform: scale(.985); }
  to { opacity: 1; transform: scale(1); }
}

/* ------------------------------------------------------------
   响应式：保持页面单一滚动容器，侧栏与工作区各自滚动
   ------------------------------------------------------------ */
@media (max-width: 1200px) {
  .sidebar { width: 300px; }
  .sidebar-module-title { padding-left: 16px; padding-right: 16px; }
  .sidebar-module-body { padding-left: 16px; padding-right: 16px; }
  .shortcut-card,
  .annotation-card { width: calc(100% - 40px); }
  .shortcut-column { padding-right: 14px; }
  .shortcut-column--divider { padding-left: 14px; }
}

@media (max-width: 900px) {
  .sidebar { width: 280px; }
  .doc-counter-label { display: none; }
  .shortcut-card { padding: 12px 14px; }
  .shortcut-column { padding-right: 12px; }
  .shortcut-column--divider { padding-left: 12px; }
  .document-eyebrow { letter-spacing: .08em; }
}

@media (max-width: 760px) {
  .text-page { flex-direction: column; }
  .sidebar {
    width: 100%;
    max-height: 46vh;
    overflow-y: auto;
    border-right: none;
    border-bottom: 1px solid var(--tf-line);
  }
  .sidebar-module-grow { flex: 0 0 auto; }
  .sidebar-module-flex { overflow: visible; }
  .doc-list { max-height: 220px; }
  .workspace { flex: 1; min-height: 0; }
  .shortcut-grid { flex-direction: column; gap: 12px; }
  .shortcut-column--divider {
    border-left: none;
    border-top: 1px solid var(--tf-line);
    padding-left: 0;
    padding-top: 12px;
  }
  .workspace-toolbar { align-items: flex-start; }
  .workspace-toolbar-actions { width: 100%; }
  .shortcut-card,
  .annotation-card { width: calc(100% - 28px); }
  .annotation-card { border-radius: 18px; }
  .document-eyebrow { flex-wrap: wrap; gap: 6px; }
}

/* 矮屏保底：让侧栏整体可滚动，避免前两个模块把文档列表挤出可视区 */
@media (max-height: 720px) {
  .sidebar { overflow-y: auto; }
  .sidebar-module-grow { flex: 0 0 auto; }
  .sidebar-module-flex { overflow: visible; }
  .doc-list { max-height: 260px; }
}


/* ============================================================
   三栏工作台布局：项目/标签栏 + 待标注对象列 + 文本画布
   ============================================================ */
.sidebar {
  width: 320px;
}

.sidebar-foot {
  flex-shrink: 0;
  margin-top: auto;
  padding: 18px 20px 22px;
  background: var(--tf-surface);
}
.sidebar-foot-eyebrow {
  display: block;
  font-family: var(--tf-mono);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: .16em;
  text-transform: uppercase;
  color: var(--tf-ink-4);
}
.sidebar-foot-text {
  margin: 8px 0 16px;
  font-size: 11px;
  line-height: 1.75;
  color: var(--tf-ink-3);
}
.sidebar-foot-text kbd {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid var(--tf-line);
  border-radius: 5px;
  background: var(--tf-sunken);
  font-family: var(--tf-mono);
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--tf-ink-2);
}
.sidebar-foot-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  font-size: 10px;
  color: var(--tf-ink-3);
}
.sidebar-foot-stats strong {
  font-family: var(--tf-mono);
  font-size: 12px;
  font-weight: 500;
  color: var(--tf-ink);
  font-variant-numeric: tabular-nums;
}

/* 工作台左列：待标注对象 */
.doc-panel {
  width: 248px;
  flex: 0 0 248px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--tf-paper-deep);
  border-right: 1px solid var(--tf-line);
  animation: tf-fade 320ms var(--tf-ease) both;
}
.doc-panel-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 18px 16px 10px;
  border-bottom: 1px solid var(--tf-line);
}
.doc-panel-heading {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.doc-panel-title {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  letter-spacing: .02em;
  color: var(--tf-ink);
  white-space: nowrap;
}
.doc-panel-count {
  flex-shrink: 0;
  font-family: var(--tf-mono);
  font-size: 10px;
  letter-spacing: .06em;
  color: var(--tf-ink-3);
  font-variant-numeric: tabular-nums;
}
.doc-panel-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 10px 8px;
  overflow: hidden;
}
.doc-panel .upload-card {
  gap: 8px;
  padding: 10px;
}
.doc-panel .upload-copy strong {
  font-size: 11.5px;
}
.doc-panel .upload-copy span {
  font-size: 10px;
  line-height: 1.4;
}
.doc-panel .upload-card-controls {
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.doc-panel .upload-card-actions {
  margin-left: 0;
  justify-content: space-between;
}
.doc-panel .segmentation-tabs {
  width: 100%;
}
.doc-panel .segmentation-tabs .tab-item {
  flex: 1;
  text-align: center;
}
.doc-panel .upload-bar-btn {
  flex: 1;
  justify-content: center;
}
.doc-panel .doc-list {
  padding: 0 0 4px;
}
.doc-panel .list-item {
  padding: 4px 8px 4px 10px;
  gap: 6px;
  font-size: 11.5px;
  line-height: 1.45;
  border-radius: 7px;
}
.doc-panel .doc-list {
  gap: 1px;
}
.doc-panel .list-item:hover {
  background: var(--tf-surface);
}
.doc-panel .count-badge {
  min-width: 20px;
  height: 18px;
  padding: 0 .3rem;
  font-size: 9px;
}
.doc-panel .status-dot {
  width: 6px;
  height: 6px;
}
.doc-panel-foot {
  flex-shrink: 0;
  padding: 10px 14px 12px;
  border-top: 1px solid var(--tf-line);
}
.doc-progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.doc-progress-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10px;
  letter-spacing: .04em;
  color: var(--tf-ink-3);
}
.doc-progress-label span:last-child {
  font-family: var(--tf-mono);
  color: var(--tf-ink-2);
  font-variant-numeric: tabular-nums;
}
.doc-progress-bar {
  display: block;
  height: 3px;
  border-radius: 999px;
  background: var(--tf-line);
  overflow: hidden;
}
.doc-progress-bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--tf-signal);
  transition: width 220ms var(--tf-ease);
}

/* 画布：压缩左右留白，扩大阅读宽度 */
.workspace-toolbar {
  padding-left: clamp(16px, 2.2vw, 28px);
  padding-right: clamp(16px, 2.2vw, 28px);
}
.shortcut-card,
.annotation-card {
  width: calc(100% - 32px);
  max-width: 1280px;
}
.shortcut-card {
  margin: 16px auto 0;
}
.annotation-card {
  margin: 12px auto 32px;
}
.document-eyebrow {
  max-width: 96ch;
  padding-left: clamp(20px, 3vw, 48px);
  padding-right: clamp(20px, 3vw, 48px);
}
.text-page .annotation-area {
  max-width: 96ch;
  padding: 18px clamp(20px, 3vw, 48px) clamp(28px, 4vw, 48px) !important;
}

/* 选中文本 / 实体后的内联操作提示（替代弹窗） */
.inline-picker-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 8px 12px;
  border: 1px solid #F0D2C6;
  border-radius: 9px;
  background: var(--tf-signal-soft);
  font-size: 11px;
  line-height: 1.5;
  color: var(--tf-signal-ink);
}
.inline-hint-dot {
  width: 6px;
  height: 6px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--tf-signal);
}
.inline-picker-hint kbd {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid #EBC3B4;
  border-radius: 5px;
  background: rgba(255, 255, 255, .55);
  font-family: var(--tf-mono);
  font-size: 9.5px;
  line-height: 1.5;
  color: var(--tf-signal-ink);
}
.inline-hint-cancel {
  margin-left: auto;
  padding: 2px 6px;
  border: none;
  background: transparent;
  color: var(--tf-signal-ink);
  font-family: inherit;
  font-size: 10px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.inline-hint-cancel:hover {
  color: var(--tf-ink);
}

@media (max-width: 1500px) {
  .sidebar { width: 300px; }
  .doc-panel { width: 236px; flex-basis: 236px; }
}
@media (max-width: 1280px) {
  .sidebar { width: 280px; }
  .doc-panel { width: 224px; flex-basis: 224px; }
  .document-eyebrow,
  .text-page .annotation-area { max-width: 88ch; }
}
@media (max-width: 1100px) {
  .text-page {
    flex-direction: column;
    height: auto;
    min-height: 100%;
    overflow: visible;
  }
  .sidebar {
    width: 100%;
    max-height: none;
    overflow-y: visible;
    border-right: none;
    border-bottom: 1px solid var(--tf-line);
  }
  .sidebar-foot {
    margin-top: 0;
    padding-bottom: 16px;
  }
  .doc-panel {
    width: 100%;
    flex: 0 0 auto;
    max-height: 340px;
    border-right: none;
    border-bottom: 1px solid var(--tf-line);
  }
  .doc-panel-body {
    min-height: 0;
  }
  .doc-panel .doc-list {
    max-height: 180px;
  }
  .workspace {
    flex: 1;
    min-height: 520px;
  }
  .shortcut-card,
  .annotation-card {
    width: calc(100% - 24px);
  }
}
@media (max-height: 720px) {
  .sidebar { overflow-y: auto; }
}

@media (prefers-reduced-motion: reduce) {
  .text-page *,
  .text-page *::before,
  .text-page *::after {
    animation-duration: .001ms !important;
    animation-delay: 0ms !important;
    transition-duration: .001ms !important;
  }
}
</style>
