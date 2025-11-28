import React, { useMemo, useRef, useState } from "react"

type Span = { start: number; end: number; label: string }

function splitBySpans(text: string, spans: Span[]) {
  const sorted = [...spans].sort((a, b) => a.start - b.start || a.end - b.end)
  const res: { text: string; label?: string }[] = []
  let i = 0
  for (const s of sorted) {
    if (i < s.start) res.push({ text: text.slice(i, s.start) })
    res.push({ text: text.slice(s.start, s.end), label: s.label })
    i = s.end
  }
  if (i < text.length) res.push({ text: text.slice(i) })
  return res
}

function useSelectionOffsets(container: React.RefObject<HTMLDivElement>, text: string) {
  const getOffsets = () => {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return null
    const range = sel.getRangeAt(0)
    if (!container.current || !container.current.contains(range.commonAncestorContainer)) return null
    const pre = range.cloneRange()
    pre.selectNodeContents(container.current)
    pre.setEnd(range.startContainer, range.startOffset)
    const start = pre.toString().length
    const length = range.toString().length
    if (length === 0) return null
    const end = start + length
    if (start < 0 || end > text.length || start >= end) return null
    return { start, end }
  }
  return getOffsets
}

export default function App() {
  const [projectName, setProjectName] = useState("Demo")
  const [labelsInput, setLabelsInput] = useState("PER,LOC,ORG")
  const labels = useMemo(() => labelsInput.split(",").map(s => s.trim()).filter(Boolean), [labelsInput])
  const palette = useMemo(() => {
    const base = ["#ffb3ba", "#baffc9", "#bae1ff", "#ffffba", "#ffc9de", "#c9fff2"]
    const m: Record<string, string> = {}
    labels.forEach((l, i) => m[l] = base[i % base.length])
    return m
  }, [labels])
  const [text, setText] = useState("Mike lives in America.")
  const [spans, setSpans] = useState<Span[]>([])
  const containerRef = useRef<HTMLDivElement>(null)
  const getOffsets = useSelectionOffsets(containerRef, text)
  const [pending, setPending] = useState<{ start: number; end: number } | null>(null)
  const [labelPickerOpen, setLabelPickerOpen] = useState(false)

  const onMouseUp = () => {
    const off = getOffsets()
    if (!off) return
    setPending(off)
    setLabelPickerOpen(true)
  }

  const addSpan = (label: string) => {
    if (!pending) return
    if (!labels.includes(label)) return
    const s = { start: pending.start, end: pending.end, label }
    for (const a of spans) {
      if (!(s.end <= a.start || s.start >= a.end)) return
    }
    setSpans([...spans, s])
    setLabelPickerOpen(false)
    setPending(null)
    window.getSelection()?.removeAllRanges()
  }

  const removeSpan = (idx: number) => {
    const arr = [...spans]
    arr.splice(idx, 1)
    setSpans(arr)
  }

  const parts = splitBySpans(text, spans)

  return (
    <div style={{ display: "flex", gap: 16, padding: 16 }}>
      <div style={{ width: 300 }}>
        <div style={{ display: "grid", gap: 8 }}>
          <input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="Project name" />
          <input value={labelsInput} onChange={e => setLabelsInput(e.target.value)} placeholder="Labels comma separated" />
          <textarea value={text} onChange={e => setText(e.target.value)} rows={6} />
          <button onClick={() => setSpans([])}>Clear annotations</button>
        </div>
        <div style={{ marginTop: 16 }}>
          <div>Labels</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {labels.map(l => (
              <div key={l} style={{ background: palette[l], padding: "4px 8px", borderRadius: 4 }}>{l}</div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ flex: 1 }}>
        <div ref={containerRef} onMouseUp={onMouseUp} style={{ fontSize: 18, lineHeight: 1.8, userSelect: "text", cursor: "text", border: "1px solid #ddd", padding: 12, minHeight: 160 }}>
          {parts.map((p, i) => (
            <span key={i} style={{ background: p.label ? palette[p.label] : undefined, borderRadius: p.label ? 4 : undefined, padding: p.label ? "2px 4px" : undefined }}>
              {p.text}
            </span>
          ))}
        </div>
        {labelPickerOpen && pending && (
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {labels.map(l => (
              <button key={l} onClick={() => addSpan(l)} style={{ background: palette[l], border: "1px solid #ccc", borderRadius: 4, padding: "4px 8px" }}>{l}</button>
            ))}
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <div>Annotations</div>
          <div style={{ display: "grid", gap: 6 }}>
            {spans.map((s, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div>{s.start}-{s.end} {s.label} {text.slice(s.start, s.end)}</div>
                <button onClick={() => removeSpan(i)}>Delete</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}