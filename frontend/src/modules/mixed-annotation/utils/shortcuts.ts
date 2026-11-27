/**
 * 项目级自定义快捷键的纯函数工具集。
 *
 * 设计约束（与后端契约一致，见 `mixed_annotation/docs/项目拆分与自定义快捷键.md`）：
 * - 存储的是**规范化后的组合键字符串**，例如 `q`、`1`、`F2`、`Ctrl+k`、`Alt+Shift+p`；
 * - 修饰键顺序固定 `Ctrl` → `Alt` → `Shift`，字母统一小写（展示时再转成可读形式）；
 * - 默认规则：前 9 个标签对应数字 `1`–`9`，用户覆盖项优先；
 * - 保留键不允许绑定（关系快捷键 `Ctrl+1–9`、撤销 `Ctrl+Z`、保存 `Ctrl+S` 等）。
 *
 * 这里刻意保持无副作用、无 Vue 依赖：字典卡片、标注画布、设置弹窗
 * 和快捷键处理逻辑都复用同一套规则，避免「弹窗显示的组合键」与
 * 「实际生效的组合键」出现分歧。
 */

/** 默认快捷键覆盖的标签数量：前 N 个标签使用数字快捷键。 */
export const DEFAULT_SHORTCUT_COUNT = 9

/** 修饰键的规范化顺序（与后端一致）。 */
const MODIFIER_ORDER = ['Ctrl', 'Alt', 'Shift'] as const

/** 纯修饰键/锁定键：按下它们不构成快捷键，继续等待真正的按键。 */
const MODIFIER_KEY_NAMES = new Set([
  'Control',
  'Alt',
  'Shift',
  'Meta',
  'AltGraph',
  'OS',
  'Super',
  'Hyper',
  'CapsLock',
  'NumLock',
  'ScrollLock',
  'Fn',
  'Dead',
  'Unidentified',
  'Process',
])

/**
 * 基础保留键：任何修饰组合都不允许占用。
 * 除 F3 外与后端 `_RESERVED_KEYS` 一致；F3 是前端新增的固定入口
 * （图片／表格标注），后端仍允许历史数据里存在，只在前端忽略。
 */
const RESERVED_KEYS = new Set([
  'escape',
  'delete',
  'backspace',
  'enter',
  'tab',
  'space',
  'arrowup',
  'arrowdown',
  'arrowleft',
  'arrowright',
  'home',
  'end',
  'pageup',
  'pagedown',
  /*
   * F3 固定给右侧预览面板的「图片／表格标注」：
   * 它是截图类标注的主入口，需要不受项目级标签快捷键影响；
   * 标签快捷键不允许再占用 F3。
   * 不用 F1：F1 会被浏览器帮助页抢占，页面层 preventDefault 拦不住。
   */
  'f3',
])

/** 仅 `Ctrl` 修饰时额外保留的主键：撤销 / 保存。 */
const RESERVED_CTRL_KEYS = new Set(['z', 's'])

/**
 * 后端支持的具名键（含别名）：与 `shortcut_service._KEY_ALIASES` 对齐。
 * 不在其中的具名键（如 `Insert`、`ContextMenu`、多媒体键）会被后端 400。
 */
const NAMED_KEY_TOKENS = new Set([
  'escape',
  'esc',
  'delete',
  'del',
  'backspace',
  'back',
  'enter',
  'return',
  'tab',
  'space',
  'spacebar',
  'up',
  'arrowup',
  'down',
  'arrowdown',
  'left',
  'arrowleft',
  'right',
  'arrowright',
  'home',
  'end',
  'pageup',
  'pgup',
  'pagedown',
  'pgdn',
])

/** 后端支持的功能键：`F1`–`F24`。 */
const SUPPORTED_FUNCTION_KEY = /^F([1-9]|1\d|2[0-4])$/i

/**
 * 具名键别名 → 规范名（与后端 `_KEY_ALIASES` 对齐）。
 * `KeyboardEvent.key` 多数情况下已经是规范名，这里兜住手输与传统浏览器的别名。
 */
