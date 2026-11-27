"""项目级自定义快捷键的纯逻辑层（无文件 IO、无锁）。

设计要点（对应 ``docs/项目拆分与自定义快捷键.md`` 第 2 节）：

1. ``project.json`` 只保存**显式覆盖项** ``shortcuts: {标签名: 组合键}``；
   默认规则仍是「前 9 个标签 → 数字 1–9」。
2. 存储前统一规范化：修饰键固定顺序 ``Ctrl+Alt+Shift``，组合键的字母按键
   显示为大写（``Ctrl+K``、``Alt+Shift+P``），单键字母保持小写（``q``），
   功能键大写 ``F2``；这样同一个按键只有一种持久化形式，
   前后端比较、去重与冲突判定都不必再做兼容分支。
3. 保留键（浏览器/编辑器已经占用的按键）在写入前拦截并返回中文 400，
   避免用户把 ``Delete`` 设成标签快捷键后删不掉实体。
4. 冲突判定基于**有效快捷键**（默认 + 覆盖项），而不是仅比较覆盖项：
   覆盖项写成 ``2`` 会与第二个标签的默认 ``2`` 撞车，必须一起判。

本模块只做纯计算，调用方（``storage``）负责加锁、落盘与回滚，因此这里
不 import ``storage``，也不会参与循环依赖。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from errors import BadRequestError, ConflictError

# 默认快捷键覆盖的标签数量：前 9 个标签对应数字 1–9。
DEFAULT_SHORTCUT_COUNT = 9

# 单条快捷键的长度上限：最长形态形如 ``Ctrl+Alt+Shift+F24``（18 字符）。
MAX_SHORTCUT_LENGTH = 32

# 修饰键固定顺序：持久化形式永远是 Ctrl → Alt → Shift → 主键。
_MODIFIER_ORDER: tuple[str, ...] = ("Ctrl", "Alt", "Shift")
_MODIFIER_ALIASES: dict[str, str] = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "ctl": "Ctrl",
    "alt": "Alt",
    "opt": "Alt",
    "option": "Alt",
    "shift": "Shift",
}
# 明确拒绝的修饰键（与契约的 Ctrl/Alt/Shift 三选不符），单独报错而不是
# 当成主键，避免 ``Cmd+K`` 被误解为「两个主键」的歧义提示。
_UNSUPPORTED_MODIFIERS = {"cmd", "command", "meta", "win", "super", "fn"}

# 浏览器/编辑器保留键（规范化后的形式）。
_RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "Escape",
        "Delete",
        "Backspace",
        "Enter",
        "Tab",
        "Space",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
    }
)

# 键盘事件里常见的别名 → 规范化名称。
_KEY_ALIASES: dict[str, str] = {
    "esc": "Escape",
    "escape": "Escape",
    "del": "Delete",
    "delete": "Delete",
    "backspace": "Backspace",
    "back": "Backspace",
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "space": "Space",
    "spacebar": "Space",
    "up": "ArrowUp",
    "arrowup": "ArrowUp",
    "↑": "ArrowUp",
    "down": "ArrowDown",
    "arrowdown": "ArrowDown",
    "↓": "ArrowDown",
    "left": "ArrowLeft",
    "arrowleft": "ArrowLeft",
    "←": "ArrowLeft",
    "right": "ArrowRight",
    "arrowright": "ArrowRight",
    "→": "ArrowRight",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pgup": "PageUp",
    "pagedown": "PageDown",
    "pgdn": "PageDown",
}

# 系统/应用已占用的组合键：Ctrl+Z 撤销、Ctrl+S 保存、Ctrl+1–9 关系快捷键。
_RESERVED_COMBINATIONS: frozenset[tuple[str, str]] = frozenset(
    {("Ctrl", "z"), ("Ctrl", "s")}
    | {("Ctrl", str(digit)) for digit in range(1, 10)}
)

_FUNCTION_KEY = re.compile(r"^f([1-9]|1\d|2[0-4])$")
_SEPARATOR = "+"


def _describe(raw: Any) -> str:
    return str(raw or "").strip()


def _normalize_base_key(token: str) -> str:
    """规范化主键：单字符（字母小写）/ 功能键 / 具名键。"""

    if len(token) == 1:
        char = token
        if char == " ":
            return "Space"
        if char == _SEPARATOR:
            raise BadRequestError("快捷键不能使用「+」作为按键，请改用 Ctrl+ 组合")
        if char.isascii() and char.isalpha():
            return char.lower()
        if char.isascii() and char.isprintable():
            # 数字与标点（如 1 / q / !）原样保留。
            return char
        raise BadRequestError(f"不支持的按键：{token}（仅支持字母、数字、标点与功能键）")

    lowered = token.lower()
    alias = _KEY_ALIASES.get(lowered)
    if alias is not None:
        return alias
    if _FUNCTION_KEY.match(lowered):
        return "F" + lowered[1:]
    raise BadRequestError(f"不支持的按键：{token}")


def normalize_shortcut(raw: Any) -> str:
    """把用户按键描述规范化成唯一持久化形式。

    - 单键：``q`` / ``1`` / ``!`` / ``F2``（字母统一小写）；
    - 组合键：修饰键按 ``Ctrl+Alt+Shift`` 排序，如 ``Ctrl+K``、``Alt+Shift+P``；
    - 保留键（``Delete``、``Escape``、``Ctrl+Z``、``Ctrl+1``…）抛
      :class:`BadRequestError`（400，中文 detail）。

    非法输入一律 400：调用方（``storage``）负责加锁，本函数只做判定。
    """

    text = _describe(raw)
    if not text:
        raise BadRequestError("快捷键不能为空")
    if len(text) > MAX_SHORTCUT_LENGTH:
        raise BadRequestError(
            f"快捷键「{text}」过长，最多 {MAX_SHORTCUT_LENGTH} 个字符"
        )

    modifiers: list[str] = []
    base_token: str | None = None
    for part in (segment.strip() for segment in text.split(_SEPARATOR)):
        if not part:
            # 允许 "Ctrl + K" 这类带空格写法，空段直接忽略。
            continue
        lowered = part.lower()
        if lowered in _UNSUPPORTED_MODIFIERS:
            raise BadRequestError(
                f"不支持的修饰键：{part}（仅支持 Ctrl / Alt / Shift）"
            )
        modifier = _MODIFIER_ALIASES.get(lowered)
        if modifier is not None:
            if modifier not in modifiers:
                modifiers.append(modifier)
            continue
        if base_token is not None:
            raise BadRequestError(f"快捷键「{text}」只能包含一个主键")
        base_token = part

    if base_token is None:
        raise BadRequestError(f"快捷键「{text}」不能只包含修饰键")
    base_key = _normalize_base_key(base_token)

    if base_key in _RESERVED_KEYS:
        raise BadRequestError(
            f"「{base_key}」是保留按键，不能作为标签快捷键"
        )

    ordered = [item for item in _MODIFIER_ORDER if item in modifiers]
    # 组合键里的字母按习惯显示为大写（Ctrl+K / Alt+Shift+P），单键字母保持
    # 小写（q）；两者都是稳定的持久化形式，比较与去重只依赖规范化结果。
    display_key = (
        base_key.upper() if len(base_key) == 1 and base_key.isalpha() else base_key
    )
    if len(ordered) == 1 and (ordered[0], base_key) in _RESERVED_COMBINATIONS:
        raise BadRequestError(
            f"「{ordered[0]}{_SEPARATOR}{display_key}」是系统保留快捷键，"
            "请换一个组合"
        )
    return _SEPARATOR.join([*ordered, display_key if ordered else base_key])


def effective_shortcuts(
    labels: Sequence[str], overrides: Mapping[str, str] | None = None
) -> dict[str, str]:
    """计算有效快捷键：默认前 9 个标签 1–9，覆盖项优先。

    返回有序字典，键为标签名；不在字典内的覆盖项被忽略（不报错），
    这样历史脏数据不会让「读取项目」失败。
    """

    known = set(labels)
    result: dict[str, str] = {}
    for index, label in enumerate(labels[:DEFAULT_SHORTCUT_COUNT], start=1):
        result[str(label)] = str(index)
    for raw_label, raw_key in (overrides or {}).items():
        label = str(raw_label)
        if label in known:
            result[label] = str(raw_key)
    return result


def shortcut_conflicts(
    shortcuts: Mapping[str, str]
) -> list[tuple[str, list[str]]]:
    """返回被多个标签占用的组合键：``[(组合键, [标签...]), ...]``。"""

    by_key: dict[str, list[str]] = {}
    for label, key in shortcuts.items():
        by_key.setdefault(str(key), []).append(str(label))
    return [
        (key, labels)
        for key, labels in sorted(by_key.items())
        if len(labels) > 1
    ]


def conflict_detail(conflicts: Iterable[tuple[str, list[str]]]) -> str:
    """生成 409 中文提示，列出每个冲突组合键及其标签。"""

    parts = []
    for key, labels in conflicts:
        listed = "、".join(f"「{label}」" for label in labels)
        parts.append(f"快捷键「{key}」被标签{listed}同时占用")
    return "，".join(parts) + "。请为其中一个标签更换快捷键后重试。"


def merge_shortcuts(
    *,
    labels: Sequence[str],
    current: Mapping[str, str] | None = None,
    set_items: Mapping[str, str] | Iterable[tuple[str, str]] = (),
    unset_labels: Iterable[str] = (),
    removed_labels: Iterable[str] = (),
) -> dict[str, str]:
    """按契约顺序合并快捷键覆盖项并完成全部校验。

    顺序：``unset`` → 删除标签时清理 → ``set``（规范化 + 标签归属）→
    基于有效快捷键做冲突判定。任何一步失败都抛业务异常且不写盘，
    调用方因此可以保持「一次 PATCH 只落盘一次」。

    - ``set_items`` 的标签必须存在于 ``labels``（合并 ``labels_add`` 之后
      的字典），否则 :class:`BadRequestError`（400）；
    - 任两个标签的有效快捷键相同 → :class:`ConflictError`（409）；
    - 字典中已不存在的标签的残留覆盖项会被静默清理（历史脏数据自愈）。
    """

    known = {str(label) for label in labels}
    result: dict[str, str] = {
        str(label): str(key) for label, key in (current or {}).items()
    }
    for label in unset_labels:
        result.pop(str(label), None)
    for label in removed_labels:
        result.pop(str(label), None)

    items = (
        set_items.items() if isinstance(set_items, Mapping) else set_items
    )
    for raw_label, raw_key in items:
        label = str(raw_label).strip()
        if not label:
            raise BadRequestError("快捷键对应的标签名不能为空")
        if label not in known:
            raise BadRequestError(f"标签「{label}」不存在，无法设置快捷键")
        result[label] = normalize_shortcut(raw_key)

    filtered = {
        label: key for label, key in result.items() if label in known
    }

    conflicts = shortcut_conflicts(effective_shortcuts(list(labels), filtered))
    if conflicts:
        raise ConflictError(conflict_detail(conflicts))
    return filtered


def normalize_overrides(raw: Any) -> dict[str, str]:
    """读取已持久化的覆盖项并收敛为 ``dict[str, str]``（不校验格式）。

    历史 ``project.json`` 可能没有该字段、写成列表或含非字符串值；
    读取路径只做「尽量可用」的收敛，写入路径才做严格校验。
    """

    if not isinstance(raw, Mapping):
        return {}
    return {
        str(label): str(key)
        for label, key in raw.items()
        if isinstance(label, str) and label.strip() and isinstance(key, str)
    }
