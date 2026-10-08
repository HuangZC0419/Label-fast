import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import "./App.css"
import HelpModal from './HelpModal'
import { useAuth } from './contexts/AuthContext'

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

export default function AnnotatorApp() {
  const { user, token, logout } = useAuth()
  const navigate = useNavigate()

  // 为所有 API 请求添加认证头（JSON 请求时设置 Content-Type）
  const authHeaders = (jsonBody?: boolean) => {
    const h: Record<string, string> = {}
    if (token) h['Authorization'] = `Bearer ${token}`
    if (jsonBody !== false) h['Content-Type'] = 'application/json'
    return h
  }

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
          const res = await fetch('/api/projects', { headers: authHeaders(false) })
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
      const res = await fetch(`/api/projects/${pid}/record`, {
        method: 'POST',
        headers: authHeaders(),
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
      const res = await fetch(`/api/projects/${pid}/record`, {
        method: 'POST',
        headers: authHeaders(),
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
      } catch {
          // 编码尝试失败是预期的——继续尝试下一个编码
        }
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

  // 使用 ref 存储键盘事件处理所需的函数引用，避免 useEffect 依赖数组膨胀
  // 导致每次状态变化都重新绑定事件监听器（严重性能问题）
  // 注意：必须同时存储函数引用，因为 removeSpanById/prevItem/nextItem/addSpan/addRelation
  // 每次渲染都会重新创建（无 useCallback），它们的闭包捕获了当次渲染的状态。
  // useEffect([]) 中只能拿到首次渲染的闭包，必须通过 ref 访问最新版本。
  const keyStateRef = useRef({
    labelPickerOpen, pending, relPickerOpen, pendingRel,
    labels, relationTypes, selectedSpanId,
  })
  keyStateRef.current = {
    labelPickerOpen, pending, relPickerOpen, pendingRel,
    labels, relationTypes, selectedSpanId,
  }

  // 存储所有快捷键调用的函数引用，确保始终拿到最新闭包
  const removeSpanByIdRef = useRef(removeSpanById)
  removeSpanByIdRef.current = removeSpanById
  const prevItemRef = useRef(prevItem)
  prevItemRef.current = prevItem
  const nextItemRef = useRef(nextItem)
  nextItemRef.current = nextItem
  const addRelationRef = useRef(addRelation)
  addRelationRef.current = addRelation
  const addSpanRef = useRef(addSpan)
  addSpanRef.current = addSpan
  const undoRef = useRef(undo)
  undoRef.current = undo
  const handleSaveAndNextRef = useRef(handleSaveAndNext)
  handleSaveAndNextRef.current = handleSaveAndNext

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const editable = !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      if (editable) return
      const s = keyStateRef.current
      if (e.ctrlKey && e.key.toLowerCase() === 'z') { e.preventDefault(); undoRef.current(); return }
      if (e.key === 'Delete') { if (s.selectedSpanId !== null) { removeSpanByIdRef.current(s.selectedSpanId); setSelectedSpanId(null); setRelFromId(null); } return }
      if (e.key === 'Escape') { e.preventDefault(); setSelectedSpanId(null); setPending(null); setLabelPickerOpen(false); setRelPickerOpen(false); setRelFromId(null); setShowSettings(false); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); prevItemRef.current(); return }
      if (e.key === 'ArrowRight') { e.preventDefault(); nextItemRef.current(); return }
      const d = Number(e.key)
      if (!Number.isNaN(d) && d >= 1 && d <= 9) {
        const idx = d - 1
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault(); e.stopPropagation()
          if (s.relPickerOpen && s.pendingRel && s.relationTypes[idx]) addRelationRef.current(s.relationTypes[idx])
        } else {
          if (s.labelPickerOpen && s.pending && s.labels[idx]) { e.preventDefault(); addSpanRef.current(s.labels[idx]) }
        }
        return
      }
      if (e.key === ' ') {
        e.preventDefault()
        if (s.labelPickerOpen && s.pending && s.labels[0]) {
          addSpanRef.current(s.labels[0])
        } else if (!s.relPickerOpen) {
          // 空格键 = 保存并下一篇，与点击按钮行为一致
          handleSaveAndNextRef.current()
        }
        return
      }
    }
    window.addEventListener('keydown', onKey, { capture: true })
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    const syncRes = await fetch(`/api/projects/${projectId}/sync`, { headers: authHeaders(false) })
    if (!syncRes.ok) throw new Error(await syncRes.text())
    const syncData = await syncRes.json()
    applySyncData(syncData)
  }

  const onClearAll = async () => {
    if (!pid || !projectName) return
    if (!confirm("确定要清空项目配置和待标注对象吗？此操作无法撤销。")) return
    try {
        const res = await fetch(`/api/projects/${pid}/clear`, { method: 'DELETE', headers: authHeaders(false) })
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
              const res = await fetch(`/api/documents/${docId}`, { method: 'DELETE', headers: authHeaders(false) })
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
          const res = await fetch(`/api/projects/${pid}`, { method: 'DELETE', headers: authHeaders(false) })
          if (!res.ok) throw new Error("删除失败")
          alert("项目已删除")
          window.location.reload()
      } catch(e) {
          alert("删除失败: " + e)
      }
  }

  const onExportZip = async () => {
    try {
      const res = await fetch(`/api/projects/${pid}/export-zip`, {
        headers: authHeaders(false)
      })
      if (!res.ok) {
        const err = await res.text()
        throw new Error(`导出失败 (${res.status}): ${err}`)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const safeName = (projectName || 'export').replace(/[^a-zA-Z0-9一-鿿 _-]/g, '').trim() || 'export'
      a.href = url
      a.download = `${safeName}_${new Date().toISOString().slice(0,10)}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch(e: any) {
      alert('打包导出失败: ' + (e.message || e))
    }
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
      const res = await fetch(`/api/projects/${pid}/sync`, {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: authHeaders()
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
        const res = await fetch('/api/projects', {
            method: 'POST',
            headers: authHeaders(),
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

  // 处理退出登录
  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-container">
      <header className="header">
          <div className="flex items-center gap-3">
              {/* 品牌 Logo */}
              <div style={{
                width: 32, height: 32, borderRadius: 'var(--radius)',
                background: 'linear-gradient(135deg, #1E40AF, #3B82F6)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 2px 8px rgba(30,64,175,.2)'
              }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                </svg>
              </div>
              <h2>LabelFast 文本标注</h2>
              <button className="btn btn-sm" onClick={() => setShowSettings(true)}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
                </svg>
                设置
              </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div className="user-info">
              <span className="username">{user?.username || '未知用户'}</span>
              <button className="logout-btn" onClick={handleLogout}>退出</button>
            </div>
            <button className="btn" onClick={() => window.location.href = '/minimind/'} style={{ fontWeight: 500 }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/>
              </svg>
              图像标注
            </button>
          </div>
      </header>

      <div className="main-content">
        <aside className="sidebar">
          {/* ================================================================ */}
          {/*  模块 1 — 项目配置                                                   */}
          {/* ================================================================ */}
          <div className="sidebar-module">
            <div className="sidebar-module-title">
              项目配置
              <span className="sidebar-module-actions">
                <button onClick={onSave} className="btn btn-primary btn-sm" disabled={!pid}>保存</button>
                <button onClick={onExportZip} className="btn btn-accent btn-sm" disabled={!pid} title="一键打包 ZIP（含 JSON+JSONL+CSV）">打包导出</button>
              </span>
            </div>
            <div className="sidebar-module-body">
              <select className="input" onChange={async (e) => {
                  const id = Number(e.target.value)
                  if (!id) return
                  const p = projectList.find(x => x.id === id)
                  if (!p) return
                  setPid(p.id); setProjectName(p.name)
                  try { await loadProject(p.id) } catch (err) { alert("加载失败: " + err) }
              }} value={pid ? String(pid) : ""}>
                  <option value="">选择已有项目...</option>
                  {projectList.map(p => <option key={p.id} value={String(p.id)}>{p.name}</option>)}
              </select>

              <div className="sidebar-divider">或 新建项目</div>

              <input className="input" value={projectName} onChange={e => setProjectName(e.target.value)} placeholder="输入新项目名称" />
              <button onClick={handleSwitchProject} className="btn btn-primary btn-sm" disabled={!projectName.trim()} style={{width:'100%'}}>
                {pid ? '切换 / 创建项目' : '创建新项目'}
              </button>

              {pid ? (
                <div className="sidebar-status ok">当前项目: {projectName}</div>
              ) : (
                <div className="sidebar-status hint">请选择项目或输入名称创建</div>
              )}

              <div className="flex gap-1">
                <button onClick={onClearAll} className="btn btn-danger btn-sm" style={{flex:1}} disabled={!pid}>清空数据</button>
                <button onClick={onDeleteProject} className="btn btn-danger btn-sm" style={{flex:1}} disabled={!pid}>删除项目</button>
              </div>
            </div>
          </div>

          {/* ================================================================ */}
          {/*  模块 2 — 标签配置                                                   */}
          {/* ================================================================ */}
          <div className="sidebar-module">
            <div className="sidebar-module-title">标签配置</div>
            <div className="sidebar-module-body">
              <div className="sidebar-field">
                <label className="sidebar-field-label">实体标签</label>
                <input className="input" value={labelsInput} onChange={e => setLabelsInput(e.target.value)} placeholder="逗号分隔，如: 人名, 地名, 组织" />
              </div>
              <div className="sidebar-field">
                <label className="sidebar-field-label">关系类型</label>
                <input className="input" value={relationTypesInput} onChange={e => setRelationTypesInput(e.target.value)} placeholder="逗号分隔，如: 位于, 属于, 担任" />
              </div>
              <div className="sidebar-field">
                <label className="sidebar-field-label">从 TXT 文件导入</label>
                <input type="file" accept=".txt" onChange={handleConfigUpload} className="input input-file" />
              </div>
            </div>
          </div>

          {/* ================================================================ */}
          {/*  模块 3 — 待标注对象 (占据全部剩余空间)                                 */}
          {/* ================================================================ */}
          <div className="sidebar-module sidebar-module-grow">
            <div className="sidebar-module-title">
              待标注对象
              {items.length > 0 && <span className="sidebar-module-badge">{items.length}</span>}
            </div>
            <div className="sidebar-module-body sidebar-module-flex">
              {/* 上传 + 切分 — 单行紧凑布局 */}
              <div className="upload-bar" onDragOver={e => e.preventDefault()} onDrop={onDrop}>
                <span className="upload-bar-hint">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  拖拽 .txt 到此处
                </span>
                <div className="segmentation-tabs" ref={splitHelpRef} style={{flex:'none'}}>
                  <button type="button" onClick={() => setSplitMode('as_is')} className={`tab-item ${splitMode==='as_is'?'active':''}`}>原文</button>
                  <button type="button" onClick={() => setSplitMode('paragraph')} className={`tab-item ${splitMode==='paragraph'?'active':''}`}>段落</button>
                  <button type="button" onClick={() => setSplitMode('sentence')} className={`tab-item ${splitMode==='sentence'?'active':''}`}>句子</button>
                </div>
                <label className="upload-bar-btn">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
                  </svg>
                  选择文件
                  <input type="file" multiple accept=".txt" onChange={onSelectFiles} />
                </label>
              </div>
              {uploadInfo && <div className="upload-info-text">{uploadInfo}</div>}

              {/* 文档列表 — flex:1 占满剩余全部空间 */}
              <div className="doc-list">
                {filteredIndices.length === 0 ? (
                  <div className="doc-list-empty">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{opacity:.25,marginBottom:6}}>
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
                    </svg>
                    暂无待标注对象<br/>导入数据后在此显示
                  </div>
                ) : (
                  filteredIndices.map((i, idx) => {
                    const st = itemStatuses[i] || 'pending'
                    return (
                    <div key={i} onClick={() => { saveCurrent(); loadIndex(i) }} className={`list-item ${currentIndex===i?'active':''}`}>
                      <span className="count-badge">{idx+1}</span>
                      <span className="list-item-text">{items[i]}</span>
                      <span className={`status-dot ${st}`} title={st==='completed'?'已完成':st==='in_progress'?'进行中':'待处理'} />
                    </div>
                    )
                  })
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
                    <h3 className="modal-title">显示设置与快捷键</h3>
                    <button onClick={() => setShowSettings(false)} className="modal-close-btn">&times;</button>
                </div>

                <div className="settings-grid">
                    <div className="settings-group">
                        <div className="font-bold text-sm mb-1" style={{color: 'var(--text)'}}>显示设置</div>
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
                        <label className="flex items-center gap-2" style={{cursor: 'pointer'}}>
                            <input type="checkbox" checked={relDashed} onChange={e => setRelDashed(e.target.checked)} />
                            虚线关系连线
                        </label>
                    </div>

                    <div>
                        <div className="font-bold text-sm mb-2" style={{color: 'var(--text)'}}>快捷键说明</div>
                        <div className="shortcut-list">
                            <div className="shortcut-item"><span>选择实体标签</span> <span className="shortcut-key">1 - 9</span></div>
                            <div className="shortcut-item"><span>选择关系类型</span> <span className="shortcut-key">Ctrl + 1-9</span></div>
                            <div className="shortcut-item"><span>确认 / 下一篇</span> <span className="shortcut-key">Space</span></div>
                            <div className="shortcut-item"><span>撤销操作</span> <span className="shortcut-key">Ctrl + Z</span></div>
                            <div className="shortcut-item"><span>删除选中标注</span> <span className="shortcut-key">Delete</span></div>
                            <div className="shortcut-item"><span>切换文档</span> <span className="shortcut-key">&larr; / &rarr;</span></div>
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
