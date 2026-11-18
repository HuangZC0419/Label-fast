# 命中片段与高亮一一对应 重构设计

## 原则
**不合并、不去重。** 每个实体实例独立渲染为一个片段条目和一个高亮 mark，通过 `entity_id` 双向绑定。

## 一、架构变化

```
当前:
后端 entities[] ─ dedup ─→ snippets[]  (丢信息)
         └───→ highlightHtmlContent (regex, 无序匹配)

重构后:
后端 entities[] ────→ entries[]  (每个实体一条,带 offset+context)
         └───→ highlightByOffset  (按 start/end 精确定位 mark)
         
entry ↔ mark 通过 entity_id 双向绑定
```

## 二、后端改动 (model_service.py)

1. `run_inference` 中删除 `seen_texts` 去重逻辑（约 line 748-753）
2. 每个 entity 保留原始 `id` 和 `context`
3. 每个 entity 直接生成一个 entry（替代 snippet），字段：
   - `id`: 唯一标识，如 "工序编号:3"
   - `rule_label`: 标签名
   - `text`: 实体文本
   - `context`: 前后文
   - `start_offset`/`end_offset`: 在原句中的位置
4. 返回 `entries` 替代 `snippets`

## 三、前端改动 (App.vue)

### 1. highlightHtmlContent 重写
- 删除 regex 匹配方式
- 改为按 `(start_offset, end_offset)` 在文本中定位
- 遍历每个实体 → 找到对应字符位置 → 注入 `<mark>` 标签
- 每个 mark 带 `data-entity-id` 属性

### 2. 左侧面板
- 每条 entry 渲染为一个卡片
- 显示：标签名 + 实体文本 + 上下文截断（前后15字）
- 左侧色条颜色与标签对应
- 卡片带 `data-entity-id`

### 3. 双向导航
- 点击条目 → `querySelector([data-entity-id="..."])` → 滚动 → 焦点框(亮色边框+脉冲动画,持续到下次点击)
- 点击高亮 → 反向查找对应条目 → 滚动列表中该条目可见

### 4. 焦点框样式
```css
.annotation-highlight-focus {
  outline: 3px solid var(--color-primary);
  outline-offset: 3px;
  animation: focus-pulse 0.6s ease;
  z-index: 10;
}
```

### 5. 颜色系统
保持现有动态颜色分配，标签 → 颜色一致。

## 四、数据流

```
用户点击「标注」
    ↓
后端 run_inference → entities[] (每个实体有唯一id+offset)
    ↓
前端 entries[] = entities (不去重)
    ↓
highlightByOffset() → 按 offset 在 HTML 中精确插入 <mark data-entity-id="X">
    ↓
左侧列表 render entries → 卡片(data-entity-id="X")
    ↓
用户点击卡片 → querySelector mark → scrollIntoView + focus class
或: 用户点击 mark → querySelector card → scrollIntoView
```
