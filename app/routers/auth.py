from fastapi import APIRouter, HTTPException

from app.models.schemas import (
    BrowserQrcodeCreateRequest,
    BrowserQrcodePollRequest,
)
from app.services.browser_qrcode_login import browser_qrcode_create, browser_qrcode_status

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/login/browser-qrcode/create")
async def login_browser_qrcode_create(req: BrowserQrcodeCreateRequest):
    """打开受控浏览器窗口，用户扫码后导出完整 music.163.com cookie jar。"""
    try:
        return await browser_qrcode_create(req.account_role)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:500]) from e


@router.post("/login/browser-qrcode/poll")
async def login_browser_qrcode_poll(req: BrowserQrcodePollRequest):
    """轮询受控浏览器扫码状态；成功后返回完整 cookie jar 和本地 user_id。"""
    try:
        return await browser_qrcode_status(req.session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:500]) from e