const KEY_ALIASES: Record<string, string> = {
  esc: 'Escape',
  escape: 'Escape',
  del: 'Delete',
  delete: 'Delete',
  backspace: 'Backspace',
  back: 'Backspace',
  enter: 'Enter',
  return: 'Enter',
  tab: 'Tab',
  space: 'Space',
  spacebar: 'Space',
  up: 'ArrowUp',
  arrowup: 'ArrowUp',
  down: 'ArrowDown',
  arrowdown: 'ArrowDown',
  left: 'ArrowLeft',
  arrowleft: 'ArrowLeft',
  right: 'ArrowRight',
  arrowright: 'ArrowRight',
  home: 'Home',
  end: 'End',
  pageup: 'PageUp',
  pgup: 'PageUp',
  pagedown: 'PageDown',
  pgdn: 'PageDown',
}

/** 保留键的说明结构（用于就地报错/冲突展示）。 */
export interface ShortcutConflict {
  combo: string
  labels: string[]
}

/**
 * 规范化组合键：与后端持久化形式完全一致。
 *
 * - 修饰键顺序固定 `Ctrl` → `Alt` → `Shift`；
 * - 组合键里的单个字母显示为大写（`Ctrl+K`），单键字母保持小写（`q`）；
 * - 功能键大写（`F2`），其他具名键保留原样（`Escape`、`ArrowUp`）；
 * - `+` 作为主键时映射为内部标记 `Plus`（后端不接受 `+`，录制时会被拒绝）。
 *
 * 空串表示「无效/未设置」，调用方应忽略。
 */
export function normalizeShortcut(raw: string | null | undefined): string {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (!value) return ''
  // 单独的主键 `+` 会被 split 拆成空片段，这里显式映射成可比较的名字。
  if (value === '+') return 'Plus'

  const parts = value
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
  if (parts.length === 0) return ''

  const modifiers = new Set<string>()
  let key = ''

  for (const part of parts) {
    const lower = part.toLowerCase()
    if (lower === 'ctrl' || lower === 'control' || lower === 'meta' || lower === 'cmd') {
      modifiers.add('Ctrl')
    } else if (lower === 'alt' || lower === 'option') {
      modifiers.add('Alt')
    } else if (lower === 'shift') {
      modifiers.add('Shift')
    } else {
      // 多个非修饰键时以最后一个为主键（例如用户手输的脏数据）。
      key = part
    }
  }

  if (!key) return ''
  const ordered = MODIFIER_ORDER.filter((modifier) => modifiers.has(modifier))
  return [...ordered, normalizeMainKey(key, ordered.length > 0)].join('+')
}

/**
 * 主键规范化：字母小写、功能键大写、`+` 映射为 `Plus`、具名键收敛为规范名；
 * 带修饰键时单字母转大写，与后端 `Ctrl+K` / `Alt+Shift+P` 的持久化形式一致。
 */
function normalizeMainKey(key: string, hasModifier: boolean): string {
  if (key === '+') return 'Plus'
  if (key.length === 1) {
    const lower = key.toLowerCase()
    return hasModifier && /[a-z]/.test(lower) ? lower.toUpperCase() : lower
  }
  const alias = KEY_ALIASES[key.toLowerCase()]
  if (alias) return alias
  if (/^f\d{1,2}$/i.test(key)) return key.toUpperCase()
  return key
}

/**
 * 计算某个标签集合的**有效快捷键**。
 *
 * @param labels 标签顺序（决定默认 `1`–`9` 的分配）
 * @param overrides 项目里保存的覆盖项（只含用户显式设置过的标签）
 */
