from fastapi import APIRouter, HTTPException

from app.client import weapi_request
from app.deps import UserRecordDep
from app.user_store import sync_profile_from_account_payload

router = APIRouter(prefix="/api/users/{user_id}", tags=["user"])


def _level_summary(data: dict) -> dict:
    now_play = data.get("nowPlayCount")
    next_play = data.get("nextPlayCount")
    now_login = data.get("nowLoginCount")
    next_login = data.get("nextLoginCount")
    summary: dict = {
        "userId": data.get("userId"),
        "level": data.get("level"),
        "progress": data.get("progress"),
        "info": data.get("info"),
    }
    if isinstance(now_play, (int, float)) and isinstance(next_play, (int, float)):
        summary["plays_current"] = int(now_play)
        summary["plays_target_for_next_level"] = int(next_play)
        summary["plays_remaining_estimate"] = max(int(next_play) - int(now_play), 0)
    if isinstance(now_login, (int, float)) and isinstance(next_login, (int, float)):
        summary["login_days_current"] = int(now_login)
        summary["login_days_target_for_next_level"] = int(next_login)
        summary["login_days_remaining_estimate"] = max(int(next_login) - int(now_login), 0)
    return summary


@router.get("/check")
async def check_login(u: UserRecordDep):
    """检查该本地用户绑定的网易云会话是否有效。"""
    result = await weapi_request(
        u,
        "https://music.163.com/weapi/w/nuser/account/get",
        {"csrf_token": u.csrf},
        extract_cookies=True,
    )
    ok = bool(result.get("account")) or bool(result.get("profile"))
    msg = result.get("message") or result.get("msg")
    if result.get("code") == 200 and ok:
        sync_profile_from_account_payload(u.user_id, result)
    return {
        "user_id": u.user_id,
        "code": 200 if (result.get("code") == 200 and ok) else result.get("code", -1),
        "message": msg,
        "full_response": result if not (result.get("code") == 200 and ok) else None,
    }


@router.get("/level")
async def user_level(u: UserRecordDep):
    """当前绑定账号的音乐等级与听歌量。"""
    csrf = (u.csrf or "").strip()
    url = (
        f"https://music.163.com/weapi/user/level?csrf_token={csrf}"
        if csrf
        else "https://music.163.com/weapi/user/level"
    )
    result = await weapi_request(
        u,
        url,
        {"csrf_token": csrf},
    )
    data = result.get("data")
    if result.get("code") == 200 and isinstance(data, dict):
        return {**result, "summary": _level_summary(data)}
    return result


@router.get("/detail/{uid}")
async def user_detail(u: UserRecordDep, uid: int):
    """查询用户详情（公开资料）。"""
    result = await weapi_request(
        u,
        f"https://music.163.com/weapi/v1/user/detail/{uid}",
        {"csrf_token": u.csrf},
        extract_cookies=True,
    )
    return result
