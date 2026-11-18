<template>
  <div class="model-root"><div class="model-shell">
    <aside class="model-sidebar" :class="{ collapsed: sidebarCollapsed }">

      <div class="sidebar-history-container" :class="{ hidden: sidebarCollapsed }">
        <div class="sidebar-history-header">
          <span>历史记录</span>
          <button class="btn-refresh-history" @click.stop="fetchHistory" title="刷新历史记录">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" :class="{ spin: isHistoryLoading }">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
        </div>

        <button class="btn-new-task-sidebar" @click.stop="reset">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>新建任务</span>
        </button>

        <div class="sidebar-history-list">
          <div v-if="isHistoryLoading && historyRecords.length === 0" class="history-empty">
            加载中...
          </div>
          <div v-else-if="historyRecords.length === 0" class="history-empty">
            暂无历史记录
          </div>
          <div 
            v-else
            v-for="record in historyRecords" 
            :key="record.task_id" 
            class="history-item"
            :class="{ active: taskInfo.task_id === record.task_id }"
            @click="loadHistoryTask(record)"
          >
            <div class="history-item-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              </svg>
            </div>
            <div class="history-item-content">
              <div class="history-item-title" :title="record.file_name">{{ record.file_name }}</div>
              <div class="history-item-meta">
                <span class="history-item-time">{{ formatDate(record.created_at) }}</span>
                <span class="history-item-status" :class="record.status">
                  {{ record.status === 'completed' ? '已完成' : record.status === 'failed' ? '失败' : '处理中' }}
                </span>
              </div>
            </div>
            <button
              class="history-item-delete"
              @click.stop="pendingDeleteId = record.task_id"
              title="删除此记录"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      <!-- 模型管理入口按钮 -->
      <button class="nav-item nav-item-models" :class="{ active: currentPage === 'models' }" @click="currentPage = 'models'; wizardStep = 1" title="模型管理">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
          <path d="M12 2L2 7l10 5 10-5-10-5z" />
          <path d="M2 17l10 5 10-5" />
          <path d="M2 12l10 5 10-5" />
        </svg>
        <span class="nav-label">模型管理</span>
      </button>

      <div class="sidebar-footer">
        <div class="sidebar-version">v1.2.0</div>
      </div>
    </aside>

    <div class="model-main-wrap">
      <header class="model-header">
        <div class="header-left">
          <button class="header-menu-btn" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? '展开侧边栏' : '折叠侧边栏'" aria-label="切换侧边栏">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div class="header-breadcrumb">
            <button class="breadcrumb-tab" :class="{ active: currentPage === 'console' }" @click="currentPage = 'console'">系统控制台</button>
            <button class="breadcrumb-tab" :class="{ active: currentPage === 'models' }" @click="currentPage = 'models'">模型管理</button>
          </div>
        </div>
        <div class="header-right">
          <div v-if="taskInfo.task_id" class="header-task-id">
            <span class="task-id-label">任务</span>
            <code class="task-id-value">{{ taskInfo.file_name }}</code>
          </div>
          <div class="header-status-pill" :class="taskInfo.status">
            <span class="model-status-dot"></span>
            <span>{{ statusText }}</span>
          </div>
        </div>
      </header>

      <!-- Wizard Bar -->
      <div v-if="currentPage === 'console'" class="wizard-bar">
        <div
          v-for="(step, idx) in wizardSteps"
          :key="step.key"
          class="wizard-step"
          :class="{
            active: wizardStep === idx + 1,
            done: wizardStep > idx + 1
          }"
        >
          <div class="wstep-circle">
            <svg v-if="wizardStep > idx + 1" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" width="14" height="14">
              <polyline points="20 6 9 17 4 12" />
            </svg>
            <span v-else>{{ idx + 1 }}</span>
          </div>
          <span class="wstep-label">{{ step.label }}</span>
          <div v-if="idx < wizardSteps.length - 1" class="wstep-connector">
            <div class="wstep-connector-fill" :style="{ width: wizardStep > idx + 1 ? '100%' : '0%' }"></div>
          </div>
        </div>
      </div>

      <main class="model-main" v-if="currentPage === 'console'">
        <!-- Step 1-5 content unchanged -->

        <!-- Step 1: Upload -->
        <section v-if="wizardStep === 1" class="step-view step-upload">
          <div class="step-hero">
            <h2 class="step-title">上传文档</h2>
            <p class="step-desc">支持 PDF、PNG、JPG 格式，拖拽或点击选择文件，最大 50MB</p>
          </div>
          <div class="upload-center">
            <div
              class="drop-zone"
              :class="{ 'drag-over': isDragOver, 'has-file': selectedFile }"
              @dragover.prevent="isDragOver = true"
              @dragleave.prevent="isDragOver = false"
              @drop.prevent="onDrop"
              @click="!selectedFile && openFilePicker()"
            >
              <transition name="fade-scale" mode="out-in">
                <div v-if="!selectedFile" key="empty" class="drop-zone-inner">
                  <div class="drop-icon-ring">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                  </div>
                  <p class="drop-title">拖拽文件到此处</p>
                  <p class="drop-subtitle">或点击选择文件</p>
                  <div class="drop-formats">
                    <span class="format-badge">PDF</span>
                    <span class="format-badge">PNG</span>
                    <span class="format-badge">JPG</span>
                  </div>
                  <p class="drop-hint">最大 50MB</p>
                </div>
                <div v-else key="file" class="drop-zone-file-preview">
                  <div class="file-preview-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                  </div>
                  <p class="drop-file-name">{{ selectedFile.name }}</p>
                  <p class="drop-file-size">{{ formatSize(selectedFile.size) }}</p>
                  <button class="drop-file-remove" @click.stop="clearFile" title="移除文件">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </div>
              </transition>
            </div>
            <input ref="fileInput" type="file" class="hidden-input" accept=".pdf,.png,.jpg,.jpeg" @change="handleFileChange" />
            <button class="model-btn-primary btn-next" :disabled="!selectedFile" @click="wizardStep = 2">
              下一步：配置参数
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="18" height="18">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </button>
          </div>
        </section>

        <!-- Step 2: Configure -->
        <section v-else-if="wizardStep === 2" class="step-view step-config">
          <div class="step-hero">
            <h2 class="step-title">配置解析参数</h2>
            <p class="step-desc">选择后端引擎、语言策略与功能开关，完成后点击开始解析</p>
          </div>
          <div class="config-layout">
            <div class="config-card card-glass">
              <div class="config-section">
                <h4 class="config-label">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" />
                  </svg>
                  后端引擎
                </h4>
                <div class="radio-grid">
                  <label
                    v-for="item in availableOptions.backend_types"
                    :key="item.value"
                    class="radio-card"
                    :class="{ active: parseConfig.backend_type === item.value }"
                  >
                    <input v-model="parseConfig.backend_type" type="radio" :value="item.value" />
                    <div class="radio-content">
                      <span class="radio-title">{{ item.label }}</span>
                      <span class="radio-desc">{{ item.description }}</span>
                    </div>
                    <div class="radio-check" v-if="parseConfig.backend_type === item.value">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" width="14" height="14">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                  </label>
                </div>
              </div>

              <div class="config-row">
                <div class="config-section config-half">
                  <h4 class="config-label">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <circle cx="12" cy="12" r="10" /><path d="M2 12h20" />
                      <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
                    </svg>
                    语言
                  </h4>
                  <select v-model="parseConfig.language" class="select-field">
                    <option v-for="item in availableOptions.languages" :key="item.value" :value="item.value">{{ item.label }}</option>
                  </select>
                </div>
                <div class="config-section config-half">
                  <h4 class="config-label">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <rect x="2" y="2" width="20" height="20" rx="2.18" />
                      <line x1="7" y1="2" x2="7" y2="22" /><line x1="17" y1="2" x2="17" y2="22" /><line x1="2" y1="12" x2="22" y2="12" />
                    </svg>
                    OCR 模式
                  </h4>
                  <select v-model="parseConfig.ocr_mode" class="select-field">
                    <option v-for="item in availableOptions.ocr_modes" :key="item.value" :value="item.value">{{ item.label }}</option>
                  </select>
                </div>
              </div>

              <div class="config-section">
                <h4 class="config-label">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
                    <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
                  </svg>
                  功能开关
                </h4>
                <div class="toggle-grid">
                  <label v-for="item in availableOptions.feature_toggles" :key="item.key" class="toggle-card">
                    <div class="toggle-content">
                      <span class="toggle-title">{{ item.label }}</span>
                      <span class="toggle-desc">{{ item.description }}</span>
                    </div>
                    <div class="toggle-switch-wrap">
                      <input v-model="parseConfig[item.key]" type="checkbox" class="toggle-switch" />
                      <span class="toggle-track"></span>
                    </div>
                  </label>
                </div>
              </div>

              <div class="config-preview">
                <div class="preview-header">
                  <span class="preview-label">当前参数预览</span>
                  <span class="preview-count">{{ configPreviewTags.length }} 项</span>
                </div>
                <div class="preview-tags">
                  <span v-for="tag in configPreviewTags" :key="tag" class="preview-tag">{{ tag }}</span>
                </div>
              </div>

              <div class="config-actions">
                <button class="btn-secondary" @click="wizardStep = 1">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                    <polyline points="15 18 9 12 15 6" />
                  </svg>
                  上一步
                </button>
                <button class="model-btn-primary btn-start" :disabled="isUploading" @click="uploadFile">
                  <svg v-if="!isUploading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="18" height="18" class="spin">
                    <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                    <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                  </svg>
                  {{ isUploading ? '上传中...' : '开始解析' }}
                </button>
              </div>
            </div>
          </div>
        </section>

        <!-- Step 3: Processing -->
        <section v-else-if="wizardStep === 3" class="step-view step-processing" aria-live="polite" aria-label="文档解析进度">
          <div class="processing-card card-glass">
            <div class="processing-header">
              <div class="processing-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="32" height="32" class="spin">
                  <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                  <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                </svg>
              </div>
              <div>
                <h2>正在解析文档</h2>
                <p class="processing-filename">{{ taskInfo.file_name }}</p>
              </div>
            </div>

            <div class="feature-tags-row">
              <span v-for="tag in taskInfo.feature_summary || []" :key="tag" class="feature-tag">{{ tag }}</span>
            </div>

            <div class="stepper">
              <div
                v-for="(stage, idx) in stages"
                :key="stage.label"
                class="step"
                :class="{ active: idx === currentStage, done: idx < currentStage }"
              >
                <div class="step-circle">
                  <svg v-if="idx < currentStage" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" width="14" height="14">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  <span v-else>{{ idx + 1 }}</span>
                </div>
                <span class="step-label">{{ stage.label }}</span>
              </div>
            </div>

            <div class="progress-section">
              <div class="progress-bar-wrap">
                <div class="progress-bubble" :style="{ left: `clamp(20px, ${taskInfo.progress}%, calc(100% - 20px))` }">
                  <span>{{ taskInfo.progress }}%</span>
                </div>
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: `${taskInfo.progress}%` }">
                    <div class="progress-shine"></div>
                  </div>
                </div>
              </div>
            </div>

            <div class="processing-stats">
              <div class="model-stat-item">
                <span class="stat-value">{{ formatDuration(elapsed) }}</span>
                <span class="model-stat-label">已用时间</span>
              </div>
              <div class="stat-divider"></div>
              <div class="model-stat-item">
                <span class="stat-value">{{ taskInfo.progress }}%</span>
                <span class="model-stat-label">完成进度</span>
              </div>
              <div class="stat-divider"></div>
              <div class="model-stat-item">
                <span class="stat-value">{{ estimatedRemaining }}</span>
                <span class="model-stat-label">预计剩余</span>
              </div>
            </div>
            <div class="processing-message">
              <div class="processing-stage">{{ taskInfo.stage_label || stages[currentStage].label }}</div>
              <p>{{ taskInfo.message || '正在处理中...' }}</p>
            </div>
          </div>
        </section>

        <!-- Step 4: Results -->
        <section v-else-if="wizardStep === 4" class="step-view step-results">
          <div class="result-top-bar">
            <div class="result-info">
              <h2 class="result-filename">{{ taskInfo.file_name || selectedFile?.name || '解析结果' }}</h2>
              <div class="result-params">
                <span v-for="tag in taskInfo.feature_summary || []" :key="tag" class="param-badge">{{ tag }}</span>
              </div>
            </div>
          </div>

            <div class="toolbar">
              <div class="toolbar-left">
                <div class="tool-group">
                  <button class="tool-btn" :class="{ active: splitMode === 'horizontal' }" @click="splitMode = 'horizontal'" title="左右分栏" aria-label="左右分栏布局">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <rect x="3" y="3" width="8" height="18" rx="1" /><rect x="13" y="3" width="8" height="18" rx="1" />
                    </svg>
                  </button>
                  <button class="tool-btn" :class="{ active: splitMode === 'vertical' }" @click="splitMode = 'vertical'" title="上下分栏" aria-label="上下分栏布局">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <rect x="3" y="3" width="18" height="8" rx="1" /><rect x="3" y="13" width="18" height="8" rx="1" />
                    </svg>
                  </button>
                </div>
              </div>
              <div class="toolbar-right">
                <button class="tool-btn" :class="{ active: pdfFullscreen }" @click="pdfFullscreen = !pdfFullscreen" title="PDF 全屏">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                </button>
                <button class="tool-btn" :class="{ active: mdFullscreen }" @click="mdFullscreen = !mdFullscreen" title="Markdown 全屏">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                </button>
                <button class="tool-btn" @click="copyMarkdown" title="复制 Markdown">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
                <template v-if="isEditing">
                  <button class="tool-btn btn-save" :disabled="isSaving" @click="saveEdit" title="保存修改">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
                      <polyline points="17 21 17 13 7 13 7 21" /><polyline points="7 3 7 8 15 8" />
                    </svg>
                  </button>
                  <button class="tool-btn btn-cancel-edit" @click="cancelEdit" title="取消编辑">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                    </svg>
                  </button>
                </template>
                <button v-else class="tool-btn btn-edit" @click="startEdit" title="编辑 Markdown">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                  </svg>
                </button>
                <span class="tool-sep"></span>
                <button class="model-btn-primary btn-mark-cta" :disabled="taskInfo.status !== 'completed'" @click="navigateToStep(5)" title="进入快速标注">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M5 4h10l4 4v12H5z" />
                    <path d="M9 12h6M9 16h4M15 4v4h4" />
                  </svg>
                  <span>快速标注</span>
                </button>
              </div>
            </div>

            <div
              class="panels-container"
              :class="[splitMode, { 'pdf-fullscreen': pdfFullscreen, 'md-fullscreen': mdFullscreen }]"
            >
              <div v-show="!mdFullscreen" class="panel panel-pdf">
                <div class="panel-header" @dblclick="pdfFullscreen = !pdfFullscreen">
                  <div class="panel-header-left">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                    <span>Layout PDF</span>
                  </div>
                  <div class="panel-header-right">
                    <span v-if="pdfLoadError" class="pdf-status-error">加载失败</span>
                    <span v-else-if="pdfLoading" class="pdf-status-loading">加载中...</span>
                    <span class="panel-hint">双击全屏</span>
                  </div>
                </div>
                <div class="panel-body" :class="{ 'has-error': pdfLoadError }">
                  <div v-if="pdfLoadError" class="panel-error-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <p class="panel-error-title">PDF 无法加载</p>
                    <p class="panel-error-desc">后端尚未生成布局 PDF 文件，请确认处理已完成。</p>
                    <button class="btn-retry" @click="retryLoadPdf">重新加载</button>
                  </div>
                  <iframe v-else :src="pdfUrl" class="pdf-iframe" frameborder="0" @load="onPdfLoad" @error="onPdfError"></iframe>
                </div>
              </div>

              <div v-show="!pdfFullscreen && !mdFullscreen" class="panel-divider" @mousedown="startResize">
                <div class="divider-handle"></div>
              </div>

              <div v-show="!pdfFullscreen" class="panel panel-md">
                <div class="panel-header" @dblclick="mdFullscreen = !mdFullscreen">
                  <div class="panel-header-left">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                    <span>Markdown 结果</span>
                  </div>
                  <div class="panel-header-right">
                    <span class="word-count">{{ wordCount }} 字</span>
                    <span class="panel-hint">双击全屏</span>
                  </div>
                </div>
                <div class="panel-body md-body" ref="mdBodyRef">
                  <div v-if="mdLoadError" class="panel-error-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <p class="panel-error-title">Markdown 加载失败</p>
                    <p class="panel-error-desc">无法获取解析结果，请检查后端服务是否正常运行。</p>
                    <button class="btn-retry" @click="retryLoadMd">重新加载</button>
                  </div>
                  <div v-else-if="mdLoading" class="panel-loading-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="32" height="32" class="spin">
                      <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                    </svg>
                    <p>正在加载解析结果...</p>
                  </div>
                  <div v-else class="md-content-wrap review-md-content">
                    <div
                      :key="mdViewKey"
                      v-html="renderedMarkdown"
                      :contenteditable="isEditing"
                      ref="editableRef"
                      spellcheck="false"
                      :class="{ 'md-editing': isEditing }"
                    ></div>
                  </div>
                </div>
              </div>
            </div>

        </section>

        <!-- Step 5: Quick Annotation -->
        <section v-else-if="wizardStep === 5" class="step-view step-annotation">
          <div class="annotation-workspace-toolbar">
            <div class="annotation-workspace-copy">
              <div class="annotation-workspace-kicker">快速标注</div>
              <div class="annotation-workspace-status-row">
                <span class="annotation-status-pill">{{ annotationUpdatedText }}</span>
                <span class="annotation-workspace-tip">仅分析最近保存的 Markdown，不显示 PDF</span>
              </div>
            </div>
            <div class="annotation-workspace-actions">
              <button class="tool-btn" @click="copyMarkdown" title="复制 Markdown">
                复制 MD
              </button>
              <button
                class="tool-btn"
                :disabled="exportLoading || annotationLoading || modelAnnotationLoading || (!selectedAnnotationRules.length && !(selectedPersistentModelId && modelAnnotationLastRunAt))"
                @click="exportAnnotations"
                title="导出当前规则+模型标注结果为 JSONL"
              >
                {{ exportLoading ? '导出中...' : '导出标注' }}
              </button>
            </div>
          </div>

          <div class="annotation-workspace-body">
            <aside class="annotation-sidebar">
              <div class="annotation-card">
                <div class="annotation-card-tabs">
                  <button class="annotation-card-tab" :class="{ active: annotationMode === 'rules' }" @click="annotationMode = 'rules'">规则标注</button>
                  <button class="annotation-card-tab" :class="{ active: annotationMode === 'model' }" @click="annotationMode = 'model'; fetchSavedModels()">模型标注</button>
                </div>
                <div v-if="annotationMode === 'rules'">
                <div class="annotation-card-header">
                  <div>
                    <div class="annotation-title">标注规则</div>
                    <p class="annotation-desc">勾选规则后点击启动标注，使用导航浏览命中片段。</p>
                  </div>
                </div>

                <div class="annotation-utility-row">
                  <button class="annotation-utility-btn" @click="selectAllAnnotationRules">全选规则</button>
                  <button class="annotation-utility-btn" @click="clearAnnotationRules">清空选择</button>
                </div>

                <div class="annotation-settings-section">
                  <button class="annotation-settings-toggle" @click="annotationSettingsExpanded = !annotationSettingsExpanded">
                    <svg class="annotation-settings-chevron" :class="{ expanded: annotationSettingsExpanded }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                    <span>规则标注参数设置</span>
                  </button>
                  <div v-show="annotationSettingsExpanded" class="annotation-rule-list">
                    <label v-for="rule in annotationRules" :key="rule.id" class="annotation-rule-item">
                      <input v-model="selectedAnnotationRules" type="checkbox" :value="rule.id" />
                      <div class="annotation-rule-content">
                        <div class="annotation-rule-top">
                          <span class="annotation-rule-label">{{ rule.label }}</span>
                          <span class="annotation-rule-count">{{ getRuleCount(rule.id) }}</span>
                        </div>
                        <p class="annotation-rule-desc">{{ rule.description }}</p>
                      </div>
                    </label>
                  </div>
                </div>

                <button
                  class="btn-start-annotation"
                  :disabled="annotationLoading || !selectedAnnotationRules.length"
                  @click="fetchAnnotations"
                >
                  <svg v-if="annotationLoading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" class="spin">
                    <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                    <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <span>{{ annotationLoading ? '标注中...' : '启动标注' }}</span>
                </button>

                <div v-if="annotationLoading" class="annotation-empty-state">
                  正在分析 Markdown 中的有效信息...
                </div>
                <div v-else-if="annotationError" class="annotation-empty-state error">
                  {{ annotationError }}
                </div>
                <div v-else-if="!annotationLastRunAt && !annotationSnippets.length" class="annotation-empty-state">
                  请选择规则后点击「启动标注」。
                </div>
                <div v-else-if="annotationLastRunAt && !annotationSnippets.length" class="annotation-empty-state">
                  当前规则下暂无明显命中内容。
                </div>
                </div>

                <!-- Model Annotation Panel -->
                <div v-else-if="annotationMode === 'model'" class="annotation-model-panel">
                  <div class="annotation-model-section">
                    <label class="annotation-model-label">持久模型</label>
                    <select v-model="selectedPersistentModelId" class="select-field">
                      <option value="">-- 选择已训练模型 --</option>
                      <option v-for="m in savedModels" :key="m.model_id" :value="m.model_id">{{ m.model_name }} ({{ (m.entity_labels || m.labels || []).length }} 标签)</option>
                    </select>
                  </div>
                  <!-- 置信度控件：选择模型后即可见，标注前即可调整阈值 -->
                  <div class="conf-slider-card" v-if="selectedPersistentModelId">
                    <div class="conf-slider-card-header">
                      <span class="conf-slider-card-title">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                          <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
                        </svg>
                        置信度阈值
                      </span>
                      <span class="conf-slider-badge" :class="{ 'conf-badge-high': modelConfThreshold >= 70, 'conf-badge-mid': modelConfThreshold >= 40, 'conf-badge-low': modelConfThreshold < 40 }">≥ {{ modelConfThreshold }}%</span>
                    </div>
                    <div class="conf-slider-track-wrap">
                      <div class="conf-slider-gradient" :style="{ '--conf-pct': modelConfThreshold + '%' }">
                        <div class="conf-slider-gradient-fill"></div>
                      </div>
                      <input type="range" v-model.number="modelConfThreshold" min="0" max="100" step="5" class="conf-slider" />
                    </div>
                    <div class="conf-slider-presets">
                      <button v-for="pct in [25, 50, 70, 90]" :key="pct" class="conf-preset-btn" :class="{ active: modelConfThreshold === pct }" @click="modelConfThreshold = pct">{{ pct }}%</button>
                    </div>
                  </div>
                  <button class="btn-start-annotation" style="background: var(--color-accent);" :disabled="modelAnnotationLoading || !selectedPersistentModelId" @click="runModelInference">
                    <svg v-if="modelAnnotationLoading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14" class="spin"><circle cx="12" cy="12" r="10" stroke-opacity="0.2" /><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" /></svg>
                    <span>{{ modelAnnotationLoading ? '推理中...' : '执行模型标注' }}</span>
                  </button>
                </div>
              </div>
            </aside>

            <div class="annotation-preview-area">
              <aside class="annotation-snippet-column" v-if="annotationSnippets.length && !annotationLoading">
                <div class="snippet-column-header">
                  <div class="snippet-column-header-left">
                    <span class="snippet-column-title">命中片段</span>
                    <span class="snippet-column-count">{{ annotationSnippets.length }}</span>
                  </div>
                  <div class="snippet-column-nav">
                    <button class="snippet-column-nav-btn" title="上一段" @click="goToPrevSnippet" :disabled="currentSnippetIndex <= 0">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polyline points="15 18 9 12 15 6" />
                      </svg>
                    </button>
                    <span class="snippet-column-position">{{ currentSnippetIndex + 1 }}/{{ annotationSnippets.length }}</span>
                    <button class="snippet-column-nav-btn" title="下一段" @click="goToNextSnippet" :disabled="currentSnippetIndex >= annotationSnippets.length - 1">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div class="snippet-column-list">
                  <button
                    v-for="(entry, idx) in annotationSnippets"
                    :key="entry.id || idx"
                    class="annotation-snippet-card"
                    :class="{ active: idx === currentSnippetIndex }"
                    :data-entity-id="entry.id"
                    @click="goToSnippet(idx)"
                  >
                    <div class="annotation-snippet-head">
                      <span class="snippet-color-bar" :style="{ background: getSnippetColor(entry) }"></span>
                      <span class="annotation-snippet-rule">{{ entry.rule_label }}</span>
                      <span class="annotation-snippet-idx">{{ idx + 1 }}</span>
                      <span v-if="entry._sources?.includes('rule')" class="snippet-source-tag source-rule" title="来自规则标注">R</span>
                      <span v-if="entry._sources?.includes('model')" class="snippet-source-tag source-model" title="来自模型标注">M</span>
                      <span v-if="entry._sources?.includes('model') && entry.confidence != null" class="snippet-conf-badge" :class="{ 'conf-high': entry.confidence >= 0.7, 'conf-mid': entry.confidence >= 0.4, 'conf-low': true }">{{ (entry.confidence * 100).toFixed(0) }}%</span>
                    </div>
                    <p class="annotation-snippet-text">{{ entry.text }}</p>
                    <p v-if="entry.context" class="annotation-snippet-context">{{ truncateContext(entry.context, 80) }}</p>
                    <div v-if="entry.tags?.length" class="annotation-snippet-tags">
                      <span v-for="tag in entry.tags" :key="tag" class="annotation-tag">{{ tag }}</span>
                    </div>
                  </button>
                </div>
              </aside>

              <div v-else class="annotation-snippet-column-empty">
                <div class="annotation-empty-state">
                  {{ annotationLoading ? '正在分析 Markdown 中的有效信息...' : selectedAnnotationRules.length ? '当前规则下暂无明显命中内容。' : '请先选择至少一个标注规则。' }}
                </div>
              </div>

              <section class="annotation-preview-panel">
                <div class="panel-header annotation-preview-header">
                  <div class="panel-header-left">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                    <span>Markdown 标注预览</span>
                  </div>
                  <div class="panel-header-right">
                    <span class="word-count">{{ wordCount }} 字</span>
                    <span v-if="annotationCounts.entries || annotationCounts.snippets" class="panel-hint">
                      命中 {{ annotationCounts.entries || annotationCounts.snippets }} 段 &middot; 高亮 {{ annotationCounts.entities }} 实体
                    </span>
                  </div>
                </div>
                <div class="panel-body md-body annotation-preview-body" ref="mdBodyRef">
                  <div v-if="annotationScanActive" class="annotation-scan-line" :style="{ top: scanLineY + 'px' }"><span class="annotation-scan-cursor"></span></div>
                  <div v-if="mdLoadError" class="panel-error-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <p class="panel-error-title">Markdown 加载失败</p>
                    <p class="panel-error-desc">无法获取解析结果，请检查后端服务是否正常运行。</p>
                    <button class="btn-retry" @click="retryLoadMd">重新加载</button>
                  </div>
                  <div v-else-if="mdLoading" class="panel-loading-state">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="32" height="32" class="spin">
                      <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                    </svg>
                    <p>正在加载解析结果...</p>
                  </div>
                  <div v-else class="md-content-wrap annotation-md-content">
                    <div :key="mdViewKey" v-html="renderedMarkdown"></div>
                  </div>
                </div>
              </section>
            </div>
          </div>

          <div class="step-bottom-nav step-bottom-nav--annotation">
            <button class="btn-secondary" @click="navigateToStep(4)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="16" height="16">
                <polyline points="15 18 9 12 15 6" />
              </svg>
              上一步：返回校对
            </button>
            <span class="step-nav-hint">修改 MD 后返回此步骤将重新分析</span>
          </div>
        </section>
      </main>

      <!-- Model Management Page -->
      <main class="model-main" v-else>
        <section class="step-view step-models">
          <div class="models-split-layout">
            <!-- ===== 左侧面板：已训练模型列表 ===== -->
            <div class="models-left-panel">
              <div class="models-left-header">
                <h3 class="models-left-title">已训练模型</h3>
                <span class="models-left-count" v-if="!modelsLoading">{{ savedModels.length }} 个</span>
              </div>
              <div class="models-left-body">
                <div v-if="modelsLoading" class="models-empty">加载中...</div>
                <div v-else-if="!savedModels.length" class="models-empty">暂无已训练的模型</div>
                <div v-else class="models-card-list">
                  <div v-for="model in savedModels" :key="model.model_id" class="models-card" :class="{ 'models-card-selected': selectedModelId === model.model_id }" @click="viewModelDetail(model.model_id)">
                    <div class="models-card-top">
                      <span class="model-name-cell">{{ model.model_name }}</span>
                      <span class="models-card-count">{{ model.example_count || 0 }} 示例</span>
                    </div>
                    <div class="models-card-tags">
                      <span v-for="label in (model.entity_labels || model.labels || [])" :key="label" class="model-label-badge">{{ label }}</span>
                    </div>
                    <div class="models-card-bottom">
                      <span class="model-time-cell">{{ model.created_at || '--' }}</span>
                      <div class="model-actions-cell">
                        <button class="model-btn-sm btn-download" @click.stop="downloadModel(model.model_id)">下载</button>
                        <button class="model-btn-sm btn-danger-text" @click.stop="deleteModelConfirmId = model.model_id">删除</button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- ===== 右侧面板：训练新模型 ===== -->
            <div class="models-right-panel">
              <div class="models-right-header" style="gap:8px;">
                <button class="models-tab-btn" :class="{ active: modelsSubTab === 'train' }" @click="modelsSubTab = 'train'; selectedModelId = null">模型训练</button>
                <button class="models-tab-btn" :class="{ active: modelsSubTab === 'eval' }" @click="modelsSubTab = 'eval'; selectedModelId = null">模型评价</button>
              </div>
              <div class="models-right-body">

                <!-- TAB: 模型训练 -->
                <template v-if="modelsSubTab === 'train' && !selectedModelId">

                <!-- 训练表单 -->
                <div v-if="!isTraining" class="train-form-section">
                <!-- 训练数据集 + 模型名称 -->
                <div class="dataset-section">
                  <div class="dataset-section-head">
                    <div>
                      <div class="dataset-section-title">训练数据集</div>
                      <p class="dataset-section-desc">上传后自动入库，可多选合并训练</p>
                    </div>
                    <div class="dataset-summary-pill" v-if="datasets.length">
                      {{ datasets.length }} 个数据集 · {{ allDatasetSampleCount }} 样本 · {{ allDatasetLabelCount }} 类别
                    </div>
                  </div>

                  <label
                    class="dataset-upload-zone"
                    :class="{ 'is-uploading': datasetUploading }"
                    @click="!datasetUploading && !isTraining && datasetFileInput?.click()"
                    @dragover.prevent
                    @drop.prevent="onDatasetDrop"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                      <polyline points="17 8 12 3 7 8" />
                      <line x1="12" y1="3" x2="12" y2="15" />
                    </svg>
                    <span>{{ datasetUploading ? '正在解析并上传数据集...' : '点击或拖拽上传 JSONL 数据集' }}</span>
                  </label>
                  <input ref="datasetFileInput" type="file" class="hidden-input" accept=".jsonl,.json" @change="onDatasetFileChange" />

                  <div v-if="datasetsLoading" class="dataset-empty">正在加载数据集...</div>
                  <div v-else-if="!datasets.length" class="dataset-empty">暂无数据集，请先上传</div>
                  <div v-else class="dataset-list">
                    <div
                      v-for="dataset in datasets"
                      :key="dataset.dataset_id"
                      class="dataset-card"
                      :class="{ 'is-selected': selectedDatasetIds.includes(dataset.dataset_id) }"
                    >
                      <div class="dataset-card-main">
                        <label class="dataset-check" @click.stop>
                          <input v-model="selectedDatasetIds" type="checkbox" :value="dataset.dataset_id" :disabled="isTraining" />
                        </label>
                        <div class="dataset-card-info">
                          <div class="dataset-card-title-row">
                            <span class="dataset-card-name" :title="dataset.name">{{ dataset.name }}</span>
                            <span class="dataset-card-meta">
                              {{ dataset.sample_count }} 样本 · {{ dataset.entity_count }} 实体 · {{ dataset.label_count }} 类别
                            </span>
                          </div>
                          <div class="dataset-card-time">{{ dataset.uploaded_at }}</div>
                          <div class="dataset-label-chips" v-if="dataset.label_count">
                            <span v-for="[label, count] in getDatasetLabelEntries(dataset).slice(0, 6)" :key="label" class="dataset-label-chip">
                              {{ label }} <b>{{ count }}</b>
                            </span>
                            <span v-if="dataset.label_count > 6" class="dataset-label-chip dataset-label-more">+{{ dataset.label_count - 6 }}</span>
                          </div>
                        </div>
                        <div class="dataset-card-actions">
                          <button class="model-btn-sm" @click.stop="toggleDatasetStats(dataset.dataset_id)">
                            {{ expandedDatasetId === dataset.dataset_id ? '收起' : '统计' }}
                          </button>
                          <button class="model-btn-sm btn-danger-text" :disabled="isTraining" @click.stop="deleteDataset(dataset.dataset_id)">删除</button>
                        </div>
                      </div>

                      <div v-if="expandedDatasetId === dataset.dataset_id" class="dataset-stats-panel">
                        <div class="dataset-stat-grid">
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.sample_count }}</span>
                            <span class="dataset-stat-label">样本数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.entity_count }}</span>
                            <span class="dataset-stat-label">实体数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ dataset.label_count }}</span>
                            <span class="dataset-stat-label">类别数</span>
                          </div>
                          <div class="dataset-stat-block">
                            <span class="dataset-stat-value">{{ formatNumber(dataset.char_count) }}</span>
                            <span class="dataset-stat-label">总字数</span>
                          </div>
                        </div>
                        <div class="dataset-label-bars">
                          <div v-for="[label, count] in getDatasetLabelEntries(dataset)" :key="label" class="dataset-label-bar-row">
                            <span class="dataset-label-bar-name" :title="label">{{ label }}</span>
                            <div class="dataset-label-bar-track">
                              <div class="dataset-label-bar-fill" :style="{ width: getDatasetLabelPct(dataset, count) + '%' }"></div>
                            </div>
                            <span class="dataset-label-bar-count">{{ count }}</span>
                          </div>
                        </div>
                        <div class="dataset-stats-foot" v-if="dataset.unlabeled_sample_count">
                          无标注样本：{{ dataset.unlabeled_sample_count }} 条
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div class="train-name-row">
                  <label class="config-label">模型名称</label>
                  <input v-model="trainModelName" class="select-field" placeholder="输入模型名称" :disabled="isTraining" />
                </div>

                <!-- 第二行：超参数网格 -->
                <div class="train-params-grid">
                  <div class="train-param-item">
                    <label class="config-label">Epochs</label>
                    <input v-model.number="trainEpochs" class="select-field" type="number" min="1" max="50" :disabled="isTraining" />
                  </div>
                  <div class="train-param-item">
                    <label class="config-label">Batch Size</label>
                    <input v-model.number="trainBatchSize" class="select-field" type="number" min="2" max="64" :disabled="isTraining" />
                  </div>
                  <div class="train-param-item">
                    <label class="config-label">Learning Rate</label>
                    <input v-model.number="trainLearningRate" class="select-field" type="number" step="0.00001" min="1e-6" max="0.1" :disabled="isTraining" />
                  </div>
                </div>

                <!-- 开始训练按钮 -->
                <div class="train-actions">
                  <button
                    class="btn-train-start"
                    :disabled="isTraining || !selectedDatasetIds.length || !trainModelName.trim()"
                    @click="trainFromDatasets"
                  >
                    <svg v-if="isTraining" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18" class="spin">
                      <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                      <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                    </svg>
                    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                    {{ isTraining ? '训练中...' : '开始训练' }}
                  </button>
                </div>

                </div>

                <!-- 可视化区域（始终占位，预训练时灰色占位，训练中显示真实图表） -->
                <div class="train-progress-area">
                  <template v-if="isTraining">
                    <!-- 训练中：真实进度和图表 -->
                    <div class="train-progress-header">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20" class="spin">
                        <circle cx="12" cy="12" r="10" stroke-opacity="0.2" />
                        <path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                      </svg>
                      <span class="train-progress-title">正在训练模型...</span>
                    </div>
                    <p class="train-status-msg">{{ trainStatusMsg }}</p>
                    <div v-if="trainProgress?.val_loss != null" class="train-val-bar">
                      <span class="train-val-label">验证集</span>
                      <span class="train-val-metric">Loss {{ Number(trainProgress.val_loss).toFixed(4) }}</span>
                      <span class="train-val-sep">|</span>
                      <span class="train-val-metric">Acc {{ (Number(trainProgress.val_accuracy) * 100).toFixed(1) }}%</span>
                    </div>
                    <div class="train-progress-bar-wrap">
                      <div class="train-progress-bar">
                        <div class="train-progress-bar-fill" :style="{ width: trainProgressPercent + '%' }"></div>
                      </div>
                      <span class="train-progress-pct">{{ trainProgressPercent }}%</span>
                    </div>
                  </template>
                  <template v-else>
                    <!-- 预训练：灰色占位 -->
                    <div class="train-progress-header" style="opacity:0.4;">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                        <polygon points="5 3 19 12 5 21 5 3" />
                      </svg>
                      <span class="train-progress-title">等待开始训练...</span>
                    </div>
                    <div class="train-progress-bar-wrap" style="opacity:0.3;">
                      <div class="train-progress-bar" style="background:var(--color-border);">
                        <div class="train-progress-bar-fill" style="width:0%;"></div>
                      </div>
                      <span class="train-progress-pct">0%</span>
                    </div>
                  </template>

                  <div class="train-progress-detail">

                    <!-- ===== 训练可视化区域 ===== -->
                    <div class="train-charts-grid">
                      <!-- Loss 主图 + LR 叠加 -->
                      <div class="train-chart-card train-chart-large">
                        <div class="train-chart-card-header">
                          <span class="train-chart-card-title">Loss 曲线</span>
                          <div style="display:flex;gap:16px;align-items:center;">
                            <span class="train-chart-card-value" v-if="trainProgress?.loss_smooth != null">EMA {{ Number(trainProgress.loss_smooth).toFixed(4) }}</span>
                            <span class="train-chart-card-value" style="color:#A9761E;" v-if="trainProgress?.learning_rate != null">LR {{ Number(trainProgress.learning_rate).toExponential(2) }}</span>
                          </div>
                        </div>
                        <div class="train-chart-body">
                          <canvas ref="lossChartCanvas"></canvas>
                        </div>
                      </div>

                      <!-- 三小图并排 -->
                      <div class="train-small-charts">
                        <!-- Grad Norm -->
                        <div class="train-chart-card">
                          <div class="train-chart-card-header">
                            <span class="train-chart-card-title">Grad Norm</span>
                            <span class="train-chart-card-value train-val-red" v-if="trainProgress?.grad_norm != null">{{ Number(trainProgress.grad_norm).toFixed(3) }}</span>
                          </div>
                          <div class="train-chart-body train-chart-sm">
                            <canvas ref="gradNormChartCanvas"></canvas>
                          </div>
                          <div class="train-chart-hint">实际更新被 clip 在 1.0 以内。平滑线下降 → 收敛中；持续接近 1.0 → 震荡。</div>
                        </div>

                        <!-- Token Accuracy -->
                        <div class="train-chart-card">
                          <div class="train-chart-card-header">
                            <span class="train-chart-card-title">Accuracy</span>
                            <span class="train-chart-card-value train-val-purple" v-if="trainProgress?.accuracy != null">{{ (Number(trainProgress.accuracy) * 100).toFixed(1) }}%</span>
                          </div>
                          <div class="train-chart-body train-chart-sm">
                            <canvas ref="accuracyChartCanvas"></canvas>
                          </div>
                        </div>

                        <!-- 训练日志 -->
                        <div class="train-chart-card" style="grid-column: span 1;">
                          <div class="train-chart-card-header">
                            <span class="train-chart-card-title">训练日志</span>
                            <span class="train-chart-card-value" style="font-size:10px;color:var(--color-text-muted);">{{ trainLogMessages.length }} 条</span>
                          </div>
                          <div class="train-chart-body train-chart-sm" style="padding:0;">
                            <pre ref="trainLogPanel" class="train-log-panel">{{ trainLogMessages.join('\n') || '等待日志...' }}</pre>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                </template>

                <!-- 模型详情视图 -->
                <div v-if="selectedModelId" class="model-detail-view">
                  <div class="model-detail-topbar">
                    <button class="btn-new-model-train" @click="selectedModelId = null; modelsSubTab = 'train'">
                      ← 新建模型训练
                    </button>
                    <span class="model-detail-name">{{ selectedModelMeta?.model_name || '' }}</span>
                  </div>
                  <div v-if="modelDetailLoading" class="models-empty">加载中...</div>
                  <div v-else-if="selectedModelMeta" class="model-detail-content">
                    <div class="model-detail-stats">
                      <span>{{ selectedModelMeta.example_count || 0 }} 训练样本</span>
                      <span>{{ selectedModelMeta.train_duration_seconds || 0 }}s 训练耗时</span>
                      <span>{{ (selectedModelMeta.entity_labels || []).length }} 标签</span>
                    </div>
                    <div class="model-detail-charts" v-if="selectedModelMeta.training_history && selectedModelMeta.training_history.length > 0">
                      <div class="train-chart-card train-chart-large" style="margin-bottom:12px;">
                        <div class="train-chart-card-header">
                          <span class="train-chart-card-title">Loss / LR 曲线</span>
                        </div>
                        <div class="train-chart-body" style="height:170px;position:relative;">
                          <canvas ref="historyLossChartCanvas"></canvas>
                        </div>
                      </div>
                      <div class="train-chart-card">
                        <div class="train-chart-card-header">
                          <span class="train-chart-card-title">Grad Norm</span>
                        </div>
                        <div class="train-chart-body" style="height:120px;position:relative;">
                          <canvas ref="historyGradChartCanvas"></canvas>
                        </div>
                      </div>
                    </div>
                    <div v-else class="models-empty">该模型无训练历史数据</div>
                  </div>
                </div>
                <div v-if="modelsSubTab === 'eval' && savedModels.length > 0" class="eval-section">
                  <div class="eval-section-header">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
                      <path d="M9 11l3 3L22 4" />
                      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                    </svg>
                    <span>评估模型</span>
                  </div>

                  <div class="eval-form">
                    <select v-model="evalModelId" class="select-field" style="flex:1;">
                      <option value="">-- 选择要评估的模型 --</option>
                      <option v-for="m in savedModels" :key="m.model_id" :value="m.model_id">{{ m.model_name }} ({{ (m.entity_labels || []).length }} 标签)</option>
                    </select>

                    <label class="train-file-upload eval-file-upload" :class="{ 'has-file': evalTestFile }" @click="!isEvaluating && evalFileInput?.click()">
                      <div class="train-file-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                          <polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
                        </svg>
                      </div>
                      <div class="train-file-text">
                        <span v-if="!evalTestFile" class="train-file-placeholder">上传测试 JSONL</span>
                        <span v-else class="train-file-name">{{ evalTestFile.name }}</span>
                      </div>
                    </label>
                    <input ref="evalFileInput" type="file" class="hidden-input" accept=".jsonl,.json" @change="onEvalFileChange" />

                    <button
                      class="btn-train-start"
                      style="width:auto;padding:10px 24px;"
                      :disabled="isEvaluating || !evalTestFile || !evalModelId.trim()"
                      @click="runEvaluation"
                    >
                      <svg v-if="isEvaluating" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" class="spin">
                        <circle cx="12" cy="12" r="10" stroke-opacity="0.2" /><path d="M12 2a10 10 0 0 1 10 10" stroke-linecap="round" />
                      </svg>
                      <span>{{ isEvaluating ? '评估中...' : '开始评估' }}</span>
                    </button>
                  </div>

                  <!-- 评估结果 -->
                  <div v-if="evalResult" class="eval-results">
                    <div class="eval-metrics-row">
                      <div class="eval-metric-card">
                        <span class="eval-metric-value">{{ (evalResult.overall.precision * 100).toFixed(1) }}%</span>
                        <span class="eval-metric-label">Precision</span>
                      </div>
                      <div class="eval-metric-card">
                        <span class="eval-metric-value">{{ (evalResult.overall.recall * 100).toFixed(1) }}%</span>
                        <span class="eval-metric-label">Recall</span>
                      </div>
                      <div class="eval-metric-card">
                        <span class="eval-metric-value">{{ (evalResult.overall.f1 * 100).toFixed(1) }}%</span>
                        <span class="eval-metric-label">F1 Score</span>
                      </div>
                      <div class="eval-metric-card">
                        <span class="eval-metric-value">{{ evalResult.sample_count }}</span>
                        <span class="eval-metric-label">测试样本</span>
                      </div>
                    </div>

                    <!-- 每类 F1 柱状图 -->
                    <div v-if="evalResult.per_class && Object.keys(evalResult.per_class).length > 0" class="eval-chart-container">
                      <div class="train-chart-card-header" style="padding:8px 0;">
                        <span class="train-chart-card-title">每类 F1 得分</span>
                      </div>
                      <div style="height:160px;position:relative;">
                        <canvas ref="evalF1ChartCanvas"></canvas>
                      </div>
                    </div>
                  </div>
                </div>

              </div>
            </div>
          </div>
        </section>
      </main>

      <!-- 模型删除确认对话框 -->
      <transition name="fade">
        <div v-if="deleteModelConfirmId" class="confirm-overlay" @click.self="deleteModelConfirmId = null">
          <div class="confirm-dialog">
            <div class="confirm-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <p class="confirm-title">确认删除模型</p>
            <p class="confirm-desc">此操作将永久删除该模型及其相关文件，不可恢复。确定要继续吗？</p>
            <div class="confirm-actions">
              <button class="btn-confirm-cancel" @click="deleteModelConfirmId = null">取消</button>
              <button class="btn-confirm-delete" @click="confirmDeleteModel">确认删除</button>
            </div>
          </div>
        </div>
      </transition>

      <!-- 训练完成弹窗 -->
      <transition name="fade">
        <div v-if="showTrainCompleteModal" class="confirm-overlay" @click.self="closeTrainCompleteModal">
          <div class="confirm-dialog" style="text-align:left;max-width:420px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
              <div class="confirm-icon" style="background:var(--color-success-light);color:var(--color-success);margin:0;">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              <p class="confirm-title" style="margin:0;">训练完成</p>
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:20px;padding:12px;background:var(--color-bg-subtle);border-radius:8px;">
              <div style="display:flex;justify-content:space-between;"><span style="color:var(--color-text-secondary);">模型名称</span><span style="font-weight:600;">{{ trainCompleteResult?.model_name || '--' }}</span></div>
              <div style="display:flex;justify-content:space-between;"><span style="color:var(--color-text-secondary);">训练耗时</span><span style="font-weight:600;">{{ trainCompleteResult?.train_duration_seconds || 0 }}s</span></div>
              <div style="display:flex;justify-content:space-between;"><span style="color:var(--color-text-secondary);">最终 Loss</span><span style="font-weight:600;color:#2F7D5B;">{{ trainProgress?.finalLoss != null ? Number(trainProgress.finalLoss).toFixed(4) : '--' }}</span></div>
            </div>
            <div class="confirm-actions">
              <button class="btn-confirm-delete" style="background:var(--color-primary);" @click="closeTrainCompleteModal">关闭</button>
            </div>
          </div>
        </div>
      </transition>
    </div>

    <transition-group name="model-toast" tag="div" class="toast-container">
      <div v-for="toast in toasts" :key="toast.id" class="model-toast" :class="toast.type">
        <div class="model-toast-icon">
          <svg v-if="toast.type === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
          </svg>
          <svg v-else-if="toast.type === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          <svg v-else-if="toast.type === 'warning'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
        </div>
        <span class="toast-msg">{{ toast.message }}</span>
      </div>
    </transition-group>

    <transition name="fade">
      <div v-if="pendingDeleteId" class="confirm-overlay" @click.self="cancelDelete">
        <div class="confirm-dialog">
          <div class="confirm-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="24" height="24">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <p class="confirm-title">确认删除</p>
          <p class="confirm-desc">此操作将永久删除该历史记录及相关文件，不可恢复。</p>
          <div class="confirm-actions">
            <button class="btn-confirm-cancel" @click="cancelDelete">取消</button>
            <button class="btn-confirm-delete" @click="confirmDeleteHistory">确认删除</button>
          </div>
        </div>
      </div>
    </transition>
  </div>
  </div>
