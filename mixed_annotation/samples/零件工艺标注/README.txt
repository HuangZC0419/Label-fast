项目名称：零件工艺标注
项目 ID：f59be0dc-97c0-4600-bb30-686ce864ffe2
导出时间：2026-10-24T06:15:59Z
文件数量：2

ZIP 结构：
  original/   原始 PDF / 图片
  markdown/   OCR 或人工编辑后的 Markdown 与图片
  annotations.jsonl  每个文件一行标注记录
  README.txt

- test.pdf → 零件工艺标注/original/test__7b1bef13/source.pdf / 零件工艺标注/markdown/test__7b1bef13/result.md
- GBT+4423-2020.pdf → 零件工艺标注/original/GBT+4423-2020__5a3fbef2/source.pdf / 零件工艺标注/markdown/GBT+4423-2020__5a3fbef2/result.md

说明：
1. annotations.jsonl 的 text 字段是标注坐标系使用的 canonical text。
2. spans 的 start/end 为 text 中的字符偏移（左闭右开）。
3. Markdown 内图片引用使用相对路径 images/...。
4. 重新 OCR 或修改 Markdown 会使旧标注失效，导出前请确认标注数据。
