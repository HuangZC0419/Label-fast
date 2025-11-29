import React, { useEffect, useMemo, useRef, useState } from "react"

type Span = { id: number; start: number; end: number; label: string }
type Piece = { text: string; label?: string; id?: number }
type Relation = { fromId: number; toId: number; type: string }

function splitBySpans(text: string, spans: Span[]): Piece[] {
  const sorted = [...spans].sort((a, b) => a.start - b.start || a.end - b.end)
  const res: Piece[] = []
  let i = 0
  for (const s of sorted) {
    if (i < s.start) res.push({ text: text.slice(i, s.start) })
    res.push({ text: text.slice(s.start, s.end), label: s.label, id: s.id })
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
  const [relationTypesInput, setRelationTypesInput] = useState("LOCATED_IN,WORKS_AT,FOUNDED_IN")
  const labels = useMemo(() => labelsInput.split(",").map(s => s.trim()).filter(Boolean), [labelsInput])
  const relationTypes = useMemo(() => relationTypesInput.split(",").map(s => s.trim()).filter(Boolean), [relationTypesInput])
  const palette = useMemo(() => {
    const base = ["#ffb3ba", "#baffc9", "#bae1ff", "#ffffba", "#ffc9de", "#c9fff2"]
    const m: Record<string, string> = {}
    labels.forEach((l, i) => m[l] = base[i % base.length])
    return m
  }, [labels])
  const relPalette = useMemo(() => {
    const base = ["#9c27b0", "#3f51b5", "#009688", "#ff5722", "#795548", "#607d8b"]
    const m: Record<string, string> = {}
    relationTypes.forEach((r, i) => m[r] = base[i % base.length])
    return m
  }, [relationTypes])
  const [text, setText] = useState("Mike lives in America.")
  const [spans, setSpans] = useState<Span[]>([])
  const [spansByIndex, setSpansByIndex] = useState<{[key:number]: Span[]}>({})
  const [nextId, setNextId] = useState(1)
  const [relations, setRelations] = useState<Relation[]>([])
  const [relationsByIndex, setRelationsByIndex] = useState<{[key:number]: Relation[]}>({})
  const [items, setItems] = useState<string[]>([])
  const [itemStatuses, setItemStatuses] = useState<{[key:number]: "pending"|"in_progress"|"completed"}>({})
  const [currentIndex, setCurrentIndex] = useState<number>(-1)
  const [splitMode, setSplitMode] = useState<"as_is"|"paragraph"|"sentence"|"length">("sentence")
  const [fixedLength, setFixedLength] = useState<number>(500)
  const [uploadInfo, setUploadInfo] = useState<string>("")
  const [search, setSearch] = useState<string>("")
  const containerRef = useRef<HTMLDivElement>(null)
  const getOffsets = useSelectionOffsets(containerRef, text)
  const [pending, setPending] = useState<{ start: number; end: number } | null>(null)
  const [labelPickerOpen, setLabelPickerOpen] = useState(false)
  const [dragFromId, setDragFromId] = useState<number | null>(null)
  const [pendingRel, setPendingRel] = useState<{ fromId: number; toId: number } | null>(null)
  const [relPickerOpen, setRelPickerOpen] = useState(false)
  const [hoverRelIdx, setHoverRelIdx] = useState<number | null>(null)
  const [boxes, setBoxes] = useState<Record<number, { x: number; y: number; w: number; h: number }>>({})
  const pieceRefs = useRef<Record<number, HTMLSpanElement | null>>({})

  const onMouseUp = () => {
    const off = getOffsets()
    if (!off) return
    setPending(off)
    setLabelPickerOpen(true)
  }

  const addSpan = (label: string) => {
    if (!pending) return
    if (!labels.includes(label)) return
    const s = { id: nextId, start: pending.start, end: pending.end, label }
    for (const a of spans) {
      if (!(s.end <= a.start || s.start >= a.end)) return
    }
    setSpans([...spans, s])
    setNextId(nextId + 1)
    setLabelPickerOpen(false)
    setPending(null)
    window.getSelection()?.removeAllRanges()
  }

  const removeSpanById = (id: number) => {
    const arr = spans.filter(s => s.id !== id)
    const rel = relations.filter(r => r.fromId !== id && r.toId !== id)
    setSpans(arr)
    setRelations(rel)
  }

  const parts = splitBySpans(text, spans)

  useEffect(() => {
    const c = containerRef.current
    if (!c) return
    const cb = c.getBoundingClientRect()
    const m: Record<number, { x: number; y: number; w: number; h: number }> = {}
    for (const id of Object.keys(pieceRefs.current)) {
      const el = pieceRefs.current[Number(id)]
      if (!el) continue
      const r = el.getBoundingClientRect()
      m[Number(id)] = { x: r.left - cb.left + r.width / 2, y: r.top - cb.top, w: r.width, h: r.height }
    }
    setBoxes(m)
  }, [spans, text])

  useEffect(() => {
    if (currentIndex < 0) return
    const has = (spans.length > 0 || relations.length > 0)
    const st = has ? "in_progress" : (itemStatuses[currentIndex] || "pending")
    setItemStatuses({ ...itemStatuses, [currentIndex]: st })
  }, [spans, relations, currentIndex])

  const saveCurrent = () => {
    if (currentIndex < 0) return
    setSpansByIndex({ ...spansByIndex, [currentIndex]: spans })
    setRelationsByIndex({ ...relationsByIndex, [currentIndex]: relations })
  }
  const loadIndex = (idx: number) => {
    setCurrentIndex(idx)
    setText(items[idx])
    setSpans(spansByIndex[idx] || [])
    setRelations(relationsByIndex[idx] || [])
  }
  const prevItem = () => {
    if (items.length === 0 || currentIndex <= 0) return
    saveCurrent()
    loadIndex(currentIndex - 1)
  }
  const nextItem = () => {
    if (items.length === 0 || currentIndex >= items.length - 1) return
    saveCurrent()
    loadIndex(currentIndex + 1)
  }
  const markCompleted = () => {
    if (currentIndex < 0) return
    setItemStatuses({ ...itemStatuses, [currentIndex]: "completed" })
  }

  const readFileBuffer = (file: File): Promise<ArrayBuffer> => {
    return new Promise((resolve, reject) => {
      const fr = new FileReader()
      fr.onload = () => resolve(fr.result as ArrayBuffer)
      fr.onerror = e => reject(e)
      fr.readAsArrayBuffer(file)
    })
  }
  const tryDecode = (buf: ArrayBuffer): string => {
    const encs = ["utf-8", "gbk", "utf-16le", "utf-16be"]
    for (const e of encs) {
      try {
        const td = new TextDecoder(e as any, { fatal: true })
        const s = td.decode(buf)
        return s
      } catch {}
    }
    return new TextDecoder("utf-8").decode(buf)
  }
  const splitTextUI = (t: string): string[] => {
    const s = t.replace(/\r\n/g, "\n")
    if (splitMode === "as_is") return [s]
    if (splitMode === "paragraph") return s.split(/\n\n+/).map(x => x.trim()).filter(Boolean)
    if (splitMode === "sentence") {
      const out: string[] = []
      let cur = ""
      for (const ch of s) {
        cur += ch
        if (/[。．\.!？!?]/.test(ch)) {
          const k = cur.trim()
          if (k) out.push(k)
          cur = ""
        }
      }
      const rest = cur.trim()
      if (rest) out.push(rest)
      return out
    }
    if (splitMode === "length") {
      const n = fixedLength || 500
      const out: string[] = []
      for (let i = 0; i < s.length; i += n) out.push(s.slice(i, i + n))
      return out.filter(Boolean)
    }
    return [s]
  }
  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    const maxSize = 10 * 1024 * 1024
    const all: string[] = []
    let count = 0
    for (const f of Array.from(files)) {
      if (f.size > maxSize) {
        setUploadInfo("file too large: " + f.name)
        continue
      }
      try {
        const buf = await readFileBuffer(f)
        const txt = tryDecode(buf)
        const units = splitTextUI(txt)
        all.push(...units)
        count += units.length
      } catch (e) {
        setUploadInfo("failed: " + f.name)
      }
    }
    if (all.length) {
      const idx0 = items.length
      const newItems = [...items, ...all]
      const st = { ...itemStatuses }
      for (let i = 0; i < all.length; i++) st[idx0 + i] = "pending"
      setItems(newItems)
      setItemStatuses(st)
      if (currentIndex < 0) {
        setCurrentIndex(0)
        setText(newItems[0])
        setSpans(spansByIndex[0] || [])
        setRelations(relationsByIndex[0] || [])
      }
      setUploadInfo("imported " + count + " units")
    }
  }
  const onDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    await handleFiles(e.dataTransfer.files)
  }
  const onSelectFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const input = e.currentTarget
    await handleFiles(input.files)
    if (input) input.value = ""
  }
  const filteredIndices = items.map((_, i) => i).filter(i => items[i].toLowerCase().includes(search.toLowerCase()))

  const onPieceMouseDown = (id?: number) => {
    if (!id) return
    setDragFromId(id)
  }
  const onPieceMouseUp = (id?: number) => {
    if (!id) return
    if (dragFromId && dragFromId !== id) {
      setPendingRel({ fromId: dragFromId, toId: id })
      setRelPickerOpen(true)
    }
    setDragFromId(null)
  }

  const addRelation = (type: string) => {
    if (!pendingRel) return
    if (!relationTypes.includes(type)) return
    const exists = relations.some(r => r.fromId === pendingRel.fromId && r.toId === pendingRel.toId && r.type === type)
    if (exists) {
      setRelPickerOpen(false)
      setPendingRel(null)
      return
    }
    setRelations([...relations, { fromId: pendingRel.fromId, toId: pendingRel.toId, type }])
    setRelPickerOpen(false)
    setPendingRel(null)
  }

  const updateRelationType = (i: number, t: string) => {
    const arr = [...relations]
    arr[i] = { ...arr[i], type: t }
    setRelations(arr)
  }

  const deleteRelation = (i: number) => {
    const arr = [...relations]
    arr.splice(i, 1)
    setRelations(arr)
  }

  const highlightIds = new Set<number>()
  if (hoverRelIdx !== null) {
    highlightIds.add(relations[hoverRelIdx].fromId)
    highlightIds.add(relations[hoverRelIdx].toId)
  }

  return (
    <div style={{ display: "flex", gap: 16, padding: 16 }}>
      <div style={{ width: 300 }}>
        <div style={{ display: "grid", gap: 8 }}>
          <input value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="Project name" />
          <input value={labelsInput} onChange={e => setLabelsInput(e.target.value)} placeholder="Labels comma separated" />
          <input value={relationTypesInput} onChange={e => setRelationTypesInput(e.target.value)} placeholder="Relation types comma separated" />
          <textarea value={text} onChange={e => setText(e.target.value)} rows={6} />
          <button onClick={() => { setSpans([]); setRelations([]) }}>Clear annotations</button>
        </div>
        <div style={{ marginTop: 16, display: "grid", gap: 8 }}>
          <div>Upload TXT</div>
          <div onDragOver={e => e.preventDefault()} onDrop={onDrop} style={{ border: "2px dashed #bbb", borderRadius: 8, padding: 12 }}>
            <div>Drop .txt files here or select</div>
            <input type="file" multiple accept=".txt" onChange={onSelectFiles} />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <label><input type="radio" checked={splitMode==='as_is'} onChange={() => setSplitMode('as_is')} /> as_is</label>
              <label><input type="radio" checked={splitMode==='paragraph'} onChange={() => setSplitMode('paragraph')} /> paragraph</label>
              <label><input type="radio" checked={splitMode==='sentence'} onChange={() => setSplitMode('sentence')} /> sentence</label>
              <label><input type="radio" checked={splitMode==='length'} onChange={() => setSplitMode('length')} /> length</label>
              {splitMode==='length' && (<input type="number" value={fixedLength} onChange={e => setFixedLength(parseInt(e.target.value||'500'))} style={{ width: 80 }} />)}
            </div>
            <div>{uploadInfo}</div>
          </div>
          <input placeholder="Search" value={search} onChange={e => setSearch(e.target.value)} />
          <div style={{ maxHeight: 240, overflow: "auto", border: "1px solid #eee", borderRadius: 6 }}>
            {filteredIndices.map(i => (
              <div key={i} onClick={() => { saveCurrent(); loadIndex(i) }} style={{ padding: 8, cursor: "pointer", background: currentIndex===i?"#f0f0f0":undefined, display: "flex", justifyContent: "space-between" }}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 200 }}>{items[i]}</div>
                <div>{itemStatuses[i]==='completed'?"✅":itemStatuses[i]==='in_progress'?"⏳":"🕒"}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div>Labels</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {labels.map(l => (
              <div key={l} style={{ background: palette[l], padding: "4px 8px", borderRadius: 4 }}>{l}</div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div>Relation Types</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {relationTypes.map(t => (
              <div key={t} style={{ background: relPalette[t], padding: "4px 8px", borderRadius: 4, color: "#fff" }}>{t}</div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ flex: 1, position: "relative" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <button onClick={prevItem}>Prev</button>
          <button onClick={nextItem}>Next</button>
          <div>{currentIndex>=0?`第${currentIndex+1}/共${items.length}`:"未导入"}</div>
          <button onClick={markCompleted}>Mark completed</button>
          <div>{currentIndex>=0 && itemStatuses[currentIndex]==='completed'?"✅":null}</div>
        </div>
        <div ref={containerRef} onMouseUp={onMouseUp} style={{ fontSize: 18, lineHeight: 1.8, userSelect: "text", cursor: "text", border: "1px solid #ddd", padding: 12, minHeight: 160, position: "relative" }}>
          {parts.map((p, i) => (
            <span
              key={i}
              ref={el => { if (p.id) pieceRefs.current[p.id] = el }}
              onMouseDown={() => onPieceMouseDown(p.id)}
              onMouseUp={() => onPieceMouseUp(p.id)}
              style={{
                background: p.label ? palette[p.label] : undefined,
                borderRadius: p.label ? 4 : undefined,
                padding: p.label ? "2px 4px" : undefined,
                outline: p.id && highlightIds.has(p.id) ? "2px solid #333" : undefined
              }}
            >
              {p.text}
            </span>
          ))}
          <svg style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
            <defs>
              <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="#333" />
              </marker>
            </defs>
            {relations.map((r, i) => {
              const a = boxes[r.fromId]
              const b = boxes[r.toId]
              if (!a || !b) return null
              const y = Math.min(a.y, b.y) - 10
              const x1 = a.x
              const x2 = b.x
              const mx = (x1 + x2) / 2
              const color = relPalette[r.type] || "#333"
              return (
                <g key={i} onMouseEnter={() => setHoverRelIdx(i)} onMouseLeave={() => setHoverRelIdx(null)} style={{ pointerEvents: "auto" }}>
                  <path d={`M ${x1} ${y} C ${mx} ${y-20}, ${mx} ${y-20}, ${x2} ${y}`} stroke={color} fill="none" strokeWidth={hoverRelIdx===i?3:2} markerEnd="url(#arrow)" />
                  <text x={mx} y={y-24} fill={color} fontSize={12} textAnchor="middle">{r.type}</text>
                </g>
              )
            })}
          </svg>
        </div>
        {labelPickerOpen && pending && (
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {labels.map(l => (
              <button key={l} onClick={() => addSpan(l)} style={{ background: palette[l], border: "1px solid #ccc", borderRadius: 4, padding: "4px 8px" }}>{l}</button>
            ))}
          </div>
        )}
        {relPickerOpen && pendingRel && (
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {relationTypes.map(t => (
              <button key={t} onClick={() => addRelation(t)} style={{ background: relPalette[t], color: "#fff", border: "1px solid #ccc", borderRadius: 4, padding: "4px 8px" }}>{t}</button>
            ))}
          </div>
        )}
        <div style={{ marginTop: 16 }}>
          <div>Annotations</div>
          <div style={{ display: "grid", gap: 6 }}>
            {spans.map(s => (
              <div key={s.id} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div>{s.start}-{s.end} {s.label} {text.slice(s.start, s.end)}</div>
                <button onClick={() => removeSpanById(s.id)}>Delete</button>
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div>Relations</div>
          <div style={{ display: "grid", gap: 6 }}>
            {relations.map((r, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <select value={r.type} onChange={e => updateRelationType(i, e.target.value)}>
                  {relationTypes.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <div>{r.fromId} → {r.toId}</div>
                <button onClick={() => deleteRelation(i)}>Delete</button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}