"""文件系统数据访问层。

所有 JSON 写入都采用“同目录临时文件 + os.replace”的原子替换方式，
并通过进程内可重入锁串行化，避免后台轮询与用户请求互相覆盖。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from config import PROJECTS_DIR, PROJECTS_INDEX_PATH
from errors import BadRequestError, ConflictError, NotFoundError, ServiceError
from services.shortcut_service import merge_shortcuts, normalize_overrides
from utils import ensure_within, utc_now

logger = logging.getLogger(__name__)

_LOCK = threading.RLock()

# 进程内 file_id -> (project_id, 文件目录名) 缓存。文件目录以用户可读名称
# 命名后，按 id 定位目录不能再假设目录名等于 id；缓存让热路径（get_file、
# blocks、标注读写等）避免每次遍历 files/ 下所有目录。
# 目录名而非完整路径：项目改名只移动项目目录，文件名不受影响，缓存仍有效。
_FILE_DIR_CACHE: dict[str, tuple[str, str]] = {}

# 批量上传可能在同一秒内完成（utc_now 只有秒精度），因此用纳秒时间戳作为
# 内部排队序号，保证导入顺序稳定。进程内额外保证严格递增，避免时钟精度
# 导致同一纳秒出现相同序号。
_last_queue_seq = 0


def _next_queue_seq() -> int:
    """返回严格递增的排队序号（调用方需持有 ``_LOCK``）。"""

    global _last_queue_seq
    value = time.time_ns()
    if value <= _last_queue_seq:
        value = _last_queue_seq + 1
    _last_queue_seq = value
    return value


# ---------------------------------------------------------------------------
# 基础 JSON / 路径工具
# ---------------------------------------------------------------------------


def _assert_id(value: str, kind: str = "资源") -> str:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise NotFoundError(f"{kind}不存在") from exc
    # 统一使用规范格式，避免 Windows 大小写/短路径绕过。
    return str(parsed)


def _ensure_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ServiceError(500, f"数据文件损坏：{path.name}") from exc
    except OSError as exc:
        raise ServiceError(500, f"读取数据文件失败：{path.name}") from exc


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    """公开的原子 JSON 写入，供服务层（如 block_service）复用。"""

    _atomic_write_json(path, payload)


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """同目录临时文件 + os.replace，保证二进制资产不会出现半写状态。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _load_index() -> dict[str, Any]:
    _ensure_dirs()
    data = _read_json(PROJECTS_INDEX_PATH, {"projects": []})
    if isinstance(data, list):
        data = {"projects": data}
    if not isinstance(data, dict) or not isinstance(data.get("projects", []), list):
        raise ServiceError(500, "项目索引格式不正确")
    data.setdefault("projects", [])
    return data


# ---------------------------------------------------------------------------
# 项目目录命名
# ---------------------------------------------------------------------------

# Windows 文件名非法字符：<>:"/\|?* 以及 0x00-0x1F / DEL 控制字符。
_INVALID_DIR_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
# 目录名长度上限：远低于 Windows 单段 255 的限制，同时避免长中文名
# 在不同文件系统/同步盘上出现兼容问题。
_DIR_NAME_MAX_LEN = 80
_DIR_NAME_CONFLICT_LIMIT = 10000


def _sanitize_component_name(name: str, fallback: str) -> str:
    """文件夹/文件名通用清洗：项目目录与文件目录共用同一套规则。"""

    text = _INVALID_DIR_CHARS.sub("_", str(name or "")).strip().rstrip(" .")
    if not text:
        text = fallback
    if len(text) > _DIR_NAME_MAX_LEN:
        text = text[:_DIR_NAME_MAX_LEN].rstrip(" .") or text[:_DIR_NAME_MAX_LEN]
    # Windows 对设备名（含带扩展名的形式，如 con.txt）同样保留。
    if text.split(".", 1)[0].strip().upper() in _WINDOWS_RESERVED_NAMES:
        suffix = "_"
        text = text[: _DIR_NAME_MAX_LEN - len(suffix)].rstrip(" .") + suffix
    return text


def _sanitize_dir_name(name: str, project_id: str) -> str:
    """由项目名称生成合法、稳定的目录名。

    规则：非法字符替换为下划线；去除首尾空格与结尾的点；保留中文；
    超长截断到 80；空名称回退 ``项目-<id前8位>``；Windows 保留名追加下划线。
    """

    return _sanitize_component_name(
        name, f"项目-{str(project_id or '')[:8]}"
    )


def _sanitize_file_dir_name(name: str, file_id: str) -> str:
    """由文件显示名主干生成文件目录名，空名称回退 ``文件-<id前8位>``。"""

    return _sanitize_component_name(
        name, f"文件-{str(file_id or '')[:8]}"
    )


def _sanitize_figure_asset_stem(caption: str, figure_id: str) -> str:
    """图表资产文件名主干：优先 caption，空 caption 回退 figure id。"""

    fallback = str(figure_id or "").strip() or "图表"
    return _sanitize_component_name(caption, fallback)


def _file_label(meta: dict[str, Any]) -> str:
    """文件在错误提示里的展示名：优先用户可见文件名，退化到 id。"""

    name = str(meta.get("name") or "").strip()
    return name or str(meta.get("id") or "")


def _dedupe_dir_name(base: str, taken: set[str]) -> str:
    """在 ``taken``（已 casefold 的名称集合）中为 ``base`` 找到唯一名称。"""

    candidate = base
    counter = 2
    while candidate.casefold() in taken:
        suffix = f" ({counter})"
        stem = base[: max(1, _DIR_NAME_MAX_LEN - len(suffix))].rstrip(" .")
        candidate = f"{stem or base[:1]}{suffix}"
        counter += 1
        if counter > _DIR_NAME_CONFLICT_LIMIT:
            raise ServiceError(500, "项目目录名称冲突过多")
    return candidate


def _taken_dir_names(
    *,
    exclude_name: str | None = None,
    exclude_id: str | None = None,
) -> set[str]:
    """收集当前被占用的目录名（大小写不敏感）。

    同时覆盖磁盘上的实际目录与索引中的 ``dir_name``：即便某个项目目录
    暂时缺失，索引里登记过的名称也不会被新项目复用。
    """

    names: set[str] = set()
    for item in _load_index()["projects"]:
        if exclude_id and str(item.get("id") or "") == exclude_id:
            continue
        dir_name = item.get("dir_name")
        if dir_name:
            names.add(str(dir_name).casefold())
    if PROJECTS_DIR.is_dir():
        # 同名文件同样会阻塞目录创建/重命名，因此一起计入占用。
        for child in PROJECTS_DIR.iterdir():
            names.add(child.name.casefold())
    if exclude_name:
        names.discard(exclude_name.casefold())
    return names


def _rename_dir(source: Path, target: Path) -> None:
    """目录重命名入口；独立成函数便于测试模拟文件占用失败。"""

    source.rename(target)


def _project_dir_for_record(record: dict[str, Any]) -> Path:
    """按单条索引记录解析目录，供批量遍历时复用，避免重复读取索引。"""

    dir_name = record.get("dir_name")
    if dir_name:
        candidate = PROJECTS_DIR / str(dir_name)
        if candidate.is_dir():
            return candidate
    return PROJECTS_DIR / str(record.get("id") or "")


def _project_dir(project_id: str) -> Path:
    """解析项目目录：优先索引中的 ``dir_name``，否则回退旧 UUID 目录。"""

    pid = _assert_id(project_id, "项目")
    with _LOCK:
        for item in _load_index()["projects"]:
            if str(item.get("id") or "") == pid:
                return _project_dir_for_record(item)
    return PROJECTS_DIR / pid


def _public_project(record: dict[str, Any]) -> dict[str, Any]:
    """API 输出不暴露内部实现的 ``dir_name``，保持既有响应结构。

    ``shortcuts`` 在这里补齐默认值：旧项目的 ``project.json`` 没有该字段，
    对外一律表现为 ``{}``（前端因此不需要兼容 ``undefined``）。
    """

    result = {key: value for key, value in record.items() if key != "dir_name"}
    result["shortcuts"] = _project_shortcuts(record)
    return result


def _project_shortcuts(record: dict[str, Any]) -> dict[str, str]:
    """读取项目级快捷键覆盖项；缺失/脏数据一律收敛为空字典。"""

    return normalize_overrides(record.get("shortcuts"))


def _cache_file_dir(file_id: str, project_id: str, dir_name: str) -> None:
    with _LOCK:
        _FILE_DIR_CACHE[file_id] = (project_id, dir_name)


def _forget_file_dir(file_id: str) -> None:
    with _LOCK:
        _FILE_DIR_CACHE.pop(file_id, None)


def _forget_project_file_dirs(project_id: str) -> None:
    with _LOCK:
        for file_id, (pid, _) in list(_FILE_DIR_CACHE.items()):
            if pid == project_id:
                _FILE_DIR_CACHE.pop(file_id, None)


def _taken_file_dir_names(files_dir: Path) -> set[str]:
    """收集 files/ 下已占用的名称（大小写不敏感，文件与目录都计入）。"""

    if not files_dir.is_dir():
        return set()
    return {child.name.casefold() for child in files_dir.iterdir()}


def _resolve_file_dir(project_id: str, file_id: str) -> Path | None:
    """解析文件目录：缓存 → 旧 UUID 目录 → 扫描 meta.id；找不到返回 None。"""

    with _LOCK:
        cached = _FILE_DIR_CACHE.get(file_id)
        if cached is not None and cached[0] == project_id:
            candidate = _project_dir(project_id) / "files" / cached[1]
            if candidate.is_dir():
                return candidate
            _FILE_DIR_CACHE.pop(file_id, None)

        files_dir = _project_dir(project_id) / "files"
        # 兼容尚未迁移的 ``files/<uuid>/`` 布局。
        legacy = files_dir / file_id
        if (legacy / "meta.json").is_file():
            _cache_file_dir(file_id, project_id, file_id)
            return legacy

        if files_dir.is_dir():
            for child in sorted(files_dir.iterdir(), key=lambda path: path.name):
                if not child.is_dir():
                    continue
                meta_path = child / "meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = _read_json(meta_path, None)
                except (ServiceError, OSError):
                    logger.exception("跳过无法读取的文件元数据：%s", meta_path)
                    continue
                if isinstance(meta, dict) and str(meta.get("id") or "") == file_id:
                    _cache_file_dir(file_id, project_id, child.name)
                    return child
    return None