</template>

<script setup>
import '../styles/model-annotation.css'
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { marked } from 'marked'
import TurndownService from 'turndown'
import { gfm } from 'turndown-plugin-gfm'
import { Chart, LineController, LineElement, PointElement, LinearScale, CategoryScale, BarController, BarElement, Title, Tooltip, Legend, Filler } from 'chart.js'
Chart.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, BarController, BarElement, Title, Tooltip, Legend, Filler)
// quickTrainShortcuts 已移除 —— 训练功能已迁移至模型管理页面

function resolveApiBase() {
  return '/model-api'
}
const API_BASE = resolveApiBase()

// 模型后端冷启动约需 20 秒（导入 torch/模型）。若页面在它监听端口之前就加载，
// Vite 代理会返回 500/502/503，这里在首次加载时对这些瞬时错误做有限重试。
async function getWithStartupRetry(url, attempts = 8, delayMs = 2500) {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await axios.get(url)
    } catch (error) {
      const status = error?.response?.status
      const retriable = status === undefined || status === 500 || status === 502 || status === 503
      if (!retriable || attempt >= attempts) throw error
      await new Promise(resolve => setTimeout(resolve, delayMs))
    }
  }
}

const FALLBACK_ANNOTATION_RULES = [
  { id: 'standards', label: '标准条文', description: '识别 GB、GB/T、ISO、IEC、SJ/T 等标准编号，并提取所在句子。' },
  { id: 'decisions', label: '判定结论', description: '提取包含判定结果、符合性、阴性/阳性、合格/不合格等关键信息的句子。' },
  { id: 'dates', label: '日期节点', description: '提取发布日期、实施日期及其他明显的日期信息。' },
  { id: 'limits', label: '限值指标', description: '提取 ppm、mg/kg、百分比等明显指标及对应语句。' },
  { id: 'numeric_facts', label: '数值信息', description: '提取 CAS 号、比例、网格尺寸、电压尺寸和其他与数值相关的关键信息。' }
]

