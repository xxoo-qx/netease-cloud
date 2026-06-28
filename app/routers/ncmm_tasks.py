from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import ActiveUserRecordDep
from app.models.schemas import NcmmDirectCommandRequest, NcmmMusicianRequest, NcmmTaskRequest
from app.services.playlist_resolver import resolve_multiple_playlist_track_ids
from app.services.ncmm_task_bridge import (
    BridgePlayPoolOptions,
    NcmmMusicianBridgeOptions,
    NcmmTaskOptions,
    run_ncmm_direct_command_for_user,
    run_ncmm_musician_for_user,
    run_ncmm_task_for_user,
)
from app.user_store import UserRecord, list_bound_secondary_users

router = APIRouter(prefix="/api/users/{user_id}/ncmm", tags=["ncmm"])


def _http_error_detail(exc: RuntimeError, fallback: str) -> str:
    detail = str(exc).strip()
    return detail or fallback


def _is_main_account(user: UserRecord) -> bool:
    return (user.account_role or "main").strip().lower() != "secondary"


def _task_target_summary(user: UserRecord) -> dict[str, object]:
    return {
        "user_id": user.user_id,
        "nickname": (user.nickname or "").strip(),
        "netease_user_id": (user.netease_user_id or "").strip(),
        "account_role": (user.account_role or "main").strip() or "main",
    }


def _build_play_pool_options(payload) -> BridgePlayPoolOptions | None:
    if payload is None:
        return None
    return BridgePlayPoolOptions(
        ids=list(payload.ids or []),
        ids_file=payload.ids_file,
        daily_min=payload.daily_min,
        daily_max=payload.daily_max,
        run_min=payload.run_min,
        run_max=payload.run_max,
        gap_min=payload.gap_min,
        gap_max=payload.gap_max,
        mix_enabled=payload.mix_enabled,
        mix_ratio=payload.mix_ratio,
        count_target_for_mix=payload.count_target_for_mix,
    )


def _playlist_resolution_meta(payload, playlist_summaries: list[dict[str, object]] | None) -> dict[str, object]:
    summaries = list(playlist_summaries or [])
    if payload is None or not summaries:
        return {}
    requested_playlist_ids = list(payload.playlist_ids or [])
    if payload.playlist_id and payload.playlist_id not in requested_playlist_ids:
        requested_playlist_ids.insert(0, payload.playlist_id)
    resolved_song_count = 0
    if payload.ids:
        resolved_song_count = len(list(payload.ids or []))
    else:
        seen_track_ids: set[int] = set()
        for summary in summaries:
            track_ids = summary.get("track_ids")
            if not isinstance(track_ids, list):
                continue
            for raw_track_id in track_ids:
                try:
                    track_id = int(raw_track_id)
                except (TypeError, ValueError):
                    continue
                if track_id > 0:
                    seen_track_ids.add(track_id)
        resolved_song_count = len(seen_track_ids)

    clean_summaries: list[dict[str, object]] = []
    for summary in summaries:
        clean_summaries.append(
            {
                "playlist_id": summary.get("playlist_id"),
                "playlist_name": summary.get("playlist_name"),
                "song_count": summary.get("song_count"),
            }
        )

    meta: dict[str, object] = {
        "source_playlist_ids": requested_playlist_ids,
        "source_playlists": clean_summaries,
        "resolved_song_count": resolved_song_count,
        "mode": "playlist",
    }
    if requested_playlist_ids:
        meta["source_playlist_id"] = requested_playlist_ids[0]
    if clean_summaries:
        first_name = str(clean_summaries[0].get("playlist_name") or "").strip()
        if first_name:
            meta["source_playlist_name"] = first_name
    return meta


