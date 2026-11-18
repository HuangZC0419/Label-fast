<script setup lang="ts">
import { computed, ref } from "vue";

import DataDialog from "./DataDialog.vue";
import FileDrop from "./FileDrop.vue";
import { formatFileSize, joinRows, rowLabel } from "../format";
import type {
  CategoryGroup,
  DialogColumn,
  DialogRow,
  ReferenceAnalysis,
} from "../types";

const props = defineProps<{
  analysis: ReferenceAnalysis | null;
  busy: boolean;
  error: string | null;
  file: File | null;
}>();

const emit = defineEmits<{
  upload: [file: File];
  clear: [];
  next: [];
}>();

const query = ref("");
const professionFilter = ref("");

const dialogOpen = ref(false);
const dialogTitle = ref("");
const dialogDescription = ref("");
const dialogColumns = ref<DialogColumn[]>([]);
const dialogRows = ref<DialogRow[]>([]);
const dialogBadge = ref("");
const dialogSearchPlaceholder = ref("搜索");
const dialogEmptyText = ref("没有符合条件的数据。");

const codeLabel = computed(() => props.analysis?.columns.code || "标准号");
const nameLabel = computed(() => props.analysis?.columns.name || "标准名称");
const systemLabel = computed(
  () => props.analysis?.columns.system || "选用系统名称",
);
const professionLabel = computed(
  () => props.analysis?.columns.profession || "选用专业名称",
);

const conflictCount = computed(
  () => props.analysis?.quality.conflict_group_count ?? 0,
);
const conflictRows = computed(
  () => props.analysis?.quality.conflict_row_count ?? 0,
);

/** 样本量不足的类别：统计结果不稳定，需要在分类分布面板显式提示。 */
const lowSupportWarnings = computed(() =>
  (props.analysis?.keyword_report ?? [])
    .filter((group) => group.warning)
    .map((group) => `${group.profession}（${group.class_support} 条）`),
);

const filteredCategories = computed(() => {
  const groups = props.analysis?.categories ?? [];
  const keyword = query.value.trim().toLowerCase();
  return groups.filter((group) => {
    if (professionFilter.value && group.profession !== professionFilter.value) {
      return false;
    }
    if (!keyword) return true;
    if (group.profession.toLowerCase().includes(keyword)) return true;
    if (group.system.toLowerCase().includes(keyword)) return true;
    return group.entries.some(
      (entry) =>
        entry.code.toLowerCase().includes(keyword) ||
        entry.name.toLowerCase().includes(keyword),
    );
  });
});

const entriesByRow = computed(() => {
  const map = new Map<
    string,
    {
      row: number | string;
      code: string;
      name: string;
      system: string;
      profession: string;
    }
  >();
  for (const group of props.analysis?.categories ?? []) {
    for (const entry of group.entries) {
      map.set(String(entry.row), {
        row: entry.row,
        code: entry.code,
        name: entry.name,
        system: entry.system,
        profession: group.profession,
      });
    }
  }
  return map;
});

function professionsText(professions: string[]): string {
  if (!professions.length) return "未填写专业";
  return professions.length === 1
    ? `均为 ${professions[0]}`
    : professions.join(" / ");
}

function clean(value: string): string {
  return value && !value.startsWith("（未填写") ? value : "—";
}

function missingRows(field: "name" | "profession" | "system" | "code"): DialogRow[] {
  const rows = props.analysis?.quality.missing[field].rows ?? [];
  return rows.map((row) => {
    const entry = entriesByRow.value.get(String(row));
    return {
      row: rowLabel(row),
      code: clean(entry?.code ?? ""),
      name: clean(entry?.name ?? ""),
      profession: clean(entry?.profession ?? ""),
      system: clean(entry?.system ?? ""),
    };
  });
}

function codeColumn(width: string): DialogColumn {
  return { key: "code", label: codeLabel.value, mono: true, width };
}

function nameColumn(width: string): DialogColumn {
  return { key: "name", label: nameLabel.value, width, wrap: true };
}

function professionColumn(width: string): DialogColumn {
  return { key: "profession", label: professionLabel.value, width };
}

function systemColumn(width: string): DialogColumn {
  return { key: "system", label: systemLabel.value, width, wrap: true };
}

function rowColumn(width: string): DialogColumn {
  return { key: "row", label: "Excel 行", mono: true, width, wrap: true };
}

