"""NetEase Cloud Music API — FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.admin_guard_middleware import AdminSessionGuardMiddleware
from app.client import close_shared_http
from app.config import SESSION_SECRET
from app.routers import auth, music, ncmm_tasks, playids_batch, ui, user
from app.user_store import ensure_user_data_dir


def _configure_windows_event_loop() -> None:
  if sys.platform != "win32":
    return
  try:
    policy = asyncio.get_event_loop_policy()
    if isinstance(policy, asyncio.WindowsProactorEventLoopPolicy):
      return
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
  except Exception:
    pass


_configure_windows_event_loop()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    ensure_user_data_dir()
    yield
    await close_shared_http()


app = FastAPI(
    title="NetEase Cloud Music API",
    description="网易云音乐升级 API — 重构版",
    version="2.0.0",
    lifespan=lifespan,
)

# 先注册的在栈中更靠近路由；Session 在外层以便先填充 session，再交给 AdminSessionGuard 校验。
app.add_middleware(AdminSessionGuardMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
)
app.include_router(ui.router)
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(music.router)
app.include_router(ncmm_tasks.router)
app.include_router(playids_batch.router)

_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Welcome page ──────────────────────────────────────────────────────────

WELCOME_HTML = """\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>NetEase Cloud Music API</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff;
  }
  .card {
    background: rgba(255,255,255,0.12); backdrop-filter: blur(12px);
    border-radius: 16px; padding: 48px 56px; text-align: center;
    box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  }
  h1 { font-size: 2rem; margin-bottom: 12px; }
  p  { font-size: 1.05rem; opacity: 0.9; margin-bottom: 24px; }
  a  {
    display: inline-block; padding: 10px 28px; border-radius: 8px;
    background: rgba(255,255,255,0.2); color: #fff; text-decoration: none;
    transition: background 0.2s;
  }
  a:hover { background: rgba(255,255,255,0.35); }
  .links { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; }
</style>
</head>
<body>
  <div class="card">
    <h1>🎵 NetEase Cloud Music API</h1>
    <p>服务已成功运行！</p>
    <div class="links">
      <a href="/">🔐 网页登录</a>
      <a href="/docs">📖 API 文档 (Swagger)</a>
      <a href="/redoc">📚 API 文档 (ReDoc)</a>
      <a href="/admin/login">⚙️ 管理后台</a>
    </div>
  </div>
</body>
</html>
"""


@app.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
async def welcome():
    return WELCOME_HTML


# ── Global exception handler ─────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": str(exc)},
    )

