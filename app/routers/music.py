import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.client import weapi_request
from app.deps import ActiveUserRecordDep, UserRecordDep
from app.models.schemas import PlayidsRequest
from app.services.playlist_resolver import resolve_multiple_playlist_track_ids
from app.services.playids_ncmm import PlayidsOptions, run_playids_via_ncmm
from app.user_store import UserRecord

router = APIRouter(prefix="/api/users/{user_id}", tags=["music"])
logger = logging.getLogger(__name__)


def _is_secondary_account(user: UserRecord) -> bool:
    return (user.account_role or "main").strip().lower() == "secondary"


async def _get_current_uid(u: UserRecord) -> int | None:
    result = await weapi_request(
        u,
        "https://music.163.com/weapi/w/nuser/account/get",
        {"csrf_token": u.csrf},
    )
    account = result.get("account") or {}
    uid = account.get("id")
    if uid is None:
        profile = result.get("profile") or {}
        uid = profile.get("userId")
    try:
        return int(uid) if uid is not None else None
    except (TypeError, ValueError):
        return None
@router.post("/sign-test")
async def sign_test(u: ActiveUserRecordDep):
    """模拟网页签到请求并返回幂等状态。"""
    csrf = (u.csrf or "").strip()
    sign_url = (
        f"https://music.163.com/weapi/point/dailyTask?csrf_token={csrf}"
        if csrf
        else "https://music.163.com/weapi/point/dailyTask"
    )
    tried_types: list[int] = []

    async def _call_sign(dtype: int) -> dict:
        tried_types.append(dtype)
        return await weapi_request(
            u,
            sign_url,
            {"type": dtype, "csrf_token": csrf},
        )

    resp = await _call_sign(0)
    msg0 = str(resp.get("message") or resp.get("msg") or "")
    if "功能暂不支持" in msg0:
        resp = await _call_sign(1)

    code = resp.get("code", -1)
    point = int(resp.get("point", 0) or 0)
    message = str(resp.get("message") or resp.get("msg") or "")
    lower_msg = message.lower()

    if "功能暂不支持" in message:
        status = "unsupported"
    elif (
        "already" in lower_msg
        or "repeat" in lower_msg
        or "重复" in message
        or "已签到" in message
    ):
        status = "already_signed"
    elif code == 200 and point > 0:
        status = "signed_today"
    elif code == 200 and point == 0:
        status = "already_signed"
    else:
        status = "failed"

    return {
        "code": code,
        "status": status,
        "tried_types": tried_types,
        "point": point,
        "message": message or None,
        "raw": resp,
    }


@router.get("/play-record")
async def play_record(
    u: ActiveUserRecordDep,
    uid: Optional[int] = Query(None, description="用户 ID；不传则自动使用当前登录账号"),
    record_type: int = Query(1, ge=0, le=1, description="0=全部时间, 1=最近一周"),
):
    """查询听歌记录。"""
    real_uid = uid if uid is not None else await _get_current_uid(u)
    if real_uid is None:
        raise HTTPException(status_code=400, detail="Unable to determine uid; please pass uid explicitly")

    csrf = (u.csrf or "").strip()
    result = await weapi_request(
        u,
        f"https://music.163.com/weapi/v1/play/record?csrf_token={csrf}",
        {"uid": real_uid, "type": record_type, "csrf_token": csrf},
    )
    return {
        "code": result.get("code", -1),
        "uid": real_uid,
        "record_type": record_type,
        "all_data_count": len(result.get("allData", []) or []),
        "week_data_count": len(result.get("weekData", []) or []),
        "raw": result,
    }


@router.post("/playids")
async def playids(u: ActiveUserRecordDep, req: PlayidsRequest):
    try:
        if _is_secondary_account(u):
            raise RuntimeError("辅助账号池不支持直接刷歌，请在主账号工作台发起刷歌")
        resolved_ids = list(req.ids or [])
        playlist_summaries: list[dict[str, object]] = []
        requested_playlist_ids = list(req.playlist_ids or [])
        if req.playlist_id and req.playlist_id not in requested_playlist_ids:
            requested_playlist_ids.insert(0, req.playlist_id)
        if not resolved_ids and not req.ids_file and requested_playlist_ids:
            resolved_ids, playlist_summaries = await resolve_multiple_playlist_track_ids(u, requested_playlist_ids)
        if not resolved_ids and not req.ids_file:
            raise RuntimeError("当前 playids 仅支持显式歌曲池，请传 ids 或 ids_file")
        opts = PlayidsOptions(
            count=req.count,
            ids=resolved_ids,
            ids_file=req.ids_file,
            playlist_id=requested_playlist_ids[0] if requested_playlist_ids else req.playlist_id,
            track_pool=req.track_pool,
            rotate_playlists=req.rotate_playlists,
            daily_min=req.daily_min,
            daily_max=req.daily_max,
            run_min=req.run_min,
            run_max=req.run_max,
            gap_min=req.gap_min,
            gap_max=req.gap_max,
            mix_enabled=req.mix_enabled,
            mix_ratio=req.mix_ratio,
            count_target_for_mix=req.count_target_for_mix,
            source=req.source,
            source_id=req.source_id,
            content=req.content,
            content_empty=req.content_empty,
            end=req.end,
            print_weblog_response=req.print_weblog_response,
        )
        result = await run_playids_via_ncmm(u, opts)
        if requested_playlist_ids:
            result["source_playlist_id"] = requested_playlist_ids[0]
            result["source_playlist_ids"] = requested_playlist_ids
            result["resolved_song_count"] = len(resolved_ids)
            if playlist_summaries:
                first_name = str(playlist_summaries[0].get("playlist_name") or "").strip()
                if first_name:
                    result["source_playlist_name"] = first_name
                result["source_playlists"] = playlist_summaries
            if result.get("mode") == "explicit_ids":
                result["mode"] = "playlist"
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