function countColumn(width: string): DialogColumn {
  return { key: "count", label: "数量", width, align: "right" };
}

function missingColumns(): DialogColumn[] {
  return [
    rowColumn("22%"),
    codeColumn("18%"),
    nameColumn("26%"),
    professionColumn("16%"),
    systemColumn("18%"),
  ];
}

interface CheckDefinition {
  key: string;
  label: string;
  count: number;
  severity: "info" | "warning" | "danger";
  description: string;
  columns: DialogColumn[];
  rows: DialogRow[];
  searchPlaceholder: string;
}

const checks = computed<CheckDefinition[]>(() => {
  const quality = props.analysis?.quality;
  if (!quality) return [];

  const sameName = quality.same_name_different_code;
  const sameCode = quality.same_code_different_name;
  const sameNameConflict = sameName.filter((item) => !item.same_profession);
  const sameCodeConflict = sameCode.filter((item) => !item.same_profession);

  return [
    {
      key: "same-name",
      label: sameNameConflict.length
        ? `同名不同标准号（${sameNameConflict.length} 组分类不同）`
        : "同名不同标准号（同专业，不影响训练）",
      count: sameName.length,
      severity: sameNameConflict.length ? "warning" : "info",
      description:
        "同一标准名称对应多个标准号。专业一致时通常是版本差异或叫法不同，不影响训练；只有专业不同才需要处理。",
      columns: [
        nameColumn("28%"),
        {
          key: "codes",
          label: codeLabel.value,
          mono: true,
          wrap: true,
          width: "28%",
        },
        professionColumn("18%"),
        rowColumn("26%"),
      ],
      rows: sameName.map((item) => ({
        name: item.name,
        codes: item.codes.join("、"),
        profession: professionsText(item.professions),
        row: joinRows(item.rows),
      })),
      searchPlaceholder: "搜索标准名称、标准号或专业",
    },
    {
      key: "same-code",
      label: sameCodeConflict.length
        ? `同标准号不同名称（${sameCodeConflict.length} 组分类不同）`
        : "同标准号不同名称（同专业，不影响训练）",
      count: sameCode.length,
      severity: sameCodeConflict.length ? "warning" : "info",
      description:
        "同一标准号对应多个标准名称。专业一致时通常只是叫法差异，不影响训练；只有专业不同才需要处理。",
      columns: [
        codeColumn("24%"),
        {
          key: "names",
          label: nameLabel.value,
          wrap: true,
          width: "28%",
        },
        professionColumn("18%"),
        rowColumn("30%"),
      ],
      rows: sameCode.map((item) => ({
        code: item.code,
        names: item.names.join("、"),
        profession: professionsText(item.professions),
        row: joinRows(item.rows),
      })),
      searchPlaceholder: "搜索标准号、标准名称或专业",
    },
    {
      key: "duplicates",
      label: "完全重复记录（已合并）",
      count: quality.duplicates.length,
      severity: "info",
      description: "标准号、名称、专业、系统完全相同的重复记录，训练和导出时会合并处理。",
      columns: [
        codeColumn("16%"),
        nameColumn("22%"),
        professionColumn("14%"),
        systemColumn("16%"),
        countColumn("8%"),
        rowColumn("24%"),
      ],
      rows: quality.duplicates.map((item) => ({
        code: item.code || "无标准号",
        name: item.name,
        profession: item.profession,
        system: item.system,
        count: item.count,
        row: joinRows(item.rows),
      })),
      searchPlaceholder: "搜索标准号、名称、专业或系统",
    },
    {
      key: "multi-system",
      label: "一个专业对应多个系统（需确认）",
      count: quality.profession_multiple_systems.length,
      severity: quality.profession_multiple_systems.length ? "warning" : "info",
      description:
        "同一专业出现多个选用系统名称。系统输出按多数票确定，建议核对映射关系。",
      columns: [
        professionColumn("40%"),
        systemColumn("40%"),
        countColumn("20%"),
      ],
      rows: quality.profession_multiple_systems.flatMap((item) =>
        item.systems.map((system) => ({
          profession: item.profession,
          system: system.system,
          count: system.count,
        })),
      ),
      searchPlaceholder: "搜索专业或系统",
    },
    {
      key: "missing-name",
      label: "缺少标准名称",
      count: quality.missing.name.count,
      severity: quality.missing.name.count ? "warning" : "info",
      description: "这些行缺少标准名称，不参与训练。",
      columns: missingColumns(),
      rows: missingRows("name"),
      searchPlaceholder: "搜索标准号或专业",
    },
    {
      key: "missing-profession",
      label: "缺少选用专业名称",
      count: quality.missing.profession.count,
      severity: quality.missing.profession.count ? "warning" : "info",
      description: "这些行缺少选用专业名称，不参与训练。",
      columns: missingColumns(),
      rows: missingRows("profession"),
      searchPlaceholder: "搜索标准号或名称",
    },
    {
      key: "missing-system",
      label: "缺少选用系统名称",
      count: quality.missing.system.count,
      severity: quality.missing.system.count ? "warning" : "info",
      description: "这些行缺少选用系统名称，系统名称会按专业映射兜底。",
      columns: missingColumns(),
      rows: missingRows("system"),
      searchPlaceholder: "搜索标准号或专业",
    },
    {
      key: "missing-code",
      label: "缺少标准号",
      count: quality.missing.code.count,
      severity: quality.missing.code.count ? "warning" : "info",
      description: "这些行缺少标准号，仍会保留在数据中，但无法按标准号匹配。",
      columns: missingColumns(),
      rows: missingRows("code"),
      searchPlaceholder: "搜索标准名称或专业",
    },
  ];
});

