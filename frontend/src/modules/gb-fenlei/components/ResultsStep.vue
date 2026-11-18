<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { resolveDownloadUrl } from "../api";
import { percent } from "../format";
import type {
  ClassifyResponse,
  ExportResponse,
  ResultRow,
} from "../types";

const props = defineProps<{
  result: ClassifyResponse;
  overrides: Record<string, string>;
  exporting: boolean;
  exportResult: ExportResponse | null;
  exportError: string | null;
}>();

const emit = defineEmits<{
  override: [index: number, profession: string];
  export: [];
}>();

type ViewMode = "auto" | "manual";

const mode = ref<ViewMode>(
  props.result.summary.auto_count > 0 ? "auto" : "manual",
);
const search = ref("");
const professionFilter = ref("");
const lowOnly = ref(false);
const confirmOnly = ref(false);
const page = ref(1);
const confirmed = ref<Set<number>>(new Set());
const expanded = ref<Set<number>>(new Set());
const pageSize = 50;

function toggleDetail(row: ResultRow): void {
  const next = new Set(expanded.value);
  if (next.has(row.index)) {
    next.delete(row.index);
  } else {
    next.add(row.index);
  }
  expanded.value = next;
}

function evidenceSummary(row: ResultRow): string {
  if (!row.evidence?.length) return "—";
  return row.evidence[0];
}

function evidenceTitle(row: ResultRow): string {
  return (row.evidence ?? []).join("\n") || "无依据";
}

const EVIDENCE_LEVEL_LABELS: Record<string, string> = {
  reference: "参照表",
  ensemble: "统计集成",
  term: "关键词统计",
  similar: "相似名称",
  nb: "字符统计",
  model: "模型兜底",
  manual: "人工",
  // 旧版规则引擎的返回值，仅用于兼容历史结果。
  rule: "规则（旧版）",
};

function evidenceLevelLabel(level: string): string {
  return EVIDENCE_LEVEL_LABELS[level] ?? level;
}

const codeLabel = computed(() => props.result.columns.code || "标准号");
const nameLabel = computed(() => props.result.columns.name || "标准名称");
const systemLabel = computed(
  () => props.result.columns.system || "选用系统名称",
);
const professionLabel = computed(
  () => props.result.columns.profession || "选用专业名称",
);

const categoryMap = computed(() => {
  const map = new Map<string, string>();
  for (const item of props.result.categories) {
    map.set(item.profession, item.system);
  }
  return map;
});

const autoRows = computed(() => props.result.auto_rows ?? []);
const manualRows = computed(() => props.result.manual_rows ?? []);

function currentProfession(row: ResultRow): string {
  return props.overrides[String(row.index)] ?? row.profession;
}

function isCorrected(row: ResultRow): boolean {
  const override = props.overrides[String(row.index)];
  return override !== undefined && override !== row.profession;
}

function isManualSelected(row: ResultRow): boolean {
  return Boolean(props.overrides[String(row.index)]);
}

function currentSystem(row: ResultRow): string {
  const profession = currentProfession(row);
  if (!isCorrected(row) && row.status === "auto") return row.system;
  return categoryMap.value.get(profession) ?? row.system;
}

function isConfirmed(row: ResultRow): boolean {
  return confirmed.value.has(row.index);
}

function unitsSummary(units: string[]): string {
  if (!units.length) return "—";
  if (units.length <= 2) return units.join("、");
  return `${units.slice(0, 2).join("、")} 等 ${units.length} 个单位`;
}

function unitsTitle(units: string[]): string {
  return units.length ? units.join("、") : "未填写主营单位";
}

function visibleBaseRows(): ResultRow[] {
  return mode.value === "auto" ? autoRows.value : manualRows.value;
}

const filtered = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  return visibleBaseRows().filter((row) => {
    if (keyword) {
      const text = `${row.code} ${row.name} ${row.units.join(" ")}`.toLowerCase();
      if (!text.includes(keyword)) return false;
    }
    if (
      professionFilter.value &&
      currentProfession(row) !== professionFilter.value
    ) {
      return false;
    }
    if (mode.value === "auto" && lowOnly.value && !row.low_confidence) {
      return false;
    }
    if (
      mode.value === "auto" &&
      confirmOnly.value &&
      (!row.needs_confirmation || isConfirmed(row))
    ) {
      return false;
    }
    return true;
  });
});

const pageCount = computed(() =>
  Math.max(1, Math.ceil(filtered.value.length / pageSize)),
);

const pageRows = computed(() => {
  const start = (page.value - 1) * pageSize;
  return filtered.value.slice(start, start + pageSize);
});

