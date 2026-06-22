"""认证服务模块 — 从 users.xlsx 读取账号，登录后签发 JWT。"""

import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jwt
from openpyxl import load_workbook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExcelUser:
    """Excel 中的一条用户记录。"""

    id: int
    username: str
    password: str
    role: str = ""
    name: str = ""

# ============================================================
# JWT 密钥管理
# ============================================================

def _get_jwt_secret() -> str:
    """获取 JWT 签名密钥。

    优先级：
    1. 环境变量 JWT_SECRET（最高优先级，支持外部注入）
    2. backend/.env 文件中已有的 JWT_SECRET（持久化密钥，跨重启不变）
    3. 若以上均无，随机生成并写入 backend/.env 文件

    Returns:
        JWT 签名密钥字符串
    """
    # 1. 优先从环境变量读取
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret

    # 计算 backend/.env 路径
    # 当前文件: backend/文本标注器/services/auth_service.py
    # 需要定位到: backend/.env
    current_dir = os.path.dirname(os.path.abspath(__file__))        # services/
    parent_dir = os.path.dirname(current_dir)                        # 文本标注器/
    backend_dir = os.path.dirname(parent_dir)                        # backend/
    env_path = os.path.join(backend_dir, ".env")

    # 2. 尝试从 .env 文件读取已有密钥（避免每次重启重新生成导致 Token 失效）
    existing_secret = _read_jwt_secret_from_env_file(env_path)
    if existing_secret:
        os.environ["JWT_SECRET"] = existing_secret
        return existing_secret

    # 3. 生成新的安全随机密钥并持久化到 .env 文件
    secret = secrets.token_urlsafe(32)

    try:
        if os.path.exists(env_path):
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\n# 自动生成的 JWT 签名密钥\nJWT_SECRET={secret}\n")
            logger.info("JWT_SECRET 已追加到 %s", env_path)
        else:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"# 自动生成的 JWT 签名密钥\nJWT_SECRET={secret}\n")
            logger.info(".env 文件已创建，JWT_SECRET 已写入 %s", env_path)
    except OSError as e:
        logger.warning("无法写入 .env 文件 (%s)，JWT_SECRET 仅保存在内存中", e)

    os.environ["JWT_SECRET"] = secret
    return secret


def _read_jwt_secret_from_env_file(env_path: str) -> str | None:
    """从 .env 文件中提取已存在的 JWT_SECRET 值。"""
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过注释和空行
                if not line or line.startswith("#"):
                    continue
                if line.startswith("JWT_SECRET="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
    except OSError:
        pass
    return None


# 模块加载时获取密钥
JWT_SECRET = _get_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7


# 账号 Excel 路径：backend/users.xlsx
USERS_XLSX_PATH = Path(__file__).resolve().parents[2] / "users.xlsx"


def _normalize_cell(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def load_excel_users() -> dict[str, ExcelUser]:
    """从 users.xlsx 读取账号，启动时加载一次。

    若文件不存在或为空，记录警告并返回空字典而不是抛出异常，
    确保服务可以正常启动（登录时会返回清晰的错误信息）。
    """
    if not USERS_XLSX_PATH.exists():
        logger.warning("用户账号文件不存在: %s，服务将以无用户模式启动", USERS_XLSX_PATH)
        return {}

    workbook = load_workbook(USERS_XLSX_PATH, read_only=True, data_only=True)
    try:
        worksheet = workbook[workbook.sheetnames[0]]
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    if not rows:
        logger.warning("users.xlsx 为空")
        return {}

    header = [_normalize_cell(cell).lower() for cell in rows[0]]
    required_headers = {"username", "password"}
    if not required_headers.issubset(set(header)):
        logger.warning("users.xlsx 缺少 username/password 表头")
        return {}

    username_index = header.index("username")
    password_index = header.index("password")
    role_index = header.index("role") if "role" in header else None
    name_index = header.index("name") if "name" in header else None

    users: dict[str, ExcelUser] = {}
    next_id = 1
    for row in rows[1:]:
        if row is None:
            continue

        username = _normalize_cell(row[username_index] if username_index < len(row) else None)
        password = _normalize_cell(row[password_index] if password_index < len(row) else None)
        if not username or not password:
            continue

        users[username] = ExcelUser(
            id=next_id,
            username=username,
            password=password,
            role=_normalize_cell(row[role_index] if role_index is not None and role_index < len(row) else None),
            name=_normalize_cell(row[name_index] if name_index is not None and name_index < len(row) else None),
        )
        next_id += 1

    if not users:
        logger.warning("users.xlsx 中没有可用账号")

    logger.info("已从 %s 加载 %d 个账号", USERS_XLSX_PATH, len(users))
    return users


EXCEL_USERS_BY_USERNAME = load_excel_users()


# ============================================================
# JWT 令牌工具函数
# ============================================================

def create_token(user_id: int, username: str) -> str:
    """生成 JWT 访问令牌。

    Args:
        user_id: 用户 ID
        username: 用户名

    Returns:
        JWT 令牌字符串
    """
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def verify_token(token: str) -> dict | None:
    """验证 JWT 令牌的有效性。

    Args:
        token: JWT 令牌字符串

    Returns:
        解析成功的 payload 字典，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.info("JWT 令牌已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.info("JWT 令牌无效: %s", e)
        return None


# ============================================================
# 认证业务逻辑
# ============================================================

def get_user_by_username(username: str) -> ExcelUser | None:
    return EXCEL_USERS_BY_USERNAME.get(username)


def get_user_by_id(user_id: int) -> ExcelUser | None:
    for user in EXCEL_USERS_BY_USERNAME.values():
        if user.id == user_id:
            return user
    return None


def login_user(username: str, password: str) -> dict:
    """使用 users.xlsx 中的账号密码登录。"""
    if not EXCEL_USERS_BY_USERNAME:
        raise ValueError("系统尚未配置任何用户账号，请联系管理员添加 users.xlsx")
    user = get_user_by_username(username)
    if not user or user.password != password:
        raise ValueError("用户名或密码错误")

    token = create_token(user.id, user.username)
    logger.info("用户登录成功: %s (id=%d)", username, user.id)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "name": user.name or user.username,
        },
    }
