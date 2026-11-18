# 标注结果导出 + 训练数据集库 设计规格

日期：2026-10-26
状态：已确认

## 1. 背景

系统已具备规则标注与模型标注能力，但缺少：

1. 将标注结果导出为标准 JSONL 的能力
2. 模型训练时持久化、复用训练数据集的入口，以及上传数据集的统计视图

目标导出格式以仓库根目录 `测试文本_annotations.jsonl` 为唯一标准（`mineru-annotation-jsonl-v1`）。

## 2. 标注结果导出

### 2.1 接口

`POST /result/{task_id}/export-annotations`

请求体：

```json
{
  "rules": ["standards", "limits"],
  "model_id": "abc123",
  "model_conf_threshold": 0.5
}
```

- `rules`：当前勾选的规则 id 列表，可为空
- `model_id`：当前选择的持久模型，可为空
- `model_conf_threshold`：0~1，默认 0
- `rules` 与 `model_id` 同时为空时返回 400

响应：`application/x-ndjson`，`Content-Disposition: attachment; filename=<stem>_annotations.jsonl`

### 2.2 输出行结构（严格遵循样例）

```json
{
  "file_name": "测试文本.png",
  "file_number": 2,
  "task_id": "c1c14f8a-...",
  "text": "句子文本",
  "annotations": [
    {
      "id": "standards:0",
      "rule_id": "standards",
      "label": "标准条文",
      "tags": ["GB/T3191-2019"],
      "sources": ["rule"]
    }
  ],
  "spans": [
    {
      "id": "standards:standard:GB/T3191-2019",
      "start": 44,
      "end": 57,
      "label": "标准条文",
      "text": "GB/T3191-2019",
      "rule_id": "standards",
      "sources": ["rule"]
    }
  ],
  "relations": [],
  "meta": {
    "export_format": "mineru-annotation-jsonl-v1",
    "annotation_sources": ["rule"]
  }
}
```

### 2.3 生成规则

1. `file_name`：任务的文件名（`progress_store` 或输入目录首个文件）
2. `file_number`：全部任务按创建时间升序排序后，当前任务的序号（从 1 开始）
3. `task_id`：路由参数
4. 分句：复用 `model_service._split_sentences`，每句作为一行 `text`
5. 规则标注逐句计算：
   - `standards`：`STANDARD_CODE_PATTERN` → span，类型 `standard`
   - `dates`：`DATE_PATTERN` + `is_plausible_date_match` → span，类型 `date`
   - `limits`：`find_limit_matches` → span，类型 `metric`
   - `numeric_facts`：`find_numeric_matches` → span，类型为函数返回的 entity_type
   - `decisions`：`is_decision_sentence` → 仅 annotation，`tags` 为句内标准编号
   - 所有规则均跳过 `is_structural_noise_sentence` 命中的句子
6. 模型标注：传入 `model_id` 时调用一次 `run_inference(model_id, markdown)`，实体按 `text` 定位到句子并计算偏移；`confidence < threshold` 的实体丢弃；定位失败的实体跳过
7. `annotations`：每个规则/模型标签在句内生成一条，`tags` 为该标签在本句的 span 文本去重列表；`decisions` 使用句内标准编号
8. `spans`：按 `start` 升序；相同 `(start,end,text,label)` 合并，`sources` 取并集并排序
9. `id`：
   - annotation：`<rule_id>:<全局递增序号>`
   - span：`<rule_id>:<type>:<text>`
   - 模型结果的 `rule_id` 直接使用模型标签（通常为中文），不做映射
10. `relations` 恒为 `[]`
11. `meta.annotation_sources`：该行 spans + annotations 中出现过的 sources 并集，排序
12. 只输出至少包含 1 条 annotation 的句子
13. 当 `limits` 与 `numeric_facts` 同时启用时，`numeric_facts` 只保留 `cas`/`numeric` 类型，带单位的指标（`metric`）由 `limits` 独占，避免同一区间出现矛盾标签
14. 仓库根 `测试文本_annotations.jsonl` 仅作为字段结构基准；实际分句与命中内容由当前 Markdown 和所选规则决定，不要求逐行内容一致

### 2.4 前端

- 快速标注页工具栏「复制 MD」旁新增「导出标注」按钮
- 请求参数：当前 `selectedAnnotationRules`、`selectedPersistentModelId`、`modelConfThreshold / 100`
- 模型仅在用户至少执行过一次模型标注后才纳入导出，避免误触发全量推理
- 两者均为空时按钮禁用
- 使用 axios `responseType: 'blob'` 下载，解析 `Content-Disposition` 文件名；失败时 toast 提示
- 无结果（0 字节）时不下载，toast：`当前没有可导出的标注结果`

