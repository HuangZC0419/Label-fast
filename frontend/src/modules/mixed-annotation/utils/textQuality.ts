/**
 * 判断 Markdown 是否像「PDF 文本层编码坏掉」产生的符号串。
 *
 * 典型特征（中文标准文档）：几乎没有汉字、标点/符号占比极高、字母很少且不成词。
 * 英文文档虽然汉字为 0，但字母占比高、标点比例低，不会命中。
 * 只用于提示用户可重新 OCR，不阻塞任何操作。
 */
export function looksLikeGarbledMarkdown(text: string): boolean {
  const sample = String(text ?? '').replace(/\s+/g, '').slice(0, 20000)
  if (sample.length < 200) return false

  const cjk = (sample.match(/[\u4e00-\u9fff]/g) ?? []).length
  const latin = (sample.match(/[A-Za-z]/g) ?? []).length
  const punct = (sample.match(/[!"#$%&'()*+,\-./:;<=>?@[\]^_`{|}~]/g) ?? []).length
  const total = sample.length

  return cjk / total < 0.02 && punct / total > 0.2 && latin / total < 0.5
}