const turndownService = new TurndownService({
  headingStyle: 'atx',
  codeBlockStyle: 'fenced',
  emDelimiter: '*',
  bulletListMarker: '-',
})

turndownService.use(gfm)

const fileInput = ref(null)
const mdBodyRef = ref(null)
const editableRef = ref(null)
const mdViewKey = ref(0)
const selectedFile = ref(null)
const isDragOver = ref(false)
const pdfUrl = ref('')
const renderedMarkdown = ref('')
const rawMarkdown = ref('')
const splitMode = ref('horizontal')
const pdfFullscreen = ref(false)
const mdFullscreen = ref(false)
const sidebarCollapsed = ref(false)
const wizardStep = ref(1)
const currentPage = ref('console') // 'console' | 'models'
const annotationMode = ref('rules') // 'rules' | 'model'
const selectedPersistentModelId = ref('')
const modelAnnotationLoading = ref(false)
const savedModels = ref([])
const modelsLoading = ref(false)
const modelsSubTab = ref('train')
const selectedModelId = ref(null)
const selectedModelMeta = ref(null)
const modelDetailLoading = ref(false)
// 模型管理页面状态
const trainModelName = ref('')
const datasets = ref([])
const datasetsLoading = ref(false)
const datasetUploading = ref(false)
const selectedDatasetIds = ref([])
const expandedDatasetId = ref('')
const datasetFileInput = ref(null)

