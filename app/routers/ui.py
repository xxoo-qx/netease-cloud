"""网页：网易云登录（短信 / 扫码）与管理员后台。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import ADMIN_PASSWORD, ADMIN_USERNAME
from app.user_store import delete_user, list_users_public, update_bound_main_user, update_remark

router = APIRouter(tags=["ui"])
_templates_dir = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


class AdminLoginBody(BaseModel):
    username: str
    password: str


class RemarkBody(BaseModel):
    remark: str = ""


class BindMainBody(BaseModel):
    main_user_id: str = ""


def _require_admin_session(request: Request) -> None:
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=401, detail="需要管理员登录")


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.get("/admin/login", response_class=HTMLResponse, include_in_schema=False)
async def admin_login_page(request: Request):
    if request.session.get("admin_logged_in"):
        return RedirectResponse(url="/admin", status_code=302)
    return templates.TemplateResponse(request, "admin_login.html")


@router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_dashboard_page(request: Request):
    if not request.session.get("admin_logged_in"):
        return RedirectResponse(url="/admin/login", status_code=302)
    return templates.TemplateResponse(request, "admin_dashboard.html")


@router.post("/admin/api/login", include_in_schema=False)
async def admin_api_login(request: Request, body: AdminLoginBody):
    if body.username == ADMIN_USERNAME and body.password == ADMIN_PASSWORD:
        request.session["admin_logged_in"] = True
        return {"success": True, "message": "登录成功"}
    raise HTTPException(status_code=401, detail="用户名或密码错误")


@router.post("/admin/api/logout", include_in_schema=False)
async def admin_api_logout(request: Request):
    request.session.pop("admin_logged_in", None)
    return {"success": True, "message": "已退出"}


@router.get("/admin/api/users", include_in_schema=False)
async def admin_list_users(request: Request):
    _require_admin_session(request)
    return {"users": list_users_public()}


@router.delete("/admin/api/users/{user_id}", include_in_schema=False)
async def admin_delete_user(request: Request, user_id: str):
    _require_admin_session(request)
    if not delete_user(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "message": "已删除"}


@router.patch("/admin/api/users/{user_id}/remark", include_in_schema=False)
async def admin_update_remark(request: Request, user_id: str, body: RemarkBody):
    _require_admin_session(request)
    if not update_remark(user_id, body.remark):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"success": True, "message": "备注已更新"}


@router.patch("/admin/api/users/{user_id}/bind-main", include_in_schema=False)
async def admin_bind_main_user(request: Request, user_id: str, body: BindMainBody):
    _require_admin_session(request)
    ok, message = update_bound_main_user(user_id, body.main_user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}
