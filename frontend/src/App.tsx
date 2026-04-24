import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import "./App.css"
import HelpModal from './HelpModal'

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
  const [projectName, setProjectName] = useState("")
  const [labelsInput, setLabelsInput] = useState("")
  const [relationTypesInput, setRelationTypesInput] = useState("")
  const labels = useMemo(() => (labelsInput || "").split(/[，,;；]/).map(s => s.trim()).filter(Boolean), [labelsInput])
  const relationTypes = useMemo(() => (relationTypesInput || "").split(/[，,;；]/).map(s => s.trim()).filter(Boolean), [relationTypesInput])
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
  const [text, setText] = useState("")
  const [spans, setSpans] = useState<Span[]>([])
  const [spansByIndex, setSpansByIndex] = useState<{[key:number]: Span[]}>({})
  const [nextId, setNextId] = useState(1)
  const [relations, setRelations] = useState<Relation[]>([])
  const [relationsByIndex, setRelationsByIndex] = useState<{[key:number]: Relation[]}>({})
  const [items, setItems] = useState<string[]>([])
  const [docIds, setDocIds] = useState<number[]>([])
  const [pid, setPid] = useState<number>(0)
  const [itemStatuses, setItemStatuses] = useState<{[key:number]: "pending"|"in_progress"|"completed"}>({})
  const [projectList, setProjectList] = useState<{id: number, name: string}[]>([])

  const fetchProjects = async () => {
      try {
          const res = await fetch('http://localhost:8000/api/projects')
          if(res.ok) {
              const data = await res.json()
              setProjectList(data)
          }
      } catch(e) {
          console.error("Failed to fetch projects", e)
      }
  }

  useEffect(() => {
    fetchProjects()

  }, [])
  const [currentIndex, setCurrentIndex] = useState<number>(-1)
  const [splitMode, setSplitMode] = useState<"as_is"|"paragraph"|"sentence">("sentence")
  const [uploadInfo, setUploadInfo] = useState<string>("")
  const containerRef = useRef<HTMLDivElement>(null)
  const getOffsets = useSelectionOffsets(containerRef, text)
  const [pending, setPending] = useState<{ start: number; end: number } | null>(null)
  const [labelPickerOpen, setLabelPickerOpen] = useState(false)
  const [dragFromId, setDragFromId] = useState<number | null>(null)
  const [pendingRel, setPendingRel] = useState<{ fromId: number; toId: number } | null>(null)
  const [relPickerOpen, setRelPickerOpen] = useState(false)
  const [hoverRelIdx, setHoverRelIdx] = useState<number | null>(null)
  const [boxes, setBoxes] = useState<Record<number, { x: number; y: number; w: number; h: number }>>({})
  const [overlayHeight, setOverlayHeight] = useState<number>(0)
  const [selectedSpanId, setSelectedSpanId] = useState<number | null>(null)
  const [relFromId, setRelFromId] = useState<number | null>(null)
  const charRefs = useRef<{[key:number]: HTMLSpanElement|null}>({})
  const [charRects, setCharRects] = useState<{x:number;y:number;w:number;h:number}[]>([])
  const [fontSize, setFontSize] = useState<number>(18)
  const [lineH, setLineH] = useState<number>(1.8)
  const [relStrokeWidth, setRelStrokeWidth] = useState<number>(2)
  const [relDashed, setRelDashed] = useState<boolean>(false)
  const [showSettings, setShowSettings] = useState(false)
  const [splitHelpOpen, setSplitHelpOpen] = useState(false)
  const splitHelpRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!splitHelpOpen) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node | null
      if (!t) return
      if (splitHelpRef.current && !splitHelpRef.current.contains(t)) setSplitHelpOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [splitHelpOpen])

  const IconOriginal = ({ active }: { active: boolean }) => (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true" className="icon">
      <path d="M6.5 2.5h6l3 3v12a1 1 0 0 1-1 1h-8a1 1 0 0 1-1-1v-14a1 1 0 0 1 1-1Z" stroke={active ? "currentColor" : "currentColor"} strokeWidth="1.5" opacity={active ? 1 : 0.8}/>
      <path d="M12.5 2.5v3a1 1 0 0 0 1 1h3" stroke="currentColor" strokeWidth="1.5" opacity={active ? 1 : 0.8}/>
      <path d="M7.5 9h6.5M7.5 12h5.2M7.5 15h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.65}/>
    </svg>
  )

  const IconParagraph = ({ active }: { active: boolean }) => (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true" className="icon">
      <path d="M4 5.5h12M4 8.8h8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.75}/>
      <path d="M4 12.7h12M4 16h8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.75}/>
      <path d="M14.6 8.8h1.4M14.6 16h1.4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.55}/>
    </svg>
  )

  const IconSentence = ({ active }: { active: boolean }) => (
    <svg width="16" height="16" viewBox="0 0 20 20" fill="none" aria-hidden="true" className="icon">
      <path d="M4 6h9.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.8}/>
      <path d="M4 10h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.8}/>
      <path d="M4 14h8.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity={active ? 1 : 0.8}/>
      <path d="M14.8 6.1a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0Z" fill="currentColor" opacity={active ? 1 : 0.6}/>
      <path d="M17 10.1a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0Z" fill="currentColor" opacity={active ? 1 : 0.6}/>
      <path d="M14.2 14.1a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0Z" fill="currentColor" opacity={active ? 1 : 0.6}/>
    </svg>
  )

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
    let maxY = 0
    for (const r of rects) maxY = Math.max(maxY, r.y + r.h)
    setOverlayHeight(Math.max(maxY, cb.height))
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

  const handleSaveAndNext = async () => {
    if (currentIndex < 0) return
    
    // Save to local state first
    saveCurrent()

    const record = {
      id: docIds[currentIndex] || -1,
      text: text,
      spans: spans,
      relations: relations,
      meta: {
        timestamp: new Date().toISOString(),
        project_name: projectName,
        project_id: pid
      }
    }

    try {
      const res = await fetch(`http://localhost:8000/api/projects/${pid}/record`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(record)
      })

      if (!res.ok) {
          const errText = await res.text()
          throw new Error(`Failed to save record (${res.status}): ${errText}`)
      }

      // Mark as completed
      setItemStatuses(prev => ({ ...prev, [currentIndex]: "completed" }))
      
      // Move next
      if (currentIndex < items.length - 1) {
        loadIndex(currentIndex + 1)
      } else {
        alert("已完成所有文档！")
      }
    } catch (e) {
      alert("保存记录失败: " + e)
    }
  }

  const handleSaveOnly = async () => {
    if (currentIndex < 0) return
    
    // Save to local state first
    saveCurrent()

    const record = {
      id: docIds[currentIndex] || -1,
      text: text,
      spans: spans,
      relations: relations,
      meta: {
        timestamp: new Date().toISOString(),
        project_name: projectName,
        project_id: pid
      }
    }

    try {
      const res = await fetch(`http://localhost:8000/api/projects/${pid}/record`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(record)
      })

      if (!res.ok) {
          const errText = await res.text()
          throw new Error(`Failed to save record (${res.status}): ${errText}`)
      }

      // Mark as completed
      setItemStatuses(prev => ({ ...prev, [currentIndex]: "completed" }))
      
      // Just alert, don't move
      // alert("已保存")
    } catch (e) {
      alert("保存记录失败: " + e)
    }
  }

  const handleSkip = () => {
      if (currentIndex < items.length - 1) {
          saveCurrent() 
          loadIndex(currentIndex + 1)
      } else {
          alert("已到列表末尾")
      }
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
    if (splitMode === "paragraph") return s.split(/\n+/).map(x => x.trim()).filter(Boolean)
    if (splitMode === "sentence") {
      const out: string[] = []
      const regex = /([。；！？!?;]|\.{3}|…{1,2})/
      const parts = s.split(regex)
      
      let cur = ""
      for (const part of parts) {
        if (regex.test(part)) {
          cur += part
          if (cur.trim()) out.push(cur.trim())
          cur = ""
        } else {
          cur += part
        }
      }
      const rest = cur.trim()
      if (rest) out.push(rest)
      return out
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
        setUploadInfo("文件过大: " + f.name)
        continue
      }
      try {
        const buf = await readFileBuffer(f)
        const txt = tryDecode(buf)
        const units = splitTextUI(txt)
        all.push(...units)
        count += units.length
      } catch (e) {
        setUploadInfo("导入失败: " + f.name)
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
      setUploadInfo("已导入 " + count + " 条")
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
  const filteredIndices = items.map((_, i) => i)

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
      if (e.key === 'Escape') { e.preventDefault(); setSelectedSpanId(null); setPending(null); setLabelPickerOpen(false); setRelPickerOpen(false); setRelFromId(null); setShowSettings(false); return }
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

  const applySyncData = (syncData: any) => {
    if (syncData.project) {
      setProjectName(syncData.project.name)
      const l = syncData.project.labels
      setLabelsInput(Array.isArray(l) ? l.join(",") : (l || ""))
      const r = syncData.project.relation_types
      setRelationTypesInput(Array.isArray(r) ? r.join(",") : (r || ""))
    }

    const newItems: string[] = []
    const newDocIds: number[] = []
    const newStatuses: any = {}
    const newSpans: any = {}
    const newRels: any = {}

    if (syncData.documents && Array.isArray(syncData.documents)) {
      syncData.documents.forEach((doc: any, i: number) => {
        newItems.push(doc.text)
        newDocIds.push(doc.id)
        newStatuses[i] = doc.status
        newSpans[i] = doc.spans || []
        newRels[i] = doc.relations || []
      })
    }

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
    } else {
      setCurrentIndex(-1)
      setText("")
      setSpans([])
      setRelations([])
    }
  }

  const loadProject = async (projectId: number) => {
    const syncRes = await fetch(`http://localhost:8000/api/projects/${projectId}/sync`)
    if (!syncRes.ok) throw new Error(await syncRes.text())
    const syncData = await syncRes.json()
    applySyncData(syncData)
  }

  const onClearAll = async () => {
    if (!pid || !projectName) return
    if (!confirm("确定要清空项目配置和待标注对象吗？此操作无法撤销。")) return
    try {
        const res = await fetch(`http://localhost:8000/api/projects/${pid}/clear`, { method: 'DELETE' })
        if (!res.ok) throw new Error("清空失败")
        await loadProject(pid)
        alert("已清空")
    } catch(e) {
        alert("清空失败: " + e)
    }
  }

  const onDeleteDoc = async (i: number, e: React.MouseEvent) => {
      e.stopPropagation()
      if (!confirm("删除此标注对象？")) return
      const docId = docIds[i]
      if (docId && docId !== -1) {
          try {
              const res = await fetch(`http://localhost:8000/api/documents/${docId}`, { method: 'DELETE' })
              if (!res.ok) throw new Error("删除失败")
          } catch(e) {
              alert("删除失败: " + e)
              return
          }
      }
      
      // Update local state without reload
      const newItems = [...items]
      newItems.splice(i, 1)
      setItems(newItems)
      
      const newDocIds = [...docIds]
      newDocIds.splice(i, 1)
      setDocIds(newDocIds)
      
      const newStatuses = { ...itemStatuses }
      // Shift keys down for statuses > i
      const updatedStatuses: Record<number, "pending" | "in_progress" | "completed"> = {}
      Object.keys(newStatuses).forEach(k => {
          const key = Number(k)
          if (key < i) updatedStatuses[key] = newStatuses[key]
          else if (key > i) updatedStatuses[key - 1] = newStatuses[key]
      })
      setItemStatuses(updatedStatuses)
      
      const newSpansByIndex = { ...spansByIndex }
      const updatedSpansByIndex: Record<number, Span[]> = {}
      Object.keys(newSpansByIndex).forEach(k => {
          const key = Number(k)
          if (key < i) updatedSpansByIndex[key] = newSpansByIndex[key]
          else if (key > i) updatedSpansByIndex[key - 1] = newSpansByIndex[key]
      })
      setSpansByIndex(updatedSpansByIndex)
      
      const newRelationsByIndex = { ...relationsByIndex }
      const updatedRelationsByIndex: Record<number, Relation[]> = {}
      Object.keys(newRelationsByIndex).forEach(k => {
          const key = Number(k)
          if (key < i) updatedRelationsByIndex[key] = newRelationsByIndex[key]
          else if (key > i) updatedRelationsByIndex[key - 1] = newRelationsByIndex[key]
      })
      setRelationsByIndex(updatedRelationsByIndex)
      
      // Reset current view
      if (newItems.length === 0) {
          setCurrentIndex(-1)
          setText("")
          setSpans([])
          setRelations([])
      } else {
          // If deleted last item, go to previous, else stay at current index (which is now the next item)
          const nextIdx = i >= newItems.length ? newItems.length - 1 : i
          setCurrentIndex(nextIdx)
          setText(newItems[nextIdx])
          setSpans(updatedSpansByIndex[nextIdx] || [])
          setRelations(updatedRelationsByIndex[nextIdx] || [])
      }
  }

  const onDeleteProject = async () => {
      if (!pid || !projectName) return
      if (!confirm(`确定要彻底删除项目 "${projectName}" 吗？此操作不可恢复！`)) return
      try {
          const res = await fetch(`http://localhost:8000/api/projects/${pid}`, { method: 'DELETE' })
          if (!res.ok) throw new Error("删除失败")
          alert("项目已删除")
          window.location.reload()
      } catch(e) {
          alert("删除失败: " + e)
      }
  }

  const onExport = () => {
    let url = `http://localhost:8000/api/projects/${pid}/export`
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
      if (!res.ok) throw new Error("保存失败")
      
      const data = await res.json()
      if (data.documents && Array.isArray(data.documents)) {
          // Update docIds with the returned IDs from backend
          const newDocIds = [...docIds]
          data.documents.forEach((d: any, i: number) => {
              if (i < newDocIds.length) newDocIds[i] = d.id
          })
          setDocIds(newDocIds)
      }
      
      alert("项目已保存！")
    } catch (e) {
      alert("保存失败: " + e)
    }
  }

  const handleSwitchProject = async () => {
    if(!projectName) return
    try {
        const res = await fetch('http://localhost:8000/api/projects', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: projectName,
                labels: labels,
                relation_types: relationTypes
            })
        })
        if(!res.ok) throw new Error(await res.text())
        const d = await res.json()
        setPid(d.id)
        alert(`切换到项目: ${d.name} (ID: ${d.id})`)
        await fetchProjects()
        await loadProject(d.id)
    } catch(e) {
        alert("创建/切换项目失败: " + e)
    }
  }

  const handleConfigUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const buf = await readFileBuffer(file)
      const text = tryDecode(buf)
      const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      
      const newLabels: string[] = []
      const newRels: string[] = []
      
      let mode = 'labels' // default
      for (const line of lines) {
        let cleanLine = line
        // Check for headers and switch mode
        if (/^(LABELS|标签)[:：]?/i.test(line)) {
          mode = 'labels'
          cleanLine = line.replace(/^(LABELS|标签)[:：]?/i, '').trim()
        } else if (/^(RELATIONS|关系)[:：]?/i.test(line)) {
          mode = 'relations'
          cleanLine = line.replace(/^(RELATIONS|关系)[:：]?/i, '').trim()
        } else {
            // Check if line looks like a header but wasn't caught (e.g. [Labels])
            if (line.match(/^\[.*\]$/)) continue
            if (line.startsWith('#')) continue
        }

        if (!cleanLine) continue

        if (mode === 'labels') newLabels.push(cleanLine)
        else newRels.push(cleanLine)
      }
      
      if (newLabels.length > 0) setLabelsInput(newLabels.join(','))
      if (newRels.length > 0) setRelationTypesInput(newRels.join(','))
      
      alert(`已导入 ${newLabels.length > 0 ? '标签' : ''} ${newRels.length > 0 ? '关系' : ''}`)
    } catch (err) {
      alert("配置导入失败: " + err)
    }
    e.target.value = ""
  }

  return (
    <div className="app-container">
      <header className="header">
          <div className="flex items-center gap-4">
              <h2>文本类标注平台</h2>
              <button className="btn btn-sm" onClick={() => setShowSettings(true)}>设置</button>
          </div>
          <button className="btn btn-primary" onClick={() => window.location.href = 'http://localhost:8000/minimind/'}>
            切换到图像类标注平台
          </button>
      </header>
      
      <div className="main-content">
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="flex justify-between items-center mb-2">
               <span className="sidebar-title" style={{marginBottom:0}}>项目配置</span>
               <div className="flex gap-2">
                 <button onClick={onSave} className="btn btn-primary btn-sm" disabled={!projectName || !pid}>保存</button>
                 <button onClick={onExport} className="btn btn-sm" disabled={!projectName || !pid}>导出</button>
               </div>
            </div>
            <div className="flex flex-col gap-2 mb-2">
              <select className="input" onChange={async (e) => {
                  const id = Number(e.target.value)
                  if (!id) return
                  const p = projectList.find(x => x.id === id)
                  if (!p) return
                  setPid(p.id)
                  setProjectName(p.name)
                  try {
                    await loadProject(p.id)
                  } catch (err) {
                    alert("加载项目失败: " + err)
                  }
              }} value={pid ? String(pid) : ""}>
                  <option value="">-- 选择已有项目 --</option>
                  {projectList.map(p => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
              </select>
              <div className="flex gap-2">
                <input className="input" value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="项目名称" />
                <button onClick={handleSwitchProject} className="btn btn-primary btn-sm">切换/创建</button>
              </div>
            </div>
            <div className="flex gap-2">
                <button type="button" onClick={onClearAll} className="btn btn-danger btn-sm" style={{flex: 1}} disabled={!projectName || !pid}>清空数据</button>
                <button type="button" onClick={onDeleteProject} className="btn btn-danger btn-sm" style={{flex: 1}} disabled={!projectName || !pid}>删除项目</button>
            </div>
            
            <div className="mt-4">
              <div className="text-sm text-gray mb-2">上传配置 (TXT):</div>
              <input type="file" accept=".txt" onChange={handleConfigUpload} className="input" style={{padding: '4px'}} />
            </div>
          </div>

          <div className="sidebar-content" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
            <div className="mb-4" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <div className="sidebar-title">文档列表</div>
              <div 
                onDragOver={e => e.preventDefault()} 
                onDrop={onDrop} 
                style={{ border: "2px dashed var(--border)", borderRadius: "var(--radius)", padding: "12px", textAlign: "center", marginBottom: "1rem" }}
              >
                <div className="text-sm text-gray mb-2">拖拽 .txt 文件到此处</div>
                <input type="file" multiple accept=".txt" onChange={onSelectFiles} style={{maxWidth: '100%'}} />
                <div className="segmentation-wrapper" ref={splitHelpRef}>
                  <div className="segmentation-header">
                    <span className="segmentation-title">切分方式</span>
                    <button 
                      type="button"
                      className="help-icon-btn"
                      onClick={() => setSplitHelpOpen(true)}
                      title="查看详细说明"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
                        <line x1="12" y1="17" x2="12.01" y2="17"></line>
                      </svg>
                      <span>说明</span>
                    </button>
                  </div>
                  <div className="segmentation-tabs">
                    <button
                      type="button"
                      onClick={() => setSplitMode('as_is')}
                      className={`tab-item ${splitMode === 'as_is' ? 'active' : ''}`}
                    >
                      <IconOriginal active={splitMode === 'as_is'} />
                      <span>原文</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setSplitMode('paragraph')}
                      className={`tab-item ${splitMode === 'paragraph' ? 'active' : ''}`}
                    >
                      <IconParagraph active={splitMode === 'paragraph'} />
                      <span>段落</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setSplitMode('sentence')}
                      className={`tab-item ${splitMode === 'sentence' ? 'active' : ''}`}
                    >
                      <IconSentence active={splitMode === 'sentence'} />
                      <span>句子</span>
                    </button>
                  </div>
                </div>
                <div className="text-sm text-gray mt-1">{uploadInfo}</div>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, overflowY: 'auto', minHeight: 0 }}>
                {filteredIndices.length === 0 ? (
                   <div style={{ 
                       border: "1px dashed var(--border)", 
                       borderRadius: "var(--radius)", 
                       padding: "1rem", 
                       textAlign: "left", 
                       color: "gray",
                       fontSize: "0.85rem",
                       background: "rgba(0,0,0,0.02)",
                       flex: 1,
                       display: 'flex',
                       alignItems: 'flex-start',
                       justifyContent: 'flex-start',
                       overflowY: 'auto',
                       whiteSpace: 'pre-wrap'
                   }}>
                       暂无待标注对象，请导入数据
                   </div>
                ) : (
                  filteredIndices.map((i, idx) => (
                  <div 
                    key={i} 
                    onClick={() => { saveCurrent(); loadIndex(i) }} 
                    className={`list-item ${currentIndex === i ? 'active' : ''}`}
                  >
                    <div className="flex items-center gap-2 overflow-hidden">
                        <span className="count-badge">{idx + 1}</span>
                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{items[i]}</div>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className={`status-badge ${itemStatuses[i] || 'pending'}`} title={itemStatuses[i]}></div>
                    </div>
                  </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </aside>

        <main className="workspace">
          <div className="flex items-center justify-between">
             <div className="flex items-center gap-4">
                <div className="flex gap-2">
                  <button onClick={prevItem} className="btn">上一篇</button>
                  <button onClick={nextItem} className="btn">下一篇</button>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-sm font-medium">
                    {currentIndex>=0 ? `待标注对象 ${currentIndex+1} / ${items.length}` : "无待标注对象"}
                  </div>
                  {currentIndex >= 0 && items.length > 0 && (
                    <button 
                      onClick={(e) => onDeleteDoc(currentIndex, e)} 
                      className="btn btn-danger"
                    >
                      删除当前
                    </button>
                  )}
                </div>
             </div>
             <div className="flex gap-2">
                <button onClick={handleSkip} className="btn">跳过</button>
                <button onClick={handleSaveOnly} className="btn">保存 {currentIndex>=0 && itemStatuses[currentIndex]==='completed'?"✅":""}</button>
                <button onClick={handleSaveAndNext} className="btn btn-primary">保存并下一篇</button>
             </div>
          </div>

          {/* Label/Relation Shortcuts */}
          <div className="card mb-4" style={{padding: '1rem', marginBottom: '1rem'}}>
             <div className="flex flex-wrap gap-4">
                <div className="flex-1">
                   <h4 className="text-sm font-bold mb-2">实体标签 (快捷键 1-9)</h4>
                   <div className="flex flex-wrap gap-2">
                     {labels.map((l, i) => (
                       <button key={l} onClick={() => addSpan(l)} className="label-chip" style={{background: palette[l], border: '1px solid rgba(0,0,0,0.1)', cursor: 'pointer', display: 'flex', alignItems: 'center'}}>
                          {i < 9 && (
                            <span style={{
                               background: 'rgba(255,255,255,0.5)',
                               borderRadius: 3,
                               padding: '0px 4px',
                               marginRight: 6,
                               fontSize: '0.75rem',
                               fontWeight: 'bold',
                               fontFamily: 'monospace',
                               boxShadow: '0 1px 0 rgba(0,0,0,0.1)'
                            }}>
                              {i+1}
                            </span>
                          )}
                          {l}
                       </button>
                     ))}
                     {labels.length === 0 && <span className="text-gray text-xs">请导入配置</span>}
                   </div>
                </div>
                <div className="flex-1" style={{borderLeft: '1px solid #eee', paddingLeft: '1rem'}}>
                   <h4 className="text-sm font-bold mb-2">关系类型 (快捷键 Ctrl+1-9)</h4>
                   <div className="flex flex-wrap gap-2">
                     {relationTypes.map((t, i) => (
                       <button key={t} onClick={() => addRelation(t)} className="label-chip" style={{background: relPalette[t], color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center'}}>
                          {i < 9 && (
                            <span style={{
                               background: 'rgba(255,255,255,0.3)',
                               borderRadius: 3,
                               padding: '0px 4px',
                               marginRight: 6,
                               fontSize: '0.75rem',
                               fontWeight: 'bold',
                               fontFamily: 'monospace',
                               boxShadow: '0 1px 0 rgba(0,0,0,0.1)'
                            }}>
                              {i+1}
                            </span>
                          )}
                          {t}
                       </button>
                     ))}
                     {relationTypes.length === 0 && <span className="text-gray text-xs">请导入配置</span>}
                   </div>
                </div>
             </div>
          </div>



          <div className="card" style={{ padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 400, flex: 1 }}>
             <div 
               ref={containerRef} 
               tabIndex={0} 
               onMouseUp={onMouseUp} 
               onContextMenu={onContainerContextMenu} 
               className="annotation-area"
               style={{ 
                 fontSize: fontSize, 
                 lineHeight: lineH, 
                 padding: "3rem", 
                 minHeight: 300, 
                 flex: 1,
                 background: "#fff",
                 outline: 'none'
               }}
             >
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
              <svg style={{ position: "absolute", left: 0, top: 0, width: "100%", height: overlayHeight > 0 ? overlayHeight : "100%", pointerEvents: "none" }}>
                <defs>
                  <marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                    <path d="M0,0 L6,3 L0,6 Z" fill="#333" />
                  </marker>
                </defs>
                {relations.map((r, i) => {
                  const a = boxes[r.fromId]
                  const b = boxes[r.toId]
                  if (!a || !b) return null
                  
                  const y1 = a.y - 8
                  const y2 = b.y - 8
                  const x1 = a.x
                  const x2 = b.x
                  
                  const minY = Math.min(y1, y2)
                  const dy = Math.abs(y2 - y1)
                  
                  const arcHeight = 25 + Math.min(dy * 0.4, 80)
                  const cpY = Math.max(12, Math.min(minY - 18, minY - arcHeight))
                  
                  const mx = (x1 + x2) / 2
                  
                  const color = relPalette[r.type] || "#333"
                  const isHovered = hoverRelIdx === i
                  const labelY = Math.max(12, cpY - 4)
                  
                  return (
                    <g key={i} onMouseEnter={() => setHoverRelIdx(i)} onMouseLeave={() => setHoverRelIdx(null)} style={{ pointerEvents: "auto" }}>
                      <path 
                        d={`M ${x1} ${y1} C ${mx} ${cpY}, ${mx} ${cpY}, ${x2} ${y2}`} 
                        stroke={color} 
                        fill="none" 
                        strokeWidth={isHovered ? Math.max(relStrokeWidth, relStrokeWidth + 1) : relStrokeWidth} 
                        markerEnd="url(#arrow)" 
                        strokeDasharray={relDashed ? '6 4' : undefined} 
                        opacity={isHovered ? 1 : 0.7}
                      />
                      <text 
                        x={mx} 
                        y={labelY} 
                        fill={color} 
                        fontSize={12} 
                        textAnchor="middle"
                        fontWeight={isHovered ? "bold" : "normal"}
                        style={{ textShadow: '0 1px 2px rgba(255,255,255,0.8)' }}
                      >
                        {r.type}
                      </text>
                    </g>
                  )
                })}
              </svg>
             </div>
          </div>

          {/* Floating Pickers */}
          {labelPickerOpen && pending && (
            <div className="card" style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 100, padding: '1rem', display: "flex", gap: 8, flexWrap: "wrap", maxWidth: 400 }}>
              <div className="w-full text-sm font-bold mb-2">选择标签</div>
              {labels.map(l => (
                <button key={l} onClick={() => addSpan(l)} className="label-chip" style={{ background: palette[l], cursor: 'pointer', fontSize: '0.9rem', padding: '4px 12px' }}>{l}</button>
              ))}
              <button onClick={() => setLabelPickerOpen(false)} className="btn btn-sm" style={{marginLeft: 'auto'}}>取消</button>
            </div>
          )}
          {relPickerOpen && pendingRel && (
            <div className="card" style={{ position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', zIndex: 100, padding: '1rem', display: "flex", gap: 8, flexWrap: "wrap", maxWidth: 400 }}>
              <div className="w-full text-sm font-bold mb-2">选择关系</div>
              {relationTypes.map(t => (
                <button key={t} onClick={() => addRelation(t)} className="label-chip" style={{ background: relPalette[t], color: "#fff", cursor: 'pointer', fontSize: '0.9rem', padding: '4px 12px' }}>{t}</button>
              ))}
              <button onClick={() => setRelPickerOpen(false)} className="btn btn-sm" style={{marginLeft: 'auto'}}>取消</button>
            </div>
          )}


        </main>
      </div>
      
      {/* Settings Modal */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
                <div className="modal-header">
                    <h3 className="modal-title">主题与快捷键</h3>
                    <button onClick={() => setShowSettings(false)} className="btn btn-sm">×</button>
                </div>
                
                <div className="settings-grid">
                    <div className="settings-group">
                        <label className="flex justify-between items-center">
                            字体大小 (px)
                            <input type="number" className="input" style={{width: 80}} value={fontSize} onChange={e => setFontSize(parseInt(e.target.value||'18'))} />
                        </label>
                        <label className="flex justify-between items-center">
                            行高 (倍数)
                            <input type="number" className="input" style={{width: 80}} value={lineH} step={0.1} onChange={e => setLineH(parseFloat(e.target.value||'1.8'))} />
                        </label>
                        <label className="flex justify-between items-center">
                            关系线宽 (px)
                            <input type="number" className="input" style={{width: 80}} value={relStrokeWidth} onChange={e => setRelStrokeWidth(parseInt(e.target.value||'2'))} />
                        </label>
                        <label className="flex items-center gap-2">
                            <input type="checkbox" checked={relDashed} onChange={e => setRelDashed(e.target.checked)} /> 
                            虚线关系
                        </label>
                    </div>
                    
                    <div>
                        <div className="font-bold text-sm mb-2">快捷键说明</div>
                        <div className="shortcut-list">
                            <div className="shortcut-item"><span>选择实体</span> <span className="shortcut-key">1-9</span></div>
                            <div className="shortcut-item"><span>选择关系</span> <span className="shortcut-key">Ctrl+1-9</span></div>
                            <div className="shortcut-item"><span>确认 / 下一篇</span> <span className="shortcut-key">Space</span></div>
                            <div className="shortcut-item"><span>撤销</span> <span className="shortcut-key">Ctrl+Z</span></div>
                            <div className="shortcut-item"><span>删除选中</span> <span className="shortcut-key">Delete</span></div>
                            <div className="shortcut-item"><span>切换文档</span> <span className="shortcut-key">← / →</span></div>
                        </div>
                    </div>
                </div>
                
                <div className="flex justify-end mt-4">
                    <button onClick={() => setShowSettings(false)} className="btn btn-primary">关闭</button>
                </div>
            </div>
        </div>
      )}
      
      {/* Help Modal */}
      <HelpModal isOpen={splitHelpOpen} onClose={() => setSplitHelpOpen(false)} />
    </div>
  )
}