function openDialog(config: {
  title: string;
  description: string;
  columns: DialogColumn[];
  rows: DialogRow[];
  badge: string;
  searchPlaceholder: string;
  emptyText?: string;
}): void {
  dialogTitle.value = config.title;
  dialogDescription.value = config.description;
  dialogColumns.value = config.columns;
  dialogRows.value = config.rows;
  dialogBadge.value = config.badge;
  dialogSearchPlaceholder.value = config.searchPlaceholder;
  dialogEmptyText.value = config.emptyText || "没有符合条件的数据。";
  dialogOpen.value = true;
}

function openCheck(check: CheckDefinition): void {
  if (!check.count) return;
  openDialog({
    title: check.label,
    description: check.description,
    columns: check.columns,
    rows: check.rows,
    badge: `共 ${check.count} 组`,
    searchPlaceholder: check.searchPlaceholder,
  });
}

function openCategoryEntries(group: CategoryGroup): void {
  openDialog({
    title: `${group.profession} · ${codeLabel.value}清单`,
    description: `共 ${group.count} 条标准，其中可参与训练 ${group.trainable_count} 条。`,
    columns: [
      codeColumn("18%"),
      nameColumn("28%"),
      systemColumn("18%"),
      rowColumn("18%"),
      { key: "status", label: "训练状态", width: "18%" },
    ],
    rows: group.entries.map((entry) => ({
      code: entry.code || "—",
      name: entry.name || "—",
      system: entry.system || "—",
      row: rowLabel(entry.row),
      status: entry.excluded ? "已排除" : "参与训练",
    })),
    badge: `${group.count} 条`,
    searchPlaceholder: `搜索${codeLabel.value}或${nameLabel.value}`,
  });
}

function openConflictDialog(): void {
  const conflicts = props.analysis?.quality.conflicts ?? [];
  const rows: DialogRow[] = [];
  for (const group of conflicts) {
    for (const item of group.detail) {
      rows.push({
        code: group.code || "—",
        name: group.name || "—",
        profession: item.profession || "—",
        system: item.system || "—",
        row: rowLabel(item.row),
      });
    }
  }
  openDialog({
    title: "同号同名但分类不一致",
    description:
      "这些记录的标准号和标准名称相同，但选用专业不一致（系统差异单独提示，不影响训练）。整组已排除，不参与训练。",
    columns: [
      codeColumn("18%"),
      nameColumn("24%"),
      professionColumn("16%"),
      systemColumn("18%"),
      rowColumn("24%"),
    ],
    rows,
    badge: `${conflictCount.value} 组 / ${rows.length} 行`,
    searchPlaceholder: "搜索标准号、名称、专业或系统",
  });
}

