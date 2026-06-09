"""开发环境：创建默认管理员账号 admin / admin123"""

import sys
import os

# 切换到 backend 目录以确保相对导入正确
backend_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(backend_dir)

from 文本标注器.storage.db import init_db, get_session
from 文本标注器.storage.schema import User
from 文本标注器.services.auth_service import hash_password

def seed():
    init_db()
    session = get_session()
    try:
        existing = session.query(User).filter(User.username == "admin").first()
        if existing:
            print("[seed] 管理员账号已存在: admin / admin123")
            return
        user = User(
            username="admin",
            password_hash=hash_password("admin123"),
        )
        session.add(user)
        session.commit()
        print("[seed] 默认管理员创建成功: admin / admin123")
    except Exception as e:
        session.rollback()
        print(f"[seed] 错误: {e}")
        sys.exit(1)
    finally:
        session.close()

if __name__ == "__main__":
    seed()