export function effectiveShortcuts(
  labels: readonly string[],
  overrides: Record<string, string> | null | undefined,
): Record<string, string> {
  const source = overrides ?? {}
  const result: Record<string, string> = {}
  const list = Array.isArray(labels) ? labels : []

  for (let index = 0; index < list.length; index += 1) {
    const label = list[index]
    if (typeof label !== 'string' || !label) continue

    const override = source[label]
    const normalizedOverride =
      typeof override === 'string' ? normalizeShortcut(override) : ''
    /*
     * 历史项目里可能有标签占用了保留键（例如 F3 曾被绑给某个标签）。
     * 这些键在画布上不会生效，继续显示徽标只会误导，因此按「未设置」处理；
     * 项目数据不在这里改写，用户下次录制快捷键时自然覆盖。
     */
    if (normalizedOverride && !isReservedShortcut(normalizedOverride)) {
      result[label] = normalizedOverride
      continue
    }
    if (index < DEFAULT_SHORTCUT_COUNT) result[label] = String(index + 1)
  }

  return result
}

/**
 * 数字主键统一按**物理按键**识别（Digit1–9 / Numpad1–9）。
 *
 * 这样能覆盖不同键盘/输入法下的差异：
 * - 非 US 布局（如 AZERTY）需要 Shift 才能打出数字，`event.key` 不是 "1"；
 * - 小键盘关闭 NumLock 时 `event.key` 会变成 End / ArrowDown；
 * - 部分中文输入法把 `event.key` 报成 "Process"。
 * `event.code` 在这些情况下仍然稳定。
 */
export function digitFromKeyboardEvent(event: KeyboardEvent): string {
  const code = typeof event.code === 'string' ? event.code : ''
  const matched = /^(?:Digit|Numpad)([1-9])$/.exec(code)
  if (matched) return matched[1]
  const key = typeof event.key === 'string' ? event.key : ''
  return /^[1-9]$/.test(key) ? key : ''
}

/**
 * 从键盘事件推导规范化组合键。
 *
 * - 数字主键按物理位置识别，不依赖键盘布局/输入法（见 `digitFromKeyboardEvent`）；
 * - 纯修饰键（Ctrl/Shift/…）返回空串，调用方据此继续等待下一次按键；
 * - 单个字母在无修饰键时保持小写（`q`），带修饰键时大写（`Ctrl+K`），
 *   与后端持久化形式一致；
 * - 符号键（如 `!`、`@`）本身依赖 Shift 输入，因此不再把 Shift 记录为修饰键，
 *   否则用户「看到的是 !，录到的却是 Shift+!」，无法再次触发；
 * - `+` 作为主键时返回内部标记 `Plus`：后端明确不支持，由调用方就地提示；
 * - `Meta`（macOS 的 ⌘ / Windows 键）统一折算为 `Ctrl`，与后端修饰键集合对齐。
 */
export function comboFromKeyboardEvent(event: KeyboardEvent): string {
  /*
   * 数字键：不同键盘布局下「1」可能是 Shift+&，小键盘关 NumLock 时是 End；
   * 统一用物理键位，且不把 Shift 计入数字组合，避免同一颗键录到不同结果。
   */
  const digit = digitFromKeyboardEvent(event)
  if (digit) {
    const digitModifiers: string[] = []
    if (event.ctrlKey || event.metaKey) digitModifiers.push('Ctrl')
    if (event.altKey) digitModifiers.push('Alt')
    return [...digitModifiers, digit].join('+')
  }

  // 空格的 `event.key` 是一个空格字符，先折算成具名键再参与规范化。
  const rawKey = typeof event.key === 'string'
    ? event.key === ' '
      ? 'Space'
      : event.key
    : ''
  if (!rawKey) return ''
  if (MODIFIER_KEY_NAMES.has(rawKey)) return ''

  const singleChar = rawKey.length === 1
  const isLetter = singleChar && /[a-z]/i.test(rawKey)

  const modifiers: string[] = []
  if (event.ctrlKey || event.metaKey) modifiers.push('Ctrl')
  if (event.altKey) modifiers.push('Alt')
  // 只有「字母 + Shift」与「具名键 + Shift」才把 Shift 视为修饰键。
  if (event.shiftKey && (!singleChar || isLetter)) modifiers.push('Shift')

  const main = normalizeMainKey(rawKey, modifiers.length > 0)
  if (!main) return ''
  return [...modifiers, main].join('+')
}

