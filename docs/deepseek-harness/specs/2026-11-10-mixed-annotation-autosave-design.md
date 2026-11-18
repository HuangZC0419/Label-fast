# 混合标注：模式切换内嵌与自动保存

- 日期：2026-11-10
- 状态：已确认
- 范围：`frontend/src/modules/mixed-annotation/` 前端交互
- 不改动：上传/导入/轮询、图表创建/编辑/删除、PDF 预览与分栏拖拽

## 1. 目标

1. 把「标注 / 编辑 Markdown」移入左侧内容面板标题栏，合并为一个模式切换按钮。
2. 工具栏只保留视图控制（PDF 预览 / 同步滚动），删除保存按钮；导出 ZIP 保留在顶栏。
3. 标注与 Markdown 改为自动保存，内容面板显示「保存中／已保存」。
4. PDF 预览入口改名「图片／表格标注」。

## 2. 模式切换

- 新增 `ModeToggle.vue`：一个药丸按钮，显示当前状态「标注模式」或「编辑模式」，点击切换。
- 放置位置：
  - 标注模式：`MarkdownAnnotator` 的 `tools-head` 右侧（撤销按钮旁）。
  - 编辑模式：`MarkdownEditor` 的 `editor-head` 右侧（还原按钮旁）。
- 两个组件通过 `#mode-toggle` 插槽接收同一个 `ModeToggle`。
- 工具栏移除两个模式按钮。

## 3. 保存状态

新增 `SaveStatus.vue`：

| 状态 | 文案 | 颜色 |
|---|---|---|
| `saved` | 已保存 | 绿 |
| `saving` | 保存中… | 琥珀（脉冲） |
| `pending` | 待保存 | 灰 |
| `error` | 保存失败 | 红，title 显示错误 |

- 标注模式：放在 `tools-head` 中（`#save-status` 插槽）。
- 编辑模式：替换 `editor-head` 原有的「有未应用修改 / 已同步」pill（`#save-status` 插槽）。
- 编辑器的「应用修改」按钮删除，保留「还原」与字符数。

## 4. 自动保存

### 4.1 标注模式

- `MarkdownAnnotator` 新增 `change` 事件：`spans / relations / paragraphs` 深度变化且 `active` 时触发；文档加载期间抑制。
- `MixedWorkspace` 收到 `change` 后进入 `pending`，1.2 秒防抖后 PUT `/api/files/{id}/annotations`。
- 成功后 `saved`，并触发一次 `saved` 事件刷新文件列表的「已标注」徽标。

### 4.2 编辑模式

- `MarkdownEditor` 的 `update:model-value` 触发 `pending`，1.2 秒防抖后应用 Markdown。
- 应用 Markdown 会重建 blocks 并清空实体/关系标注（图表保留）。
- 从标注模式进入编辑模式时：
  - 先 flush 待保存的标注；
  - 若存在标注，弹一次性确认「进入编辑模式并自动保存 Markdown 会清空已有的实体/关系标注（图表保留）」，确认后才进入；
  - 本次编辑会话内后续自动保存不再重复确认。
- `applyMarkdown` 增加选项：`skipConfirm`、`silent`、保持编辑模式（不再自动切回标注模式）。

### 4.3 落盘时机

- 1.2 秒空闲自动保存。
- 切换模式、切换文件、组件卸载前强制 flush。
- `Ctrl+S` 立即保存（标注模式保存标注；编辑模式应用 Markdown）。

### 4.4 失败处理

- 失败时状态为 `error`，保留草稿，5 秒后自动重试（最多 3 次）。
- 同时设置 `actionError` 横幅展示具体错误；成功后清除。

## 5. PDF 入口

- `PdfPreview` 头部按钮文案：`图片／表格标注`；激活时 `退出标注`。
- 框选流程不变，`FigureDialog` 内选择「图 / 表」。

## 6. 验收标准

1. 工作区顶部只剩 PDF 预览 / 同步滚动；模式切换在内容面板标题栏。
2. 模式按钮显示当前状态，点击可在两种模式间切换。
3. 标注操作停止 1.2 秒后自动保存，内容面板显示「保存中…／已保存」。
4. Markdown 编辑停止 1.2 秒后自动保存；切换模式前强制落盘。
5. 有标注时进入编辑模式会一次性确认；取消则留在标注模式。
6. 保存失败显示红色「保存失败」，5 秒后自动重试。
7. PDF 按钮显示「图片／表格标注」，框选后可创建图/表。
8. `npm run typecheck` 与 `npm run build` 通过。
