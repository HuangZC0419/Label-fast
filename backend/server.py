import os

from fastapi import FastAPI, HTTPException, Body, Response, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
from 文本标注器.services import export_service, sync_service, record_service, project_service, auth_service
from 图像标注器.label_system.app import app as minimind_app
from typing import Dict, Any, List, Optional

# 加载 .env 文件（必须在 app 初始化之前）
load_dotenv()

app = FastAPI()

# Mount Minimind Image Labeler
app.mount("/minimind", minimind_app)

# Add CORS to allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# JWT 认证中间件
# ============================================================

class JWTAuthMiddleware(BaseHTTPMiddleware):
    """JWT 认证中间件 — 拦截 /api/* 路径，校验 Authorization Bearer 令牌。

    排除路径：
    - /api/auth/*  — 认证相关接口（注册、登录）
    - /api/health   — 健康检查
    - 非 /api/* 路径 — 直通不拦截
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 排除不需要认证的路径
        if path.startswith("/api/auth/") or path == "/api/health":
            return await call_next(request)

        # 只拦截 /api/* 路径，其它路径直通
        if not path.startswith("/api/"):
            return await call_next(request)

        # 从 Authorization header 中提取 Bearer 令牌
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "未提供有效的认证令牌"},
            )

        token = auth_header[len("Bearer "):]
        payload = auth_service.verify_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "认证令牌无效或已过期"},
            )

        # 将 user_id 注入 request.state，下游路由可通过 request.state.user_id 获取
        request.state.user_id = payload.get("user_id")
        return await call_next(request)


# 在 CORS 中间件之后注册（CORS 在外层，JWT 在内层）
# 这样 CORS 预检请求（OPTIONS）先被 CORS 中间件处理，不会到达 JWT 中间件
app.add_middleware(JWTAuthMiddleware)


@app.get("/")
def read_root():
    return {"message": "Label Fast Backend is running. Visit /api/health to check status."}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# ============================================================
# 认证路由
# ============================================================

@app.post("/api/auth/register")
def register_api(data: Dict[str, Any] = Body(...)):
    """用户注册 — 创建账号并返回 JWT 令牌"""
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(status_code=400, detail="用户名和密码必须为字符串")
    if len(username) > 64:
        raise HTTPException(status_code=400, detail="用户名不能超过64个字符")
    try:
        result = auth_service.register_user(username, password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/login")
def login_api(data: Dict[str, Any] = Body(...)):
    """用户登录 — 验证凭据并返回 JWT 令牌"""
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    try:
        result = auth_service.login_user(username, password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/auth/me")
def get_current_user(request: Request):
    """获取当前登录用户信息 — 从 Authorization header 解析 JWT

    注意：此路由被中间件排除，自行解析令牌。
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header[len("Bearer "):]
    payload = auth_service.verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="令牌无效")

    # 查找用户信息
    from 文本标注器.storage.db import get_session
    from 文本标注器.storage.schema import User
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"id": user.id, "username": user.username}
    finally:
        session.close()


@app.get("/api/health")
def health_check():
    return {"status": "ok"}

@app.get("/api/projects")
def list_projects_api():
    try:
        projects = project_service.list_projects()
        return [{"id": p.id, "name": p.name} for p in projects]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/id-by-name/{name}")
def get_project_id(name: str):
    pid = sync_service.get_project_id_by_name(name)
    if not pid:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"id": pid}

@app.post("/api/projects")
def create_project_api(data: Dict[str, Any] = Body(...)):
    name = data.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Project name required")
    try:
        pid = sync_service.create_project(
            name=name,
            labels=data.get("labels", []),
            relation_types=data.get("relation_types", [])
        )
        return {"id": pid, "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/projects/{project_id}")
def delete_project_api(project_id: int):
    try:
        success = project_service.delete_project(project_id)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found or failed to delete")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/sync")
def load_project_data(project_id: int):
    data = sync_service.load_project_data(project_id)
    if not data:
        raise HTTPException(status_code=404, detail="Project not found")
    return data

@app.post("/api/projects/{project_id}/sync")
def save_project_data(project_id: int, data: Dict[str, Any] = Body(...)):
    try:
        return sync_service.save_project_data(project_id, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/record")
def save_record_api(project_id: int, data: Dict[str, Any] = Body(...)):
    try:
        success = record_service.append_jsonl(project_id, data)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to append record")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/projects/{project_id}/clear")
def clear_project_api(project_id: int):
    try:
        success = sync_service.clear_project(project_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear project")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/documents/{doc_id}")
def delete_document_api(doc_id: int):
    try:
        success = sync_service.delete_document(doc_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete document")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/export")
def export_project_api(project_id: int, format: str = "json_v2", doc_ids: Optional[List[int]] = Query(None)):
    try:
        # Call the pure service function
        # Note: export_service.export_project returns the absolute file path
        file_path = export_service.export_project(project_id, fmt=format, doc_ids=doc_ids)
        
        if not os.path.exists(file_path):
            raise HTTPException(status_code=500, detail="Export failed to generate file")
            
        filename = os.path.basename(file_path)
        return FileResponse(path=file_path, filename=filename, media_type='application/json')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    import argparse
    import socket

    parser = argparse.ArgumentParser(description="Label Fast Backend Server")
    parser.add_argument("--port", type=int, default=8000, help="服务端口 (默认: 8000)")
    args = parser.parse_args()

    def is_port_available(port: int) -> bool:
        """检测指定端口是否可用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return True
            except OSError:
                return False

    port = args.port
    max_attempts = 20

    print("Starting Label Fast Backend...")
    for attempt in range(max_attempts):
        if is_port_available(port):
            print(f"Access the API at: http://localhost:{port}")
            uvicorn.run(app, host="0.0.0.0", port=port)
            break
        else:
            print(f"Port {port} is busy, trying {port + 1}...")
            port += 1
    else:
        print(f"ERROR: No available port found after {max_attempts} attempts.")
        import sys
        sys.exit(1)

# Server updated with record endpoint
