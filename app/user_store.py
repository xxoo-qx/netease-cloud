"""多用户网易云会话：每个用户一个 JSON 文件，按 MUSIC_U 去重合并。"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import NCMM_HOME_DIR, USER_DATA_DIR

_file_locks: dict[str, threading.Lock] = {}
_file_locks_guard = threading.Lock()


def _path_for(user_id: str) -> Path:
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
    if not safe or safe != user_id:
        raise ValueError("invalid user_id")
    return USER_DATA_DIR / f"{safe}.json"


def _get_file_lock(path: str) -> threading.Lock:
    with _file_locks_guard:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def ensure_user_data_dir() -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)


def ncmm_workspace_dir_for_user_id(user_id: str) -> Path:
    safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
    if not safe or safe != user_id:
        raise ValueError("invalid user_id")
    path = NCMM_HOME_DIR / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class UserRecord:
    user_id: str
    music_u: str
    account_role: str = "main"
    bound_main_user_id: str = ""
    csrf: str = ""
    cookies: dict[str, str] | None = None
    nickname: str = ""
    remark: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_login: str = ""
    netease_user_id: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserRecord:
        raw_cookies = d.get("cookies")
        cookies: dict[str, str] = {}
        if isinstance(raw_cookies, dict):
            for key, value in raw_cookies.items():
                name = str(key or "").strip()
                if not name:
                    continue
                text = str(value or "").strip()
                if text:
                    cookies[name] = text
        return cls(
            user_id=str(d.get("user_id", "")),
            music_u=str(d.get("music_u", "")),
            account_role=str(d.get("account_role", "main") or "main"),
            bound_main_user_id=str(d.get("bound_main_user_id", "") or ""),
            csrf=str(d.get("csrf", "") or ""),
            cookies=cookies or None,
            nickname=str(d.get("nickname", "") or ""),
            remark=str(d.get("remark", "") or ""),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
            last_login=str(d.get("last_login", "") or ""),
            netease_user_id=str(d.get("netease_user_id", "") or ""),
        )


def _normalize_cookie_jar(cookies: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(cookies, dict):
        return normalized
    for key, value in cookies.items():
        name = str(key or "").strip()
        if not name:
            continue
        text = str(value or "").strip()
        if text:
            normalized[name] = text
    return normalized


def load_user(user_id: str) -> UserRecord | None:
    path = _path_for(user_id)
    if not path.is_file():
        return None
    lk = _get_file_lock(str(path))
    with lk:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            return UserRecord.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None


def save_user(rec: UserRecord) -> None:
    ensure_user_data_dir()
    path = _path_for(rec.user_id)
    lk = _get_file_lock(str(path))
    with lk:
        path.write_text(
            json.dumps(asdict(rec), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def find_user_by_music_u(music_u: str) -> UserRecord | None:
    mu = music_u.strip()
    if not mu:
        return None
    ensure_user_data_dir()
    try:
        for p in USER_DATA_DIR.glob("*.json"):
            u = load_user(p.stem)
            if u and u.music_u.strip() == mu:
                return u
    except OSError:
        return None
    return None


def find_user_by_netease_user_id(netease_user_id: str) -> UserRecord | None:
    nuid = netease_user_id.strip()
    if not nuid:
        return None
    ensure_user_data_dir()
    try:
        for p in USER_DATA_DIR.glob("*.json"):
            u = load_user(p.stem)
            if u and u.netease_user_id.strip() == nuid:
                return u
    except OSError:
        return None
    return None


def _merge_user_records(target: UserRecord, source: UserRecord, *, nickname: str = "", netease_user_id: str = "") -> UserRecord:
    merged_cookies = dict(target.cookies or {})
    merged_cookies.update(source.cookies or {})
    nick = (nickname or source.nickname or target.nickname or "").strip()
    nuid = (netease_user_id or source.netease_user_id or target.netease_user_id or "").strip()
    csrf = (source.csrf or target.csrf or "").strip()
    music_u = (source.music_u or target.music_u or "").strip()
    account_role = (target.account_role or source.account_role or "main").strip().lower() or "main"
    bound_main_user_id = (target.bound_main_user_id or source.bound_main_user_id or "").strip()

    target.music_u = music_u
    target.account_role = account_role
    target.bound_main_user_id = bound_main_user_id if account_role == "secondary" else ""
    target.csrf = csrf
    target.cookies = merged_cookies or None
    target.nickname = nick
    if not target.remark and source.remark:
        target.remark = source.remark.strip()
    target.netease_user_id = nuid
    target.last_login = source.last_login or target.last_login
    target.updated_at = source.updated_at or target.updated_at
    return target


def upsert_user_from_login(
    music_u: str,
    csrf: str | None,
    *,
    account_role: str = "main",
    cookies: dict[str, Any] | None = None,
    nickname: str = "",
    netease_user_id: str = "",
) -> str:
    """登录成功后写入或更新用户；相同 MUSIC_U 合并为同一 user_id。"""
    music_u = music_u.strip()
    if not music_u:
        raise ValueError("缺少 MUSIC_U")
    csrf_s = (csrf or "").strip()
    normalized_cookies = _normalize_cookie_jar(cookies)
    role = account_role.strip().lower() or "main"
    if role not in {"main", "secondary"}:
        role = "main"
    if music_u:
        normalized_cookies.setdefault("MUSIC_U", music_u)
    if csrf_s:
        normalized_cookies.setdefault("__csrf", csrf_s)
    nick = (nickname or "").strip()
    nuid = (netease_user_id or "").strip()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    existing = find_user_by_music_u(music_u)
    if not existing and nuid:
        existing = find_user_by_netease_user_id(nuid)
    if existing:
        existing.music_u = music_u
        existing.account_role = role
        if role == "main":
            existing.bound_main_user_id = ""
        existing.csrf = csrf_s
        merged = dict(existing.cookies or {})
        merged.update(normalized_cookies)
        existing.cookies = merged or None
        if nick:
            existing.nickname = nick
        if nuid:
            existing.netease_user_id = nuid
        existing.updated_at = now
        existing.last_login = now
        save_user(existing)
        return existing.user_id

    uid = uuid.uuid4().hex
    rec = UserRecord(
        user_id=uid,
        music_u=music_u,
        account_role=role,
        bound_main_user_id="",
        csrf=csrf_s,
        cookies=normalized_cookies or None,
        nickname=nick,
        remark="",
        created_at=now,
        updated_at=now,
        last_login=now,
        netease_user_id=nuid,
    )
    save_user(rec)
    return uid


def delete_user(user_id: str) -> bool:
    path = _path_for(user_id)
    if not path.is_file():
        return False
    lk = _get_file_lock(str(path))
    with lk:
        try:
            path.unlink()
            return True
        except OSError:
            return False


def _uid_from_profile_block(block: dict[str, Any]) -> str:
    for k in ("userId", "user_id", "id"):
        if k not in block:
            continue
        v = block.get(k)
        if v is not None:
            s = str(v).strip()
            if s:
                return s
    return ""


def sync_profile_from_account_payload(user_id: str, api_body: dict[str, Any]) -> str:
    """会话有效时，把 account/get 等返回里的昵称、网易云 UID 写回本地 JSON。"""
    nick = ""
    nuid = ""
    for key in ("profile", "account"):
        block = api_body.get(key)
        if isinstance(block, dict):
            if not nick:
                n = (block.get("nickname") or "").strip()
                if n:
                    nick = n
            if not nuid:
                u = _uid_from_profile_block(block)
                if u:
                    nuid = u
    u = load_user(user_id)
    if not u:
        return user_id
    if nuid:
        existing = find_user_by_netease_user_id(nuid)
        if existing and existing.user_id != user_id:
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            merged = _merge_user_records(existing, u, nickname=nick, netease_user_id=nuid)
            merged.updated_at = now
            merged.last_login = now
            save_user(merged)
            delete_user(user_id)
            return existing.user_id
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    changed = False
    if nick and u.nickname != nick:
        u.nickname = nick
        changed = True
    if nuid and u.netease_user_id != nuid:
        u.netease_user_id = nuid
        changed = True
    if changed:
        u.updated_at = now
        save_user(u)
    return user_id


def update_remark(user_id: str, remark: str) -> bool:
    u = load_user(user_id)
    if not u:
        return False
    u.remark = remark.strip()[:500]
    u.updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_user(u)
    return True


def update_bound_main_user(user_id: str, bound_main_user_id: str) -> tuple[bool, str]:
    user = load_user(user_id)
    if not user:
        return False, "用户不存在"

    role = (user.account_role or "main").strip().lower()
    if role != "secondary":
        return False, "只有辅助账号可以绑定主账号"

    main_user_id = (bound_main_user_id or "").strip()
    if not main_user_id:
        user.bound_main_user_id = ""
        user.updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save_user(user)
        return True, "绑定已清除"

    if main_user_id == user.user_id:
        return False, "辅助账号不能绑定自己"

    main_user = load_user(main_user_id)
    if not main_user:
        return False, "目标主账号不存在"

    main_role = (main_user.account_role or "main").strip().lower()
    if main_role != "main":
        return False, "只能绑定到主账号"

    user.bound_main_user_id = main_user_id
    user.updated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    save_user(user)
    return True, "绑定已更新"


def list_bound_secondary_users(main_user_id: str) -> list[UserRecord]:
    target_id = (main_user_id or "").strip()
    if not target_id:
        return []

    ensure_user_data_dir()
    rows: list[UserRecord] = []
    try:
        for path in USER_DATA_DIR.glob("*.json"):
            user = load_user(path.stem)
            if not user:
                continue
            role = (user.account_role or "main").strip().lower()
            if role != "secondary":
                continue
            if (user.bound_main_user_id or "").strip() != target_id:
                continue
            rows.append(user)
    except OSError:
        return []
    return rows


def list_users_public() -> list[dict[str, Any]]:
    """列表摘要（不含完整 MUSIC_U）。

    `last_login` 在旧 JSON 中可能缺失；列表展示时回退到 `created_at`
    （该时间通常即首次登录写入本地的时间）。
    """
    ensure_user_data_dir()
    rows: list[dict[str, Any]] = []
    try:
        paths = sorted(USER_DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return rows
    loaded_users: list[UserRecord] = []
    for p in paths:
        u = load_user(p.stem)
        if not u:
            continue
        loaded_users.append(u)

    users_by_id = {u.user_id: u for u in loaded_users}
    bound_counts: dict[str, int] = {}
    for u in loaded_users:
        role = (u.account_role or "main").strip().lower()
        if role != "secondary":
            continue
        bound_main_user_id = (u.bound_main_user_id or "").strip()
        if bound_main_user_id:
            bound_counts[bound_main_user_id] = bound_counts.get(bound_main_user_id, 0) + 1

    for u in loaded_users:
        ll = (u.last_login or "").strip()
        if not ll:
            ll = (u.created_at or "").strip()
        bound_main_user_id = (u.bound_main_user_id or "").strip()
        bound_main = users_by_id.get(bound_main_user_id) if bound_main_user_id else None
        rows.append(
            {
                "user_id": u.user_id,
                "account_role": (u.account_role or "main").strip() or "main",
                "bound_main_user_id": bound_main_user_id,
                "bound_main_nickname": (bound_main.nickname if bound_main else "").strip(),
                "bound_secondary_count": bound_counts.get(u.user_id, 0),
                "nickname": u.nickname,
                "remark": u.remark,
                "created_at": u.created_at,
                "updated_at": u.updated_at,
                "last_login": ll,
                "netease_user_id": (u.netease_user_id or "").strip(),
            },
        )
    return rows