## 3. 训练数据集库

### 3.1 存储

- 目录：`backend/datasets/`
- 原始数据：`<dataset_id>.jsonl`（UTF-8 原样保存）
- 元数据：`<dataset_id>.meta.json`
- `dataset_id = uuid4().hex[:12]`

元数据字段：

```json
{
  "dataset_id": "abc123def456",
  "name": "测试文本_annotations",
  "file_name": "测试文本_annotations.jsonl",
  "uploaded_at": "2026-10-26 12:00:00",
  "sample_count": 4,
  "entity_count": 6,
  "label_count": 4,
  "label_counts": {"标准条文": 3, "数值信息": 2, "判定结论": 1, "限值指标": 1},
  "char_count": 583,
  "avg_text_length": 145.8,
  "unlabeled_sample_count": 0,
  "format": "mineru-annotation-jsonl-v1"
}
```

统计口径：

- `sample_count`：含非空 `text` 的有效行数
- `entity_count`：所有 span/entity 总数（只统计 span）
- `label_counts`：按 label 计数；包含仅出现在 `annotations`、没有对应 span 的类别（如 `判定结论`），同一行中已作为 span 出现的标签不重复计数
- `label_count`：`label_counts` 的键数量
- `char_count`：所有 `text` 的字符总数
- `avg_text_length`：`char_count / sample_count`，保留 1 位小数
- `unlabeled_sample_count`：无标注的样本数

### 3.2 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/datasets/upload` | multipart：`file`、可选 `name`；解析成功才落盘；返回元数据 |
| GET | `/datasets` | 返回所有数据集元数据，按 `uploaded_at` 倒序 |
| GET | `/datasets/{dataset_id}` | 返回单个数据集元数据 |
| DELETE | `/datasets/{dataset_id}` | 删除原始文件与元数据 |
| POST | `/model/train-from-dataset` | JSON + SSE：`{dataset_ids, model_name, epochs, batch_size, lr}` |

错误处理：

- 非 UTF-8 或无法解析出有效样本 → 400，中文提示
- 数据集不存在 → 404
- 训练异常 → SSE `error` 事件，包含异常信息

训练实现：

1. 读取选中数据集，逐个 `parse_jsonl_training_data`
2. 合并 examples
3. 调用 `train_model(mode="persistent", model_name=..., labels=[], examples=..., epochs=..., batch_size=..., lr=...)`
4. 复用现有 SSE 心跳/进度格式

### 3.3 前端（模型训练页）

替换原「点击上传 JSONL 训练数据文件」入口：

- 顶部「训练数据集」区块，显示汇总：`N 个数据集 · X 样本 · Y 类别`
- 上传区：点击/拖拽，`accept=".jsonl,.json"`；上传后自动入库、自动勾选、展开统计
- 数据集卡片：勾选框、名称、样本数、实体数、类别数、上传时间、删除按钮
- 统计面板：
  - 四个指标块：样本数、实体数、类别数、总字数
  - 各类别数量条形图，宽度按当前数据集最大值归一化
- 训练按钮：`isTraining || selectedDatasetIds.length === 0 || !trainModelName.trim()` 时禁用
- 模型名称默认取最新上传数据集名（若用户未填写）
- 删除数据集使用 `confirm()` 确认，成功后 toast
- 右侧模型详情中原有下载/删除逻辑不变

### 3.4 兼容性

- 保留旧接口 `POST /model/upload-and-train`
- 前端训练全部改走 `/model/train-from-dataset`

## 4. 验证

新增测试：

1. `backend/tests/test_annotation_export.py`
   - 规则 span 偏移与 `text` 切片一致
   - `decisions` 只出现在 annotations
   - 合并模型结果时 `sources` 正确
   - 输出行包含样例的全部 9 个顶层字段
2. `backend/tests/test_dataset_stats.py`
   - 给定样例 JSONL 的统计值与预期一致
   - 无效行被忽略

手动联调：

- 用 `测试文本_annotations.jsonl` 在模型训练页上传，核对统计
- 勾选该数据集启动训练，确认 SSE 进度正常
- 在快速标注页导出，核对 JSONL 每行结构与样例一致

## 5. 非目标

- 不做关系抽取（`relations` 恒为空）
- 不做数据集版本管理、去重、编辑
- 不改造模型评价页的数据集入口
