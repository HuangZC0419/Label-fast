/** 统一把 0–1（或 0–100）的数值收敛到 0–1。 */
export function ratio(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const normalized = value > 1 ? value / 100 : value;
  return Math.min(1, Math.max(0, normalized));
}

/** 以百分比展示置信度。 */
export function percent(value: number, digits = 1): string {
  return `${(ratio(value) * 100).toFixed(digits)}%`;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function rowLabel(value: number | string): string {
  return value === "" || value === null || value === undefined
    ? "—"
    : String(value);
}

export function joinRows(rows: Array<number | string>): string {
  if (!rows.length) return "—";

  const numbers = rows
    .map((row) => (typeof row === "number" ? row : Number(row)))
    .filter((value) => Number.isFinite(value))
    .sort((left, right) => left - right);

  // 行号无法全部转成数字时，保留原始文本。
  if (numbers.length !== rows.length) {
    return rows.map(rowLabel).join("、");
  }

  // 连续行号压缩成区间，避免几十个行号把单元格撑得很高。
  const parts: string[] = [];
  let start = numbers[0];
  let previous = numbers[0];
  for (let index = 1; index < numbers.length; index += 1) {
    const current = numbers[index];
    if (current === previous + 1) {
      previous = current;
      continue;
    }
    parts.push(start === previous ? String(start) : `${start}–${previous}`);
    start = current;
    previous = current;
  }
  parts.push(start === previous ? String(start) : `${start}–${previous}`);
  return parts.join("、");
}