const lowCount = computed(
  () => autoRows.value.filter((row) => row.low_confidence).length,
);

const toConfirmCount = computed(
  () =>
    autoRows.value.filter(
      (row) => row.needs_confirmation && !isConfirmed(row),
    ).length,
);

const overrideCount = computed(() => Object.keys(props.overrides).length);

const manualDoneCount = computed(
  () => manualRows.value.filter((row) => isManualSelected(row)).length,
);

const manualPendingCount = computed(
  () => manualRows.value.length - manualDoneCount.value,
);

const rangeText = computed(() => {
  if (!filtered.value.length) return "0 条";
  const start = (page.value - 1) * pageSize + 1;
  const end = Math.min(page.value * pageSize, filtered.value.length);
  return `${start}–${end} / ${filtered.value.length}`;
});

const downloadHref = computed(() =>
  resolveDownloadUrl(props.exportResult?.download_url ?? ""),
);

watch(
  () => props.result,
  () => {
    mode.value = props.result.summary.auto_count > 0 ? "auto" : "manual";
    search.value = "";
    professionFilter.value = "";
    lowOnly.value = false;
    confirmOnly.value = false;
    page.value = 1;
    confirmed.value = new Set();
    expanded.value = new Set();
  },
);

watch([mode, search, professionFilter, lowOnly, confirmOnly], () => {
  page.value = 1;
});

watch(pageCount, (count) => {
  if (page.value > count) page.value = count;
});

function onProfessionChange(row: ResultRow, event: Event): void {
  const value = (event.target as HTMLSelectElement).value;
  if (!value) return;
  emit("override", row.index, value);
  if (row.needs_confirmation) {
    const next = new Set(confirmed.value);
    next.add(row.index);
    confirmed.value = next;
  }
}

function resetOverride(row: ResultRow): void {
  emit("override", row.index, row.profession);
}

function confirmRow(row: ResultRow): void {
  const next = new Set(confirmed.value);
  next.add(row.index);
  confirmed.value = next;
}

function confirmAllVisible(): void {
  const next = new Set(confirmed.value);
  for (const row of autoRows.value) {
    if (row.needs_confirmation) next.add(row.index);
  }
  confirmed.value = next;
}

function goPage(next: number): void {
  page.value = Math.min(Math.max(1, next), pageCount.value);
}
</script>

