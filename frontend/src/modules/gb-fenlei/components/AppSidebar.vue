<script setup lang="ts">
import { computed } from "vue";

type ServiceState = "loading" | "online" | "offline";

const props = defineProps<{
  current: number;
  reachable: number;
  completed: number[];
  serviceState: ServiceState;
  version?: string;
}>();

const emit = defineEmits<{
  navigate: [step: number];
}>();

const steps = [
  {
    step: 1,
    title: "数据体检",
    description: "上传已分类国标表",
  },
  {
    step: 2,
    title: "待分类目录",
    description: "上传需要判断的标准",
  },
  {
    step: 3,
    title: "执行分类",
    description: "运行分类生成结果",
  },
  {
    step: 4,
    title: "分类结果",
    description: "复核、修正并导出",
  },
];

const serviceLabel = computed(() => {
  if (props.serviceState === "online") return "服务在线";
  if (props.serviceState === "offline") return "服务未连接";
  return "正在连接";
});

function stateOf(step: number): "done" | "current" | "idle" {
  if (props.current === step) return "current";
  if (props.completed.includes(step)) return "done";
  return "idle";
}

function selectable(step: number): boolean {
  return step <= props.reachable;
}
</script>

<template>
  <aside class="gb-sidebar">
    <nav class="side-nav" aria-label="工作步骤">
      <p class="side-nav-title">分类流程</p>
      <button
        v-for="item in steps"
        :key="item.step"
        class="side-nav-item"
        :class="[stateOf(item.step), { 'is-current': current === item.step }]"
        type="button"
        :disabled="!selectable(item.step)"
        @click="emit('navigate', item.step)"
      >
        <span class="side-nav-index" aria-hidden="true">
          <svg v-if="stateOf(item.step) === 'done'" viewBox="0 0 16 16">
            <path
              d="m3.5 8.4 2.8 2.8 6.2-6.4"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <template v-else>{{ item.step }}</template>
        </span>
        <span class="side-nav-copy">
          <span class="side-nav-label">{{ item.title }}</span>
          <span class="side-nav-desc">{{ item.description }}</span>
        </span>
      </button>
    </nav>

    <div class="sidebar-foot">
      <div class="service-line" :class="serviceState">
        <span class="service-dot" aria-hidden="true"></span>
        <span>{{ serviceLabel }}</span>
        <span v-if="version" class="service-version">v{{ version }}</span>
      </div>
      <p class="sidebar-note">本机运行 · 文件不上传外部服务</p>
    </div>
  </aside>
</template>