const allDatasetSampleCount = computed(() =>
  datasets.value.reduce((sum, item) => sum + (item.sample_count || 0), 0)
)
const allDatasetLabelCount = computed(() => {
  const labels = new Set()
  for (const dataset of datasets.value) {
    for (const label of Object.keys(dataset.label_counts || {})) labels.add(label)
  }
  return labels.size
})
const trainEpochs = ref(2)
const trainBatchSize = ref(8)
const trainLearningRate = ref(3e-5)
const trainProgress = ref(null)
const trainStatusMsg = ref('')
const isTraining = ref(false)
const showTrainCompleteModal = ref(false)
const trainCompleteResult = ref(null)
const deleteModelConfirmId = ref(null)

// 训练历史数据（一大三小图表）
const trainLossHistory = ref([])       // {step, loss}
const trainLrHistory = ref([])         // {step, lr}
const trainGradNormHistory = ref([])   // {step, grad_norm}
const trainStartTime = ref(null)       // 训练开始时间戳
const lossChartCanvas = ref(null)
const gradNormChartCanvas = ref(null)
const accuracyChartCanvas = ref(null)
let lossChart = null
let gradNormChart = null
let accuracyChart = null
const historyLossChartCanvas = ref(null)
const historyGradChartCanvas = ref(null)
let historyLossChart = null
let historyGradChart = null
const trainLogMessages = ref([])
const trainLogPanel = ref(null)
const evalFileInput = ref(null)
const evalTestFile = ref(null)
const isEvaluating = ref(false)
const evalResult = ref(null)
const evalModelId = ref('')
const evalF1ChartCanvas = ref(null)
let evalF1Chart = null

// 训练已用时间
const trainElapsedTime = computed(() => {
  if (!trainStartTime.value) return '--'
  const diff = Math.floor((Date.now() - trainStartTime.value) / 1000)
  const m = Math.floor(diff / 60)
  const s = diff % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

// Perplexity 实时计算
const trainPerplexity = computed(() => {
  if (trainProgress.value?.loss == null) return null
  return Math.exp(Number(trainProgress.value.loss))
})

// Epoch 环形进度百分比
const epochRingPercent = computed(() => {
  if (!trainProgress.value || !trainProgress.value.epoch) return 0
  return Math.round((trainProgress.value.epoch / trainEpochs.value) * 100)
})

// Epoch 环形进度 conic-gradient
const epochRingGradient = computed(() => {
  const pct = epochRingPercent.value
  return `conic-gradient(#E4572E ${pct * 3.6}deg, rgba(228,87,46,0.12) ${pct * 3.6}deg)`
})
const isUploading = ref(false)
const loadingOptions = ref(true)
const pdfLoading = ref(false)
const pdfLoadError = ref(false)
const mdLoading = ref(false)
const mdLoadError = ref(false)
const isEditing = ref(false)
const isSaving = ref(false)
const nowTick = ref(Date.now())
const annotationRules = ref(FALLBACK_ANNOTATION_RULES)
const selectedAnnotationRules = ref([])
const annotationLoading = ref(false)
const exportLoading = ref(false)
const annotationError = ref('')
const annotationResult = ref({ rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } })
const modelAnnotationResult = ref({ rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } })
// highlightHtmlContent 单次 DOM 遍历后返回的实体消费顺序，用于构建命中片段
const _consumedEntities = ref([])
const modelConfThreshold = ref(0)
const annotationLastRunAt = ref(0)
const modelAnnotationLastRunAt = ref(0)
const currentSnippetIndex = ref(0)
const annotationScanActive = ref(false)
const scanLineY = ref(0)
const annotationSettingsExpanded = ref(true)

const historyRecords = ref([])
const isHistoryLoading = ref(false)
const pendingDeleteId = ref(null)

const toasts = reactive([])
let toastId = 0