def _file_dir(project_id: str, file_id: str) -> Path:
    pid = _assert_id(project_id, "项目")
    fid = _assert_id(file_id, "文件")
    resolved = _resolve_file_dir(pid, fid)
    if resolved is not None:
        return resolved
    # 保持旧行为：文件不存在时返回 UUID 路径，由调用方在读写时判定。
    return _project_dir(pid) / "files" / fid


def _meta_path(project_id: str, file_id: str) -> Path:
    return _file_dir(project_id, file_id) / "meta.json"


def _annotation_path(project_id: str, file_id: str) -> Path:
    return _file_dir(project_id, file_id) / "annotations.json"


# ---------------------------------------------------------------------------
# 项目
# ---------------------------------------------------------------------------


def list_projects() -> list[dict[str, Any]]:
    with _LOCK:
        projects = [_public_project(item) for item in _load_index()["projects"]]
    projects.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return projects


def get_project(project_id: str) -> dict[str, Any]:
    with _LOCK:
        pid = _assert_id(project_id, "项目")
        path = _project_dir(pid) / "project.json"
        if path.is_file():
            project = _read_json(path, None)
            if not isinstance(project, dict):
                raise ServiceError(500, "项目数据格式不正确")
            return _public_project(project)
        # 索引仍在但 project.json 丢失时，尽量从索引恢复。
        for item in _load_index()["projects"]:
            if str(item.get("id") or "") == pid:
                record = _public_project(item)
                path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_json(path, record)
                return record
    raise NotFoundError("项目不存在")


def create_project(
    name: str,
    labels: list[str],
    relation_types: list[str],
    shortcuts: dict[str, str] | None = None,
) -> dict[str, Any]:
    """创建项目。

    ``shortcuts`` 为项目级快捷键覆盖项（只存显式设置过的标签），默认
    ``{}``：既保持旧调用方 ``create_project(name, labels, relation_types)``
    不变，也让拆分项目时可以整份继承源项目的快捷键（已在源项目内校验过）。
    """

    now = utc_now()
    project = {
        "id": str(uuid.uuid4()),
        "name": name,
        "labels": labels,
        "relation_types": relation_types,
        "shortcuts": normalize_overrides(shortcuts),
        "created_at": now,
        "updated_at": now,
    }
    with _LOCK:
        index = _load_index()
        base = _sanitize_dir_name(name, project["id"])
        dir_name = _dedupe_dir_name(base, _taken_dir_names())
        project_dir = PROJECTS_DIR / dir_name
        try:
            (project_dir / "files").mkdir(parents=True, exist_ok=False)
            _atomic_write_json(project_dir / "project.json", project)
            index["projects"].append({**project, "dir_name": dir_name})
            _atomic_write_json(PROJECTS_INDEX_PATH, index)
        except BaseException:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise
    return project


def update_project(project_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        project = get_project(project_id)
        pid = project["id"]
        old_dir = _project_dir(pid)
        old_project = dict(project)
        old_dir_name = old_dir.name
        target_dir = old_dir
        new_dir_name = old_dir_name

        new_name = changes.get("name")
        name_changed = (
            new_name is not None and str(new_name) != str(project.get("name") or "")
        )
        if name_changed:
            base = _sanitize_dir_name(str(new_name), pid)
            taken = _taken_dir_names(exclude_name=old_dir_name, exclude_id=pid)
            candidate = _dedupe_dir_name(base, taken)
            # 仅大小写差异的改名不移动目录，避免 Windows 大小写不敏感文件系统
            # 上的 rename 歧义；索引继续记录目录的实际名称。
            if candidate.casefold() != old_dir_name.casefold():
                target_dir = PROJECTS_DIR / candidate
                try:
                    _rename_dir(old_dir, target_dir)
                except OSError as exc:
                    raise ServiceError(
                        500, "项目目录重命名失败，请关闭占用该目录的程序后重试"
                    ) from exc
                new_dir_name = candidate

        for field in ("name", "labels", "relation_types", "shortcuts"):
            if field in changes and changes[field] is not None:
                project[field] = changes[field]
        project["updated_at"] = utc_now()

        index = _load_index()
        records: list[dict[str, Any]] = []
        found = False
        for item in index["projects"]:
            if str(item.get("id") or "") == pid:
                record = dict(item)
                record.update(project)
                record["dir_name"] = new_dir_name
                records.append(record)
                found = True
            else:
                records.append(item)
        if not found:
            records.append({**project, "dir_name": new_dir_name})
        index["projects"] = records

        try:
            _atomic_write_json(target_dir / "project.json", project)
            _atomic_write_json(PROJECTS_INDEX_PATH, index)
        except BaseException:
            # 先 rename 成功、后写索引失败时回滚目录与 project.json，
            # 保证索引和磁盘目录始终指向同一位置。
            if target_dir != old_dir:
                try:
                    _rename_dir(target_dir, old_dir)
                except OSError:
                    logger.exception(
                        "回滚项目目录重命名失败：%s -> %s", target_dir, old_dir
                    )
                try:
                    _atomic_write_json(old_dir / "project.json", old_project)
                except Exception:
                    logger.exception("回滚项目元数据失败：%s", old_dir)
            raise
    return project


# ---------------------------------------------------------------------------
# 项目字典（实体标签 / 关系类型）引用统计与增量合并
# ---------------------------------------------------------------------------
#
# 设计要点：
#
# 1. 字典是多人共享的元数据，PATCH 语义改为「增量」：旧前端的整份数组只当
#    追加项求并集，删除必须显式声明。这样即使三方各持旧快照也不会互相抹掉。
# 2. 只读统计与写操作拆开：``project_label_usage`` 是纯扫描，删除冲突判定
#    复用它，避免在每次追加标签时都去读一遍全部 annotations.json（大项目
#    上百份标注文件，无谓 IO 会拖慢保存）。
# 3. 扫描不修改任何数据文件，损坏/缺失的 annotations.json 直接跳过：字典
#    维护不能因为一份坏文件而整体失败。


def _clean_names(values: Iterable[Any]) -> list[str]:
    """去首尾空白、去重并保持顺序；非字符串按字符串处理，不抛异常。

    路由层的 ``normalize_string_list`` 已完成类型/长度校验并返回 422，这里
    只是数据层兜底：历史 ``project.json`` 可能含脏数据，合并过程不能因此 500。
    """

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value if isinstance(value, str) else str(value or "")).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dictionary_field(project: dict[str, Any], key: str) -> list[str]:
    """读取项目字典字段并清洗；非列表（历史脏数据）视为空字典。"""

    value = project.get(key)
    if not isinstance(value, (list, tuple)):
        return []
    return _clean_names(value)


def _merge_dictionary(
    base: Iterable[str],
    additions: Iterable[str],
    removals: Iterable[str],
) -> list[str]:
    """合并字典：保留现有顺序，先删除再按传入顺序把新项追加到末尾。"""

    removed = set(removals)
    result = [item for item in base if item not in removed]
    seen = set(result)
    for item in additions:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _sort_label_counts(usage: dict[str, int]) -> list[tuple[str, int]]:
    """按引用数降序、其次标签名排序，保证同一份数据每次输出顺序稳定。"""

    return sorted(usage.items(), key=lambda item: (-item[1], item[0]))


def _collect_label_counts(record: Any, counter: dict[str, int]) -> None:
    """累计单份 annotations.json 的实体标签与段落标签引用次数。"""

    if not isinstance(record, dict):
        return
    for key in ("spans", "paragraphs"):
        for item in _dict_list(record, key):
            label = item.get("label")
            if not isinstance(label, str):
                continue
            name = label.strip()
            if name:
                counter[name] = counter.get(name, 0) + 1


def project_label_usage(project_id: str) -> dict[str, int]:
    """统计项目内被标注引用的标签及次数：``{标签名: 引用条数}``。

    覆盖 ``spans[].label``（实体）与 ``paragraphs[].label``（段落）；缺失、
    不可读或格式损坏的 annotations.json 跳过，不影响其余文件统计。
    目录解析走 ``_project_dir``，因此项目改名后依然能定位到数据。
    """

    with _LOCK:
        project = get_project(project_id)  # 同时校验项目存在
        files_dir = _project_dir(project["id"]) / "files"
        counter: dict[str, int] = {}
        if not files_dir.is_dir():
            return counter
        for child in sorted(files_dir.iterdir(), key=lambda path: path.name):
            if not child.is_dir():
                continue
            annotation_path = child / "annotations.json"
            if not annotation_path.is_file():
                continue
            try:
                data = _read_json(annotation_path, None)
            except (ServiceError, OSError):
                # 损坏/被占用不影响字典维护，按契约跳过。
                logger.warning("标签统计跳过无法读取的标注：%s", annotation_path)
                continue
            _collect_label_counts(data, counter)
        return counter


