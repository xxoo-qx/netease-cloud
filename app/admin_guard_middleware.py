"""外网仅开放首页与网易云登录 API；其余 /api 与文档类路径需管理员浏览器会话。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse


def _requires_admin_session(path: str) -> bool:
    """未登录管理员时拒绝访问的路径（返回 True）。"""
    p = path.split("?", 1)[0]
    if p == "/welcome" or p.startswith("/welcome/"):
        return True
    if p == "/openapi.json":
        return True
    if p == "/docs" or p.startswith("/docs/"):
        return True
    if p == "/redoc" or p.startswith("/redoc/"):
        return True
    # 除网易云登录外的全部业务 API
    if p == "/api" or p.startswith("/api/"):
        if p == "/api/login" or p.startswith("/api/login/"):
            return False
        return True
    return False


class AdminSessionGuardMiddleware(BaseHTTPMiddleware):
    """须先注册、后于 SessionMiddleware 挂载，以便读取 scope['session']。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not _requires_admin_session(path):
            return await call_next(request)
        session = request.scope.get("session") or {}
        if session.get("admin_logged_in"):
            return await call_next(request)
        # 机器/脚本调用 API 时用 401 JSON；浏览器访问文档页用跳转登录
        if path.startswith("/api"):
            return JSONResponse(
                status_code=401,
                content={"detail": "需要管理员登录"},
            )
        return RedirectResponse(url="/admin/login", status_code=302)