// ── 动态标签颜色系统 ──
const LABEL_COLOR_PALETTE = [
  [59, 130, 246],   // 蓝
  [16, 185, 129],   // 绿
  [245, 158, 11],   // 橙
  [139, 92, 246],   // 紫
  [236, 72, 153],   // 粉
  [99, 102, 241],   // 靛
  [20, 184, 166],   // 青
  [249, 115, 22],   // 橘
  [14, 165, 233],   // 天蓝
  [168, 85, 247],   // 紫罗兰
  [34, 197, 94],    // 翠绿
  [225, 29, 72],    // 玫红
  [250, 204, 21],   // 黄
  [107, 114, 128],  // 灰
  [59, 130, 246],   // 蓝(循环)
]
const _labelColorCache = new Map()
let _labelColorNext = 0

function getLabelColor(label) {
  if (!label) return LABEL_COLOR_PALETTE[13]  // 灰 fallback
  if (_labelColorCache.has(label)) return _labelColorCache.get(label)
  const [r, g, b] = LABEL_COLOR_PALETTE[_labelColorNext % LABEL_COLOR_PALETTE.length]
  _labelColorNext++
  const color = { bg: `rgba(${r},${g},${b},0.28)`, border: `rgba(${r},${g},${b},0.6)`, solid: `rgba(${r},${g},${b},0.7)` }
  _labelColorCache.set(label, color)
  return color
}

function ensureLabelStyles() {
  // 动态注入 CSS 规则（用原始 label 做类名，中文在 CSS3 中合法）
  const styleId = '_annotation_label_styles'
  let el = document.getElementById(styleId)
  if (!el) {
    el = document.createElement('style')
    el.id = styleId
    document.head.appendChild(el)
  }
  let css = ''
  for (const [label, color] of _labelColorCache) {
    css += `.annotation-highlight.annotation-${label}{background:${color.bg};border-bottom-color:${color.border};color:inherit;}\n`
  }
  el.textContent = css
}
function showToast(message, type = 'info') {
  const id = ++toastId
  toasts.push({ id, message, type })
  setTimeout(() => {
    const idx = toasts.findIndex(t => t.id === id)
    if (idx !== -1) toasts.splice(idx, 1)
  }, 3500)
}

const availableOptions = reactive({
  backend_types: [],
  languages: [],
  ocr_modes: [],
  feature_toggles: [],
  defaults: {}
})

const parseConfig = reactive({
  backend_type: 'pipeline',
  language: 'auto',
  ocr_mode: 'auto',
  high_accuracy: true,
  enable_ocr: true,
  enable_layout: true,
  enable_formula: false,
  enable_table: true,
  enable_image: true,
  enable_heading: true,
  preserve_whitespace: true
})

const taskInfo = reactive({
  task_id: null,
  status: 'idle',
  progress: 0,
  message: '',
  file_name: '',
  feature_summary: []
})

let pollingInterval = null
let clockTimer = null

const wizardSteps = [
  { key: 'upload', label: '上传文件' },
  { key: 'config', label: '配置参数' },
  { key: 'processing', label: '解析中' },
  { key: 'review', label: '结果校对' },
  { key: 'annotation', label: '快速标注' }
]

const stages = [
  { label: '初始化', threshold: 8 },
  { label: '语言策略', threshold: 18 },
  { label: '版面分析', threshold: 32 },
  { label: 'OCR 识别', threshold: 52 },
  { label: '内容提取', threshold: 76 },
  { label: '生成结果', threshold: 100 }
]

const currentStage = computed(() => {
  if (typeof taskInfo.stage_index === 'number' && taskInfo.stage_index >= 0) {
    return Math.min(taskInfo.stage_index, stages.length - 1)
  }
  for (let i = stages.length - 1; i >= 0; i--) {
    if (taskInfo.progress >= stages[i].threshold) return i
  }
  return 0
})

const statusText = computed(() => {
  switch (taskInfo.status) {
    case 'processing': return '处理中'
    case 'completed': return '已完成'
    case 'failed': return '失败'
    default: return '就绪'
  }
})

const currentPageTitle = computed(() => {
  if (currentPage.value === 'models') return '模型管理'
  const titles = ['上传文件', '配置参数', '解析中', '结果校对', '快速标注']
  return titles[wizardStep.value - 1] || '新建任务'
})

const configPreviewTags = computed(() => {
  const tags = [
    getLabel(availableOptions.backend_types, parseConfig.backend_type),
    getLabel(availableOptions.languages, parseConfig.language),
    getLabel(availableOptions.ocr_modes, parseConfig.ocr_mode)
  ]
  availableOptions.feature_toggles.forEach(item => {
    if (parseConfig[item.key]) tags.push(item.label)
  })
  return tags
})

const wordCount = computed(() => {
  if (!rawMarkdown.value) return 0
  return rawMarkdown.value.replace(/\s+/g, '').length
})

/**
 * 收集所有标注结果中的实体（规则 + 模型），只做收集和置信度过滤，不做排序。
 * 排序和命中片段的构建由 highlightHtmlContent 单次 DOM 遍历统一完成。
 */
function mergeAnnotationResults() {
  const rule = annotationResult.value || { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }
  const model = modelAnnotationResult.value || { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }

  // Merge rules: deduplicate by id, sum counts
  const ruleMap = new Map()
  const addRule = (r, source) => {
    const existing = ruleMap.get(r.id)
    if (existing) {
      existing.count = (existing.count || 0) + (r.count || 0)
    } else {
      ruleMap.set(r.id, { ...r, _source: source })
    }
  }
  (rule.rules || []).forEach(r => addRule(r, 'rule'))
  ;(model.rules || []).forEach(r => addRule(r, 'model'))

  // 收集所有实体：规则实体全收，模型实体按置信度过滤
  const confThreshold = modelConfThreshold.value / 100
  const allEntities = []
  const addEntity = (e, source) => {
    allEntities.push({ ...e, _sources: [source] })
  }
  ;(rule.entities || []).forEach(e => addEntity(e, 'rule'))
  ;(model.entities || [])
    .filter(e => (e.confidence ?? 1) >= confThreshold)
    .forEach(e => addEntity(e, 'model'))

  const mergedRules = [...ruleMap.values()]
  const mergedSnippets = [...(rule.snippets || []), ...(model.snippets || [])]

  return {
    rules: mergedRules,
    entities: allEntities,  // 未排序，由 highlightHtmlContent 实际 DOM 遍历决定顺序
    snippets: mergedSnippets,
    counts: {
      entities: allEntities.length,
      snippets: mergedSnippets.length,
      rules: mergedRules.length,
    },
  }
}

const mergedResult = computed(() => mergeAnnotationResults())

// 命中片段：直接使用 highlightHtmlContent 一次 DOM 遍历返回的消费顺序
// 与 Markdown 中的高亮标记 1:1 精确对应
const annotationSnippets = computed(() => {
  const consumed = _consumedEntities.value
  if (consumed.length === 0) {
    // 尚未运行高亮时回退到 snippets
    return mergedResult.value?.snippets || []
  }
  return consumed.map((ent, idx) => ({
    id: ent.id,
    rule_id: ent.rule_id,
    rule_label: ent.rule_label,
    text: ent.text,
    context: ent.context || '',
    tags: [ent.text],
    confidence: ent.confidence ?? null,
    _sources: ent._sources || [],
  }))
})

const annotationCounts = computed(() => {
  const consumed = _consumedEntities.value
  const m = mergedResult.value
  return {
    entities: consumed.length || (m?.entities?.length || 0),
    entries: consumed.length,
    snippets: m?.snippets?.length || 0,
    rules: m?.rules?.length || 0,
  }
})

// 监听 mergedResult 变化，自动注入标签颜色样式，并刷新 Markdown 高亮
watch(mergedResult, () => {
  if (mergedResult.value?.entities) {
    for (const e of mergedResult.value.entities) {
      getLabelColor(e.rule_label || e.rule_id || e.type || 'entity')
    }
    ensureLabelStyles()
  }
  // 置信度阈值变化时 mergedResult 会重新计算（entities 过滤变化），
  // 需要同步更新 Markdown 渲染中的高亮标注
  refreshMarkdownView()
}, { deep: false })
const currentSnippet = computed(() => {
  const snippets = annotationSnippets.value
  if (!snippets.length) return null
  const idx = Math.min(Math.max(currentSnippetIndex.value, 0), snippets.length - 1)
  return snippets[idx] || null
})
const annotationUpdatedText = computed(() => {
  const parts = []
  if (annotationLastRunAt.value) parts.push(`规则：${new Date(annotationLastRunAt.value).toLocaleString('zh-CN', { hour12: false })}`)
  if (modelAnnotationLastRunAt.value) parts.push(`模型：${new Date(modelAnnotationLastRunAt.value).toLocaleString('zh-CN', { hour12: false })}`)
  if (!parts.length) return '尚未执行标注'
  return `最近标注 | ${parts.join(' · ')}`
})

const elapsed = computed(() => {
  if (!taskInfo.started_at) return 0
  return Math.max(0, Math.floor(nowTick.value / 1000 - taskInfo.started_at))
})

const estimatedRemaining = computed(() => {
  if (taskInfo.status === 'completed') return '0s'
  if (Number.isFinite(taskInfo.eta_seconds) && taskInfo.eta_seconds >= 0) {
    return formatDuration(taskInfo.eta_seconds)
  }
  if (elapsed.value < 2 || taskInfo.progress <= 0) return '--'
  const rate = taskInfo.progress / elapsed.value
  const remaining = Math.ceil((100 - taskInfo.progress) / rate)
  return remaining > 0 ? formatDuration(remaining) : '--'
})

function getLabel(items, value) {
  return items.find(item => item.value === value)?.label || value
}

function canNavigateToStep(step) {
  if (taskInfo.status === 'processing') return false
  if (step === 1) return wizardStep.value > 1
  if (step === 2) return wizardStep.value > 2
  if (step === 3) return wizardStep.value > 3
  if (step === 4) return wizardStep.value > 4
  if (step === 5) return taskInfo.status === 'completed' && (wizardStep.value === 4 || wizardStep.value === 5)
  return false
}

function navigateToStep(step) {
  if (step === 1) {
    reset()
    return
  }
  if (step === 5) {
    wizardStep.value = 5
    return
  }
  if (step === 4 && wizardStep.value === 5) {
    resetAnnotationState()
    refreshMarkdownView()
  }
  wizardStep.value = step
}

const MAX_FILE_SIZE = 50 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']

async function loadOptions(retryOnStartup = false) {
  try {
    loadingOptions.value = true
    const url = `${API_BASE}/options`
    const response = retryOnStartup ? await getWithStartupRetry(url) : await axios.get(url)
    Object.assign(availableOptions, response.data)
    Object.assign(parseConfig, response.data.defaults || {})
  } catch {
    showToast('无法加载后端配置选项，部分功能可能不可用', 'error')
  } finally {
    loadingOptions.value = false
  }
}

function validateFile(file) {
  if (!file) return false
  const ext = '.' + file.name.split('.').pop().toLowerCase()
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    showToast(`不支持的文件格式: ${ext}，请选择 PDF、PNG 或 JPG`, 'error')
    return false
  }
  if (file.size > MAX_FILE_SIZE) {
    showToast(`文件过大 (${formatSize(file.size)})，最大支持 50MB`, 'error')
    return false
  }
  return true
}

function openFilePicker() {
  fileInput.value?.click()
}

function handleFileChange(event) {
  const file = event.target.files?.[0]
  if (file && validateFile(file)) selectedFile.value = file
  else clearFile()
}

function onDrop(event) {
  isDragOver.value = false
  const file = event.dataTransfer.files?.[0]
  if (file && validateFile(file)) selectedFile.value = file
  else clearFile()
}

function clearFile() {
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '--'
  const seconds = Math.max(0, Math.floor(totalSeconds))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = seconds % 60
  if (minutes < 60) return `${minutes}m ${remainSeconds}s`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}h ${remainMinutes}m`
}

function formatDate(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp * 1000)
  const pad = (n) => n.toString().padStart(2, '0')
  return `${date.getMonth() + 1}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function rewriteMarkdownAssets(mdText, taskId = taskInfo.task_id) {
  if (!mdText) return ''
  if (!taskId) return mdText
  return mdText.replace(/images\//g, `${API_BASE}/result/${taskId}/images/`)
}

function resetAnnotationState() {
  annotationLoading.value = false
  annotationError.value = ''
  annotationLastRunAt.value = 0
  modelAnnotationLastRunAt.value = 0
  annotationResult.value = { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }
  modelAnnotationResult.value = { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }
  _consumedEntities.value = []
  currentSnippetIndex.value = 0
  selectedAnnotationRules.value = []
  annotationSettingsExpanded.value = true
}
function highlightHtmlContent(html, entities) {
  if (!html || !entities?.length || typeof DOMParser === 'undefined') return { html, consumedOrder: [] }

  // 确保标签颜色 CSS 已注入
  ensureLabelStyles()

  // 构建 FIFO pool：相同文本的实体按数组顺序排列
  const indexMap = new Map()
  entities.forEach((entity) => {
    if (!entity?.text) return
    const arr = indexMap.get(entity.text) || []
    arr.push(entity)
    indexMap.set(entity.text, arr)
  })
  const pools = new Map()
  for (const [txt, arr] of indexMap) {
    pools.set(txt, arr.slice())
  }

  // 收集所有唯一文本，按长度降序排列（长文本优先匹配，避免子串误匹配）
  const allTexts = new Set()
  entities.forEach(e => { if (e?.text) allTexts.add(e.text) })
  const terms = Array.from(allTexts).sort((a, b) => b.length - a.length)
  if (!terms.length) return { html, consumedOrder: [] }

  const parser = new DOMParser()
  const doc = parser.parseFromString(`<div id="annotation-root">${html}</div>`, 'text/html')
  const root = doc.getElementById('annotation-root')
  if (!root) return { html, consumedOrder: [] }

  const matcher = new RegExp(terms.map(escapeRegExp).join('|'), 'g')
  const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT
      const parent = node.parentElement
      if (!parent) return NodeFilter.FILTER_REJECT
      if (parent.closest('.annotation-highlight')) return NodeFilter.FILTER_REJECT
      if (['SCRIPT', 'STYLE', 'CODE', 'PRE'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT
      return NodeFilter.FILTER_ACCEPT
    }
  })

  const textNodes = []
  while (walker.nextNode()) textNodes.push(walker.currentNode)

  // 记录被消费的实体顺序 —— 这就是文档中实体出现的顺序
  const consumedOrder = []

  function _popEntity(matchedText) {
    const pool = pools.get(matchedText)
    if (pool && pool.length > 0) {
      const entity = pool.shift()
      consumedOrder.push(entity)
      return entity
    }
    return null
  }

  textNodes.forEach((node) => {
    const source = node.nodeValue
    if (!source) return
    matcher.lastIndex = 0
    let lastIndex = 0
    let hasMatch = false
    const fragment = doc.createDocumentFragment()
    let match
    while ((match = matcher.exec(source)) !== null) {
      hasMatch = true
      const matchedText = match[0]
      const entity = _popEntity(matchedText)
      if (match.index > lastIndex) {
        fragment.appendChild(doc.createTextNode(source.slice(lastIndex, match.index)))
      }
      const mark = doc.createElement('mark')
      if (entity) {
        const entityType = entity.rule_label || entity.rule_id || entity.type || 'entity'
        getLabelColor(entityType)
        mark.className = `annotation-highlight annotation-${entityType}`
        mark.dataset.entityId = entity.id || ''
        mark.dataset.entityType = entityType
        mark.dataset.entityText = entity.text || ''
      } else {
        // orphan 匹配不生成 mark
        fragment.appendChild(doc.createTextNode(matchedText))
        lastIndex = match.index + matchedText.length
        continue
      }
      mark.textContent = matchedText
      fragment.appendChild(mark)
      lastIndex = match.index + matchedText.length
    }
    if (!hasMatch) return
    if (lastIndex < source.length) {
      fragment.appendChild(doc.createTextNode(source.slice(lastIndex)))
    }
    node.parentNode?.replaceChild(fragment, node)
  })

  return { html: root.innerHTML, consumedOrder }
}