def label_catalog(exclude_project_id: str | None = None) -> list[dict[str, Any]]:
    """跨项目汇总实体标签：字典里出现过的标签 + 实际标注引用次数。

    返回 ``[{label, project_count, usage_count}]``，按引用数、项目数降序排列。
    ``exclude_project_id`` 用于导入弹窗排除当前项目，避免把自己已有的标签列出来。
    只读取 project.json / annotations.json，不修改任何数据。
    """

    excluded = str(exclude_project_id or "").strip()
    counts: dict[str, dict[str, int]] = {}

    def entry(label: str) -> dict[str, int]:
        return counts.setdefault(label, {"project_count": 0, "usage_count": 0})

    for summary in list_projects():
        pid = str(summary.get("id") or "")
        if not pid or pid == excluded:
            continue

        try:
            project = get_project(pid)
        except (NotFoundError, ServiceError):
            # 项目目录损坏不应让整个标签目录接口失败。
            project = summary

        for label in _dictionary_field(project, "labels"):
            entry(label)["project_count"] += 1

        files_dir = _project_dir(pid) / "files"
        if not files_dir.is_dir():
            continue

        counter: dict[str, int] = {}
        for child in sorted(files_dir.iterdir(), key=lambda path: path.name):
            if not child.is_dir():
                continue
            annotation_path = child / "annotations.json"
            if not annotation_path.is_file():
                continue
            try:
                data = _read_json(annotation_path, None)
            except (ServiceError, OSError):
                logger.warning(
                    "标签目录跳过无法读取的标注：%s", annotation_path
                )
                continue
            _collect_label_counts(data, counter)

        for label, count in counter.items():
            entry(label)["usage_count"] += count

    rows = [
        {
            "label": label,
            "project_count": values["project_count"],
            "usage_count": values["usage_count"],
        }
        for label, values in counts.items()
    ]
    rows.sort(
        key=lambda row: (
            -int(row["usage_count"]),
            -int(row["project_count"]),
            str(row["label"]),
        )
    )
    return rows


def project_label_usage_report(project_id: str) -> dict[str, Any]:
    """``GET /labels/usage`` 的响应体：全部引用计数 + 字典缺失标签。

    ``missing`` 只含被引用但不在字典里的标签，排序与 ``restored`` 一致
    （引用数降序，其次标签名），便于前端按优先级展示与恢复。
    """

    with _LOCK:
        project = get_project(project_id)
        ordered = dict(_sort_label_counts(project_label_usage(project["id"])))
        known = set(_dictionary_field(project, "labels"))
        missing = [label for label in ordered if label not in known]
    return {"used": ordered, "missing": missing}


def restore_missing_labels(project_id: str) -> dict[str, Any]:
    """把「被引用但字典缺失」的标签补回字典（只增不减）。

    返回 ``{"project": 完整项目, "restored": [本次补回的标签]}``；没有缺失
    标签时不写盘，保持 ``updated_at`` 与文件顺序不变。
    """

    with _LOCK:
        project = get_project(project_id)
        pid = project["id"]
        missing = project_label_usage_report(pid)["missing"]
        if not missing:
            return {"project": project, "restored": []}
        merged = _merge_dictionary(
            _dictionary_field(project, "labels"), missing, ()
        )
        updated = update_project(pid, {"labels": merged})
        return {"project": updated, "restored": list(missing)}


def _label_removal_conflict_detail(entries: Iterable[tuple[str, int]]) -> str:
    """生成 409 中文提示，包含每个被引用标签的引用条数。"""

    ordered = sorted(entries, key=lambda item: (-item[1], item[0]))
    listed = "、".join(f"「{label}」{count} 处" for label, count in ordered)
    return (
        f"标签{listed} 仍被标注引用，删除后这些标注将失去标签。"
        "请先调整标注，或确认后强制删除。"
    )


def update_project_dictionary(
    project_id: str,
    *,
    name: str | None = None,
    labels_add: Iterable[str] = (),
    labels_remove: Iterable[str] = (),
    relation_types_add: Iterable[str] = (),
    relation_types_remove: Iterable[str] = (),
    shortcuts_set: dict[str, str] | None = None,
    shortcuts_unset: Iterable[str] = (),
    force: bool = False,
) -> dict[str, Any]:
    """增量合并项目字典，一次加锁内完成，只落盘一次。

    - ``labels_add`` / ``labels``（旧字段）一律按追加处理，绝不隐式删除；
    - 删除只认 ``labels_remove`` / ``relation_types_remove``；同一标签同时
      出现在增删两侧时按「新增」处理（新增是非破坏性操作）；
    - 删除仍被标注引用的实体标签时，``force=False`` 抛 ``ConflictError``(409)
      且不写入任何文件；``force=True`` 才真正删除；
    - 关系类型不做引用校验：``relations[].type`` 不参与字典冲突判定，
      避免历史脏数据把关系维护彻底卡死；
    - 快捷键覆盖项在**合并后的字典**上校验：``shortcuts_set`` 里的标签必须
      存在（否则 400），有效快捷键冲突返回 409；``labels_remove`` 会同步
      清掉被删标签的覆盖项。快捷键相关校验只在本次请求真的动了字典删除或
      快捷键时才执行，避免历史项目因为存量数据被无关 PATCH 卡住。
    """

    with _LOCK:
        project = get_project(project_id)
        pid = project["id"]
        labels = _dictionary_field(project, "labels")
        relation_types = _dictionary_field(project, "relation_types")
        shortcuts = _project_shortcuts(project)

        add_labels = _clean_names(labels_add)
        add_relations = _clean_names(relation_types_add)
        # 增删重叠时保留（按新增处理），只在「确实要删掉已有项」时才判定冲突。
        add_label_set = set(add_labels)
        add_relation_set = set(add_relations)
        remove_labels = {
            label for label in _clean_names(labels_remove) if label not in add_label_set
        }
        remove_relations = {
            label
            for label in _clean_names(relation_types_remove)
            if label not in add_relation_set
        }

        if remove_labels and not force:
            usage = project_label_usage(pid)
            conflict = [
                (label, usage[label])
                for label in remove_labels
                if usage.get(label, 0) > 0
            ]
            if conflict:
                raise ConflictError(_label_removal_conflict_detail(conflict))

        new_labels = _merge_dictionary(labels, add_labels, remove_labels)
        new_relations = _merge_dictionary(
            relation_types, add_relations, remove_relations
        )

        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if new_labels != labels:
            changes["labels"] = new_labels
        if new_relations != relation_types:
            changes["relation_types"] = new_relations

        # 快捷键：只有「字典有删除」或「显式提交快捷键」时才重新计算，
        # 保证没动字典的 PATCH 不会因为存量数据被额外校验/改写成 409。
        if shortcuts_set or shortcuts_unset or remove_labels:
            new_shortcuts = merge_shortcuts(
                labels=new_labels,
                current=shortcuts,
                set_items=shortcuts_set or {},
                unset_labels=shortcuts_unset,
                removed_labels=remove_labels,
            )
            if new_shortcuts != shortcuts:
                changes["shortcuts"] = new_shortcuts
        return update_project(pid, changes)


def delete_project(project_id: str) -> None:
    with _LOCK:
        project = get_project(project_id)
        # 必须在移除索引前解析目录：索引删除后 _project_dir 只能回退 UUID。
        project_dir = _project_dir(project["id"])
        index = _load_index()
        index["projects"] = [
            item for item in index["projects"] if item.get("id") != project["id"]
        ]
        _atomic_write_json(PROJECTS_INDEX_PATH, index)
        _forget_project_file_dirs(project["id"])
        shutil.rmtree(project_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 项目拆分（按文件序号区间）
# ---------------------------------------------------------------------------
#
# 契约：docs/项目拆分与自定义快捷键.md 第 1 节。
#
# 设计要点：
#
# 1. 序号基于 ``list_files()`` 的顺序（created_at 倒序、queue_seq 兜底）并
#    排除 ``uploading``，与 ``GET /projects/{id}`` 返回的 files 完全一致，
#    前端因此不需要再做一次排序映射。
# 2. 文件是「移动」而不是复制：整个文件目录 rename 到目标项目，文件 id 不变，
#    annotations.json / blocks.json / assets / markdown 全部原样带走。
# 3. 先校验再动手：全部分组校验通过后才创建项目、才开始移动文件，避免留下
#    半成品项目。
# 4. 强事务性：任何一步失败都回滚（已移动文件移回源项目、已创建项目删除），
#    并抛出中文 ``ServiceError``；回滚步骤自身的失败只记日志，不掩盖原始异常。

_SPLIT_MAX_GROUPS = 50
_SPLIT_NAME_MAX_LEN = 120
# 正在转换的文件由队列 worker 持续写入，移动会让 worker 写到旧路径上。
_SPLIT_BLOCKING_STATUSES = frozenset({"converting"})


def _plan_split_groups(
    groups: Iterable[Any], files: list[dict[str, Any]]
) -> list[tuple[str, list[dict[str, Any]]]]:
    """校验分组并展开为 ``[(新项目名, 该组文件元数据列表)]``（保持提交顺序）。

    全部校验失败都抛 ``BadRequestError``(400) 且不产生任何副作用。
    """

    items = list(groups or [])
    if not items:
        raise BadRequestError("拆分分组不能为空，请至少添加一组文件区间")
    if len(items) > _SPLIT_MAX_GROUPS:
        raise BadRequestError(
            f"拆分分组最多 {_SPLIT_MAX_GROUPS} 组，请分多次拆分"
        )
    total = len(files)
    if total == 0:
        raise BadRequestError("项目内没有可拆分的文件")

    seen_names: set[str] = set()
    ranges: list[tuple[int, int, str]] = []
    for order, raw in enumerate(items, start=1):
        group = raw if isinstance(raw, dict) else {}
        name = str(group.get("name") or "").strip()
        if not name:
            raise BadRequestError(f"第 {order} 组的新项目名称不能为空")
        if len(name) > _SPLIT_NAME_MAX_LEN:
            raise BadRequestError(
                f"第 {order} 组的新项目名称过长，最多 {_SPLIT_NAME_MAX_LEN} 个字符"
            )
        key = name.casefold()
        if key in seen_names:
            raise BadRequestError(
                f"第 {order} 组的新项目名称「{name}」与本次提交的其他组重复"
            )
        seen_names.add(key)

        start = group.get("start")
        end = group.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
        ):
            raise BadRequestError(
                f"第 {order} 组（「{name}」）的起始/结束序号必须是整数"
            )
        if start < 1 or end > total or start > end:
            raise BadRequestError(
                f"第 {order} 组（「{name}」）的文件序号必须在 1–{total} 之间，"
                "且起始序号不大于结束序号"
            )
        ranges.append((start, end, name))

    # 重叠判定在按起点排序后的副本上做：提交顺序可以任意。
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] <= previous[1]:
            raise BadRequestError(
                f"拆分区间重叠：「{previous[2]}」{previous[0]}–{previous[1]} 与 "
                f"「{current[2]}」{current[0]}–{current[1]} 存在交叉，请调整后重试"
            )

    return [(name, files[start - 1 : end]) for start, end, name in ranges]