async def _resolve_play_pool_options(user: UserRecord, payload) -> BridgePlayPoolOptions | None:
    if payload is None:
        return None
    requested_playlist_ids = list(payload.playlist_ids or [])
    if payload.playlist_id and payload.playlist_id not in requested_playlist_ids:
        requested_playlist_ids.insert(0, payload.playlist_id)
    resolved_ids = list(payload.ids or [])
    if not resolved_ids and not payload.ids_file and requested_playlist_ids:
        resolved_ids, _ = await resolve_multiple_playlist_track_ids(user, requested_playlist_ids)
    return BridgePlayPoolOptions(
        ids=resolved_ids,
        ids_file=payload.ids_file,
        daily_min=payload.daily_min,
        daily_max=payload.daily_max,
        run_min=payload.run_min,
        run_max=payload.run_max,
        gap_min=payload.gap_min,
        gap_max=payload.gap_max,
        mix_enabled=payload.mix_enabled,
        mix_ratio=payload.mix_ratio,
        count_target_for_mix=payload.count_target_for_mix,
    )


def _should_fan_out_musician_secondaries(
    mode: str,
    options: NcmmMusicianBridgeOptions | None,
) -> bool:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode not in {"musician", "musician-vip"}:
        return False
    if options is None or not options.enable_vip_play:
        return False
    return options.play_pool is not None


async def _run_ncmm_task_with_bound_secondaries(
    user: UserRecord,
    options: NcmmTaskOptions,
    *,
    play_pool: BridgePlayPoolOptions | None = None,
) -> dict[str, object]:
    primary_result = await run_ncmm_task_for_user(user, options, play_pool=play_pool)
    primary_result["execution_scope"] = "single"
    primary_result["primary_user"] = _task_target_summary(user)
    primary_result["secondary_results"] = []
    primary_result["secondary_count"] = 0
    return primary_result


async def _run_ncmm_musician_with_bound_secondaries(
    user: UserRecord,
    mode: str,
    *,
    options: NcmmMusicianBridgeOptions | None = None,
) -> dict[str, object]:
    should_fan_out = _is_main_account(user) and _should_fan_out_musician_secondaries(mode, options)
    primary_mode = mode
    primary_options = options
    if should_fan_out:
        if mode == "musician":
            primary_options = NcmmMusicianBridgeOptions(
                play_pool=None,
                enable_vip_note=options.enable_vip_note if options else False,
                enable_vip_play=False,
            )
        elif mode == "musician-vip":
            primary_options = NcmmMusicianBridgeOptions(
                play_pool=None,
                enable_vip_note=options.enable_vip_note if options else False,
                enable_vip_play=False,
            )

    primary_result = await run_ncmm_musician_for_user(user, primary_mode, primary_options)
    secondary_targets = list_bound_secondary_users(user.user_id) if should_fan_out else []
    if not secondary_targets:
        primary_result["execution_scope"] = "single"
        primary_result["primary_user"] = _task_target_summary(user)
        primary_result["secondary_results"] = []
        primary_result["secondary_count"] = 0
        primary_result["play_execution_scope"] = "primary_only"
        return primary_result

    secondary_results: list[dict[str, object]] = []
    for secondary in secondary_targets:
        try:
            result = await run_ncmm_musician_for_user(secondary, mode, options)
            secondary_results.append(
                {
                    "target": _task_target_summary(secondary),
                    "ok": True,
                    "result": result,
                }
            )
        except RuntimeError as exc:
            secondary_results.append(
                {
                    "target": _task_target_summary(secondary),
                    "ok": False,
                    "error": _http_error_detail(exc, f"辅助账号 ncmm {mode} 执行失败"),
                }
            )

    primary_result["execution_scope"] = "main_with_bound_secondaries"
    primary_result["primary_user"] = _task_target_summary(user)
    primary_result["secondary_results"] = secondary_results
    primary_result["secondary_count"] = len(secondary_results)
    primary_result["secondary_failed_count"] = sum(1 for item in secondary_results if not item.get("ok"))
    primary_result["play_execution_scope"] = "bound_secondaries_only"
    return primary_result