function buildRenderedMarkdown() {
  if (!rawMarkdown.value) { _consumedEntities.value = []; return '' }
  const html = marked.parse(rewriteMarkdownAssets(rawMarkdown.value))
  if (isEditing.value || wizardStep.value !== 5) { _consumedEntities.value = []; return html }
  const result = highlightHtmlContent(html, mergedResult.value?.entities || [])
  // 将单次 DOM 遍历得到的实体消费顺序存储，供命中片段面板使用
  _consumedEntities.value = result.consumedOrder
  return result.html
}

function refreshMarkdownView() {
  renderedMarkdown.value = buildRenderedMarkdown()
}

function getRuleCount(ruleId) {
  return mergedResult.value?.rules?.find(rule => rule.id === ruleId)?.count || 0
}

async function loadAnnotationOptions(retryOnStartup = false) {
  try {
    const url = `${API_BASE}/annotation/options`
    const response = retryOnStartup ? await getWithStartupRetry(url) : await axios.get(url)
    annotationRules.value = response.data?.rules?.length ? response.data.rules : FALLBACK_ANNOTATION_RULES
  } catch {
    annotationRules.value = FALLBACK_ANNOTATION_RULES
  }
}

async function fetchAnnotations() {
  const tid = taskInfo.task_id
  if (!tid || !rawMarkdown.value || isEditing.value || wizardStep.value !== 5) {
    resetAnnotationState()
    refreshMarkdownView()
    return
  }

  if (!selectedAnnotationRules.value.length) {
    resetAnnotationState()
    refreshMarkdownView()
    return
  }

  annotationLoading.value = true
  annotationError.value = ''
  try {
    const response = await axios.post(`${API_BASE}/result/${tid}/annotations`, {
      rules: selectedAnnotationRules.value
    })
    annotationResult.value = response.data || { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }
    currentSnippetIndex.value = 0
    annotationLastRunAt.value = Date.now()
  } catch (error) {
    annotationError.value = error.response?.data?.message || '标注分析失败'
    annotationResult.value = { rules: [], entities: [], snippets: [], counts: { entities: 0, snippets: 0 } }
    currentSnippetIndex.value = 0
  } finally {
    annotationLoading.value = false
    refreshMarkdownView()
    await nextTick()
    animateAnnotationHighlights()
  }
}



function selectAllAnnotationRules() {
  selectedAnnotationRules.value = annotationRules.value.map(rule => rule.id)
}

function clearAnnotationRules() {
  selectedAnnotationRules.value = []
}

// ── Model management ──

async function fetchSavedModels() {
  modelsLoading.value = true
  try {
    const response = await axios.get(`${API_BASE}/models`)
    savedModels.value = response.data || []
  } catch {
    savedModels.value = []
  } finally {
    modelsLoading.value = false
  }
}



/**
 * 模型删除确认对话框的回调函数
 */
async function confirmDeleteModel() {
  const modelId = deleteModelConfirmId.value
  if (!modelId) return
  deleteModelConfirmId.value = null
  try {
    await axios.delete(`${API_BASE}/models/${modelId}`)
    savedModels.value = savedModels.value.filter(m => m.model_id !== modelId)
    showToast('模型已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

async function handleDeleteModel(modelId) {
  try {
    await axios.delete(`${API_BASE}/models/${modelId}`)
    savedModels.value = savedModels.value.filter(m => m.model_id !== modelId)
    showToast('模型已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

async function runModelInference() {
  if (!selectedPersistentModelId.value || !rawMarkdown.value) return
  modelAnnotationLoading.value = true
  try {
    const response = await axios.post(`${API_BASE}/model/infer`, {
      model_id: selectedPersistentModelId.value,
      document_text: rawMarkdown.value,
    })
    modelAnnotationResult.value = response.data || { entities: [], snippets: [], counts: [], rules: [] }
    modelAnnotationLastRunAt.value = Date.now()
    refreshMarkdownView()
    await nextTick()
    animateAnnotationHighlights()
    showToast('模型标注完成，结果已合并到当前视图', 'success')
  } catch (e) {
    showToast('模型推理失败: ' + (e.response?.data?.message || e.message), 'error')
  } finally {
    modelAnnotationLoading.value = false
  }
}

async function exportAnnotations() {
  const tid = taskInfo.task_id
  if (!tid) {
    showToast('当前没有可导出的任务', 'warning')
    return
  }
  const includeRules = selectedAnnotationRules.value.length > 0
  // 保留当前选择模型的语义，但要求用户至少实际执行过一次模型标注
  const includeModel = !!selectedPersistentModelId.value && !!modelAnnotationLastRunAt.value

  if (!includeRules && !includeModel) {
    showToast('请先选择标注规则或模型', 'warning')
    return
  }

  exportLoading.value = true
  try {
    const response = await axios.post(
      `${API_BASE}/result/${tid}/export-annotations`,
      {
        rules: includeRules ? selectedAnnotationRules.value : [],
        model_id: includeModel ? selectedPersistentModelId.value : '',
        model_conf_threshold: modelConfThreshold.value / 100,
      },
      { responseType: 'blob' }
    )

    // 后端返回空文件时（无任何可导出的标注结果），不触发下载也不提示成功
    if (response.data?.size === 0) {
      showToast('当前没有可导出的标注结果', 'warning')
      return
    }

    const disposition = response.headers['content-disposition'] || ''
    const utf8Matched = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    const plainMatched = disposition.match(/filename="?([^";]+)"?/)
    const rawName = utf8Matched ? utf8Matched[1] : (plainMatched ? plainMatched[1] : '')
    let filename = `${tid.slice(0, 8)}_annotations.jsonl`
    if (rawName) {
      try {
        filename = decodeURIComponent(rawName)
      } catch (_) {
        filename = rawName
      }
    }

    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/x-ndjson' }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    // 延迟释放，避免部分浏览器在下载真正开始前就取消下载
    setTimeout(() => URL.revokeObjectURL(url), 0)
    showToast('标注结果已导出', 'success')
  } catch (error) {
    let message = '导出失败'
    const payload = error.response?.data
    if (payload instanceof Blob) {
      try {
        const parsed = JSON.parse(await payload.text())
        message = parsed.message || message
      } catch (_) { /* ignore */ }
    } else if (payload?.message) {
      message = payload.message
    }
    showToast(message, 'error')
  } finally {
    exportLoading.value = false
  }
}

// ── 模型管理页面功能 ──

async function fetchDatasets(retryOnStartup = false) {
  datasetsLoading.value = true
  try {
    const url = `${API_BASE}/datasets`
    const response = retryOnStartup ? await getWithStartupRetry(url) : await axios.get(url)
    datasets.value = response.data || []
    const availableIds = new Set(datasets.value.map(item => item.dataset_id))
    selectedDatasetIds.value = selectedDatasetIds.value.filter(id => availableIds.has(id))
    // 用户未填写模型名时，默认使用最新上传（列表首位）的数据集名
    if (!trainModelName.value.trim() && datasets.value.length) {
      trainModelName.value = datasets.value[0].name
    }
  } catch {
    // 拉取失败时同步清空选中项，避免界面为空但训练按钮仍可点击导致 404
    datasets.value = []
    selectedDatasetIds.value = []
  } finally {
    datasetsLoading.value = false
  }
}

async function uploadDatasetFile(file) {
  if (!file || datasetUploading.value || isTraining.value) return
  const lower = file.name.toLowerCase()
  if (!lower.endsWith('.jsonl') && !lower.endsWith('.json')) {
    showToast('请上传 .jsonl 或 .json 文件', 'warning')
    return
  }
  datasetUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await axios.post(`${API_BASE}/datasets/upload`, formData)
    const dataset = response.data
    datasets.value = [dataset, ...datasets.value.filter(item => item.dataset_id !== dataset.dataset_id)]
    if (!selectedDatasetIds.value.includes(dataset.dataset_id)) {
      selectedDatasetIds.value = [...selectedDatasetIds.value, dataset.dataset_id]
    }
    expandedDatasetId.value = dataset.dataset_id
    if (!trainModelName.value.trim()) trainModelName.value = dataset.name
    showToast(`数据集已上传：${dataset.sample_count} 样本 · ${dataset.label_count} 类别`, 'success')
  } catch (error) {
    showToast('数据集上传失败: ' + (error.response?.data?.message || error.message), 'error')
  } finally {
    datasetUploading.value = false
  }
}

async function onDatasetFileChange(event) {
  const file = event.target.files?.[0]
  if (event.target) event.target.value = ''
  if (file) await uploadDatasetFile(file)
}

function onDatasetDrop(event) {
  const file = event.dataTransfer?.files?.[0]
  if (file) uploadDatasetFile(file)
}

async function deleteDataset(datasetId) {
  if (!datasetId || isTraining.value) return
  if (!window.confirm('确定删除该数据集？删除后不可恢复。')) return
  try {
    await axios.delete(`${API_BASE}/datasets/${datasetId}`)
    datasets.value = datasets.value.filter(item => item.dataset_id !== datasetId)
    selectedDatasetIds.value = selectedDatasetIds.value.filter(id => id !== datasetId)
    if (expandedDatasetId.value === datasetId) expandedDatasetId.value = ''
    showToast('数据集已删除', 'success')
  } catch {
    showToast('删除失败', 'error')
  }
}

function toggleDatasetStats(datasetId) {
  expandedDatasetId.value = expandedDatasetId.value === datasetId ? '' : datasetId
}

function getDatasetLabelEntries(dataset) {
  return Object.entries(dataset.label_counts || {}).sort((a, b) => b[1] - a[1])
}

function getDatasetLabelPct(dataset, count) {
  const values = Object.values(dataset.label_counts || {})
  const max = values.length ? Math.max(...values) : 1
  return max ? Math.round((count / max) * 100) : 0
}

function formatNumber(value) {
  const number = Number(value) || 0
  return number >= 10000 ? `${(number / 10000).toFixed(1)}万` : String(number)
}

/**
 * 初始化所有训练图表（Loss主图 + GradNorm + Perplexity）
 */
function initCharts() {
  const commonGrid = { color: 'rgba(148,163,184,0.08)' }
  const commonText = '#64748b'
  const commonInteraction = { intersect: false, mode: 'index' }
  const commonLegend = { labels: { color: '#94a3b8', usePointStyle: true, padding: 16, font: { size: 11 } } }

  // Destroy any existing chart instances first
  if (lossChart) { lossChart.destroy(); lossChart = null }
  if (gradNormChart) { gradNormChart.destroy(); gradNormChart = null }
  if (accuracyChart) { accuracyChart.destroy(); accuracyChart = null }

  // ── Loss 主图（双 Y 轴）──
  if (lossChartCanvas.value) {
    const lossCtx = lossChartCanvas.value.getContext('2d')
    if (lossCtx) {
      lossChart = new Chart(lossCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Loss (raw)',
            data: [],
            borderColor: 'rgba(148,163,184,0.35)',
            borderWidth: 0.8,
            pointRadius: 0,
            tension: 0.2,
            fill: false,
            yAxisID: 'y',
            borderDash: [3, 6],
          },
          {
            label: 'Loss (smooth)',
            data: [],
            borderColor: '#2F7D5B',
            backgroundColor: (ctx) => {
              const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height)
              gradient.addColorStop(0, 'rgba(47,125,91,0.20)')
              gradient.addColorStop(1, 'rgba(47,125,91,0.02)')
              return gradient
            },
            borderWidth: 2.5,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
            yAxisID: 'y',
          },
          {
            label: 'LR',
            data: [],
            borderColor: '#A9761E',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.4,
            fill: false,
            yAxisID: 'y1',
            borderDash: [5, 3],
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        interaction: commonInteraction,
        plugins: {
          legend: commonLegend,
          tooltip: {
            callbacks: {
              label(ctx) {
                if (ctx.datasetIndex === 0) return `Loss (raw): ${(ctx.raw || 0).toFixed(4)}`
                if (ctx.datasetIndex === 1) return `Loss (smooth): ${(ctx.raw || 0).toFixed(4)}`
                if (ctx.datasetIndex === 2) return `LR: ${(ctx.raw || 0).toExponential(2)}`
                return ''
              }
            }
          }
        },
        scales: {
          x: {
            display: true,
            title: { display: true, text: 'Step', color: commonText },
            ticks: { color: commonText, maxTicksLimit: 10 },
            grid: commonGrid,
          },
          y: {
            type: 'linear', display: true, position: 'left',
            title: { display: true, text: 'Loss', color: commonText },
            ticks: { color: commonText },
            grid: commonGrid,
          },
          y1: {
            type: 'linear', display: true, position: 'right',
            title: { display: true, text: 'LR', color: commonText },
            ticks: { color: commonText, callback: (v) => v.toExponential(1) },
            grid: { drawOnChartArea: false },
          }
        }
      }
    })
    }
  }

  // ── Grad Norm 小图 ──
  if (gradNormChartCanvas.value) {
    const gnCtx = gradNormChartCanvas.value.getContext('2d')
    if (gnCtx) {
    gradNormChart = new Chart(gnCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Grad Norm',
            data: [],
            borderColor: 'rgba(181,64,58,0.5)',
            backgroundColor: 'rgba(181,64,58,0.08)',
            borderWidth: 1.5,
            pointRadius: 1.5,
            pointBackgroundColor: 'rgba(181,64,58,0.8)',
            tension: 0.35,
            fill: false,
          },
          {
            label: 'Smooth',
            data: [],
            borderColor: '#B5403A',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.5,
            fill: false,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        interaction: commonInteraction,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            display: true,
            ticks: { color: commonText, maxTicksLimit: 5, font: { size: 10 } },
            grid: commonGrid,
          },
          y: {
            display: true,
            title: { display: false },
            ticks: { color: commonText, font: { size: 10 } },
            grid: commonGrid,
          }
        }
      }
    })
    }
  }

  // ── Token Accuracy 小图 ──
  if (accuracyChartCanvas.value) {
    const acCtx = accuracyChartCanvas.value.getContext('2d')
    if (acCtx) {
    accuracyChart = new Chart(acCtx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [
          {
            label: 'Accuracy',
            data: [],
            borderColor: '#E4572E',
            backgroundColor: (ctx) => {
              const gradient = ctx.chart.ctx.createLinearGradient(0, 0, 0, ctx.chart.height)
              gradient.addColorStop(0, 'rgba(228,87,46,0.15)')
              gradient.addColorStop(1, 'rgba(228,87,46,0.02)')
              return gradient
            },
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.4,
            fill: true,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 200 },
        interaction: commonInteraction,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label(ctx) { return `Accuracy: ${((ctx.raw || 0) * 100).toFixed(1)}%` }
            }
          }
        },
        scales: {
          x: {
            display: true,
            ticks: { color: commonText, maxTicksLimit: 5, font: { size: 10 } },
            grid: commonGrid,
          },
          y: {
            display: true,
            title: { display: false },
            min: 0,
            max: 1,
            ticks: { color: commonText, font: { size: 10 }, callback: (v) => `${(v * 100).toFixed(0)}%` },
            grid: commonGrid,
          }
        }
      }
    })
    }
  }
}

