# 混合标注视图左侧栏与工具栏排版重构

- 日期：2026-11-09
- 状态：已确认
- 范围：`frontend/src/modules/mixed-annotation/` 的纯前端排版与信息层级
- 不改动：所有 API、上传/导入/轮询/转换逻辑、标注与保存逻辑、PDF 预览与分栏拖拽逻辑

## 1. 问题

1. **项目切换入口重复**：顶栏项目下拉、左侧「当前项目」下拉（含「＋新建项目」选项）、「新建」按钮，共三处。
2. **上传入口层级错位**：大拖拽区与整行「导入整个文件夹」按钮视觉权重不对等。
3. **面板重名**：`Import 文件` 与 `Files 文件` 都叫“文件”。
4. **双滚动条**：`.project-sidebar` 自身 `overflow-y:auto`，`.file-scroll` 又有 `max-height:48vh; overflow-y:auto`，内外两层滚动，内层到底时外层仍未到底，内容看不完整。
5. **转换参数混在上传区**：表格识别 / 公式识别 / DPI 与导入操作平铺，层级不清。
6. **工具栏五类操作同一层级**：模式切换（状态）、PDF 预览（视图）、同步滚动（视图附属）、图片/表格标注（动作）、保存（主操作）平铺。

## 2. 设计决策

### 2.1 左侧栏：顶栏管项目，侧栏管文件

顶栏成为唯一的项目上下文入口：

```text
[项目 ▾] [+ 新建]   [● 当前文件 chip] ······   [导出 ZIP]  [● 本地工具 在线]
```

- 项目下拉是唯一切换入口；`+` 图标按钮触发新建项目。
- 左侧栏的项目区降级为**当前项目摘要 + 设置**，不再包含项目下拉。

左侧栏改为固定三段 + 单一滚动：

```text
┌ 项目 ─────────────────────┐   flex: 0 0 auto
│ 零件工艺标注        [设置] │
│ 5 标签 · 3 关系           │
├ 导入 Import ──────────────┤   flex: 0 0 auto
│ ┌───────────────────────┐ │
│ │ 拖拽 PDF / 图片 / 文件夹 │ │
│ └───────────────────────┘ │
│ [选择文件] [选择文件夹] [⚙] │
│ 批量进度 / 队列统计        │
├ 文件 (12)           [刷新] ┤   flex: 1 1 auto
│ [PDF] a.pdf      已完成    │ ↑
│ [IMG] b.png      识别中 40%│ │ 唯一滚动条
│ [PDF] c.pdf      已完成    │ ↓
└───────────────────────────┘
```

改动点：

- `ProjectPanel.vue`：删除「当前项目」下拉、下拉中的「＋新建项目」选项、摘要中的「编辑配置」按钮与删除图标。摘要保留项目名、标签/关系数、一个 `[设置]` ghost 按钮；点开后展开原表单。删除项目改为表单底部的 danger 文字按钮。
- `ProjectPanel.vue` 通过 `defineExpose({ startCreate, startEdit, cancelCreate })` 暴露入口；父组件在顶栏 `+` 点击时调用 `startCreate()`。
- `AppHeader.vue` 新增 `create` 事件与 `+` 图标按钮。
- `MixedAnnotationView.vue` 接线：`@create="projectPanelRef?.startCreate()"`。

滚动修复（`styles/app.css`）：

```css
.project-sidebar { overflow: hidden; display: flex; flex-direction: column; }
.file-panel      { flex: 1 1 auto; min-height: 0; }
.file-scroll     { flex: 1 1 auto; min-height: 0; max-height: none; overflow-y: auto; }
@media (max-height: 700px) {
  .project-sidebar { overflow-y: auto; }
  .file-panel { flex: 0 0 auto; }
}
```

结果：视口正常时项目区与导入区固定，文件列表吃掉剩余高度并独自滚动；视口过矮时回退为整栏滚动，避免文件区被压成 0。

### 2.2 导入区：同层级入口 + 参数弹窗

- 面板标题 `Import 文件` → **导入 Import**，右侧保留 `PDF · PNG · JPG` 计数，消除与文件面板重名。
- 拖拽区保持为主入口；下方三个同高控件：`[选择文件] [选择文件夹] [⚙]`。
  - 「选择文件」「选择文件夹」同为 `.mx-btn` 次级按钮，视觉同级。
  - 「⚙」打开新增的 `ConversionSettingsDialog.vue`：表格识别 / 公式识别 / DPI，底部 `[取消] [应用]`。
- 原面板内两段长提示文字移入弹窗；面板只保留导入进度、队列统计与必要的一行提示。
- 弹窗与宿主通过 `v-model:open` + `options` / `update:options` 通信，沿用现有 `conversionOptions`，不新增状态源。
- 弹窗实现方式与现有 `FigureDialog.vue` 保持一致（遮罩、Esc 关闭、焦点处理）。

### 2.3 工具栏：分隔线分三组

```text
项目 / 文件名    [标注 | 编辑 Markdown] │ [PDF 预览] [同步滚动] │ [+ 图片/表格标注]  [保存 Ctrl+S]
   身份               模式（主轴）            视图（次）              动作              主操作
```

- 组间 1px 竖直分隔线，高 16px，`var(--mw-line)`。
- `PDF 预览` 与 `同步滚动` 包进 `.mw-view-group`，二者禁用条件一致：`!completed || !documentReady || source_type !== 'pdf'`。
- 「图片/表格标注」保持 `mw-tool--capture` 橙色描边强调。
- 「保存标注」保持唯一实心主按钮。
- `≤760px`：分隔线隐藏，分组容器自动换行；不改变任何行为。

## 3. 验收标准

1. 顶栏与左侧栏合计只有一处项目切换控件。
2. 左侧栏任何滚动位置都能看到文件列表底部；不存在内外两条滚动条。
3. 「选择文件」「选择文件夹」视觉同级；DPI/表格/公式只在齿轮弹窗内出现。
4. 工具栏呈现“模式 / 视图 / 动作 / 主操作”四级层级，组间有分隔线。
5. `npm run typecheck` 通过；页面在 5175 实际渲染正常。
6. 上传、文件夹导入、转换轮询、标注保存、PDF 预览与分栏拖拽行为不变。

## 4. 不做

- 不改后端接口与数据模型。
- 不做移动端专属重排（沿用现有 ≤900px 回退）。
- 不引入新的 UI 组件库或状态管理库。
