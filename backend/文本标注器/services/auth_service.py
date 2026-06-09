"""认证服务模块 — 用户注册、登录、JWT 令牌管理"""

import os
import secrets
import logging
from datetime import datetime, timedelta

import jwt
import bcrypt

from ..storage.db import get_session
from ..storage.schema import User

logger = logging.getLogger(__name__)

# ============================================================
# JWT 密钥管理
# ============================================================

def _get_jwt_secret() -> str:
    """获取 JWT 签名密钥。

    优先级：
    1. 环境变量 JWT_SECRET
    2. 若未设置，随机生成并写入 backend/.env 文件，同时设置环境变量

    Returns:
        JWT 签名密钥字符串
    """
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret

    # 生成安全的随机密钥
    secret = secrets.token_urlsafe(32)

    # 计算 backend/.env 路径
    # 当前文件: backend/文本标注器/services/auth_service.py
    # 需要定位到: backend/.env
    current_dir = os.path.dirname(os.path.abspath(__file__))        # services/
    parent_dir = os.path.dirname(current_dir)                        # 文本标注器/
    backend_dir = os.path.dirname(parent_dir)                        # backend/
    env_path = os.path.join(backend_dir, ".env")

    try:
        if os.path.exists(env_path):
            # 追加到已有 .env
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "JWT_SECRET" not in content:
                with open(env_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# 自动生成的 JWT 签名密钥\nJWT_SECRET={secret}\n")
                logger.info("JWT_SECRET 已追加到 %s", env_path)
        else:
            # 创建新的 .env
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"# 自动生成的 JWT 签名密钥\nJWT_SECRET={secret}\n")
            logger.info(".env 文件已创建，JWT_SECRET 已写入 %s", env_path)
    except OSError as e:
        logger.warning("无法写入 .env 文件 (%s)，JWT_SECRET 仅保存在内存中", e)

    os.environ["JWT_SECRET"] = secret
    return secret


# 模块加载时获取密钥
JWT_SECRET = _get_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 7


# ============================================================
# 密码工具函数
# ============================================================

def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希后的密码字符串
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证明文密码与哈希值是否匹配。

    Args:
        password: 用户输入的明文密码
        password_hash: 数据库中存储的 bcrypt 哈希

    Returns:
        匹配返回 True，否则返回 False
    """
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


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
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRATION_DAYS),
        "iat": datetime.utcnow(),
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

def register_user(username: str, password: str) -> dict:
    """注册新用户。

    检查用户名唯一性，对密码进行哈希，创建用户记录并返回 JWT 令牌。

    Args:
        username: 用户名（最长 64 字符，唯一）
        password: 明文密码

    Returns:
        {"token": "<jwt>", "user": {"id": <int>, "username": "<str>"}}

    Raises:
        ValueError: 用户名已存在
    """
    session = get_session()
    try:
        # 检查用户名唯一性
        existing = session.query(User).filter(User.username == username).first()
        if existing:
            raise ValueError("用户名已存在")

        # 创建用户
        user = User(
            username=username,
            password_hash=hash_password(password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        token = create_token(user.id, user.username)
        logger.info("用户注册成功: %s (id=%d)", username, user.id)

        return {
            "token": token,
            "user": {"id": user.id, "username": user.username},
        }
    except ValueError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def login_user(username: str, password: str) -> dict:
    """用户登录。

    根据用户名查找用户，验证密码，返回 JWT 令牌。

    Args:
        username: 用户名
        password: 明文密码

    Returns:
        {"token": "<jwt>", "user": {"id": <int>, "username": "<str>"}}

    Raises:
        ValueError: 用户名或密码错误
    """
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            raise ValueError("用户名或密码错误")

        if not verify_password(password, user.password_hash):
            raise ValueError("用户名或密码错误")

        token = create_token(user.id, user.username)
        logger.info("用户登录成功: %s (id=%d)", username, user.id)

        return {
            "token": token,
            "user": {"id": user.id, "username": user.username},
        }
    finally:
        session.close()