function openKeywordReport(): void {
  const report = props.analysis?.keyword_report ?? [];
  const rows: DialogRow[] = [];
  for (const group of report) {
    for (const item of group.keywords) {
      rows.push({
        profession: group.profession,
        term: item.term,
        support: item.support ?? "—",
        purity:
          item.purity == null ? "—" : `${Math.round(item.purity * 100)}%`,
        weight: item.weight.toFixed(2),
        class_support: group.class_support,
        source:
          item.source === "statistical"
            ? "统计"
            : item.source === "curated"
              ? "人工"
              : item.source === "mined"
                ? "挖掘"
                : item.source,
        examples: item.examples.join("；") || "—",
      });
    }
  }
  openDialog({
    title: "分类依据词表",
    description:
      "系统用统计方法从参照表估计每个专业的特征词：支持条数表示该词在当前专业出现的标准数量，纯度表示该词只出现在本专业的比例，类别样本是该专业可用于统计的样本总数。类别样本低于 10 条时统计结果不稳定。",
    columns: [
      professionColumn("14%"),
      { key: "term", label: "特征词", width: "14%" },
      { key: "support", label: "支持条数", width: "9%", align: "right" },
      { key: "purity", label: "纯度", width: "9%", align: "right" },
      { key: "weight", label: "权重", width: "9%", align: "right" },
      { key: "class_support", label: "类别样本", width: "10%", align: "right" },
      { key: "source", label: "来源", width: "9%" },
      { key: "examples", label: "示例标准名称", width: "26%", wrap: true },
    ],
    rows,
    badge: `${report.length} 个专业`,
    searchPlaceholder: "搜索专业、特征词或示例名称",
  });
}
</script>

