<script setup lang="ts">
import { ref } from "vue";

import type { PendingAnalysis, ReferenceAnalysis } from "../types";

const props = defineProps<{
  reference: ReferenceAnalysis | null;
  pending: PendingAnalysis | null;
  busy: boolean;
  error: string | null;
}>();

const emit = defineEmits<{
  back: [];
  run: [threshold: number];
}>();

const threshold = ref(0.7);
</script>

<template>
  <section class="step-body">
    <div class="panel">
      <div class="panel-head">
        <div>
          <h2 class="panel-title">确认数据并执行分类</h2>
          <p class="panel-desc">
            系统将依据参照表中的分类记录判断待分类标准。完成后直接进入结果表，可逐条复核和修正。
          </p>
        </div>
        <span class="panel-step">第 3 步</span>
      </div>

      <div class="run-grid">
        <div class="run-card">
          <span class="run-card-label">参照表</span>
          <strong class="run-card-name">{{ reference?.file.name || "未上传" }}</strong>
          <dl class="run-list">
            <div>
              <dt>分类类别</dt>
              <dd>{{ reference?.training_category_count ?? 0 }}</dd>
            </div>
            <div>
              <dt>训练记录</dt>
              <dd>{{ reference?.training_rows ?? 0 }}</dd>
            </div>
            <div>
              <dt>排除问题数据</dt>
              <dd>{{ reference?.excluded_rows ?? 0 }}</dd>
            </div>
          </dl>
        </div>

        <div class="run-card">
          <span class="run-card-label">待分类目录</span>
          <strong class="run-card-name">{{ pending?.file.name || "未上传" }}</strong>
          <dl class="run-list">
            <div>
              <dt>标准条数</dt>
              <dd>{{ pending?.unique_rows ?? 0 }}</dd>
            </div>
            <div>
              <dt>自动分类（含待确认 {{ pending?.multi_unit_count ?? 0 }}）</dt>
              <dd>{{ pending?.auto_count ?? 0 }}</dd>
            </div>
            <div>
              <dt>人工分类</dt>
              <dd>{{ pending?.manual_count ?? 0 }}</dd>
            </div>
          </dl>
          <p class="run-note">
            {{ pending?.auto_count ?? 0 }} + {{ pending?.manual_count ?? 0 }} =
            {{ pending?.unique_rows ?? 0 }} 条标准；
            多单位待确认 {{ pending?.multi_unit_count ?? 0 }} 条包含在自动分类内。
          </p>
        </div>
      </div>

      <div class="threshold-row">
        <div>
          <label class="field-label" for="threshold">低置信度提醒阈值</label>
          <p class="field-hint">
            低于该值的记录会在结果表中标记为待复核，不影响分类结果本身。
          </p>
        </div>
        <div class="threshold-control">
          <input
            id="threshold"
            v-model.number="threshold"
            type="range"
            min="0.05"
            max="0.95"
            step="0.01"
            :disabled="busy"
          />
          <output class="threshold-value" for="threshold">
            {{ Number(threshold).toFixed(2) }}
          </output>
        </div>
      </div>

      <p v-if="error" class="form-error" role="alert">{{ error }}</p>

      <div class="step-actions">
        <button class="gb-btn btn-secondary" type="button" :disabled="busy" @click="emit('back')">
          返回待分类目录
        </button>
        <button
          class="gb-btn gb-btn-primary btn-large"
          type="button"
          :disabled="busy"
          @click="emit('run', Number(threshold))"
        >
          {{ busy ? "正在分类…" : `开始分类 ${pending?.auto_count ?? 0} 条自动数据` }}
        </button>
      </div>

      <div v-if="busy" class="run-progress" role="status">
        <div class="progress-line is-running"></div>
        <p>正在读取参照表并逐条判断，请稍候。</p>
      </div>
    </div>
  </section>
</template>
