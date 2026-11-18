<script setup lang="ts">
import { computed, ref } from "vue";

import FileDrop from "./FileDrop.vue";
import { formatFileSize } from "../format";
import type { PendingAnalysis, PendingItem } from "../types";

const props = defineProps<{
  analysis: PendingAnalysis | null;
  busy: boolean;
  error: string | null;
  file: File | null;
}>();

const emit = defineEmits<{
  upload: [file: File];
  clear: [];
  back: [];
  next: [];
}>();

const query = ref("");
const statusFilter = ref("");

const codeLabel = computed(() => props.analysis?.columns.code || "标准号");
const nameLabel = computed(() => props.analysis?.columns.name || "标准名称");

const singleUnitCount = computed(() =>
  Math.max(
    0,
    (props.analysis?.auto_count ?? 0) - (props.analysis?.multi_unit_count ?? 0),
  ),
);

const uniqueNameCount = computed(() => {
  const names = new Set<string>();
  for (const item of props.analysis?.items ?? []) {
    const name = item.name.trim();
    if (name) names.add(name);
  }
  return names.size;
});

const namedGroupCount = computed(
  () =>
    (props.analysis?.items ?? []).filter((item) => item.name.trim()).length,
);

const sameNameGroups = computed(() => {
  const counts = new Map<string, number>();
  for (const item of props.analysis?.items ?? []) {
    const name = item.name.trim();
    if (name) counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const entries = [...counts.entries()].filter(([, count]) => count > 1);
  return {
    names: entries.length,
    groups: entries.reduce((total, [, count]) => total + count, 0),
  };
});

const filteredItems = computed(() => {
  const items = props.analysis?.items ?? [];
  const keyword = query.value.trim().toLowerCase();
  return items.filter((item) => {
    if (statusFilter.value === "auto" && item.status !== "auto") return false;
    if (statusFilter.value === "manual" && item.status !== "manual") return false;
    if (statusFilter.value === "confirm" && !item.needs_confirmation) return false;
    if (!keyword) return true;
    const text = `${item.code} ${item.name}`.toLowerCase();
    return text.includes(keyword);
  });
});

function reasonText(item: PendingItem): string {
  if (item.status === "manual") return item.reason || "需人工判断";
  if (item.needs_confirmation) return "同号同名多单位，需确认";
  return "无歧义";
}

function reasonClass(item: PendingItem): string {
  if (item.status === "manual") return "cell-reason-warning";
  if (item.needs_confirmation) return "cell-reason-info";
  return "cell-reason-muted";
}
</script>

<template>
  <section class="step-body">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">上传待分类目录</h2>
          <p class="panel-desc">
            上传需要判断的标准清单。系统按{{ codeLabel }} + {{ nameLabel }}归并，
            并区分可自动分类与需要人工分类的数据。
          </p>
        </div>
        <span class="panel-step">第 2 步</span>
      </div>

      <div v-if="busy" class="progress-line" role="progressbar" aria-label="正在分析文件"></div>

      <FileDrop
        label="选择待分类 Excel"
        hint="拖入文件，或点击选择 .xlsx / .xlsm"
        :file="file"
        :busy="busy"
        @select="emit('upload', $event)"
        @clear="emit('clear')"
      />

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>

      <div class="file-requirements">
        <span class="req-title">文件要求</span>
        <ul class="req-list">
          <li><b>必需列</b>标准名称</li>
          <li><b>建议列</b>标准号</li>
          <li><b>归并规则</b>按标准号 + 标准名称；GB/T 与 GB 视为同一号</li>
          <li><b>格式</b>.xlsx / .xlsm，最大 20MB</li>
        </ul>
      </div>

      <div v-if="analysis" class="file-summary">
        <span class="file-summary-name">{{ analysis.file.name }}</span>
        <span>{{ analysis.file.sheet }} 工作表</span>
        <span>{{ formatFileSize(analysis.file.size) }}</span>
        <span class="tag tag-success">已读取</span>
      </div>
    </div>

    <template v-if="analysis">
      <div class="panel">
        <div class="panel-head panel-head-compact">
          <div>
            <h2 class="panel-title">数据处理路径</h2>
            <p class="panel-desc">
              从原始 Excel 行到最终分类的层级关系；越往下越具体，数字不并列。
            </p>
          </div>
        </div>

        <div class="flow-summary">
          <div class="flow-step">
            <div class="flow-node">
              <span class="flow-label">原始 Excel 行</span>
              <strong class="flow-value">{{ analysis.raw_rows }}</strong>
              <span class="flow-note">包含同一标准在多个主营单位下的重复行</span>
            </div>
          </div>

          <div class="flow-connector" aria-hidden="true"></div>

          <div class="flow-step">
            <div class="flow-node flow-node-primary">
              <span class="flow-label">去重后的标准组</span>
              <strong class="flow-value">{{ analysis.unique_rows }}</strong>
              <span class="flow-note">
                只合并{{ codeLabel }} + {{ nameLabel }}都完全相同的行；
                同名不同号不合并，仍保留在 {{ analysis.unique_rows }} 内。
                GB/T 与 GB 视为同一号；重复行导出时逐行回填。
              </span>
              <div class="flow-sub">
                <span class="flow-sub-item">唯一名称 {{ uniqueNameCount }}</span>
                <span class="flow-sub-item">
                  同名不同号 {{ sameNameGroups.names }} 个名称 /
                  {{ sameNameGroups.groups }} 条
                </span>
              </div>
              <span class="flow-note">
                {{ uniqueNameCount }} 个名称 +
                {{ sameNameGroups.groups - sameNameGroups.names }} 条额外版本 =
                {{ namedGroupCount }} 条有名标准组
                <template v-if="namedGroupCount !== analysis.unique_rows">
                  ，另有
                  {{ analysis.unique_rows - namedGroupCount }} 条缺少名称
                </template>
              </span>
            </div>
          </div>

          <div class="flow-connector" aria-hidden="true"></div>

          <div class="flow-step flow-branches">
            <div class="flow-node flow-node-auto">
              <span class="flow-label">自动分类</span>
              <strong class="flow-value">{{ analysis.auto_count }}</strong>
              <span class="flow-note">无歧义，交给模型</span>
              <div class="flow-sub">
                <span class="flow-sub-item">单单位 {{ singleUnitCount }}</span>
                <span class="flow-sub-item">
                  多单位待确认 {{ analysis.multi_unit_count }}
                </span>
              </div>
            </div>

            <div class="flow-node flow-node-manual">
              <span class="flow-label">人工分类</span>
              <strong class="flow-value">{{ analysis.manual_count }}</strong>
              <span class="flow-note">
                同名不同号 {{ sameNameGroups.names }} 个名称 /
                {{ sameNameGroups.groups }} 条标准组；
                只匹配到号或名、缺少字段的也在这里
              </span>
              <div class="flow-sub">
                <span class="flow-sub-item">不调用模型，由用户选择专业</span>
              </div>
            </div>
          </div>

          <p class="flow-equation">
            {{ analysis.auto_count }} + {{ analysis.manual_count }} =
            {{ analysis.unique_rows }} 条标准组。这里的
            {{ analysis.unique_rows }} 是「{{ codeLabel }} + {{ nameLabel }}」的组合数，
            不是名称数。同名不同号共 {{ sameNameGroups.groups }} 条（涉及
            {{ sameNameGroups.names }} 个名称），仍在 {{ analysis.unique_rows }} 内，
            只是被分流到人工分类。多单位待确认
            {{ analysis.multi_unit_count }} 条已经包含在自动分类
            {{ analysis.auto_count }} 条里面，不是另一类。
          </p>
        </div>

        <div v-if="analysis.missing_name_count" class="notice notice-danger">
          有 {{ analysis.missing_name_count }} 行缺少{{ nameLabel }}，这些行会保留在导出表中，但需要人工处理。
        </div>
      </div>

      <div class="panel">
        <div class="panel-head panel-head-compact">
          <div>
            <h2 class="panel-title">标准清单与处理方式</h2>
            <p class="panel-desc">
              人工分类的标准不会调用模型；导出时会回到原始 Excel 的每一行。
            </p>
          </div>
          <div class="toolbar">
            <input
              v-model="query"
              class="gb-input search-input"
              type="search"
              placeholder="搜索标准号或标准名称"
              aria-label="搜索待分类标准"
            />
            <select v-model="statusFilter" class="select" aria-label="按处理方式筛选">
              <option value="">全部处理方式</option>
              <option value="auto">自动分类</option>
              <option value="manual">人工分类</option>
              <option value="confirm">多单位待确认</option>
            </select>
          </div>
        </div>

        <div class="table-wrap table-wrap-results">
          <table class="data-table">
            <thead>
              <tr>
                <th scope="col">{{ codeLabel }}</th>
                <th scope="col">{{ nameLabel }}</th>
                <th scope="col">处理方式</th>
                <th scope="col">原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredItems" :key="item.index">
                <td class="cell-mono">{{ item.code || "—" }}</td>
                <td class="cell-name" :title="item.name">{{ item.name || "—" }}</td>
                <td>
                  <span v-if="item.status === 'manual'" class="tag tag-warning">
                    人工分类
                  </span>
                  <span v-else-if="item.needs_confirmation" class="tag tag-info">
                    自动 · 待确认
                  </span>
                  <span v-else class="tag tag-success">自动分类</span>
                </td>
                <td class="cell-reason" :class="reasonClass(item)">
                  {{ reasonText(item) }}
                </td>
              </tr>
              <tr v-if="!filteredItems.length">
                <td colspan="4" class="table-empty">没有符合当前条件的标准。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="step-actions">
        <button class="gb-btn btn-secondary" type="button" @click="emit('back')">
          返回数据体检
        </button>
        <button class="gb-btn gb-btn-primary" type="button" @click="emit('next')">
          下一步：执行分类
        </button>
      </div>
    </template>
  </section>
</template>