async def _run_ncmm_direct_command_with_bound_secondaries(
    user: UserRecord,
    subcommand: str,
) -> dict[str, object]:
    primary_result = await run_ncmm_direct_command_for_user(user, subcommand)
    primary_result["execution_scope"] = "single"
    primary_result["primary_user"] = _task_target_summary(user)
    primary_result["secondary_results"] = []
    primary_result["secondary_count"] = 0
    return primary_result


@router.post("/task")
async def run_ncmm_task(u: ActiveUserRecordDep, req: NcmmTaskRequest):
    options = NcmmTaskOptions(
        sign=req.sign,
        playids=req.playids,
        musician_sign=req.musician_sign,
        musician_vip=req.musician_vip,
        note=req.note,
        fansgroup=req.fansgroup,
    )
    if not any(
        (
            options.sign,
            options.playids,
            options.musician_sign,
            options.musician_vip,
            options.note,
            options.fansgroup,
        )
    ):
        raise HTTPException(status_code=400, detail="至少选择一个 ncmm task 子任务")
    play_pool = await _resolve_play_pool_options(u, req.playids_options)
    if options.playids and play_pool is None:
        raise HTTPException(status_code=400, detail="勾选 playids 时需要提供显式歌曲池参数")
    try:
        return await _run_ncmm_task_with_bound_secondaries(u, options, play_pool=play_pool)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=_http_error_detail(exc, "ncmm task 执行失败，请查看服务日志"),
        ) from exc


@router.post("/command")
async def run_ncmm_direct_command(u: ActiveUserRecordDep, req: NcmmDirectCommandRequest):
    subcommand = (req.command or "").strip().lower()
    allowed = {"sign", "note", "fansgroup"}
    if subcommand not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的 ncmm 子命令: {subcommand}")
    try:
        return await _run_ncmm_direct_command_with_bound_secondaries(u, subcommand)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=_http_error_detail(exc, f"ncmm {subcommand} 执行失败，请查看服务日志"),
        ) from exc


@router.post("/musician")
async def run_ncmm_musician(u: ActiveUserRecordDep, req: NcmmMusicianRequest):
    mode = (req.mode or "musician").strip().lower()
    allowed = {"musician", "musician-sign", "musician-vip"}
    if mode not in allowed:
        raise HTTPException(status_code=400, detail=f"不支持的 musician 模式: {mode}")
    playlist_summaries: list[dict[str, object]] = []
    requested_playlist_ids = list(req.playids_options.playlist_ids or []) if req.playids_options else []
    if req.playids_options and req.playids_options.playlist_id and req.playids_options.playlist_id not in requested_playlist_ids:
        requested_playlist_ids.insert(0, req.playids_options.playlist_id)
    if req.playids_options and not req.playids_options.ids and not req.playids_options.ids_file and requested_playlist_ids:
        resolved_ids, playlist_summaries = await resolve_multiple_playlist_track_ids(u, requested_playlist_ids)
        req.playids_options.ids = resolved_ids
    play_pool = await _resolve_play_pool_options(u, req.playids_options)
    musician_options = NcmmMusicianBridgeOptions(
        play_pool=play_pool,
        enable_vip_note=req.enable_vip_note,
        enable_vip_play=req.enable_vip_play,
    )
    if mode in {"musician", "musician-vip"} and req.enable_vip_play and play_pool is None:
        raise HTTPException(status_code=400, detail="启用音乐人 VIP 播放时需要提供主歌池参数")
    try:
        result = await _run_ncmm_musician_with_bound_secondaries(u, mode, options=musician_options)
        result.update(_playlist_resolution_meta(req.playids_options, playlist_summaries))
        return result
    except RuntimeError as exc:
        raise HTTPException(
            status_code=400,
            detail=_http_error_detail(exc, f"ncmm {mode} 执行失败，请查看服务日志"),
        ) from exc