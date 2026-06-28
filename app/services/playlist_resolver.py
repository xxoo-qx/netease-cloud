from __future__ import annotations

from app.client import weapi_request
from app.user_store import UserRecord


def _extract_track_ids(items: object) -> list[int]:
    if not isinstance(items, list):
        return []
    seen: set[int] = set()
    out: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_value = item.get("id")
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def merge_track_ids(*track_groups: list[int]) -> list[int]:
    seen: set[int] = set()
    merged: list[int] = []
    for group in track_groups:
        for track_id in group:
            if track_id <= 0 or track_id in seen:
                continue
            seen.add(track_id)
            merged.append(track_id)
    return merged


async def resolve_playlist_track_ids(u: UserRecord, playlist_id: int) -> tuple[list[int], str | None]:
    csrf = (u.csrf or "").strip()
    result = await weapi_request(
        u,
        "https://music.163.com/weapi/v6/playlist/detail",
        {
            "id": playlist_id,
            "n": 1000,
            "s": 0,
            "csrf_token": csrf,
        },
    )
    code = int(result.get("code", -1) or -1)
    if code != 200:
        message = str(result.get("message") or result.get("msg") or "获取歌单详情失败").strip()
        raise RuntimeError(message or "获取歌单详情失败")

    playlist = result.get("playlist") or {}
    if not isinstance(playlist, dict):
        raise RuntimeError("歌单详情返回异常")

    track_ids = _extract_track_ids(playlist.get("trackIds"))
    if not track_ids:
        track_ids = _extract_track_ids(playlist.get("tracks"))
    if not track_ids:
        raise RuntimeError("歌单中未解析到可用歌曲 ID")

    playlist_name = str(playlist.get("name") or "").strip() or None
    return track_ids, playlist_name


async def resolve_multiple_playlist_track_ids(
    u: UserRecord,
    playlist_ids: list[int],
) -> tuple[list[int], list[dict[str, object]]]:
    normalized_ids: list[int] = []
    seen_playlist_ids: set[int] = set()
    for raw_playlist_id in playlist_ids:
        try:
            playlist_id = int(raw_playlist_id)
        except (TypeError, ValueError):
            continue
        if playlist_id <= 0 or playlist_id in seen_playlist_ids:
            continue
        seen_playlist_ids.add(playlist_id)
        normalized_ids.append(playlist_id)

    if not normalized_ids:
        raise RuntimeError("请至少提供一个有效的歌单 ID")

    merged_track_ids: list[int] = []
    playlist_summaries: list[dict[str, object]] = []
    for playlist_id in normalized_ids:
        track_ids, playlist_name = await resolve_playlist_track_ids(u, playlist_id)
        merged_track_ids = merge_track_ids(merged_track_ids, track_ids)
        playlist_summaries.append(
            {
                "playlist_id": playlist_id,
                "playlist_name": playlist_name,
                "song_count": len(track_ids),
            }
        )

    if not merged_track_ids:
        raise RuntimeError("歌单中未解析到可用歌曲 ID")

    return merged_track_ids, playlist_summaries