/**
 * 计算简单移动平均（用于平滑线）
 */
function smoothArray(values, windowSize = 5) {
  if (!values || values.length === 0) return []
  const result = []
  for (let i = 0; i < values.length; i++) {
    const start = Math.max(0, i - Math.floor(windowSize / 2))
    const end = Math.min(values.length, i + Math.floor(windowSize / 2) + 1)
    const slice = values.slice(start, end)
    result.push(slice.reduce((a, b) => a + b, 0) / slice.length)
  }
  return result
}

/**
 * 更新所有训练图表数据
 */
function updateCharts(step, lossSmooth, lossRaw, lr, gradNorm, accuracy) {
  // 追加历史数据（保存 EMA 平滑值作为主 loss）
  trainLossHistory.value.push({ step, loss: lossSmooth, loss_raw: lossRaw })
  trainLrHistory.value.push({ step, lr })
  trainGradNormHistory.value.push({ step, grad_norm: gradNorm })

  // 更新 Loss 主图
  if (lossChart) {
    lossChart.data.labels.push(step)
    lossChart.data.datasets[0].data.push(lossRaw != null ? lossRaw : lossSmooth)
    lossChart.data.datasets[1].data.push(lossSmooth)
    lossChart.data.datasets[2].data.push(lr)
    lossChart.update()
  }

  // 更新 Grad Norm 小图
  if (gradNormChart) {
    gradNormChart.data.labels.push(step)
    gradNormChart.data.datasets[0].data.push(gradNorm)
    const recentGrads = trainGradNormHistory.value.map(d => d.grad_norm)
    const smoothed = smoothArray(recentGrads, 5)
    gradNormChart.data.datasets[1].data = smoothed
    gradNormChart.update()
  }

  // 更新 Token Accuracy 小图
  if (accuracyChart) {
    if (accuracy != null) {
      accuracyChart.data.labels.push(step)
      accuracyChart.data.datasets[0].data.push(accuracy)
      accuracyChart.update()
    }
  }
}

async function trainFromDatasets() {
  if (isTraining.value) return
  if (!selectedDatasetIds.value.length) {
    showToast('请至少选择一个训练数据集', 'warning')
    return
  }
  if (!trainModelName.value.trim()) {
    showToast('请填写模型名称', 'warning')
    return
  }

  isTraining.value = true
  trainProgress.value = null
  trainStatusMsg.value = '正在准备训练数据...'
  trainStartTime.value = Date.now()

  trainLossHistory.value = []
  trainLrHistory.value = []
  trainGradNormHistory.value = []
  trainLogMessages.value = []

  if (lossChart && typeof lossChart.destroy === 'function') { lossChart.destroy(); lossChart = null }
  if (gradNormChart && typeof gradNormChart.destroy === 'function') { gradNormChart.destroy(); gradNormChart = null }
  if (accuracyChart && typeof accuracyChart.destroy === 'function') { accuracyChart.destroy(); accuracyChart = null }
  await nextTick()
  initCharts()

  try {
    const response = await fetch(`${API_BASE}/model/train-from-dataset`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset_ids: selectedDatasetIds.value,
        model_name: trainModelName.value.trim(),
        epochs: trainEpochs.value,
        batch_size: trainBatchSize.value,
        lr: trainLearningRate.value,
      }),
    })

    if (!response.ok) {
      let errMsg = `服务器错误 (${response.status})`
      try {
        const errData = await response.json()
        errMsg = errData.message || errMsg
      } catch (_) { /* ignore */ }
      throw new Error(errMsg)
    }
    if (!response.body) throw new Error('服务器返回空响应')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let trainingCompleted = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        if (trainingCompleted) continue
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === 'status') {
            trainStatusMsg.value = data.message
          } else if (data.type === 'progress') {
            trainProgress.value = data
            const currentEpoch = Math.floor(data.epoch) + 1
            trainStatusMsg.value = `Epoch ${currentEpoch}/${trainEpochs.value} · Step ${data.step}/${data.max_steps}`
            const step = data.step ?? trainLossHistory.value.length + 1
            if (data.loss != null) {
              updateCharts(
                step,
                data.loss_smooth ?? data.loss,
                data.loss,
                data.learning_rate ?? 0,
                data.grad_norm ?? 0,
                data.accuracy ?? null
              )
            }
          } else if (data.type === 'complete') {
            trainingCompleted = true
            const finalLoss = trainProgress.value?.loss
            trainProgress.value = data.result
            trainProgress.value.finalLoss = finalLoss
            trainStatusMsg.value = '训练完成！'
            trainStartTime.value = null
            await fetchSavedModels()
            showTrainCompleteModal.value = true
            trainCompleteResult.value = data.result
          } else if (data.type === 'validation') {
            trainProgress.value = { ...trainProgress.value, val_loss: data.val_loss, val_accuracy: data.val_accuracy }
            trainLogMessages.value.push(`[验证] loss=${data.val_loss.toFixed(4)} acc=${(data.val_accuracy * 100).toFixed(1)}%`)
          } else if (data.type === 'error') {
            showToast('训练失败: ' + data.message, 'error')
            console.error(data.detail)
          } else if (data.type === 'log') {
            trainLogMessages.value.push(data.message)
            nextTick(() => {
              if (trainLogPanel.value) trainLogPanel.value.scrollTop = trainLogPanel.value.scrollHeight
            })
          }
        } catch (_) { /* ignore */ }
      }
    }
  } catch (error) {
    showToast('训练失败: ' + (error.message || '连接中断'), 'error')
  } finally {
    isTraining.value = false
    trainStartTime.value = null
  }
}

/**
 * 计算训练进度百分比
 */
const trainProgressPercent = computed(() => {
  if (!trainProgress.value || !trainProgress.value.step || !trainProgress.value.max_steps) return 0
  return Math.round((trainProgress.value.step / trainProgress.value.max_steps) * 100)
})

/**
 * 关闭训练完成弹窗
 */
function closeTrainCompleteModal() {
  showTrainCompleteModal.value = false
  trainCompleteResult.value = null
  trainModelName.value = ''
  trainProgress.value = null
}

/**
 * 查看模型详情（点击左侧模型卡片）
 */
async function viewModelDetail(modelId) {
  selectedModelId.value = modelId
  modelDetailLoading.value = true
  selectedModelMeta.value = null
  try {
    const response = await axios.get(`${API_BASE}/models/${modelId}`)
    selectedModelMeta.value = response.data
    modelDetailLoading.value = false
    // 用 setTimeout 确保 Vue 完成 canvas DOM 渲染后再画图
    setTimeout(() => renderHistoryCharts(), 80)
  } catch {
    modelDetailLoading.value = false
    showToast('加载模型详情失败', 'error')
  }
}

/**
 * 渲染模型历史训练曲线
 */
function renderHistoryCharts() {
  const meta = selectedModelMeta.value
  if (!meta || !meta.training_history || !meta.training_history.length) return

  if (historyLossChart) { historyLossChart.destroy(); historyLossChart = null }
  if (historyGradChart) { historyGradChart.destroy(); historyGradChart = null }

  const history = meta.training_history
  const steps = history.map(d => d.step)
  const losses = history.map(d => d.loss_smooth ?? d.loss)
  const lossesRaw = history.map(d => d.loss)
  const lrs = history.map(d => d.learning_rate)
  const gradNorms = history.map(d => d.grad_norm)

  const commonGrid = { color: 'rgba(148,163,184,0.08)' }
  const commonText = '#64748b'

  if (historyLossChartCanvas.value) {
    const ctx = historyLossChartCanvas.value.getContext('2d')
    if (ctx) {
      historyLossChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: steps,
          datasets: [
            { label: 'Loss (raw)', data: lossesRaw, borderColor: 'rgba(148,163,184,0.35)', borderWidth: 0.8, pointRadius: 0, tension: 0.2, fill: false, yAxisID: 'y', borderDash: [3,6] },
            { label: 'Loss (smooth)', data: losses, borderColor: '#2F7D5B', borderWidth: 2, pointRadius: 0, tension: 0.4, fill: true, yAxisID: 'y',
              backgroundColor: (c) => { const g = c.chart.ctx.createLinearGradient(0,0,0,c.chart.height); g.addColorStop(0,'rgba(47,125,91,0.15)'); g.addColorStop(1,'rgba(47,125,91,0.02)'); return g; }
            },
            { label: 'LR', data: lrs, borderColor: '#A9761E', borderWidth: 1.5, pointRadius: 0, tension: 0.4, fill: false, yAxisID: 'y1', borderDash: [5,3] }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { intersect: false, mode: 'index' },
          plugins: {
            legend: { labels: { color: '#94a3b8', usePointStyle: true, padding: 16, font: { size: 11 } } },
            tooltip: {
              callbacks: {
                label(ctx) {
                  if (ctx.datasetIndex === 1) return `LR: ${(ctx.raw || 0).toExponential(2)}`
                  return `Loss: ${(ctx.raw || 0).toFixed(4)}`
                }
              }
            }
          },
          scales: {
            x: { ticks: { color: commonText, maxTicksLimit: 10 }, grid: commonGrid },
            y: { type: 'linear', position: 'left', title: { display: true, text: 'Loss', color: commonText }, ticks: { color: commonText }, grid: commonGrid },
            y1: { type: 'linear', position: 'right', title: { display: true, text: 'LR', color: commonText }, ticks: { color: commonText, callback: v => v.toExponential(1) }, grid: { drawOnChartArea: false } }
          }
        }
      })
    }
  }

  if (historyGradChartCanvas.value) {
    const ctx = historyGradChartCanvas.value.getContext('2d')
    if (ctx) {
      historyGradChart = new Chart(ctx, {
        type: 'line',
        data: {
          labels: steps,
          datasets: [
            { label: 'Grad Norm', data: gradNorms, borderColor: '#B5403A', borderWidth: 1.5, pointRadius: 0, tension: 0.35, fill: false }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { intersect: false, mode: 'index' },
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: commonText, maxTicksLimit: 10, font: { size: 10 } }, grid: commonGrid },
            y: { ticks: { color: commonText, font: { size: 10 } }, grid: commonGrid }
          }
        }
      })
    }
  }
}

/**
 * 下载模型文件
 */