def _rollback_split(
    created_projects: list[dict[str, Any]],
    moved_files: list[str],
    source_project_id: str,
) -> bool:
    """拆分失败回滚，返回「是否已完全回滚」。

    - 先把文件移回源项目（逆序），再删除新建项目；顺序不能颠倒：
      文件目录的定位依赖 ``meta.project_id`` 指向的项目目录仍然存在。
    - 只要有任何一个文件移不回去，就**保留新建项目不删除**：文件数据还在
      新建项目目录里，删项目等于删数据。此时返回 ``False``，由调用方在
      ``detail`` 里提示用户手动检查。
    - 单个回滚步骤失败只记日志，尽最大努力恢复其余部分。
    """

    failures = 0
    for file_id in reversed(moved_files):
        try:
            move_file_to_project(file_id, source_project_id)
        except Exception:
            failures += 1
            logger.exception("拆分回滚：文件移回源项目失败：%s", file_id)
    if failures:
        logger.error(
            "拆分回滚未能完成：%s 个文件仍留在新建项目中，已保留这些项目以免丢失数据",
            failures,
        )
        return False
    for project in reversed(created_projects):
        try:
            delete_project(str(project["id"]))
        except Exception:
            logger.exception("拆分回滚：删除新建项目失败：%s", project.get("id"))
    return True


def split_project(project_id: str, groups: Iterable[Any]) -> dict[str, Any]:
    """按文件序号区间把项目拆成多个新项目（文件移动，源项目保留）。

    返回 ``{"projects": [{project, file_count, file_ids}], "source_project"}``，
    与接口契约一致。全流程持有 ``_LOCK``：拆分期间不会有其它请求读到
    「文件已移走但索引还没更新」的中间状态。
    """

    with _LOCK:
        source = get_project(project_id)
        pid = source["id"]
        # 与 GET /projects/{id} 完全一致的文件顺序与可见性。
        files = [
            meta
            for meta in list_files(pid)
            if meta.get("status") != "uploading"
            and isinstance(meta.get("id"), str)
            and meta.get("id")
        ]
        plan = _plan_split_groups(groups, files)

        blocking = [
            _file_label(meta)
            for _, group_files in plan
            for meta in group_files
            if str(meta.get("status") or "") in _SPLIT_BLOCKING_STATUSES
        ]
        if blocking:
            listed = "、".join(f"「{name}」" for name in blocking)
            raise ConflictError(
                f"文件{listed}正在转换，移动会中断识别。"
                "请等待转换结束或取消转换后再拆分。"
            )

        # 新项目全量继承字典与快捷键；源项目本身不被修改。
        inherited_labels = list(_dictionary_field(source, "labels"))
        inherited_relations = list(_dictionary_field(source, "relation_types"))
        inherited_shortcuts = _project_shortcuts(source)

        created: list[dict[str, Any]] = []
        moved: list[str] = []
        results: list[dict[str, Any]] = []
        try:
            for name, _ in plan:
                created.append(
                    create_project(
                        name,
                        list(inherited_labels),
                        list(inherited_relations),
                        shortcuts=dict(inherited_shortcuts),
                    )
                )
            for project, (_, group_files) in zip(created, plan):
                file_ids = [str(meta["id"]) for meta in group_files]
                for file_id in file_ids:
                    move_file_to_project(file_id, str(project["id"]))
                    moved.append(file_id)
                results.append(
                    {
                        "project": project,
                        "file_count": len(file_ids),
                        "file_ids": file_ids,
                    }
                )
        except ServiceError as exc:
            if _rollback_split(created, moved, pid):
                raise
            raise ServiceError(
                500,
                f"{exc.detail}；部分文件未能回滚，已保留新建项目以免丢失数据，"
                "请手动检查后整理",
            ) from exc
        except Exception as exc:
            fully_rolled_back = _rollback_split(created, moved, pid)
            logger.exception("项目拆分失败：%s", pid)
            if fully_rolled_back:
                raise ServiceError(
                    500, "拆分项目失败，已回滚全部改动，请稍后重试"
                ) from exc
            raise ServiceError(
                500,
                "拆分项目失败，部分文件未能回滚，已保留新建项目以免丢失数据，"
                "请手动检查后整理",
            ) from exc

        return {"projects": results, "source_project": get_project(pid)}


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------


