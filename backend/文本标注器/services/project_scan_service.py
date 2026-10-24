"""项目目录扫描服务。

服务启动时扫描 ``backend/文本标注器/projects/`` 下的一级子目录，只负责
“发现新文件夹”：数据库中不存在的项目才会被注册，并导入其 ``imports/*.txt``。

既有项目以数据库为事实来源，其文件夹一律跳过，不再重复导入；这样可避免
“删除文档后重启复活”“保存时残留的下标文件被当成新文档”等问题。
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Set

from sqlalchemy import select

from ..storage.db import get_session, init_db
from ..storage.schema import Document, Project
from .import_service import read_file_text
from .record_service import get_projects_root, sanitize_project_name

logger = logging.getLogger(__name__)

# 需要跳过的固定目录名（隐藏目录另行按前缀判断）
_SKIPPED_DIR_NAMES = {"__pycache__"}


def _empty_summary() -> Dict[str, Any]:
    """构造空扫描摘要。"""
    return {
        "created_projects": [],
        "imported_documents": 0,
        "skipped_documents": 0,
        "existing_projects": 0,
        "errors": [],
    }


def _dir_key(path: str) -> str:
    """把路径规范化为用于目录匹配的键（真实路径 + 大小写无关）。"""
    return os.path.normcase(os.path.realpath(path))


def _is_link_or_junction(path: str) -> bool:
    """判断路径是否为符号链接或 Windows 目录联接（junction）。

    兼容性说明：
    - Python 3.9 没有 ``os.path.isjunction``，且 Windows 上
      ``os.path.islink()`` 对 junction 返回 False；
    - 因此额外尝试 ``os.readlink()``：Python 3.8+ 在 Windows 可读取
      junction 的重解析点，能成功读取即说明是链接类目录。
    """
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(path):
            return True
        try:
            os.readlink(path)
        except (OSError, ValueError):
            # 普通目录在 Windows 上抛出 WinError 4390，在 POSIX 上为 EINVAL
            return False
        return True
    except OSError:
        # 路径不存在或探测失败时按普通目录处理，交给后续读取逻辑兜底
        return False


def _list_project_dirs(projects_root: str) -> List[str]:
    """列出 projects_root 下需要处理的一级子目录名（已排序）。"""
    try:
        entries = os.listdir(projects_root)
    except OSError as exc:
        logger.warning(
            "读取项目根目录失败: %s: %s: %s",
            projects_root,
            type(exc).__name__,
            exc,
        )
        return []

    names: List[str] = []
    for entry in sorted(entries):
        if entry.startswith(".") or entry in _SKIPPED_DIR_NAMES:
            continue
        dir_path = os.path.join(projects_root, entry)
        if not os.path.isdir(dir_path):
            continue
        if _is_link_or_junction(dir_path):
            logger.warning("跳过符号链接/联接目录: %s", dir_path)
            continue
        names.append(entry)
    return names


def _list_txt_files(imports_dir: str) -> List[str]:
    """列出 imports 目录下的 .txt 文件名（不递归、按文件名排序）。

    目录不存在时返回空列表；其它读取错误（如权限）向上抛出，
    由调用方按项目粒度记录到 errors。
    """
    try:
        entries = os.listdir(imports_dir)
    except (FileNotFoundError, NotADirectoryError):
        return []

    return [
        name
        for name in sorted(entries)
        if name.lower().endswith(".txt")
        and os.path.isfile(os.path.join(imports_dir, name))
    ]


def _build_existing_dir_map(session, projects_root: str) -> Dict[str, List[str]]:
    """构建“项目目录 realpath(normcase) → 项目名列表”映射。"""
    dir_map: Dict[str, List[str]] = {}
    for name in session.execute(select(Project.name)).scalars():
        key = _dir_key(os.path.join(projects_root, sanitize_project_name(name)))
        dir_map.setdefault(key, []).append(name)
    return dir_map


def _import_project_texts(
    session,
    project: Project,
    project_name: str,
    project_dir: str,
    summary: Dict[str, Any],
    errors: List[str],
) -> None:
    """把单个新项目 imports/*.txt 导入为文档（项目内按文本去重）。"""
    imports_dir = os.path.join(project_dir, "imports")
    try:
        filenames = _list_txt_files(imports_dir)
    except OSError as exc:
        logger.warning(
            "读取项目导入目录失败: %s: %s: %s",
            project_name,
            type(exc).__name__,
            exc,
        )
        errors.append(f"{project_name}/imports: {type(exc).__name__}: {exc}")
        return

    seen_texts: Set[str] = set()
    for filename in filenames:
        file_path = os.path.abspath(os.path.join(imports_dir, filename))
        try:
            text = read_file_text(file_path)
        except Exception as exc:  # 单文件失败不影响其它项目与文件
            logger.warning(
                "读取导入文件失败: %s/%s: %s: %s",
                project_name,
                filename,
                type(exc).__name__,
                exc,
            )
            errors.append(
                f"{project_name}/{filename}: {type(exc).__name__}: {exc}"
            )
            continue

        # 去掉 BOM 后再判断空白，避免带 BOM 的空文件被误导入
        text = text.lstrip("\ufeff")
        if not text.strip():
            logger.info("跳过空白导入文件: %s/%s", project_name, filename)
            continue

        if text in seen_texts:
            logger.info("跳过同项目内重复文本: %s/%s", project_name, filename)
            summary["skipped_documents"] = int(summary["skipped_documents"]) + 1
            continue

        session.add(
            Document(
                project_id=project.id,
                text=text,
                status="pending",
                source_file=file_path,
                unit_index=0,
            )
        )
        seen_texts.add(text)
        summary["imported_documents"] = int(summary["imported_documents"]) + 1


def scan_projects_directory(
    projects_root: Optional[str] = None,
    session_factory: Optional[Callable] = None,
) -> Dict[str, Any]:
    """扫描项目目录，注册新项目并导入其文本。

    只有“本次扫描中新注册”的项目才会导入 ``imports/*.txt``；已存在项目
    对应的文件夹会被跳过，数据库内容不会被目录覆盖。

    :param projects_root: 项目根目录，默认取 record_service.get_projects_root()；
    :param session_factory: 会话工厂，默认使用 storage.db.get_session
        （此时会先调用 init_db）；传入自定义工厂时不做全局初始化，
        便于测试使用独立 SQLite 文件。
    :return: 包含 created_projects / imported_documents / skipped_documents /
        existing_projects / errors 的摘要字典。
    """
    root = (
        os.path.abspath(projects_root)
        if projects_root is not None
        else get_projects_root()
    )

    if not os.path.exists(root):
        logger.warning("项目根目录不存在，跳过扫描: %s", root)
        return _empty_summary()
    if not os.path.isdir(root):
        logger.warning("项目根路径不是目录，跳过扫描: %s", root)
        return _empty_summary()

    if session_factory is None:
        init_db()
        session_factory = get_session

    summary: Dict[str, Any] = _empty_summary()
    created_projects: List[str] = summary["created_projects"]
    errors: List[str] = summary["errors"]

    session = session_factory()
    try:
        existing_dir_map = _build_existing_dir_map(session, root)

        for project_name in _list_project_dirs(root):
            project_dir = os.path.join(root, project_name)
            matched_names = existing_dir_map.get(_dir_key(project_dir))

            if matched_names:
                # 既有项目：数据库才是事实来源，不扫描其 imports
                if len(matched_names) > 1:
                    logger.warning(
                        "目录 %s 同时映射到多个项目 %s，跳过导入",
                        project_name,
                        matched_names,
                    )
                summary["existing_projects"] = int(summary["existing_projects"]) + 1
                continue

            # 未命中既有项目：只有目录名本身可安全映射时才允许新建
            sanitized = sanitize_project_name(project_name)
            if sanitized != project_name or sanitized == "default":
                logger.warning(
                    "目录名无法安全映射为项目名，跳过: %s（规范化结果: %s）",
                    project_dir,
                    sanitized,
                )
                continue

            project = Project(
                name=project_name,
                labels=[],
                relation_types=[],
                allow_overlap=0,
            )
            session.add(project)
            # 先 flush 取得自增主键，供后续 Document 关联
            session.flush()
            created_projects.append(project_name)

            _import_project_texts(
                session,
                project,
                project_name,
                project_dir,
                summary,
                errors,
            )

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(
        "项目目录扫描完成: 新建项目=%s, 导入文档=%d, 跳过文档=%d, "
        "已存在项目=%d, 错误数=%d",
        created_projects,
        summary["imported_documents"],
        summary["skipped_documents"],
        summary["existing_projects"],
        len(errors),
    )
    return summary
