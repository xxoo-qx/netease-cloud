"""路由依赖：按路径 user_id 加载本地用户，并可选校验网易云会话有效性。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path

from app.client import weapi_request

from app.user_store import UserRecord, load_user


def get_user_record(
    user_id: str = Path(..., min_length=16, max_length=64, description="本地用户 ID（登录接口返回的 user_id）"),
) -> UserRecord:
    u = load_user(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not (u.music_u or "").strip():
        raise HTTPException(status_code=400, detail="该用户未绑定有效登录态")
    return u


UserRecordDep = Annotated[UserRecord, Depends(get_user_record)]


async def get_active_user_record(
    user: UserRecordDep,
) -> UserRecord:
    result = await weapi_request(
        user,
        "https://music.163.com/weapi/w/nuser/account/get",
        {"csrf_token": user.csrf},
        extract_cookies=True,
    )
    if result.get("code") != 200 or not (result.get("account") or result.get("profile")):
        message = str(result.get("message") or result.get("msg") or "账号会话已失效，请重新登录").strip()
        raise HTTPException(status_code=401, detail=message or "账号会话已失效，请重新登录")
    return user


ActiveUserRecordDep = Annotated[UserRecord, Depends(get_active_user_record)]