<template>
  <section class="step-body">
    <div class="panel panel-results">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">分类结果</h2>
          <p class="panel-desc">
            自动分类只处理无歧义的标准；仅一项匹配的数据进入人工分类。
            导出时会在原始待分类 Excel 末尾追加「所属专业名称」「置信度」「判定依据」三列。
          </p>
        </div>
        <span class="panel-step">第 4 步</span>
      </div>

      <div class="result-bar">
        <div class="result-stats">
          <span>标准 <strong>{{ result.summary.unique_rows }}</strong> 条</span>
          <span>
            自动 <strong>{{ autoRows.length }}</strong> 条
            <span class="muted">
              （其中待确认 <strong>{{ toConfirmCount }}</strong> 条）
            </span>
          </span>
          <span>人工 <strong>{{ manualRows.length }}</strong> 条</span>
          <span>已修正 <strong>{{ overrideCount }}</strong> 条</span>
        </div>
        <button
          class="gb-btn gb-btn-primary"
          type="button"
          :disabled="exporting"
          @click="emit('export')"
        >
          {{ exporting ? "正在导出…" : "导出 Excel（原表 + 三列）" }}
        </button>
      </div>

      <p class="result-equation muted">
        自动 {{ autoRows.length }} + 人工 {{ manualRows.length }} =
        标准 {{ result.summary.unique_rows }} 条；
        待确认 {{ toConfirmCount }} 条已包含在自动分类中，不是另一类。
      </p>

      <div
        v-if="manualPendingCount > 0"
        class="notice notice-warning result-note"
        role="status"
      >
        人工分类已完成 {{ manualDoneCount }} / {{ manualRows.length }} 条；
        还有 {{ manualPendingCount }} 条未选择专业，导出时会标记为「待人工」。
      </div>

      <div v-if="exportResult" class="notice notice-success export-notice" role="status">
        导出完成：
        <a class="download-link" :href="downloadHref">{{ exportResult.filename }}</a>
        <span class="muted export-path" :title="exportResult.path">
          {{ exportResult.path }}
        </span>
      </div>
      <p v-if="exportError" class="form-error" role="alert">{{ exportError }}</p>

      <div class="mode-tabs" role="tablist" aria-label="分类结果视图">
        <button
          class="mode-tab"
          :class="{ active: mode === 'auto' }"
          type="button"
          role="tab"
          :aria-selected="mode === 'auto'"
          @click="mode = 'auto'"
        >
          自动分类
          <span>{{ autoRows.length }}</span>
        </button>
        <button
          class="mode-tab"
          :class="{ active: mode === 'manual' }"
          type="button"
          role="tab"
          :aria-selected="mode === 'manual'"
          @click="mode = 'manual'"
        >
          人工分类
          <span>{{ manualRows.length }}</span>
        </button>
      </div>

      <div class="table-toolbar">
        <input
          v-model="search"
          class="gb-input search-input"
          type="search"
          placeholder="搜索标准号、名称或主营单位"
          aria-label="搜索分类结果"
        />
        <select v-model="professionFilter" class="select" aria-label="按专业筛选">
          <option value="">全部{{ professionLabel }}</option>
          <option
            v-for="item in result.categories"
            :key="item.profession"
            :value="item.profession"
          >
            {{ item.profession }}
          </option>
        </select>

        <template v-if="mode === 'auto'">
          <label class="check">
            <input v-model="lowOnly" type="checkbox" />
            只看待复核
            <span class="check-count">{{ lowCount }}</span>
          </label>
          <label class="check">
            <input v-model="confirmOnly" type="checkbox" />
            只看待确认
            <span class="check-count">{{ toConfirmCount }}</span>
          </label>
          <button
            v-if="toConfirmCount > 0"
            class="gb-btn btn-small btn-secondary"
            type="button"
            @click="confirmAllVisible"
          >
            全部确认
          </button>
        </template>

        <span class="toolbar-range mono">{{ rangeText }}</span>
      </div>

      <div v-if="mode === 'auto'" class="table-wrap table-wrap-results">
        <table class="data-table result-table">
          <thead>
            <tr>
              <th scope="col" class="col-index">标准序号</th>
              <th scope="col">{{ codeLabel }}</th>
              <th scope="col">{{ nameLabel }}</th>
              <th scope="col" class="col-units">主营单位</th>
              <th scope="col">{{ professionLabel }}</th>
              <th scope="col">{{ systemLabel }}</th>
              <th scope="col" class="col-confidence">置信度</th>
              <th scope="col" class="col-evidence">判定依据</th>
              <th scope="col" class="col-action">状态</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in pageRows" :key="row.index">
              <tr
                :class="{
                  'row-low': row.low_confidence,
                  'row-corrected': isCorrected(row),
                }"
              >
                <td class="col-index cell-mono">
                  {{ row.index }}
                  <span
                    v-if="row.duplicate_count > 1"
                    class="dup-mark"
                    :title="`覆盖 ${row.duplicate_count} 行原始数据`"
                  >
                    ×{{ row.duplicate_count }}
                  </span>
                </td>
                <td class="cell-mono">{{ row.code || "—" }}</td>
                <td class="cell-name" :title="row.name">{{ row.name || "—" }}</td>
                <td class="cell-units cell-units-compact" :title="unitsTitle(row.units)">
                  {{ unitsSummary(row.units) }}
                </td>
                <td class="cell-edit">
                  <select
                    class="cell-select"
                    :value="currentProfession(row)"
                    :aria-label="`修改「${row.name}」的${professionLabel}`"
                    @change="onProfessionChange(row, $event)"
                  >
                    <option
                      v-for="item in result.categories"
                      :key="item.profession"
                      :value="item.profession"
                    >
                      {{ item.profession }}
                    </option>
                  </select>
                </td>
                <td>{{ currentSystem(row) || "—" }}</td>
                <td class="col-confidence">
                  <span class="confidence-text">{{ percent(row.confidence) }}</span>
                  <span v-if="row.low_confidence" class="tag tag-warning">待复核</span>
                </td>
                <td class="col-evidence">
                  <button
                    v-if="row.evidence?.length"
                    class="link-button evidence-link"
                    type="button"
                    :title="evidenceTitle(row)"
                    :aria-expanded="expanded.has(row.index)"
                    :aria-controls="'evidence-detail-' + row.index"
                    @click="toggleDetail(row)"
                  >
                    {{ evidenceSummary(row) }}
                  </button>
                  <span v-else>—</span>
                </td>
                <td class="col-action">
                  <span v-if="isCorrected(row)" class="tag tag-success">已修正</span>
                  <button
                    v-if="isCorrected(row)"
                    class="link-button"
                    type="button"
                    @click="resetOverride(row)"
                  >
                    恢复
                  </button>
                  <template v-else-if="row.needs_confirmation">
                    <span v-if="isConfirmed(row)" class="tag tag-success">已确认</span>
                    <button
                      v-else
                      class="link-button"
                      type="button"
                      @click="confirmRow(row)"
                    >
                      确认
                    </button>
                  </template>
                </td>
              </tr>
              <tr v-if="expanded.has(row.index)" class="detail-row">
                <td colspan="9">
                  <div
                    :id="'evidence-detail-' + row.index"
                    class="evidence-detail"
                  >
                    <p class="evidence-reason">
                      <strong>判定说明：</strong>{{ row.confidence_reason || "—" }}
                      <span v-if="row.evidence_level" class="tag tag-muted">
                        {{ evidenceLevelLabel(row.evidence_level) }}
                      </span>
                    </p>
                    <ul v-if="row.evidence?.length" class="evidence-list">
                      <li v-for="(item, index) in row.evidence" :key="index">
                        {{ item }}
                      </li>
                    </ul>
                    <p v-if="row.top3?.length" class="evidence-top3">
                      Top3：
                      <span
                        v-for="item in row.top3"
                        :key="item.profession"
                        class="evidence-top3-item"
                      >
                        {{ item.profession }} {{ percent(item.probability) }}
                        <span v-if="item.score != null" class="muted">
                          · 分数 {{ item.score }}
                        </span>
                      </span>
                    </p>
                    <p v-if="result.ensemble_weights" class="evidence-reason">
                      <strong>统计权重：</strong>
                      关键词 {{ percent(result.ensemble_weights.term) }} ·
                      相似名称 {{ percent(result.ensemble_weights.knn) }} ·
                      字符统计 {{ percent(result.ensemble_weights.nb) }}
                    </p>
                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="!pageRows.length">
              <td colspan="9" class="table-empty">没有符合条件的自动分类记录。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-else class="table-wrap table-wrap-results">
        <table class="data-table result-table">
          <thead>
            <tr>
              <th scope="col" class="col-index">标准序号</th>
              <th scope="col">{{ codeLabel }}</th>
              <th scope="col">{{ nameLabel }}</th>
              <th scope="col" class="col-units">主营单位</th>
              <th scope="col">人工原因</th>
              <th scope="col">{{ professionLabel }}</th>
              <th scope="col">{{ systemLabel }}</th>
              <th scope="col" class="col-action">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in pageRows"
              :key="row.index"
              :class="{ 'row-corrected': isManualSelected(row) }"
            >
              <td class="col-index cell-mono">
                {{ row.index }}
                <span
                  v-if="row.duplicate_count > 1"
                  class="dup-mark"
                  :title="`覆盖 ${row.duplicate_count} 行原始数据`"
                >
                  ×{{ row.duplicate_count }}
                </span>
              </td>
              <td class="cell-mono">{{ row.code || "—" }}</td>
              <td class="cell-name" :title="row.name">{{ row.name || "—" }}</td>
              <td class="cell-units cell-units-compact" :title="unitsTitle(row.units)">
                {{ unitsSummary(row.units) }}
              </td>
              <td class="cell-reason">{{ row.reason || "需人工判断" }}</td>
              <td class="cell-edit">
                <select
                  class="cell-select"
                  :value="currentProfession(row)"
                  :aria-label="`为「${row.name}」选择${professionLabel}`"
                  @change="onProfessionChange(row, $event)"
                >
                  <option value="" disabled>请选择专业</option>
                  <option
                    v-for="item in result.categories"
                    :key="item.profession"
                    :value="item.profession"
                  >
                    {{ item.profession }}
                  </option>
                </select>
              </td>
              <td>{{ currentSystem(row) || "—" }}</td>
              <td class="col-action">
                <span v-if="isManualSelected(row)" class="tag tag-success">已选择</span>
                <span v-else class="tag tag-warning">待分类</span>
              </td>
            </tr>
            <tr v-if="!pageRows.length">
              <td colspan="8" class="table-empty">没有符合条件的人工分类记录。</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="pagination">
        <span class="pagination-note">
          第 {{ page }} / {{ pageCount }} 页
          <span v-if="mode === 'manual'" class="muted">
            · 已完成 {{ manualDoneCount }} / {{ manualRows.length }}
          </span>
        </span>
        <div class="pagination-actions">
          <button
            class="gb-btn btn-small btn-secondary"
            type="button"
            :disabled="page <= 1"
            @click="goPage(page - 1)"
          >
            上一页
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
      </div>
    </div>
  </section>
</template>