/** 拆出组合键的各个片段（修饰键在前、主键在后）。 */
export function splitShortcut(combo: string | null | undefined): string[] {
  const normalized = normalizeShortcut(combo)
  if (!normalized) return []
  return normalized.split('+')
}

/** 组合键的展示文本：`Ctrl+K` → `Ctrl + K`，单键保持小写。 */
export function formatShortcut(combo: string | null | undefined): string {
  return splitShortcut(combo)
    .map(displayPart)
    .join(' + ')
}

/**
 * 紧凑展示文本（用于 chip 徽标这类空间有限的位置）：
 * 片段之间不加空格，例如 `Ctrl+K`、`Alt+Shift+P`。
 */
export function formatShortcutCompact(combo: string | null | undefined): string {
  return splitShortcut(combo).map(displayPart).join('+')
}

/** 单片段展示：`+` 还原为符号，其余原样（规范化阶段已完成大小写）。 */
function displayPart(part: string): string {
  return part === 'Plus' ? '+' : part
}

/**
 * 是否为保留键（与后端校验保持一致）。
 * 命中时不允许绑定为标签快捷键，由调用方就地提示。
 */
export function isReservedShortcut(combo: string | null | undefined): boolean {
  const parts = splitShortcut(combo)
  if (parts.length === 0) return false

  const main = parts[parts.length - 1]
  const modifiers = parts.slice(0, -1)
  if (RESERVED_KEYS.has(main.toLowerCase())) return true

  // Ctrl+Z / Ctrl+S / Ctrl+1–9 属于关系与撤销/保存，禁止被标签占用；
  // 带其他修饰键（Alt、Shift）时不算保留，交给冲突检测处理。
  const ctrlOnly = modifiers.length === 1 && modifiers[0] === 'Ctrl'
  if (!ctrlOnly) return false

  const lower = main.toLowerCase()
  if (RESERVED_CTRL_KEYS.has(lower)) return true
  return /^[1-9]$/.test(lower)
}

/**
 * 是否为后端支持的按键形态（与 `shortcut_service._normalize_base_key` 对齐）。
 *
 * 支持：单字符 ASCII 可打印键（字母/数字/标点，`+` 除外）、`F1`–`F24`、
 * 具名键别名（`Escape`、`ArrowUp`…）。不支持的按键（`Insert`、多媒体键、
 * 非 ASCII 字符）在录制阶段就拒绝，避免保存时才收到后端 400。
 */
export function isSupportedShortcut(combo: string | null | undefined): boolean {
  const parts = splitShortcut(combo)
  if (parts.length === 0) return false

  const main = parts[parts.length - 1]
  if (main === 'Plus') return false
  if (main.length === 1) return /^[\x20-\x7E]$/.test(main)
  if (SUPPORTED_FUNCTION_KEY.test(main)) return true
  return NAMED_KEY_TOKENS.has(main.toLowerCase())
}

/**
 * 找出同一个组合键被多个标签占用的冲突。
 * 返回结果按组合键分组，`labels` 为占用该组合键的标签名。
 */
export function findShortcutConflict(
  shortcuts: Record<string, string> | null | undefined,
): ShortcutConflict[] {
  const groups = new Map<string, string[]>()

  for (const [label, raw] of Object.entries(shortcuts ?? {})) {
    const combo = normalizeShortcut(raw)
    if (!combo) continue
    const list = groups.get(combo) ?? []
    list.push(label)
    groups.set(combo, list)
  }

  const conflicts: ShortcutConflict[] = []
  for (const [combo, labels] of groups) {
    if (labels.length > 1) conflicts.push({ combo, labels })
  }
  return conflicts
}

/**
 * 把「标签 → 组合键」表反查成「组合键 → 标签」，
 * 供按键处理逻辑 O(1) 命中；重复组合键保留先出现的标签。
 */
export function shortcutIndex(shortcuts: Record<string, string> | null | undefined): Map<string, string> {
  const index = new Map<string, string>()
  for (const [label, raw] of Object.entries(shortcuts ?? {})) {
    const combo = normalizeShortcut(raw)
    if (!combo || index.has(combo)) continue
    index.set(combo, label)
  }
  return index
}