function downloadModel(modelId) {
  const link = document.createElement('a')
  link.href = `${API_BASE}/model/download/${modelId}`
  link.download = ''
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function onEvalFileChange(event) {
  const file = event.target.files?.[0]
  if (file) evalTestFile.value = file
}

async function runEvaluation() {
  if (!evalTestFile.value || !evalModelId.value.trim() || isEvaluating.value) return

  isEvaluating.value = true
  evalResult.value = null

  const formData = new FormData()
  formData.append('file', evalTestFile.value)
  formData.append('model_id', evalModelId.value.trim())

  try {
    const response = await axios.post(`${API_BASE}/model/evaluate`, formData)
    evalResult.value = response.data

    // 画每类 F1 柱状图
    await nextTick()
    if (evalF1ChartCanvas.value) {
      if (evalF1Chart) evalF1Chart.destroy()
      const ctx = evalF1ChartCanvas.value.getContext('2d')
      if (ctx) {
        const perClass = evalResult.value.per_class || {}
        const labels = Object.keys(perClass)
        const f1Values = labels.map(l => perClass[l].f1)
        const colors = labels.map((_, i) => {
          const hue = (i * 137.5) % 360
          return `hsla(${hue}, 65%, 55%, 0.8)`
        })
        evalF1Chart = new Chart(ctx, {
          type: 'bar',
          data: {
            labels,
            datasets: [{
              label: 'F1 Score',
              data: f1Values,
              backgroundColor: colors,
              borderRadius: 4,
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              y: { beginAtZero: true, max: 1, ticks: { callback: v => (v * 100).toFixed(0) + '%' } }
            }
          }
        })
      }
    }
    showToast('评估完成', 'success')
  } catch (e) {
    showToast('评估失败: ' + (e.response?.data?.message || e.message), 'error')
  } finally {
    isEvaluating.value = false
  }
}

// Watch page switch to load models
watch(currentPage, (page) => {
  if (page === 'models') {
    fetchSavedModels()
    fetchDatasets()
  }
})

function focusAnnotation(entry) {
  if (!mdBodyRef.value) return

  let targetEl = null

  // 按 entity-id 精确匹配
  if (entry?.id) {
    targetEl = mdBodyRef.value.querySelector(
      `.annotation-highlight[data-entity-id="${CSS.escape(entry.id)}"]`
    )
  }

  // 回退：按 entity text 匹配（处理极端情况）
  if (!targetEl && entry?.text) {
    targetEl = mdBodyRef.value.querySelector(
      `.annotation-highlight[data-entity-text="${CSS.escape(entry.text)}"]`
    )
  }

  if (!targetEl) {
    showToast('未找到对应高亮', 'info')
    return
  }

  targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  targetEl.classList.add('annotation-highlight-focus')
  window.setTimeout(() => {
    targetEl.classList.remove('annotation-highlight-focus')
  }, 2000)
}

function getSnippetColor(snippet) {
  const label = snippet?.rule_label || snippet?.rule_id || ''
  return getLabelColor(label).solid
}

function truncateContext(context, maxLen) {
  if (!context || context.length <= maxLen) return context
  return context.substring(0, maxLen) + '...'
}

function goToPrevSnippet() {
  if (currentSnippetIndex.value > 0) {
    currentSnippetIndex.value--
    focusCurrentSnippet()
    scrollActiveSnippetIntoView()
  }
}

function goToNextSnippet() {
  if (currentSnippetIndex.value < annotationSnippets.value.length - 1) {
    currentSnippetIndex.value++
    focusCurrentSnippet()
    scrollActiveSnippetIntoView()
  }
}

function goToSnippet(index) {
  if (index >= 0 && index < annotationSnippets.value.length) {
    currentSnippetIndex.value = index
    focusCurrentSnippet()
    scrollActiveSnippetIntoView()
  }
}

function scrollActiveSnippetIntoView() {
  nextTick(() => {
    const card = document.querySelector('.annotation-snippet-card.active')
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function focusCurrentSnippet() {
  const snippet = currentSnippet.value
  if (snippet) focusAnnotation(snippet)
}

function animateAnnotationHighlights() {
  const container = mdBodyRef.value
  if (!container) return

  // Double rAF to ensure browser has finished layout after v-html update
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      _startAnnotationScan(container)
    })
  })
}

function _startAnnotationScan(container) {
  const highlights = Array.from(container.querySelectorAll('.annotation-highlight'))
  if (!highlights.length) return

  const containerRect = container.getBoundingClientRect()
  const sorted = highlights.map(el => ({
    el,
    top: el.getBoundingClientRect().top - containerRect.top + container.scrollTop
  })).sort((a, b) => a.top - b.top)

  sorted.forEach(({ el }) => el.classList.add('annotation-pending'))

  const totalHeight = container.scrollHeight
  const duration = Math.min(4200, Math.max(1600, totalHeight * 4.5))
  annotationScanActive.value = true

  const preGlowDistance = 80
  const startTime = performance.now()

  function frame(now) {
    const elapsed = now - startTime
    const progress = Math.min(elapsed / duration, 1)
    const scanY = progress * totalHeight

    scanLineY.value = scanY

    // Pre-glow: highlights near the scan line get a warm glow before full reveal
    // Full reveal: highlights above the scan line are revealed
    sorted.forEach(({ el, top }) => {
      const dist = top - scanY
      if (dist <= 0) {
        // Passed by scan line — fully reveal
        if (el.classList.contains('annotation-pending')) {
          el.classList.remove('annotation-pending')
          el.classList.add('annotation-revealed')
        }
        el.classList.remove('annotation-glowing')
      } else if (dist <= preGlowDistance) {
        // Approaching — warm pre-glow
        el.classList.add('annotation-glowing')
      } else {
        el.classList.remove('annotation-glowing')
      }
    })

    if (progress < 1) {
      requestAnimationFrame(frame)
    } else {
      sorted.forEach(({ el }) => {
        el.classList.remove('annotation-pending', 'annotation-revealed', 'annotation-glowing')
      })
      annotationScanActive.value = false
    }
  }

  requestAnimationFrame(frame)
}

async function fetchHistory(retryOnStartup = false) {
  if (isHistoryLoading.value) return
  isHistoryLoading.value = true
  try {
    const url = `${API_BASE}/history`
    const response = retryOnStartup ? await getWithStartupRetry(url) : await axios.get(url)
    historyRecords.value = response.data || []
  } catch (error) {
    showToast('无法加载历史记录', 'error')
  } finally {
    isHistoryLoading.value = false
  }
}

async function confirmDeleteHistory() {
  const taskId = pendingDeleteId.value
  if (!taskId) return
  pendingDeleteId.value = null
  try {
    await axios.delete(`${API_BASE}/history/${taskId}`)
    historyRecords.value = historyRecords.value.filter(r => r.task_id !== taskId)
    if (taskInfo.task_id === taskId) {
      Object.assign(taskInfo, {
        task_id: null,
        status: 'idle',
        progress: 0,
        message: '',
        file_name: '',
        feature_summary: []
      })
      wizardStep.value = 1
      pdfUrl.value = ''
      renderedMarkdown.value = ''
      rawMarkdown.value = ''
    }
    showToast('历史记录已删除', 'success')
  } catch (e) {
    const msg = e.response?.data?.message || e.message || '网络错误'
    showToast(`删除失败: ${msg}`, 'error')
  }
}

function cancelDelete() {
  pendingDeleteId.value = null
}

async function loadHistoryTask(record) {
  if (taskInfo.task_id === record.task_id) return
  
  reset()
  Object.assign(taskInfo, {
    task_id: record.task_id,
    file_name: record.file_name,
    status: record.status,
    progress: record.status === 'completed' ? 100 : 0,
    feature_summary: record.feature_summary || []
  })
  
  if (record.status === 'completed') {
    wizardStep.value = 4
    await fetchResults()
  } else if (record.status === 'failed') {
    wizardStep.value = 3
    taskInfo.message = '该任务已失败'
  } else {
    wizardStep.value = 3
    startPolling()
  }
  
  if (window.innerWidth <= 768) {
    sidebarCollapsed.value = true
  }
}

function startClock() {
  stopClock()
  nowTick.value = Date.now()
  clockTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
}

async function uploadFile() {
  if (!selectedFile.value || isUploading.value) return
  isUploading.value = true
  const formData = new FormData()
  formData.append('file', selectedFile.value)
  Object.entries(parseConfig).forEach(([key, value]) => formData.append(key, String(value)))
  try {
    const response = await axios.post(`${API_BASE}/upload`, formData)
    Object.assign(taskInfo, response.data)
    startClock()
    wizardStep.value = 3
    fetchHistory() // Refresh history after upload
    startPolling()
  } catch (error) {
    const message = error.response?.data?.detail || error.message || '未知错误'
    showToast(`上传失败: ${message}`, 'error')
  } finally {
    isUploading.value = false
  }
}

function stopPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval)
    pollingInterval = null
  }
}

function stopClock() {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
}

function stopProcessingState() {
  stopPolling()
  stopClock()
}

function startPolling() {
  stopPolling()
  pollingInterval = setInterval(async () => {
    try {
      const response = await axios.get(`${API_BASE}/progress/${taskInfo.task_id}`)
      Object.assign(taskInfo, response.data)
      if (taskInfo.status === 'completed') {
        stopProcessingState()
        wizardStep.value = 4
        await fetchResults()
        showToast('文档解析完成！', 'success')
      } else if (taskInfo.status === 'failed') {
        stopProcessingState()
        showToast(`解析失败: ${taskInfo.message || '未知错误'}`, 'error')
      }
    } catch {
      // polling errors are non-fatal
    }
  }, 800)
}

async function fetchResults() {
  const tid = taskInfo.task_id
  if (!tid) return

  pdfUrl.value = `${API_BASE}/result/${tid}/pdf`
  pdfLoading.value = true
  pdfLoadError.value = false

  mdLoading.value = true
  mdLoadError.value = false
  renderedMarkdown.value = ''

  try {
    const mdResponse = await axios.get(`${API_BASE}/result/${tid}/md`)
    let mdText = mdResponse.data
    if (typeof mdText === 'object') {
      mdText = mdText.markdown || mdText.content || JSON.stringify(mdText, null, 2)
    }
    rawMarkdown.value = mdText
    refreshMarkdownView()
  } catch {
    mdLoadError.value = true
    showToast('Markdown 结果加载失败', 'error')
  } finally {
    mdLoading.value = false
    await nextTick()
  }
}

function onPdfLoad() {
  pdfLoading.value = false
  pdfLoadError.value = false
}

function onPdfError() {
  pdfLoading.value = false
  pdfLoadError.value = true
}

function retryLoadPdf() {
  pdfLoadError.value = false
  pdfLoading.value = true
  const tid = taskInfo.task_id
  if (tid) pdfUrl.value = `${API_BASE}/result/${tid}/pdf?t=${Date.now()}`
}

function retryLoadMd() {
  fetchResults()
}

async function copyMarkdown() {
  if (!rawMarkdown.value) return
  try {
    await navigator.clipboard.writeText(rawMarkdown.value)
    showToast('Markdown 已复制到剪贴板', 'success')
  } catch {
    showToast('复制失败，请手动复制', 'error')
  }
}

function startEdit() {
  const scrollTop = mdBodyRef.value?.scrollTop || 0
  isEditing.value = true
  refreshMarkdownView()
  nextTick(() => {
    if (mdBodyRef.value) {
      mdBodyRef.value.scrollTop = scrollTop
    }
    editableRef.value?.focus({ preventScroll: true })
  })
}

function persistScroll() {
  return mdBodyRef.value?.scrollTop || 0
}

function restoreScroll(top) {
  nextTick(() => {
    if (mdBodyRef.value) {
      mdBodyRef.value.scrollTop = top
    }
  })
}

function cancelEdit() {
  const scrollTop = persistScroll()
  isEditing.value = false
  refreshMarkdownView()
  mdViewKey.value++
  restoreScroll(scrollTop)
}

async function saveEdit() {
  const tid = taskInfo.task_id
  if (!tid || isSaving.value) return
  const el = editableRef.value
  if (!el) return
  isSaving.value = true
  const scrollTop = persistScroll()
  try {
    let html = el.innerHTML
    // Reverse image URL rewrites back to relative paths
    html = html.replace(new RegExp(API_BASE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '/result/' + tid + '/images/', 'g'), 'images/')
    const mdText = turndownService.turndown(html)
    await axios.put(`${API_BASE}/result/${tid}/md`, { content: mdText })
    rawMarkdown.value = mdText
    isEditing.value = false
    resetAnnotationState()
    refreshMarkdownView()
    mdViewKey.value++
    restoreScroll(scrollTop)
    showToast('Markdown 已保存', 'success')
  } catch (e) {
    const msg = e.response?.data?.message || e.message || '保存失败'
    showToast(`保存失败: ${msg}`, 'error')
  } finally {
    isSaving.value = false
  }
}

function reset() {
  clearFile()
  stopProcessingState()
  Object.assign(taskInfo, {
    task_id: null,
    status: 'idle',
    progress: 0,
    message: '',
    file_name: '',
    feature_summary: [],
    started_at: null,
    updated_at: null,
    eta_seconds: null,
    estimated_total_seconds: null,
    stage_index: 0,
    stage_label: ''
  })
  pdfUrl.value = ''
  renderedMarkdown.value = ''
  rawMarkdown.value = ''
  splitMode.value = 'horizontal'
  pdfFullscreen.value = false
  mdFullscreen.value = false
  wizardStep.value = 1
  isUploading.value = false
  pdfLoading.value = false
  pdfLoadError.value = false
  mdLoading.value = false
  mdLoadError.value = false
  isEditing.value = false
  resetAnnotationState()
}

function startResize(event) {
  const container = event.target.closest('.panels-container')
  const isHorizontal = splitMode.value === 'horizontal'
  const startPos = isHorizontal ? event.clientX : event.clientY
  const panels = container.querySelectorAll('.panel')
  const startSize = isHorizontal ? panels[0].offsetWidth : panels[0].offsetHeight

  const onMove = (e) => {
    const delta = (isHorizontal ? e.clientX : e.clientY) - startPos
    const total = (isHorizontal ? container.clientWidth : container.clientHeight) - 6
    let ratio = ((startSize + delta) / total) * 100
    ratio = Math.max(20, Math.min(80, ratio))
    container.style.setProperty('--panel-a-pct', `${ratio}%`)
    container.style.setProperty('--panel-b-pct', `${100 - ratio}%`)
  }

  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }

  document.body.style.cursor = isHorizontal ? 'col-resize' : 'row-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

watch(splitMode, () => {
  pdfFullscreen.value = false
  mdFullscreen.value = false
})

function onKeydown(e) {
  if (e.ctrlKey && e.key === 's' && isEditing.value) {
    e.preventDefault()
    saveEdit()
  }
}

onMounted(() => {
  loadOptions(true)
  loadAnnotationOptions(true)
  fetchHistory(true)
  fetchDatasets(true)
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  stopProcessingState()
  window.removeEventListener('keydown', onKeydown)
})

</script>




