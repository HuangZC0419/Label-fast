<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import "../styles.css";
import { api, errorMessage } from "../api";
import AppSidebar from "../components/AppSidebar.vue";
import PendingStep from "../components/PendingStep.vue";
import ReferenceStep from "../components/ReferenceStep.vue";
import ResultsStep from "../components/ResultsStep.vue";
import RunStep from "../components/RunStep.vue";
import type {
  ClassifyResponse,
  ExportResponse,
  HealthResponse,
  PendingAnalysis,
  ReferenceAnalysis,
} from "../types";

type ServiceState = "loading" | "online" | "offline";

const health = ref<HealthResponse | null>(null);
const serviceState = ref<ServiceState>("loading");

const step = ref(1);
const reference = ref<ReferenceAnalysis | null>(null);
const pending = ref<PendingAnalysis | null>(null);
const result = ref<ClassifyResponse | null>(null);

const referenceFile = ref<File | null>(null);
const pendingFile = ref<File | null>(null);

const referenceBusy = ref(false);
const pendingBusy = ref(false);
const runBusy = ref(false);

const referenceError = ref<string | null>(null);
const pendingError = ref<string | null>(null);
const runError = ref<string | null>(null);

const overrides = ref<Record<string, string>>({});
const exporting = ref(false);
const exportResult = ref<ExportResponse | null>(null);
const exportError = ref<string | null>(null);

const stepInfo = [
  {
    title: "数据体检",
    description: "上传已分类国标表，查看分类分布并检查问题数据。",
  },
  {
    title: "待分类目录",
    description: "上传需要判断的标准清单，区分自动分类与人工分类。",
  },
  {
    title: "执行分类",
    description: "确认两份数据后运行分类，生成可复核的结果。",
  },
  {
    title: "分类结果",
    description: "逐条复核、修正分类，并导出 Excel 结果表。",
  },
];

const currentStep = computed(() => stepInfo[step.value - 1]);

const reachable = computed(() => {
  if (result.value) return 4;
  if (reference.value && pending.value) return 3;
  if (reference.value) return 2;
  return 1;
});

const completed = computed(() => {
  const steps: number[] = [];
  if (reference.value) steps.push(1);
  if (reference.value && pending.value) steps.push(2);
  if (result.value) steps.push(3);
  return steps;
});

const serviceVersion = computed(() => health.value?.version);

async function checkHealth(): Promise<void> {
  serviceState.value = "loading";
  try {
    health.value = await api.health();
    serviceState.value = "online";
  } catch {
    health.value = null;
    serviceState.value = "offline";
  }
}

onMounted(checkHealth);

function resetResults(): void {
  result.value = null;
  overrides.value = {};
  exportResult.value = null;
  exportError.value = null;
}

async function uploadReference(file: File): Promise<void> {
  if (referenceBusy.value) return;
  referenceBusy.value = true;
  referenceError.value = null;
  reference.value = null;
  referenceFile.value = file;
  resetResults();
  step.value = 1;

  try {
    reference.value = await api.analyzeReference(file);
    if (serviceState.value !== "online") void checkHealth();
  } catch (caught) {
    referenceError.value = errorMessage(caught, "参照表分析失败，请检查文件内容");
    referenceFile.value = null;
  } finally {
    referenceBusy.value = false;
  }
}

function clearReference(): void {
  reference.value = null;
  referenceFile.value = null;
  referenceError.value = null;
  resetResults();
  step.value = 1;
}

async function uploadPending(file: File): Promise<void> {
  if (pendingBusy.value) return;
  pendingBusy.value = true;
  pendingError.value = null;
  pending.value = null;
  pendingFile.value = file;
  resetResults();
  step.value = 2;

  try {
    pending.value = await api.analyzePending(file);
    if (serviceState.value !== "online") void checkHealth();
  } catch (caught) {
    pendingError.value = errorMessage(caught, "待分类目录分析失败，请检查文件内容");
    pendingFile.value = null;
  } finally {
    pendingBusy.value = false;
  }
}

function clearPending(): void {
  pending.value = null;
  pendingFile.value = null;
  pendingError.value = null;
  resetResults();
  step.value = 2;
}

async function runClassification(threshold: number): Promise<void> {
  if (!reference.value || !pending.value || runBusy.value) return;
  runBusy.value = true;
  runError.value = null;
  resetResults();

  try {
    result.value = await api.classifyTask(
      reference.value.reference_id,
      pending.value.pending_id,
      threshold,
    );
    step.value = 4;
  } catch (caught) {
    runError.value = errorMessage(caught, "分类失败，请检查数据和后端服务");
  } finally {
    runBusy.value = false;
  }
}

function setOverride(index: number, profession: string): void {
  const row = result.value?.rows.find((item) => item.index === index);
  const next = { ...overrides.value };
  if (!row || profession === row.profession) delete next[String(index)];
  else next[String(index)] = profession;
  overrides.value = next;
}

async function exportResults(): Promise<void> {
  if (!result.value || exporting.value) return;
  exporting.value = true;
  exportError.value = null;
  exportResult.value = null;

  try {
    exportResult.value = await api.exportTask(
      result.value.task_id,
      overrides.value,
    );
  } catch (caught) {
    exportError.value = errorMessage(caught, "导出失败，请稍后重试");
  } finally {
    exporting.value = false;
  }
}

function navigate(target: number): void {
  if (target <= reachable.value) step.value = target;
}
</script>

<template>
  <div class="gb-module">
    <div class="app-shell">
      <AppSidebar
        :current="step"
        :reachable="reachable"
        :completed="completed"
        :service-state="serviceState"
        :version="serviceVersion"
        @navigate="navigate"
      />

      <div class="gb-main">
        <header class="topbar">
          <div class="topbar-heading">
            <span class="topbar-step">第 {{ step }} 步</span>
            <h2>{{ currentStep.title }}</h2>
            <p>{{ currentStep.description }}</p>
          </div>

          <div class="topbar-context">
            <div v-if="reference" class="context-chip">
              <span>参照表</span>
              <strong :title="reference.file.name">{{ reference.file.name }}</strong>
              <em>{{ reference.training_category_count }} 类 / {{ reference.training_rows }} 条</em>
            </div>
            <div v-if="pending" class="context-chip">
              <span>待分类</span>
              <strong :title="pending.file.name">{{ pending.file.name }}</strong>
              <em>{{ pending.unique_rows }} 条标准</em>
            </div>
          </div>
        </header>

        <div class="content">
          <ReferenceStep
            v-if="step === 1"
            :analysis="reference"
            :busy="referenceBusy"
            :error="referenceError"
            :file="referenceFile"
            @upload="uploadReference"
            @clear="clearReference"
            @next="navigate(2)"
          />

          <PendingStep
            v-else-if="step === 2"
            :analysis="pending"
            :busy="pendingBusy"
            :error="pendingError"
            :file="pendingFile"
            @upload="uploadPending"
            @clear="clearPending"
            @back="navigate(1)"
            @next="navigate(3)"
          />

          <RunStep
            v-else-if="step === 3"
            :reference="reference"
            :pending="pending"
            :busy="runBusy"
            :error="runError"
            @back="navigate(2)"
            @run="runClassification"
          />

          <ResultsStep
            v-else-if="step === 4 && result"
            :result="result"
            :overrides="overrides"
            :exporting="exporting"
            :export-result="exportResult"
            :export-error="exportError"
            @override="setOverride"
            @export="exportResults"
          />
        </div>

        <footer class="app-footer">
          <span>航空标准分类系统</span>
          <span>本机运行 · 数据不离开本机</span>
        </footer>
      </div>
    </div>
  </div>
</template>
