"""Label-Fast 静态文件托管入口。

在 server.py 基础上，托管前端 dist/ 目录。
使用 Starlette 中间件确保前端页面优先于 JSON 响应。
"""

from pathlib import Path
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from server import app
import uvicorn
import argparse

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "index.html").exists():
    # 挂载静态资源
    if not any(r.path == "/assets" for r in app.routes):
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    class FrontendSPAMiddleware(BaseHTTPMiddleware):
        """中间件：将非 API 路径的 404 / JSON 响应替换为前端 SPA 页面。

        优先级：
        1. /api/* /minimind/* → 直通后端
        2. /assets/*           → 已由 StaticFiles 处理，不经过中间件
        3. 其他路径             → 尝试返回对应文件，否则返回 index.html（SPA）
        """
        async def dispatch(self, request, call_next):
            path = request.url.path

            # API 和子应用路径直通
            if path.startswith("/api/") or path.startswith("/minimind"):
                return await call_next(request)

            # 尝试返回对应的静态文件
            file_path = FRONTEND_DIST / path.lstrip("/")
            if file_path.is_file() and path != "/":
                return FileResponse(str(file_path))

            # SPA 后备：所有非 API 路径返回 index.html
            return FileResponse(str(FRONTEND_DIST / "index.html"))

    app.add_middleware(FrontendSPAMiddleware)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(app, host="0.0.0.0", port=args.port)
