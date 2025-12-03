import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"

type Span = { id: number; start: number; end: number; label: string }
type Relation = { fromId: number; toId: number; type: string }

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
  const labels = useMemo(() => (labelsInput || "").split(/[，,;；]/).map(s => s.trim()).filter(Boolean), [labelsInput])
  const relationTypes = useMemo(() => (relationTypesInput || "").split(/[，,;；]/).map(s => s.trim()).filter(Boolean), [relationTypesInput])
  const [selectedIndices, setSelectedIndices] = useState<Set<number>>(new Set())
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
  const labelAlpha = 0.5
  const rgba = (hex: string, alpha: number) => {
    const c = hex.replace('#','')
    const r = parseInt(c.substring(0,2),16)
    const g = parseInt(c.substring(2,4),16)
    const b = parseInt(c.substring(4,6),16)
    return `rgba(${r},${g},${b},${alpha})`
  }
  const spanSegments = (start: number, end: number, rects: {x:number;y:number;w:number;h:number}[]) => {
    const out: {x:number;y:number;w:number;h:number}[] = []
    if (start < 0 || end <= start || rects.length === 0) return out
    
    // Safety cap
    const safeEnd = Math.min(end, rects.length)
    
    let i = start
    while (i < safeEnd) {
      const r0 = rects[i]
      if (!r0) { i++; continue } // Should not happen if bounded by rects.length, but safe
      
      let w = r0.w
      let j = i + 1
      while (j < safeEnd) {
        const r = rects[j]
        if (!r) break
        if (Math.abs(r.y - r0.y) < 0.5) { w += r.w; j++ } else break
      }
      out.push({ x: r0.x, y: r0.y, w, h: r0.h })
      i = j
    }
    return out
  }
  const [text, setText] = useState("Mike lives in America.")
  const [spans, setSpans] = useState<Span[]>([])
  const [spansByIndex, setSpansByIndex] = useState<{[key:number]: Span[]}>({})
  const [nextId, setNextId] = useState(1)
  const [relations, setRelations] = useState<Relation[]>([])
  const [relationsByIndex, setRelationsByIndex] = useState<{[key:number]: Relation[]}>({})
  const [items, setItems] = useState<string[]>([])
  const [docIds, setDocIds] = useState<number[]>([])
  const [pid, setPid] = useState<number>(2)
  const [itemStatuses, setItemStatuses] = useState<{[key:number]: "pending"|"in_progress"|"completed"}>({})

  useEffect(() => {
    fetch('http://localhost:8000/api/projects/id-by-name/Demo')
      .then(r => r.ok ? r.json() : {id: 2})
      .then(d => {
        const id = d.id
        setPid(id)
        return fetch(`http://localhost:8000/api/projects/${id}/sync`)
      })
      .then(r => {
        if (!r.ok) throw new Error("Failed to load")
        return r.json()
      })
      .then(data => {
        if (data.project) {
          setProjectName(data.project.name)
          const l = data.project.labels
          setLabelsInput(Array.isArray(l) ? l.join(",") : (l || "PER,LOC,ORG"))
          const r = data.project.relation_types
          setRelationTypesInput(Array.isArray(r) ? r.join(",") : (r || "LOCATED_IN,WORKS_AT,FOUNDED_IN"))
        }
        if (data.documents && Array.isArray(data.documents)) {
           const newItems: string[] = []
           const newDocIds: number[] = []
           const newStatuses: any = {}
           const newSpans: any = {}
           const newRels: any = {}
           
           data.documents.forEach((d: any, i: number) => {
             newItems.push(d.text)
             newDocIds.push(d.id)
             newStatuses[i] = d.status
             newSpans[i] = d.spans || []
             newRels[i] = d.relations || []
           })
           
           setItems(newItems)
           setDocIds(newDocIds)
           setItemStatuses(newStatuses)
           setSpansByIndex(newSpans)
           setRelationsByIndex(newRels)
           
           if (newItems.length > 0) {
             setCurrentIndex(0)
             setText(newItems[0])
             setSpans(newSpans[0] || [])
             setRelations(newRels[0] || [])
           }
        }
      })
      .catch(e => console.error("Sync load error:", e))
  }, [])
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
  const [selectedSpanId, setSelectedSpanId] = useState<number | null>(null)
  const [relFromId, setRelFromId] = useState<number | null>(null)
  const charRefs = useRef<{[key:number]: HTMLSpanElement|null}>({})
  const [charRects, setCharRects] = useState<{x:number;y:number;w:number;h:number}[]>([])
  const [fontSize, setFontSize] = useState<number>(18)
  const [lineH, setLineH] = useState<number>(1.8)
  const [relStrokeWidth, setRelStrokeWidth] = useState<number>(2)
  const [relDashed, setRelDashed] = useState<boolean>(false)
  

  const onMouseUp = (e: React.MouseEvent<HTMLDivElement>) => {
    if (relPickerOpen || dragFromId !== null) return
    if (relFromId !== null) setRelFromId(null)
    e.preventDefault()
    e.stopPropagation()
    const off = getOffsets()
    if (!off) return
    setPending(off)
    setLabelPickerOpen(true)
    requestAnimationFrame(() => {
      const sel = window.getSelection()
      sel?.removeAllRanges()
      containerRef.current?.focus()
    })
  }

  const addSpan = (label: string) => {
    if (!pending) return
    if (!labels.includes(label)) return
    const s = { id: nextId, start: pending.start, end: pending.end, label }
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
    if (selectedSpanId === id) setSelectedSpanId(null)
    if (relFromId === id) setRelFromId(null)
  }

  const chars = useMemo(() => Array.from(text), [text])
  const getCharIndexAtPoint = (clientX: number, clientY: number): number => {
    const c = containerRef.current
    if (!c || charRects.length === 0) return -1
    const cb = c.getBoundingClientRect()
    const x = clientX - cb.left
    const y = clientY - cb.top
    let best = -1
    let bestScore = Number.POSITIVE_INFINITY
    for (let i = 0; i < charRects.length; i++) {
      const r = charRects[i]
      const cx = r.x + r.w / 2
      const cy = r.y + r.h / 2
      const dx = x - cx
      const dy = y - cy
      const score = Math.abs(dy) + Math.abs(dx)
      if (score < bestScore) { bestScore = score; best = i }
    }
    return best
  }
  const onContainerContextMenu = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault()
    const idx = getCharIndexAtPoint(e.clientX, e.clientY)
    if (idx < 0) return
    const candidates = spans.filter(s => s.start <= idx && idx < s.end)
    if (candidates.length === 0) return
    const pos = candidates.findIndex(s => s.id === selectedSpanId)
    const next = candidates[(pos + 1) % candidates.length]
    setSelectedSpanId(next.id)
  }

  const measureRectsAndBoxes = () => {
    const c = containerRef.current
    if (!c) return
    const cb = c.getBoundingClientRect()
    const rects: {x:number;y:number;w:number;h:number}[] = []
    for (let i = 0; i < chars.length; i++) {
      const el = charRefs.current[i]
      if (!el) { rects.push({x:0,y:0,w:0,h:0}); continue }
      const r = el.getBoundingClientRect()
      rects.push({ x: r.left - cb.left, y: r.top - cb.top, w: r.width, h: r.height })
    }
    setCharRects(rects)
    const m: Record<number, { x: number; y: number; w: number; h: number }> = {}
    for (const s of spans) {
      const segs = spanSegments(s.start, s.end, rects)
      if (segs.length > 0) {
        const first = segs[0]
        m[s.id] = { x: first.x + first.w/2, y: first.y, w: first.w, h: first.h }
      }
    }
    setBoxes(m)
  }
  useLayoutEffect(() => { measureRectsAndBoxes() }, [chars, spans, fontSize, lineH])
  useEffect(() => {
    const onResize = () => measureRectsAndBoxes()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [chars, spans, fontSize, lineH])

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
      const newDocIds = [...docIds, ...all.map(() => -1)]
      const st = { ...itemStatuses }
      for (let i = 0; i < all.length; i++) st[idx0 + i] = "pending"
      setItems(newItems)
      setDocIds(newDocIds)
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

  const onSpanMouseDown = (id: number) => {
    setDragFromId(id)
    setSelectedSpanId(id)
  }
  const onSpanMouseUp = (id: number) => {
    if (dragFromId && dragFromId !== id) {
      setPendingRel({ fromId: dragFromId, toId: id })
      setRelPickerOpen(true)
    }
    setDragFromId(null)
  }

  const onSpanClick = (id: number) => {
    if (relFromId === null) {
      setRelFromId(id)
      setSelectedSpanId(id)
      return
    }
    if (relFromId !== id) {
      setPendingRel({ fromId: relFromId, toId: id })
      setRelPickerOpen(true)
    }
    setRelFromId(null)
  }

  const addRelation = (type: string) => {
    if (!pendingRel) return
    if (!relationTypes.includes(type)) return
    const exists = relations.some(r => r.fromId === pendingRel.fromId && r.toId === pendingRel.toId && r.type === type)
    if (exists) {
      setRelPickerOpen(false)
      setPendingRel(null)
      setRelFromId(null)
      return
    }
    setRelations([...relations, { fromId: pendingRel.fromId, toId: pendingRel.toId, type }])
    setRelPickerOpen(false)
    setPendingRel(null)
    setRelFromId(null)
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
  const [history, setHistory] = useState<{spans: Span[]; relations: Relation[]}[]>([])
  const undo = () => {
    const arr = [...history]
    const last = arr.pop()
    if (last) {
      setSpans(last.spans)
      setRelations(last.relations)
      setHistory(arr)
    }
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const editable = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      if (editable) return
      if (e.ctrlKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return }
      if (e.key === 'Delete') { if (selectedSpanId !== null) { removeSpanById(selectedSpanId); setSelectedSpanId(null); setRelFromId(null); } return }
      if (e.key === 'Escape') { e.preventDefault(); setSelectedSpanId(null); setPending(null); setLabelPickerOpen(false); setRelPickerOpen(false); setRelFromId(null); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevItem(); return }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextItem(); return }
      const d = Number(e.key)
      if (!Number.isNaN(d) && d >= 1 && d <= 9) {
        const idx = d - 1
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault(); e.stopPropagation()
          if (relPickerOpen && pendingRel && relationTypes[idx]) addRelation(relationTypes[idx])
        } else {
          if (labelPickerOpen && pending && labels[idx]) { e.preventDefault(); addSpan(labels[idx]) }
        }
        return
      }
      if (e.key === ' ') {
        e.preventDefault()
        if (labelPickerOpen && pending && labels[0]) addSpan(labels[0]); else nextItem()
        return
      }
    }
    window.addEventListener('keydown', onKey, { capture: true })
    return () => window.removeEventListener('keydown', onKey)
  }, [labelPickerOpen, pending, relPickerOpen, pendingRel, labels, relationTypes, selectedSpanId, spans, relations, history, currentIndex])

  const highlightIds = new Set<number>()
  if (hoverRelIdx !== null) {
    highlightIds.add(relations[hoverRelIdx].fromId)
    highlightIds.add(relations[hoverRelIdx].toId)
  }

  const onToggleSelect = (i: number, e: React.MouseEvent) => {
    e.stopPropagation()
    const newSet = new Set(selectedIndices)
    if (newSet.has(i)) newSet.delete(i)
    else newSet.add(i)
    setSelectedIndices(newSet)
  }

  const onClearAll = async () => {
    if (!confirm("Are you sure you want to delete ALL data? This cannot be undone.")) return
    try {
        const res = await fetch(`http://localhost:8000/api/projects/${pid}/clear`, { method: 'DELETE' })
        if (!res.ok) throw new Error("Clear failed")
        window.location.reload()
    } catch(e) {
        alert("Clear failed: " + e)
    }
  }

  const onDeleteDoc = async (i: number, e: React.MouseEvent) => {
      e.stopPropagation()
      if (!confirm("Delete this document?")) return
      const docId = docIds[i]
      if (docId && docId !== -1) {
          try {
              const res = await fetch(`http://localhost:8000/api/documents/${docId}`, { method: 'DELETE' })
              if (!res.ok) throw new Error("Delete failed")
          } catch(e) {
              alert("Delete failed: " + e)
              return
          }
      }
      // Remove from local state regardless of server status (if it was local only)
      // Ideally reload to be safe, but for better UX let's reload
      window.location.reload()
  }

  const onExport = () => {
    const idsToExport = selectedIndices.size > 0 
        ? Array.from(selectedIndices).map(i => docIds[i]).filter(id => id && id !== -1)
        : [] // If none selected, export all (default behavior handled by backend if list is empty/null? No, backend needs explicit list or None)
    
    // Logic: If selected, export selected. If none selected, export all.
    
    let url = `http://localhost:8000/api/projects/${pid}/export`
    if (idsToExport.length > 0) {
        const query = idsToExport.map(id => `doc_ids=${id}`).join("&")
        url += `?${query}`
    } else if (selectedIndices.size > 0) {
         // User selected items but they have no ID (not saved)?
         alert("Selected items are not saved. Please save first.")
         return
    }
    
    window.open(url, '_blank')
  }

  const onSave = async () => {
    // Construct latest data snapshot to ensure current document changes are included
    const nextSpans = { ...spansByIndex }
    const nextRels = { ...relationsByIndex }
    if (currentIndex >= 0) {
        nextSpans[currentIndex] = spans
        nextRels[currentIndex] = relations
    }
    // Also update state to reflect these changes in UI logic immediately if needed
    setSpansByIndex(nextSpans)
    setRelationsByIndex(nextRels)

    const payload = {
      project: { 
        name: projectName, 
        labels: labelsInput.split(/[，,;；]/).map(s => s.trim()).filter(Boolean), 
        relation_types: relationTypesInput.split(/[，,;；]/).map(s => s.trim()).filter(Boolean) 
      },
      documents: items.map((text, i) => ({
        id: docIds[i] || -1,
        text,
        status: itemStatuses[i] || "pending",
        spans: nextSpans[i] || [],
        relations: nextRels[i] || []
      }))
    }
    try {
      const res = await fetch(`http://localhost:8000/api/projects/${pid}/sync`, { 
        method: 'POST', 
        body: JSON.stringify(payload), 
        headers: {'Content-Type': 'application/json'} 
      })
      if (!res.ok) throw new Error("Save failed")
      
      const data = await res.json()
      if (data.documents && Array.isArray(data.documents)) {
          // Update docIds with the returned IDs from backend
          const newDocIds = [...docIds]
          data.documents.forEach((d: any, i: number) => {
              if (i < newDocIds.length) newDocIds[i] = d.id
          })
          setDocIds(newDocIds)
      }
      
      alert("Project saved!")
    } catch (e) {
      alert("Save failed: " + e)
    }
  }

  return (
    <div style={{ display: "flex", gap: 24, padding: 16 }}>
      <div style={{ width: 300 }}>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
             <span style={{ fontWeight: "bold" }}>Project Config</span>
             <div style={{ display: "flex", gap: 8 }}>
               <button onClick={onSave} style={{ padding: "4px 8px", background: "#28a745", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>Save</button>
               <button onClick={onExport} style={{ padding: "4px 8px", background: "#007bff", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>Export JSON</button>
               <button onClick={onClearAll} style={{ padding: "4px 8px", background: "#dc3545", color: "white", border: "none", borderRadius: 4, cursor: "pointer" }}>Clear All</button>
             </div>
          </div>
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
              <div key={i} onClick={() => { saveCurrent(); loadIndex(i) }} style={{ padding: 8, cursor: "pointer", background: currentIndex===i?"#f0f0f0":undefined, display: "flex", justifyContent: "space-between", alignItems: 'center' }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
                    <input type="checkbox" checked={selectedIndices.has(i)} onClick={(e) => onToggleSelect(i, e)} onChange={()=>{}} />
                    <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 160 }}>{items[i]}</div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div>{itemStatuses[i]==='completed'?"✅":itemStatuses[i]==='in_progress'?"⏳":"🕒"}</div>
                    <button onClick={(e) => onDeleteDoc(i, e)} style={{ border: "none", background: "transparent", cursor: "pointer", color: "#dc3545" }}>×</button>
                </div>
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
        <div style={{ marginTop: 16 }}>
          <div>Theme & Shortcuts</div>
          <div style={{ display: 'grid', gap: 8 }}>
            <label>Font size <input type="number" value={fontSize} onChange={e => setFontSize(parseInt(e.target.value||'18'))} style={{ width: 80 }} /></label>
            <label>Line height <input type="number" value={lineH} step={0.1} onChange={e => setLineH(parseFloat(e.target.value||'1.8'))} style={{ width: 80 }} /></label>
            <label>Relation width <input type="number" value={relStrokeWidth} onChange={e => setRelStrokeWidth(parseInt(e.target.value||'2'))} style={{ width: 80 }} /></label>
            <label><input type="checkbox" checked={relDashed} onChange={e => setRelDashed(e.target.checked)} /> Dashed relation</label>
            <div style={{ fontSize: 12, color: '#555' }}>
              点击一个实体后再点另一个实体可添加关系；1-9 选择实体；Ctrl+1-9 选择关系；Space 确认/下一项；Ctrl+Z 撤销；Delete 删除选中；← → 导航
            </div>
          </div>
        </div>
      </div>
      <div style={{ flex: 1, position: "relative", marginLeft: 12, maxWidth: 980 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <button onClick={prevItem}>Prev</button>
          <button onClick={nextItem}>Next</button>
          <div>{currentIndex>=0?`第${currentIndex+1}/共${items.length}`:"未导入"}</div>
          <button onClick={markCompleted}>Mark completed</button>
          <div>{currentIndex>=0 && itemStatuses[currentIndex]==='completed'?"✅":null}</div>
        </div>
        <div ref={containerRef} tabIndex={0} onMouseUp={onMouseUp} onContextMenu={onContainerContextMenu} style={{ fontSize: fontSize, lineHeight: lineH, userSelect: "text", cursor: "text", border: "1px solid #ddd", borderRadius: 6, padding: 12, minHeight: 160, position: "relative", whiteSpace: "pre-wrap", overflow: "hidden", background: "#fff", maxWidth: "100%" }}>
          {chars.map((ch, i) => (
            <span key={i} ref={el => { charRefs.current[i] = el }}>
              {ch}
            </span>
          ))}
          {spans.map(s => {
            const segs = spanSegments(s.start, s.end, charRects)
            const color = palette[s.label]
            return segs.map((seg, idx) => (
              <div key={`${s.id}-${idx}`} onMouseDown={() => onSpanMouseDown(s.id)} onMouseUp={() => onSpanMouseUp(s.id)} onClick={() => onSpanClick(s.id)}
                   style={{ position: 'absolute', left: seg.x, top: seg.y, width: seg.w, height: seg.h, background: rgba(color, labelAlpha), borderRadius: 4, outline: selectedSpanId===s.id? '2px solid #333': undefined, transition: 'outline 150ms', cursor: 'pointer' }} />
            ))
          })}
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
              const dy = Math.abs(b.y - a.y)
              const y = Math.min(a.y, b.y) - 10
              const x1 = a.x
              const x2 = b.x
              const mx = (x1 + x2) / 2
              const color = relPalette[r.type] || "#333"
              return (
                <g key={i} onMouseEnter={() => setHoverRelIdx(i)} onMouseLeave={() => setHoverRelIdx(null)} style={{ pointerEvents: "auto" }}>
                  <path d={`M ${x1} ${y} C ${mx} ${y-20-dy*0.2}, ${mx} ${y-20-dy*0.2}, ${x2} ${y}`} stroke={color} fill="none" strokeWidth={hoverRelIdx===i?Math.max(relStrokeWidth, relStrokeWidth+1):relStrokeWidth} markerEnd="url(#arrow)" strokeDasharray={relDashed? '6 4': undefined} />
                  <text x={mx} y={y-24-dy*0.2} fill={color} fontSize={12} textAnchor="middle">{r.type}</text>
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