def create_file(
    project_id: str,
    display_name: str,
    extension: str,
    *,
    source_type: str,
    enable_table: bool,
    enable_formula: bool,
    dpi: int,
    initial_status: str = "uploaded",
) -> tuple[dict[str, Any], Path]:
    """创建文件元数据并返回 (meta, 源文件目标路径)。

    ``initial_status`` 默认 ``"uploaded"`` 以兼容既有调用方；上传流程传
    ``"uploading"``，避免队列在校验完成前认领半截文件。
    """

    with _LOCK:
        project = get_project(project_id)  # 同时校验项目存在
        pid = project["id"]
        now = utc_now()
        fid = str(uuid.uuid4())
        files_dir = _project_dir(pid) / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        # 目录名取显示文件名的 stem，并在同一项目内去重。
        stem = Path(str(display_name or "")).stem
        base = _sanitize_file_dir_name(stem, fid)
        dir_name = _dedupe_dir_name(base, _taken_file_dir_names(files_dir))
        file_dir = files_dir / dir_name
        (file_dir / "markdown" / "images").mkdir(parents=True, exist_ok=False)
        meta = {
            "id": fid,
            "project_id": pid,
            "name": display_name,
            # 内部字段：文件目录名，不进入 API 响应。
            "dir_name": dir_name,
            "source_type": source_type,
            "source_ext": extension.lstrip(".").lower(),
            "source_filename": f"source{extension.lower()}",
            "status": initial_status,
            "progress": 0,
            "stage": "正在上传" if initial_status == "uploading" else "等待转换",
            "message": "",
            "error": "",
            "task_id": "",
            "conversion_token": "",
            "page_count": 0,
            "enable_table": bool(enable_table),
            "enable_formula": bool(enable_formula),
            "dpi": int(dpi),
            # 内部字段：仅用于夜间队列排序，不对外暴露。
            "queue_seq": _next_queue_seq(),
            # 内部字段：OCR 服务不可用时的自动重试次数，成功后归零。
            "queue_retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        _atomic_write_json(file_dir / "meta.json", meta)
        _cache_file_dir(fid, pid, dir_name)
    return meta, file_dir / meta["source_filename"]


def _file_sort_key(meta: dict[str, Any]) -> tuple[str, int, str]:
    """文件列表排序键：创建时间倒序，同一秒内按 queue_seq 倒序。

    ``created_at`` 只有秒精度，批量上传时同一秒内会产生大量并列记录；
    加入纳秒级 ``queue_seq`` 与 id 兜底后，顺序稳定且新文件始终在前。
    """

    try:
        seq = int(meta.get("queue_seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return (
        str(meta.get("created_at") or ""),
        seq,
        str(meta.get("id") or ""),
    )


def list_files(project_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        project = get_project(project_id)
        pid = project["id"]
        files_dir = _project_dir(pid) / "files"
        if not files_dir.is_dir():
            return []
        records: list[dict[str, Any]] = []
        for child in files_dir.iterdir():
            if not child.is_dir():
                continue
            meta_path = child / "meta.json"
            if not meta_path.is_file():
                continue
            try:
                meta = _read_json(meta_path, None)
            except ServiceError:
                logger.exception("跳过损坏的文件元数据：%s", meta_path)
                continue
            if isinstance(meta, dict):
                records.append(meta)
                file_id = meta.get("id")
                if isinstance(file_id, str) and file_id:
                    # 目录扫描顺带刷新缓存，后续按 id 访问无需再扫描。
                    _cache_file_dir(file_id, pid, child.name)
    records.sort(key=_file_sort_key, reverse=True)
    return records


def _queue_sort_key(meta: dict[str, Any]) -> tuple[int, str, str]:
    """队列排序键：queue_seq 优先，其次 created_at，最后 id 兜底。"""

    try:
        seq = int(meta.get("queue_seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return (seq, str(meta.get("created_at") or ""), str(meta.get("id") or ""))


def list_queued_files() -> list[dict[str, Any]]:
    """跨项目返回所有 status == "uploaded" 的文件，按导入顺序排列。

    队列状态完全持久化在 meta.json 中，进程重启后重新扫描即可恢复，
    不依赖内存队列。
    """

    records: list[dict[str, Any]] = []
    for project in list_projects():
        pid = project.get("id")
        if not pid:
            continue
        for meta in list_files(pid):
            if meta.get("status") != "uploaded":
                continue
            # 损坏记录（缺 id 或 id 非字符串）无法安全认领，直接跳过。
            if not isinstance(meta.get("id"), str) or not meta.get("id"):
                logger.warning("跳过缺少有效 id 的排队记录：project=%s", pid)
                continue
            records.append(meta)
    records.sort(key=_queue_sort_key)
    return records


def next_queued_file(
    exclude_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """返回下一个待转换文件；``exclude_ids`` 用于跳过已被 worker 认领的文件。"""

    excluded = exclude_ids or set()
    for meta in list_queued_files():
        if str(meta.get("id") or "") not in excluded:
            return meta
    return None


def _find_meta_path(file_id: str) -> Path:
    """跨项目按 ``meta.id`` 定位文件元数据。

    优先命中进程内缓存与旧 UUID 路径；仅在未命中时扫描 ``files/*/meta.json``。
    """

    fid = _assert_id(file_id, "文件")
    with _LOCK:
        cached = _FILE_DIR_CACHE.get(fid)
        if cached is not None:
            pid, dir_name = cached
            candidate = _project_dir(pid) / "files" / dir_name / "meta.json"
            if candidate.is_file():
                return candidate
            _FILE_DIR_CACHE.pop(fid, None)

        for project in _load_index()["projects"]:
            pid = project.get("id")
            if not isinstance(pid, str) or not pid:
                continue
            project_dir = _project_dir_for_record(project)
            files_dir = project_dir / "files"
            # 旧布局：目录名即文件 id。
            legacy = files_dir / fid / "meta.json"
            if legacy.is_file():
                _cache_file_dir(fid, pid, fid)
                return legacy
            if not files_dir.is_dir():
                continue
            for child in sorted(files_dir.iterdir(), key=lambda path: path.name):
                if not child.is_dir():
                    continue
                meta_path = child / "meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = _read_json(meta_path, None)
                except (ServiceError, OSError):
                    logger.exception("跳过无法读取的文件元数据：%s", meta_path)
                    continue
                if isinstance(meta, dict) and str(meta.get("id") or "") == fid:
                    _cache_file_dir(fid, pid, child.name)
                    return meta_path
    raise NotFoundError("文件不存在")


def get_file(file_id: str) -> dict[str, Any]:
    with _LOCK:
        path = _find_meta_path(file_id)
        meta = _read_json(path, None)
        if not isinstance(meta, dict):
            raise ServiceError(500, "文件元数据格式不正确")
        return meta


def update_file(file_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """更新文件元数据；内部生成字段不可被覆盖。"""

    protected = {"id", "project_id", "source_filename", "created_at"}
    with _LOCK:
        path = _find_meta_path(file_id)
        meta = _read_json(path, None)
        if not isinstance(meta, dict):
            raise ServiceError(500, "文件元数据格式不正确")
        for key, value in changes.items():
            if key not in protected:
                meta[key] = value
        meta["updated_at"] = utc_now()
        _atomic_write_json(path, meta)
        return meta


def update_file_if_token(
    file_id: str, conversion_token: str, changes: dict[str, Any]
) -> dict[str, Any] | None:
    """仅当转换令牌仍匹配时更新，防止旧任务覆盖新一次转换。"""

    with _LOCK:
        path = _find_meta_path(file_id)
        meta = _read_json(path, None)
        if not isinstance(meta, dict):
            return None
        if meta.get("conversion_token") != conversion_token:
            return None
        protected = {
            "id",
            "project_id",
            "dir_name",
            "source_filename",
            "created_at",
        }
        for key, value in changes.items():
            if key not in protected:
                meta[key] = value
        meta["updated_at"] = utc_now()
        _atomic_write_json(path, meta)
        return meta


def update_file_if_token_and_status(
    file_id: str,
    conversion_token: str,
    allowed_statuses: set[str] | frozenset[str],
    changes: dict[str, Any],
) -> dict[str, Any] | None:
    """令牌与状态双校验后更新，避免旧任务把终态改回中间态。

    读取与写入在同一把进程锁内完成，因此不会出现“检查通过后被并发
    改写”的窗口；返回 ``None`` 表示校验失败、未写入任何字段。
    """

    with _LOCK:
        path = _find_meta_path(file_id)
        meta = _read_json(path, None)
        if not isinstance(meta, dict):
            return None
        if meta.get("conversion_token") != conversion_token:
            return None
        if meta.get("status") not in allowed_statuses:
            return None
        protected = {
            "id",
            "project_id",
            "dir_name",
            "source_filename",
            "created_at",
        }
        for key, value in changes.items():
            if key not in protected:
                meta[key] = value
        meta["updated_at"] = utc_now()
        _atomic_write_json(path, meta)
        return meta


def delete_file(file_id: str) -> None:
    with _LOCK:
        meta = get_file(file_id)
        fid = meta["id"]
        shutil.rmtree(file_dir(meta), ignore_errors=True)
        _forget_file_dir(fid)


def file_dir(file_meta: dict[str, Any]) -> Path:
    """文件目录：优先使用 meta 中的 ``dir_name``，减少目录扫描。"""

    pid = _assert_id(file_meta["project_id"], "项目")
    fid = _assert_id(file_meta["id"], "文件")
    dir_name = str(file_meta.get("dir_name") or "")
    if dir_name:
        candidate = _project_dir(pid) / "files" / dir_name
        if candidate.is_dir():
            _cache_file_dir(fid, pid, dir_name)
            return candidate
    return _file_dir(pid, fid)


def move_file_to_project(file_id: str, target_project_id: str) -> dict[str, Any]:
    """把文件（整个目录）移动到另一个项目，返回新的文件元数据。

    设计要点：

    - **移动不复制**：``files/<目录名>`` 整体 rename，``annotations.json``、
      ``blocks.json``、``assets/``、``markdown/`` 全部随目录迁移，文件 id
      保持不变，因此标注、图表资产与导出链接都不失效；
    - ``meta.json`` 的 ``project_id`` / ``dir_name`` / ``updated_at`` 同步更新，
      目标项目内目录名冲突时按 ``_dedupe_dir_name`` 追加 `` (2)`` 后缀；
    - 目录 rename 成功但元数据写入失败时回滚 rename，避免目录与 meta 不一致；
    - ``_FILE_DIR_CACHE`` 同步刷新，移动后按 id 访问无需再扫描目录；
    - 正在转换/上传的文件拒绝移动：worker 会往旧路径写结果。
    """

    with _LOCK:
        meta = get_file(file_id)
        fid = str(meta["id"])
        source_pid = str(meta.get("project_id") or "")
        target = get_project(target_project_id)
        target_pid = str(target["id"])
        if source_pid == target_pid:
            return meta

        status = str(meta.get("status") or "")
        if status in {"uploading", "converting"}:
            action = "上传" if status == "uploading" else "转换"
            raise ConflictError(
                f"文件「{_file_label(meta)}」正在{action}，暂时无法移动"
            )

        source_dir = file_dir(meta)
        if not source_dir.is_dir():
            raise ServiceError(
                500, f"文件「{_file_label(meta)}」目录不存在，无法移动"
            )

        files_dir = _project_dir(target_pid) / "files"
        try:
            files_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ServiceError(500, "目标项目文件目录不可用，无法移动文件") from exc

        # 目录名优先沿用当前名称（已清洗、已去重），旧 UUID 布局则按文件名重建。
        existing = str(meta.get("dir_name") or "").strip()
        if existing and existing != fid:
            base = existing
        else:
            base = _sanitize_file_dir_name(
                Path(str(meta.get("name") or "")).stem, fid
            )
        dir_name = _dedupe_dir_name(base, _taken_file_dir_names(files_dir))
        target_dir = files_dir / dir_name

        try:
            _rename_dir(source_dir, target_dir)
        except OSError as exc:
            raise ServiceError(
                500,
                f"移动文件「{_file_label(meta)}」失败，"
                "请关闭占用该目录的程序后重试",
            ) from exc

        moved = dict(meta)
        moved["project_id"] = target_pid
        moved["dir_name"] = dir_name
        moved["updated_at"] = utc_now()
        try:
            _atomic_write_json(target_dir / "meta.json", moved)
        except BaseException:
            try:
                _rename_dir(target_dir, source_dir)
            except OSError:
                logger.exception(
                    "回滚文件目录移动失败：%s -> %s", target_dir, source_dir
                )
            raise
        _cache_file_dir(fid, target_pid, dir_name)
        return moved


def source_path(file_meta: dict[str, Any]) -> Path:
    return file_dir(file_meta) / file_meta["source_filename"]


def markdown_dir(file_meta: dict[str, Any]) -> Path:
    return file_dir(file_meta) / "markdown"


def markdown_path(file_meta: dict[str, Any]) -> Path:
    return markdown_dir(file_meta) / "result.md"


def images_dir(file_meta: dict[str, Any]) -> Path:
    return markdown_dir(file_meta) / "images"


def pages_path(file_meta: dict[str, Any]) -> Path:
    """Worker 结果 ZIP 根目录的 pages.json 会随 markdown 目录一起解压。"""

    return markdown_dir(file_meta) / "pages.json"


def blocks_path(file_meta: dict[str, Any]) -> Path:
    """blocks.json 属于文件级派生数据，不随 Markdown 目录整体替换。"""

    return file_dir(file_meta) / "blocks.json"


def figure_assets_dir(file_meta: dict[str, Any]) -> Path:
    return file_dir(file_meta) / "assets" / "figures"


def _valid_figure_asset_name(name: str) -> bool:
    """资产文件名必须是非隐藏的单层文件名，且不含 Windows 非法字符。"""

    return bool(
        name
        and name not in {"", ".", ".."}
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
        and not _INVALID_DIR_CHARS.search(name)
        and any(ord(char) >= 32 for char in name)
        and not name.startswith(".")
    )


def figure_asset_path(file_meta: dict[str, Any], asset_path: str) -> Path | None:
    """把记录中的 assetPath（assets/figures/xxx.png）解析为真实文件路径。"""

    raw = str(asset_path or "").replace("\\", "/")
    parts = PurePosixPath(raw).parts
    # 只接受严格的 assets/figures/<单层文件名>，拒绝 "."、".." 等规范化路径。
    if (
        len(parts) != 3
        or parts[0] != "assets"
        or parts[1] != "figures"
        or raw.endswith("/")
    ):
        return None
    name = parts[2]
    if not _valid_figure_asset_name(name):
        return None
    return figure_assets_dir(file_meta) / name


def resolve_figure_asset(file_id: str, name: str) -> Path:
    """只允许读取 assets/figures 下的单层文件名，拒绝目录穿越。

    文件名可以是中文、空格与括号（来自用户 caption），但仍必须是
    ``assets/figures`` 下的单层文件，且不得含路径分隔符或控制字符。
    """

    meta = get_file(file_id)
    raw = (name or "").replace("\\", "/").replace("\x00", "").strip()
    if not _valid_figure_asset_name(raw):
        raise BadRequestError("非法的图表资源路径")
    base = figure_assets_dir(meta)
    try:
        candidate = ensure_within(base, base / raw)
    except ValueError as exc:
        raise BadRequestError("非法的图表资源路径") from exc
    if not candidate.is_file():
        raise NotFoundError("图表资源不存在")
    return candidate


def read_markdown(file_id: str) -> str | None:
    meta = get_file(file_id)
    path = markdown_path(meta)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ServiceError(500, "读取 Markdown 失败") from exc


def save_markdown(file_id: str, markdown: str) -> dict[str, Any]:
    with _LOCK:
        meta = get_file(file_id)
        path = markdown_path(meta)
        _atomic_write_text(path, markdown)
        # 即使目录被外部误删，也保证后续图片引用目录存在。
        images_dir(meta).mkdir(parents=True, exist_ok=True)
        return meta


def clear_results(
    file_id: str,
    *,
    clear_annotations: bool = True,
) -> dict[str, Any]:
    """清空上一次 Markdown/图片结果，可选清空标注（图表记录与资产保留）。"""

    with _LOCK:
        meta = get_file(file_id)
        # markdown 目录包含 result.md、images/ 与 Worker 产出的 pages.json。
        shutil.rmtree(markdown_dir(meta), ignore_errors=True)
        pages_path(meta).unlink(missing_ok=True)
        blocks_path(meta).unlink(missing_ok=True)
        if clear_annotations:
            reset_annotations(file_id)
        return meta


def resolve_asset(file_id: str, relative_path: str) -> Path:
    """安全解析 Markdown 资源路径，只允许访问 markdown/ 内文件。"""

    meta = get_file(file_id)
    raw = (relative_path or "").replace("\\", "/").replace("\x00", "")
    posix = PurePosixPath(raw)
    if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
        raise BadRequestError("非法的资源路径")
    base = markdown_dir(meta)
    try:
        candidate = ensure_within(base, base.joinpath(*posix.parts))
    except ValueError as exc:
        raise BadRequestError("非法的资源路径") from exc
    if not candidate.is_file():
        raise NotFoundError("资源不存在")
    return candidate


# ---------------------------------------------------------------------------
# 标注
# ---------------------------------------------------------------------------


def _empty_annotations() -> dict[str, Any]:
    return {
        "text": "",
        "spans": [],
        "relations": [],
        "paragraphs": [],
        "figures": [],
        "updated_at": "",
    }


def _dict_list(record: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = record.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_figure_record(raw: dict[str, Any]) -> dict[str, Any]:
    """把图表记录收敛到当前契约字段。

    历史 annotations.json 可能仍带 number/label/paragraphId，读取时直接丢弃，
    既不报错也不写回，保证 API、导出与图谱都看不到这些无意义字段。
    """

    bbox: list[float] = []
    raw_bbox = raw.get("bbox")
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            bbox = [float(value) for value in raw_bbox]
        except (TypeError, ValueError):
            bbox = []
    try:
        page = int(raw.get("page") or 0)
    except (TypeError, ValueError):
        page = 0
    kind = str(raw.get("kind") or "")
    if kind not in {"figure", "table"}:
        kind = "figure"
    return {
        "id": str(raw.get("id") or ""),
        "kind": kind,
        "caption": str(raw.get("caption") or ""),
        "note": str(raw.get("note") or ""),
        "page": page,
        "bbox": bbox,
        "assetPath": str(raw.get("assetPath") or ""),
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _write_annotations_record(meta: dict[str, Any], record: dict[str, Any]) -> None:
    _atomic_write_json(_annotation_path(meta["project_id"], meta["id"]), record)


def has_annotations_for(meta: dict[str, Any]) -> bool:
    """直接基于已加载的文件元数据判断标注记录是否存在。

    供项目详情批量序列化使用，避免对每个文件重复 get_file。
    """
    return _annotation_path(meta["project_id"], meta["id"]).is_file()


def has_annotations(file_id: str) -> bool:
    meta = get_file(file_id)
    return has_annotations_for(meta)


def load_annotations(file_id: str) -> dict[str, Any]:
    with _LOCK:
        meta = get_file(file_id)
        data = _read_json(
            _annotation_path(meta["project_id"], meta["id"]), _empty_annotations()
        )
        if not isinstance(data, dict):
            raise ServiceError(500, "标注数据格式不正确")
        # 逐字段归一化：旧 annotations.json 不含 paragraphs/figures，读取时补空列表。
        result = _empty_annotations()
        result.update(data)
        if not isinstance(result.get("text"), str):
            result["text"] = ""
        for key in ("spans", "relations", "paragraphs"):
            result[key] = _dict_list(result, key)
        result["figures"] = [
            _normalize_figure_record(item) for item in _dict_list(result, "figures")
        ]
        return result


def save_annotations(
    file_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """保存文本/实体/关系/段落标注；图表由独立接口维护，此处保留已有记录。"""

    with _LOCK:
        meta = get_file(file_id)
        existing = load_annotations(file_id)
        paragraphs = payload.get("paragraphs")
        record = {
            "text": payload["text"],
            "spans": payload["spans"],
            "relations": payload["relations"],
            "paragraphs": paragraphs if isinstance(paragraphs, list) else [],
            "figures": existing.get("figures", []),
            "updated_at": utc_now(),
        }
        _write_annotations_record(meta, record)
    return record


def reset_annotations(
    file_id: str,
    *,
    valid_paragraph_ids: set[str] | None = None,
) -> dict[str, Any]:
    """清空文本/实体/关系/段落标注，保留图表记录与截图资产。

    ``valid_paragraph_ids`` 仅为兼容旧调用方保留：图表已不再归属段落，
    该参数被忽略。
    """

    with _LOCK:
        meta = get_file(file_id)
        existing = load_annotations(file_id)
        figures = [_normalize_figure_record(raw) for raw in existing.get("figures", [])]
        path = _annotation_path(meta["project_id"], meta["id"])
        if not figures:
            path.unlink(missing_ok=True)
            return _empty_annotations()
        record = {
            "text": "",
            "spans": [],
            "relations": [],
            "paragraphs": [],
            "figures": figures,
            "updated_at": utc_now(),
        }
        _write_annotations_record(meta, record)
        return record


# ---------------------------------------------------------------------------
# 图表（PDF 拖框截图）
# ---------------------------------------------------------------------------

_FIGURE_KINDS = {"figure": "fig", "table": "tbl"}
_FIGURE_EDITABLE_FIELDS = ("caption", "note")


def next_figure_id(figures: list[dict[str, Any]], kind: str) -> str:
    """按类型生成单调递增的图表 id：fig_0001 / tbl_0001。"""

    prefix = _FIGURE_KINDS.get(kind)
    if prefix is None:
        raise BadRequestError("图表类型不合法")
    pattern = re.compile(rf"^{prefix}_(\d+)$")
    highest = 0
    for item in figures:
        if not isinstance(item, dict):
            continue
        match = pattern.match(str(item.get("id") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}_{highest + 1:04d}"


def _rename_file(source: Path, target: Path) -> None:
    """文件重命名入口；独立成函数便于测试模拟资产被占用失败。"""

    source.rename(target)


def _taken_figure_asset_stems(
    file_meta: dict[str, Any], *, exclude_filename: str | None = None
) -> set[str]:
    """assets/figures 下已占用的文件名主干（大小写不敏感）。"""

    directory = figure_assets_dir(file_meta)
    if not directory.is_dir():
        return set()
    excluded = (exclude_filename or "").casefold()
    stems: set[str] = set()
    for child in directory.iterdir():
        if not child.is_file():
            continue
        if excluded and child.name.casefold() == excluded:
            continue
        stems.add(Path(child.name).stem.casefold())
    return stems


def _figure_asset_filename(
    caption: str, figure_id: str, taken: set[str]
) -> str:
    """按 caption 生成资产文件名；空 caption 回退 figure id。"""

    stem = _sanitize_figure_asset_stem(caption, figure_id)
    return f"{_dedupe_dir_name(stem, taken)}.png"


def add_figure(
    file_id: str, figure: dict[str, Any], content: bytes
) -> dict[str, Any]:
    """写入截图资产并追加图表记录，返回新记录。"""

    if not isinstance(content, (bytes, bytearray)) or not content:
        raise BadRequestError("截图内容为空")

    with _LOCK:
        meta = get_file(file_id)
        record = load_annotations(file_id)
        figures = record.get("figures", [])
        kind = str(figure.get("kind") or "")
        figure_id = next_figure_id(figures, kind)
        filename = _figure_asset_filename(
            str(figure.get("caption") or ""),
            figure_id,
            _taken_figure_asset_stems(meta),
        )
        asset_file = figure_assets_dir(meta) / filename
        # 先落资产再写记录：记录写入失败时回滚资产，避免出现孤儿文件。
        _atomic_write_bytes(asset_file, bytes(content))
        now = utc_now()
        item = {
            "id": figure_id,
            "kind": kind,
            "caption": str(figure.get("caption") or ""),
            "note": str(figure.get("note") or ""),
            "page": int(figure.get("page") or 0),
            "bbox": [float(value) for value in figure.get("bbox") or []],
            "assetPath": f"assets/figures/{filename}",
            "created_at": now,
            "updated_at": now,
        }
        figures.append(item)
        record["figures"] = figures
        try:
            _write_annotations_record(meta, record)
        except BaseException:
            asset_file.unlink(missing_ok=True)
            raise
        return dict(item)


def update_figure(
    file_id: str, figure_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """更新 caption/note；caption 变化时同步重命名资产。

    重命名失败（文件占用、目标冲突等）只记录 warning 并保留旧 assetPath，
    caption 仍会保存，避免用户输入丢失。
    """

    with _LOCK:
        meta = get_file(file_id)
        record = load_annotations(file_id)
        figures = record.get("figures", [])
        for index, item in enumerate(figures):
            if str(item.get("id")) != figure_id:
                continue
            updated = dict(item)
            old_caption = str(item.get("caption") or "")
            for field in _FIGURE_EDITABLE_FIELDS:
                if field in changes and changes[field] is not None:
                    updated[field] = str(changes[field]).strip()

            rename: tuple[Path, Path] | None = None
            caption_changed = str(updated.get("caption") or "") != old_caption
            if caption_changed:
                old_asset_path = str(updated.get("assetPath") or "")
                old_asset = figure_asset_path(meta, old_asset_path)
                old_name = PurePosixPath(
                    old_asset_path.replace("\\", "/")
                ).name
                if old_asset is not None and old_name and old_asset.is_file():
                    target_name = _figure_asset_filename(
                        str(updated.get("caption") or ""),
                        figure_id,
                        _taken_figure_asset_stems(
                            meta, exclude_filename=old_name
                        ),
                    )
                    if target_name.casefold() != old_name.casefold():
                        target = figure_assets_dir(meta) / target_name
                        try:
                            _rename_file(old_asset, target)
                        except OSError:
                            logger.warning(
                                "图表资产重命名失败，保留旧路径：%s -> %s",
                                old_asset,
                                target,
                            )
                        else:
                            updated["assetPath"] = (
                                f"assets/figures/{target_name}"
                            )
                            rename = (old_asset, target)

            updated["updated_at"] = utc_now()
            figures[index] = updated
            record["figures"] = figures
            try:
                _write_annotations_record(meta, record)
            except BaseException:
                # 记录写失败时回滚资产重命名，避免 assetPath 与文件不一致。
                if rename is not None:
                    try:
                        _rename_file(rename[1], rename[0])
                    except OSError:
                        logger.exception("回滚图表资产重命名失败：%s", rename[1])
                raise
            return dict(updated)
        raise NotFoundError("图表不存在")


def delete_figure(file_id: str, figure_id: str) -> None:
    with _LOCK:
        meta = get_file(file_id)
        record = load_annotations(file_id)
        figures = record.get("figures", [])
        remaining = [item for item in figures if str(item.get("id")) != figure_id]
        if len(remaining) == len(figures):
            raise NotFoundError("图表不存在")
        removed = next(
            item for item in figures if str(item.get("id")) == figure_id
        )
        record["figures"] = remaining
        record["updated_at"] = utc_now()
        _write_annotations_record(meta, record)
        asset = figure_asset_path(meta, str(removed.get("assetPath") or ""))
        if asset is not None:
            try:
                asset.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # 资产被其他进程占用时保留记录删除结果，后续可由维护任务清理。
                logger.warning("删除图表资产失败：%s", asset)


def list_figures(file_id: str) -> list[dict[str, Any]]:
    """返回图表记录；资产缺失时附加 ``missing`` 标记供前端提示。"""

    with _LOCK:
        meta = get_file(file_id)
        record = load_annotations(file_id)
        result: list[dict[str, Any]] = []
        for item in record.get("figures", []):
            copy = dict(item)
            asset = figure_asset_path(meta, str(item.get("assetPath") or ""))
            copy["missing"] = asset is None or not asset.is_file()
            result.append(copy)
        result.sort(key=lambda item: str(item.get("id") or ""))
        return result


def migrate_figure_asset_names() -> int:
    """把已有的 ``fig_0001.png`` / ``tbl_0001.png`` 改为 caption 命名。

    设计要点：

    - 对每个文件先基于目录现有资产计算目标名，再逐个 rename；
    - 同一文件内 caption 重复时用 `` (2)`` / `` (3)`` 后缀，绝不互相覆盖；
    - 空 caption 保留 ``fig_`` / ``tbl_`` 命名；
    - 资产缺失、重命名失败只记录日志并跳过，不影响其它记录；
    - 每个文件的重命名与 annotations.json 写入失败会回滚该文件的本次改名；
    - 幂等：当前文件名已是目标名时不做任何写入。

    返回实际完成重命名的资产数量。
    """

    migrated = 0
    with _LOCK:
        for project in list_projects():
            pid = project.get("id")
            if not isinstance(pid, str) or not pid:
                continue
            for meta in list_files(pid):
                file_id = meta.get("id")
                if not isinstance(file_id, str) or not file_id:
                    continue
                annotation_path = _annotation_path(meta["project_id"], file_id)
                if not annotation_path.is_file():
                    continue
                try:
                    data = _read_json(annotation_path, None)
                except (ServiceError, OSError):
                    logger.exception(
                        "图表资产迁移跳过无法读取的标注：%s", annotation_path
                    )
                    continue
                if not isinstance(data, dict):
                    continue
                figures = data.get("figures")
                if not isinstance(figures, list):
                    continue
                assets_dir = figure_assets_dir(meta)
                if not assets_dir.is_dir():
                    continue

                taken = {
                    Path(child.name).stem.casefold()
                    for child in assets_dir.iterdir()
                    if child.is_file()
                }
                renames: list[tuple[Path, Path]] = []
                for figure in figures:
                    if not isinstance(figure, dict):
                        continue
                    figure_id = str(figure.get("id") or "").strip()
                    if not figure_id:
                        continue
                    asset = figure_asset_path(
                        meta, str(figure.get("assetPath") or "")
                    )
                    if asset is None or not asset.is_file():
                        continue
                    current_stem = Path(asset.name).stem
                    blocked = set(taken)
                    blocked.discard(current_stem.casefold())
                    target_name = _figure_asset_filename(
                        str(figure.get("caption") or ""),
                        figure_id,
                        blocked,
                    )
                    if target_name.casefold() == asset.name.casefold():
                        continue
                    target = assets_dir / target_name
                    try:
                        _rename_file(asset, target)
                    except OSError:
                        logger.warning(
                            "图表资产迁移失败，已跳过：%s -> %s", asset, target
                        )
                        continue
                    figure["assetPath"] = f"assets/figures/{target_name}"
                    taken.discard(current_stem.casefold())
                    taken.add(Path(target_name).stem.casefold())
                    renames.append((target, asset))

                if not renames:
                    continue
                try:
                    _write_annotations_record(meta, data)
                except BaseException:
                    logger.exception(
                        "图表资产迁移写入标注失败，回滚本文件改名：%s",
                        annotation_path,
                    )
                    for target, original in reversed(renames):
                        try:
                            _rename_file(target, original)
                        except OSError:
                            logger.exception(
                                "回滚图表资产重命名失败：%s", target
                            )
                    continue
                migrated += len(renames)

    if migrated:
        logger.info("已完成 %s 个图表资产重命名", migrated)
    return migrated


# ---------------------------------------------------------------------------
# 启动恢复
# ---------------------------------------------------------------------------


def migrate_project_dirs() -> int:
    """把旧的 ``projects/<uuid>/`` 迁移为 ``projects/<项目名称>/``。

    设计要点：

    - 先扫描全部含 ``project.json`` 的目录并计算目标名称，再逐个 rename，
      单个目录失败（例如 Windows 文件占用）只记录日志并跳过；
    - 每次 rename 成功后立即写索引；若索引写入失败则回滚该次 rename，
      避免磁盘目录与索引长期不一致；
    - 幂等：目标目录名已正确时不做任何移动，重复调用返回 0；
    - 索引缺失的项目按 ``project.json`` 补齐完整元数据。

    返回实际完成目录重命名的项目数量。调用方需持有项目操作所需的文件锁
    语义（本函数内部使用 ``_LOCK``）。
    """

    migrated = 0
    with _LOCK:
        _ensure_dirs()
        index = _load_index()
        index_projects = index["projects"]

        records_by_id: dict[str, dict[str, Any]] = {}
        for item in index_projects:
            pid = item.get("id")
            if isinstance(pid, str) and pid:
                records_by_id[pid] = item

        all_children = list(PROJECTS_DIR.iterdir())
        children = [child for child in all_children if child.is_dir()]
        # 同名文件也会占用目标名称，规划时一并避开。
        taken = {child.name.casefold() for child in all_children}
        # 记录索引中目录名的归属，规划时排除“自己”的旧名称：
        # 自己的目录已被外部删除时，不应因为自己的索引记录而被迫加后缀。
        owner_by_name: dict[str, str] = {}
        for item in index_projects:
            dir_name = item.get("dir_name")
            if dir_name:
                key = str(dir_name).casefold()
                taken.add(key)
                owner_by_name[key] = str(item.get("id") or "")

        # 第一阶段：只读取 project.json 并计算全部目标，不做任何移动。
        plans: list[tuple[Path, dict[str, Any], str]] = []
        for child in sorted(children, key=lambda path: path.name):
            project_path = child / "project.json"
            if not project_path.is_file():
                continue
            try:
                project = _read_json(project_path, None)
            except (ServiceError, OSError):
                logger.exception("项目目录迁移跳过无法读取的项目：%s", project_path)
                continue
            if not isinstance(project, dict):
                logger.warning("项目目录迁移跳过格式不正确的项目：%s", project_path)
                continue
            try:
                pid = _assert_id(project.get("id"), "项目")
            except (NotFoundError, ValueError, TypeError):
                logger.warning("项目目录迁移跳过 id 无效的项目：%s", project_path)
                continue
            base = _sanitize_dir_name(str(project.get("name") or ""), pid)
            if child.name.casefold() == base.casefold():
                target_name = child.name
            else:
                blocked = {
                    name
                    for name in taken
                    if owner_by_name.get(name) != pid
                }
                target_name = _dedupe_dir_name(base, blocked)
            taken.add(target_name.casefold())
            owner_by_name[target_name.casefold()] = pid
            plans.append((child, project, target_name))

        # 第二阶段：逐个迁移；失败项目保留原目录并继续处理其它项目。
        index_dirty = False
        for source, project, target_name in plans:
            pid = _assert_id(project.get("id"), "项目")
            record = records_by_id.get(pid)
            if record is None:
                record = {
                    key: value
                    for key, value in project.items()
                    if key != "dir_name"
                }
                record["id"] = pid
                index_projects.append(record)
                records_by_id[pid] = record
                index_dirty = True
            else:
                # project.json 为权威来源，顺带修正索引中的陈旧元数据。
                for key in (
                    "name",
                    "labels",
                    "relation_types",
                    "created_at",
                    "updated_at",
                ):
                    if key in project:
                        record[key] = project[key]

            target_path = PROJECTS_DIR / target_name
            if source.name == target_name:
                if record.get("dir_name") != target_name:
                    record["dir_name"] = target_name
                    index_dirty = True
                continue

            previous_dir_name = record.get("dir_name")
            try:
                _rename_dir(source, target_path)
            except OSError:
                logger.exception(
                    "项目目录迁移失败，已跳过（将在下次启动重试）：%s -> %s",
                    source,
                    target_path,
                )
                # 记录目录的实际位置，保证迁移失败的项目仍可通过 API 访问。
                if record.get("dir_name") != source.name:
                    record["dir_name"] = source.name
                    index_dirty = True
                continue

            record["dir_name"] = target_name
            migrated += 1
            try:
                _atomic_write_json(PROJECTS_INDEX_PATH, index)
                index_dirty = False
            except OSError:
                logger.exception(
                    "项目索引写入失败，回滚本次目录重命名：%s", target_path
                )
                record["dir_name"] = previous_dir_name
                index_dirty = True
                try:
                    _rename_dir(target_path, source)
                    migrated -= 1
                except OSError:
                    # 回滚失败时目录实际仍在目标位置，索引必须跟随实际位置。
                    logger.exception("回滚项目目录重命名失败：%s", target_path)
                    record["dir_name"] = target_name

        if index_dirty:
            _atomic_write_json(PROJECTS_INDEX_PATH, index)

    if migrated:
        logger.info("已完成 %s 个项目目录迁移", migrated)
    return migrated


def migrate_file_dirs() -> int:
    """把 ``files/<文件UUID>/`` 迁移为 ``files/<文件名>/``。

    设计要点：

    - 先扫描每个项目 ``files/`` 下含 ``meta.json`` 的目录并计算目标名，
      同项目内重名按 `` (2)`` / `` (3)`` 去重；
    - 目录名已正确时只补写 ``meta.dir_name``，不移动目录；
    - 单个目录失败（Windows 文件占用等）只记录日志并跳过；
    - rename 成功后写 ``meta.dir_name``，写入失败时回滚本次 rename；
    - 幂等：重复调用不会再次移动已迁移目录。

    返回实际完成目录重命名的文件数量。
    """

    migrated = 0
    with _LOCK:
        _ensure_dirs()
        for project in _load_index()["projects"]:
            pid = project.get("id")
            if not isinstance(pid, str) or not pid:
                continue
            project_dir = _project_dir_for_record(project)
            files_dir = project_dir / "files"
            if not files_dir.is_dir():
                continue

            all_children = list(files_dir.iterdir())
            taken = {child.name.casefold() for child in all_children}
            entries: list[tuple[Path, dict[str, Any], str, str]] = []
            for child in sorted(
                (item for item in all_children if item.is_dir()),
                key=lambda path: path.name,
            ):
                meta_path = child / "meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = _read_json(meta_path, None)
                except (ServiceError, OSError):
                    logger.exception(
                        "文件目录迁移跳过无法读取的元数据：%s", meta_path
                    )
                    continue
                if not isinstance(meta, dict):
                    logger.warning(
                        "文件目录迁移跳过格式不正确的元数据：%s", meta_path
                    )
                    continue
                try:
                    file_id = _assert_id(meta.get("id"), "文件")
                except (NotFoundError, ValueError, TypeError):
                    logger.warning(
                        "文件目录迁移跳过 id 无效的记录：%s", meta_path
                    )
                    continue
                stem = Path(str(meta.get("name") or "")).stem
                base = _sanitize_file_dir_name(stem, file_id)
                entries.append((child, meta, file_id, base))

            plans: list[tuple[Path, dict[str, Any], str, str]] = []
            # 第一阶段：目录名已经是目标名的先固定下来，并记录占用。
            settled: set[str] = set()
            for child, meta, file_id, base in entries:
                if child.name.casefold() == base.casefold():
                    settled.add(child.name.casefold())
                    plans.append((child, meta, file_id, child.name))

            # 第二阶段：其余目录按当前目录名顺序分配唯一目标名。
            for child, meta, file_id, base in entries:
                if child.name.casefold() in settled:
                    continue
                blocked = {
                    name for name in taken if name != child.name.casefold()
                }
                target_name = _dedupe_dir_name(base, blocked)
                if target_name.casefold() == child.name.casefold():
                    target_name = child.name
                else:
                    taken.discard(child.name.casefold())
                    taken.add(target_name.casefold())
                plans.append((child, meta, file_id, target_name))

            # 第三阶段：逐个执行，失败只跳过当前文件。
            for source, meta, file_id, target_name in plans:
                if source.name == target_name:
                    if meta.get("dir_name") != target_name:
                        merged = dict(meta)
                        merged["dir_name"] = target_name
                        try:
                            _atomic_write_json(
                                source / "meta.json", merged
                            )
                        except OSError:
                            logger.exception(
                                "补写文件目录名失败，已跳过：%s", source
                            )
                            _cache_file_dir(file_id, pid, source.name)
                            continue
                    _cache_file_dir(file_id, pid, target_name)
                    continue

                target = source.parent / target_name
                try:
                    _rename_dir(source, target)
                except OSError:
                    logger.exception(
                        "文件目录迁移失败，已跳过（将在下次启动重试）：%s -> %s",
                        source,
                        target,
                    )
                    _cache_file_dir(file_id, pid, source.name)
                    continue

                merged = dict(meta)
                merged["dir_name"] = target_name
                try:
                    _atomic_write_json(target / "meta.json", merged)
                except OSError:
                    logger.exception(
                        "文件元数据写入失败，回滚目录重命名：%s", target
                    )
                    try:
                        _rename_dir(target, source)
                    except OSError:
                        logger.exception(
                            "回滚文件目录重命名失败：%s", target
                        )
                        _cache_file_dir(file_id, pid, target_name)
                        migrated += 1
                        continue
                    _cache_file_dir(file_id, pid, source.name)
                    continue

                _cache_file_dir(file_id, pid, target_name)
                migrated += 1

    if migrated:
        logger.info("已完成 %s 个文件目录迁移", migrated)
    return migrated


def initialize_storage() -> None:
    global _last_queue_seq

    _ensure_dirs()
    with _LOCK:
        if not PROJECTS_INDEX_PATH.exists():
            _atomic_write_json(PROJECTS_INDEX_PATH, {"projects": []})
        highest_seq = _last_queue_seq
        for project in _load_index()["projects"]:
            pid = project.get("id")
            if not pid:
                continue
            project_dir = _project_dir(pid)
            (project_dir / "files").mkdir(parents=True, exist_ok=True)
            if not (project_dir / "project.json").is_file():
                _atomic_write_json(project_dir / "project.json", project)
            # 用历史最大 queue_seq 初始化进程内计数器：系统时钟回拨时，
            # 新文件仍排在历史积压之后，不会插队到旧任务前面。
            for meta in list_files(pid):
                try:
                    seq = int(meta.get("queue_seq") or 0)
                except (TypeError, ValueError):
                    continue
                if seq > highest_seq:
                    highest_seq = seq
        _last_queue_seq = highest_seq


def cleanup_stale_uploads() -> int:
    """删除所有残留的 uploading 记录，返回删除数量。

    进程被杀、客户端断连或 ``file.close()`` 期间中断时，可能留下
    ``status == "uploading"`` 的半截记录；启动时整体删除目录，
    避免前端永久显示“正在上传”。正常上传完成后记录已是 uploaded，
    不受影响。
    """

    removed = 0
    for project in list_projects():
        pid = project.get("id")
        if not pid:
            continue
        for meta in list_files(pid):
            if meta.get("status") != "uploading":
                continue
            try:
                delete_file(meta["id"])
            except Exception:
                logger.exception(
                    "清理残留上传记录失败：project=%s file=%s",
                    pid,
                    meta.get("id"),
                )
                continue
            removed += 1
    return removed


def requeue_interrupted_conversions() -> int:
    """服务启动时把残留 converting 文件退回队列，返回修改数量。

    只重置转换相关字段，``queue_seq`` 原样保留，重启后仍按原导入顺序执行。
    """

    changed = 0
    for project in list_projects():
        pid = project.get("id")
        if not pid:
            continue
        for meta in list_files(pid):
            if meta.get("status") != "converting":
                continue
            update_file(
                meta["id"],
                {
                    "status": "uploaded",
                    "progress": 0,
                    "stage": "服务重启，重新排队",
                    "message": "",
                    "error": "",
                    "task_id": "",
                    "conversion_token": "",
                    # 避免重启后到被认领前仍显示上一次的旧页数。
                    "page_count": 0,
                },
            )
            changed += 1
    return changed