<template>
  <section class="step-body">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">上传已分类国标表</h2>
          <p class="panel-desc">
            系统先读取这份参照表，统计每个专业下的标准数量，并检查同号同名但分类不一致的问题数据。
            问题数据会整组排除，不参与后续分类。
          </p>
        </div>
        <span class="panel-step">第 1 步</span>
      </div>

      <div v-if="busy" class="progress-line" role="progressbar" aria-label="正在分析文件"></div>

      <FileDrop
        label="选择已分类国标 Excel"
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
          <li><b>工作表</b>优先「标准分类总表」，否则第一个工作表</li>
          <li><b>必需列</b>标准名称、选用专业名称</li>
          <li><b>建议列</b>标准号、选用系统名称</li>
          <li><b>格式</b>.xlsx / .xlsm，最大 20MB</li>
        </ul>
      </div>

      <div v-if="analysis" class="file-summary">
        <span class="file-summary-name">{{ analysis.file.name }}</span>
        <span>{{ analysis.file.sheet }} 工作表</span>
        <span>{{ formatFileSize(analysis.file.size) }}</span>
        <span class="tag tag-muted">已读取</span>
      </div>
    </div>

    <template v-if="analysis">
      <div class="stat-grid">
        <div class="stat">
          <span class="gb-stat-label">原始记录</span>
          <strong class="stat-value">{{ analysis.raw_rows }}</strong>
          <span class="stat-hint">参照表总行数</span>
        </div>
        <div class="stat">
          <span class="gb-stat-label">可参与训练</span>
          <strong class="stat-value">{{ analysis.training_rows }}</strong>
          <span class="stat-hint">已排除问题数据</span>
        </div>
        <div class="stat">
          <span class="gb-stat-label">分类类别</span>
          <strong class="stat-value">{{ analysis.training_category_count }}</strong>
          <span class="stat-hint">
            参与训练 · 表内共 {{ analysis.categories.length }} 类
          </span>
        </div>
        <div class="stat" :class="{ 'stat-danger': analysis.excluded_rows > 0 }">
          <span class="gb-stat-label">问题数据</span>
          <strong class="stat-value">{{ analysis.excluded_rows }}</strong>
          <span class="stat-hint">
            {{ conflictCount }} 组同号同名不同分类
            <template
              v-if="analysis.excluded_rows > analysis.quality.conflict_row_count"
            >
              · 另有
              {{ analysis.excluded_rows - analysis.quality.conflict_row_count }}
              行同名/同号分类不一致
            </template>
          </span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head panel-head-compact">
          <div>
            <h2 class="panel-title">分类分布</h2>
            <p class="panel-desc">
              按{{ professionLabel }}查看标准数量与国标号清单；清单在弹窗中分页查看。
            </p>
          </div>
          <div class="toolbar">
            <input
              v-model="query"
              class="gb-input search-input"
              type="search"
              placeholder="搜索专业、标准号或名称"
              aria-label="搜索分类分布"
            />
            <select
              v-model="professionFilter"
              class="select"
              aria-label="按专业筛选"
            >
              <option value="">全部专业</option>
              <option
                v-for="group in analysis.categories"
                :key="group.profession"
                :value="group.profession"
              >
                {{ group.profession }}
              </option>
            </select>
            <button
              class="gb-btn btn-small btn-secondary"
              type="button"
              :disabled="!analysis.keyword_report?.length"
              @click="openKeywordReport"
            >
              分类依据词表
            </button>
          </div>
        </div>

        <div
          v-if="lowSupportWarnings.length"
          class="notice notice-warning"
          role="status"
        >
          以下类别样本量偏低，统计结果不稳定：{{ lowSupportWarnings.join("、") }}
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th scope="col">{{ professionLabel }}</th>
                <th scope="col">{{ systemLabel }}</th>
                <th scope="col" class="col-number">标准数量</th>
                <th scope="col" class="col-number">可训练</th>
                <th scope="col" class="col-action">标准号清单</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="group in filteredCategories" :key="group.profession">
                <td class="cell-strong">{{ group.profession }}</td>
                <td>{{ group.system || "—" }}</td>
                <td class="col-number">{{ group.count }}</td>
                <td class="col-number">
                  <span :class="{ 'text-danger': group.trainable_count === 0 }">
                    {{ group.trainable_count }}
                  </span>
                </td>
                <td class="col-action">
                  <button
                    class="link-button"
                    type="button"
                    @click="openCategoryEntries(group)"
                  >
                    查看国标号
                  </button>
                </td>
              </tr>
              <tr v-if="!filteredCategories.length">
                <td colspan="5" class="table-empty">没有符合当前条件的分类记录。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head panel-head-compact">
          <div>
            <h2 class="panel-title">数据体检</h2>
            <p class="panel-desc">
              重点检查相同{{ codeLabel }}、相同{{ nameLabel }}，但{{ professionLabel }}不同的数据。
              所有明细都在弹窗中查看，可搜索、翻页。
            </p>
          </div>
          <span
            class="tag"
            :class="conflictCount ? 'tag-danger' : 'tag-success'"
          >
            {{ conflictCount ? `${conflictCount} 组问题` : "未发现分类冲突" }}
          </span>
        </div>

        <div v-if="!conflictCount" class="notice notice-success" role="status">
          没有发现同号同名但分类不一致的记录，全部 {{ analysis.training_rows }} 条可参与训练。
        </div>
        <div v-else class="notice notice-danger conflict-notice" role="alert">
          <span>
            发现 {{ conflictCount }} 组、共 {{ conflictRows }} 行同号同名但分类不一致的记录。
            为避免污染训练集，这些记录已整组排除。
          </span>
          <button
            class="gb-btn btn-small btn-secondary"
            type="button"
            @click="openConflictDialog"
          >
            查看问题数据
          </button>
        </div>

        <div class="notice notice-info hint-notice" role="status">
          下面的同名/同号提示不一定是错误：同专业的通常是版本差异或叫法不同，不影响训练；
          只有分类不同才会影响模型。点击任意一项查看完整明细。
        </div>

        <div class="check-grid">
          <button
            v-for="check in checks"
            :key="check.key"
            class="check-item check-button"
            :class="check.count ? `check-${check.severity}` : ''"
            type="button"
            :disabled="!check.count"
            @click="openCheck(check)"
          >
            <span class="check-label">{{ check.label }}</span>
            <span class="check-count">{{ check.count }}</span>
            <span class="check-open">{{ check.count ? "查看" : "无数据" }}</span>
          </button>
        </div>
      </div>

      <div class="step-actions">
        <p class="step-note">
          参照表读取完成。下一步上传需要分类的标准目录。
        </p>
        <button class="gb-btn gb-btn-primary" type="button" @click="emit('next')">
          下一步：上传待分类目录
        </button>
      </div>
    </template>

    <DataDialog
      :open="dialogOpen"
      :title="dialogTitle"
      :description="dialogDescription"
      :columns="dialogColumns"
      :rows="dialogRows"
      :badge="dialogBadge"
      :search-placeholder="dialogSearchPlaceholder"
      :empty-text="dialogEmptyText"
      @close="dialogOpen = false"
    />
  </section>
</template>
