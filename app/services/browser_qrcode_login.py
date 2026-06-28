from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import NCMM_BIN, NCMM_HOME_DIR, NCMM_PROJECT_DIR, USER_DATA_DIR
from app.client import weapi_request
from app.user_store import load_user, ncmm_workspace_dir_for_user_id, sync_profile_from_account_payload, upsert_user_from_login

_SESSION_TTL_SEC = 900.0
_LOGIN_URL = "https://music.163.com/#/login"
_LOGIN_IFRAME_URL_KEYWORD = "music.163.com/login"
_QR_WAIT_TIMEOUT_SEC = 12.0
_QR_STATE_WAITING = "waiting"
_QR_STATE_SCANNED = "scanned"
_QR_STATE_EXPIRED = "expired"
_QR_STATE_SUCCESS = "success"


@dataclass
class BrowserQrcodeSession:
    session_id: str
    account_role: str
    profile_dir: Path
    playwright: Any
    browser_context: Any
    page: Any
    created_at: float = field(default_factory=time.time)
    user_id: str = ""
    imported: bool = False
    last_status: str = "waiting"


_sessions: dict[str, BrowserQrcodeSession] = {}
_sessions_lock = threading.Lock()
_playwright_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser-qrcode-playwright")


def _session_root_dir() -> Path:
    root = USER_DATA_DIR / "browser_qrcode_sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _netease_cookies_from_browser(cookies: list[dict[str, Any]]) -> dict[str, str]:
    jar: dict[str, str] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain") or "").strip().lower()
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "").strip()
        if not name or not value:
            continue
        if "163.com" not in domain:
            continue
        jar[name] = value
    return jar


def _nickname_from_storage_state(storage_state: dict[str, Any]) -> str:
    origins = storage_state.get("origins")
    if not isinstance(origins, list):
        return ""
    for origin in origins:
        if not isinstance(origin, dict):
            continue
        local_storage = origin.get("localStorage")
        if not isinstance(local_storage, list):
            continue
        for item in local_storage:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            value = str(item.get("value") or "")
            if name.lower().endswith("nickname") and value.strip():
                return value.strip()
    return ""


async def _extract_user_profile(user_id: str) -> tuple[str, str]:
    user = load_user(user_id)
    if user is None:
        return "", ""

    try:
        result = await weapi_request(
            user,
            "https://music.163.com/weapi/w/nuser/account/get",
            {"csrf_token": user.csrf},
            extract_cookies=True,
        )
    except (httpx.HTTPError, ValueError):
        return "", ""

    if result.get("code") != 200:
        return "", ""

    user_id = sync_profile_from_account_payload(user_id, result)
    updated_user = load_user(user_id)
    if updated_user is None:
        return "", ""
    return updated_user.nickname.strip(), updated_user.netease_user_id.strip()


def _build_cookie_header_from_jar(cookie_jar: dict[str, str]) -> str:
    parts: list[str] = []
    for name in sorted(cookie_jar):
        value = str(cookie_jar[name] or "").strip()
        if value:
            parts.append(f"{name}={value}")
    return ";".join(parts)


def _default_sync_config_payload(home_dir: Path) -> dict[str, object]:
    log_file = (home_dir / "sync.log").resolve()
    db_path = (home_dir / "database" / "badger").resolve()
    cookie_path = (home_dir / "cookie.json").resolve()
    return {
        "version": "1.0",
        "accounts": {
            "main": "cookie.json",
            "secondary": [],
        },
        "log": {
            "app": "ncm",
            "format": "text",
            "level": "info",
            "stdout": False,
            "rotate": {
                "filename": str(log_file),
                "maxsize": 20,
                "maxage": 3,
                "maxbackups": 2,
                "localtime": True,
                "compress": False,
            },
        },
        "network": {
            "debug": False,
            "timeout": "60s",
            "retry": 3,
            "cookie": {
                "filepath": str(cookie_path),
            },
            "user_agent": {
                "default": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "weapi": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "eapi": "NeteaseMusic 9.4.95/6806 (iPhone; iOS 16.6.1; zh_CN)",
            },
        },
        "database": {
            "driver": "badger",
            "path": str(db_path),
        },
        "task": {
            "sign": False,
            "playids": False,
            "musician-sign": False,
            "musician-vip": False,
            "note": False,
            "fansgroup": False,
        },
        "sign": {
            "enableMain": True,
            "enableSecondaries": True,
        },
        "playids": {
            "enableMain": False,
            "enableSecondaries": True,
            "daily_min": 50,
            "daily_max": 100,
            "run_min": 1,
            "run_max": 1,
            "gap_min": 10,
            "gap_max": 20,
            "ids": "33894312",
            "idsFile": [],
        },
        "musician": {
            "enableMain": True,
            "enableSecondaries": False,
            "identityCacheDays": 0,
            "enableVipNote": False,
            "enableVipPlay": False,
            "play": {
                "ids": "",
                "idsFile": [],
                "run_min": 0,
                "run_max": 0,
                "gap_min": 0,
                "gap_max": 0,
            },
        },
        "fansgroup": {
            "enableMain": True,
            "enableSecondaries": True,
        },
        "mixPlay": {
            "enabled": False,
            "dailyRecommendRatio": 0.0,
            "countTarget": False,
        },
        "note": {
            "titles": ["临时任务"],
            "titlesFile": [],
            "messages": ["临时任务"],
            "messagesFile": [],
            "imageUrls": [],
            "type": 39,
            "autoDelete": True,
        },
    }


def _ensure_ncmm_sync_config(config_path: Path, home_dir: Path) -> None:
    if config_path.is_file():
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(_default_sync_config_payload(home_dir), allow_unicode=True, sort_keys=False)
    config_path.write_text(text, encoding="utf-8")


def _sync_cookie_output_path(home_dir: Path, account_role: str, user_id: str) -> Path:
    if account_role == "main":
        return (home_dir / "cookie.json").resolve()
    return (home_dir / f"{user_id}.cookie.json").resolve()


def _ensure_ncmm_sync_paths(config_path: Path, home_dir: Path) -> None:
    if not config_path.is_file():
        return

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return

    if not isinstance(payload, dict):
        return

    changed = False
    network = payload.get("network")
    if not isinstance(network, dict):
        network = {}
        payload["network"] = network
        changed = True

    cookie_cfg = network.get("cookie")
    if not isinstance(cookie_cfg, dict):
        cookie_cfg = {}
        network["cookie"] = cookie_cfg
        changed = True

    cookie_path = str(cookie_cfg.get("filepath") or "").strip()
    expected_main = str((home_dir / "cookie.json").resolve())
    if not cookie_path or not Path(cookie_path).is_absolute():
        cookie_cfg["filepath"] = expected_main
        changed = True

    accounts = payload.get("accounts")
    if not isinstance(accounts, dict):
        accounts = {}
        payload["accounts"] = accounts
        changed = True

    main_path = str(accounts.get("main") or "").strip()
    if not main_path or not Path(main_path).is_absolute():
        accounts["main"] = expected_main
        changed = True

    if changed:
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        config_path.write_text(text, encoding="utf-8")


def _build_ncmm_sync_command(home_dir: Path, cookie_input_file: Path, account_role: str, config_path: Path, output_cookie_file: Path) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
    command = [
        *prefix,
        "--home",
        str(home_dir),
        "--config",
        str(config_path),
        "login",
        "cookie",
        "-f",
        str(cookie_input_file),
        "-o",
        str(output_cookie_file),
    ]
    if account_role == "main":
        command.append("--main")
    return command


def _sync_account_role_to_ncmm(cookie_jar: dict[str, str], account_role: str, user_id: str) -> None:
    if not NCMM_PROJECT_DIR.is_dir():
        return
    if not NCMM_BIN.is_file() and shutil.which("go") is None:
        return

    sync_dir = USER_DATA_DIR / "ncmm_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    home_dir = ncmm_workspace_dir_for_user_id(user_id)
    cookie_input_file = sync_dir / f"{user_id}.cookie.txt"
    config_path = home_dir / "config.yaml"
    output_cookie_file = _sync_cookie_output_path(home_dir, account_role, user_id)
    try:
        _ensure_ncmm_sync_config(config_path, home_dir)
        _ensure_ncmm_sync_paths(config_path, home_dir)
        cookie_input_file.write_text(_build_cookie_header_from_jar(cookie_jar), encoding="utf-8")
        subprocess.run(
            _build_ncmm_sync_command(home_dir, cookie_input_file, account_role, config_path, output_cookie_file),
            cwd=str(NCMM_PROJECT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        try:
            cookie_input_file.unlink(missing_ok=True)
        except OSError:
            pass


def _extract_qr_candidate_from_frame(frame: Any) -> str:
        script = """
() => {
    const canvases = Array.from(document.querySelectorAll('canvas'));
    for (const canvas of canvases) {
        const width = canvas.clientWidth || canvas.width || 0;
        const height = canvas.clientHeight || canvas.height || 0;
        if (width >= 100 && height >= 100) {
            return canvas.toDataURL('image/png');
        }
    }

    const images = Array.from(document.querySelectorAll('img'));
    for (const img of images) {
        const width = img.clientWidth || 0;
        const height = img.clientHeight || 0;
        const src = img.getAttribute('src') || '';
        if (width >= 100 && height >= 100 && src) {
            return src;
        }
    }

    const nodes = Array.from(document.querySelectorAll('*'));
    for (const node of nodes) {
        const style = window.getComputedStyle(node);
        const bg = style.backgroundImage || '';
        const width = node.clientWidth || 0;
        const height = node.clientHeight || 0;
        if (width >= 100 && height >= 100 && bg && bg.startsWith('url(')) {
            return bg.slice(5, -2);
        }
    }

    return '';
}
"""
        return str(frame.evaluate(script) or "").strip()


def _extract_qr_data_url(page: Any) -> str:
        deadline = time.time() + _QR_WAIT_TIMEOUT_SEC
        last_diag = "未找到登录 iframe"
        while time.time() < deadline:
                frame = _find_login_frame(page)
                if frame is None:
                        page.wait_for_timeout(400)
                        continue
                try:
                        candidate = _extract_qr_candidate_from_frame(frame)
                        if candidate:
                                return candidate
                        canvas_count = frame.locator("canvas").count()
                        img_count = frame.locator("img").count()
                        last_diag = f"二维码节点尚未就绪: canvas={canvas_count}, img={img_count}"
                except Exception as exc:
                        last_diag = f"二维码提取失败: {exc}"
                page.wait_for_timeout(500)
        raise RuntimeError(f"未在网易云登录 iframe 中找到二维码节点; {last_diag}")


def _find_login_frame(page: Any) -> Any:
    for frame in page.frames:
        frame_url = str(getattr(frame, "url", "") or "")
        if _LOGIN_IFRAME_URL_KEYWORD in frame_url:
            return frame
    return None


def _detect_qr_runtime_state(page: Any) -> tuple[str, str]:
    frame = _find_login_frame(page)
    if frame is None:
        return _QR_STATE_WAITING, "等待登录页加载"
    try:
        text = frame.locator("body").inner_text(timeout=1500)
    except Exception:
        return _QR_STATE_WAITING, "等待二维码状态同步"

    body_text = str(text or "").strip()
    if not body_text:
        return _QR_STATE_WAITING, "等待二维码状态同步"

    if "已失效" in body_text or "刷新二维码" in body_text or "二维码过期" in body_text:
        return _QR_STATE_EXPIRED, "二维码已过期"
    if "扫描成功" in body_text or "待确认" in body_text or "在手机上确认" in body_text:
        return _QR_STATE_SCANNED, "已扫码，请在手机上确认"
    return _QR_STATE_WAITING, "等待扫码"


def _refresh_qr_session(session: BrowserQrcodeSession) -> str:
    session.page.goto(_LOGIN_URL, wait_until="domcontentloaded")
    session.page.wait_for_timeout(1000)
    session.created_at = time.time()
    session.last_status = _QR_STATE_WAITING
    return _extract_qr_data_url(session.page)


def _close_session(session: BrowserQrcodeSession) -> None:
    try:
        session.page.close()
    except Exception:
        pass
    try:
        session.browser_context.close()
    except Exception:
        pass
    try:
        session.playwright.stop()
    except Exception:
        pass
    shutil.rmtree(session.profile_dir, ignore_errors=True)


def _cleanup_expired_sessions() -> None:
    now = time.time()
    stale_ids: list[str] = []
    with _sessions_lock:
        for session_id, session in _sessions.items():
            if now - session.created_at > _SESSION_TTL_SEC:
                stale_ids.append(session_id)
        stale_sessions = [_sessions.pop(session_id) for session_id in stale_ids]
    for session in stale_sessions:
        _close_session(session)


def _browser_qrcode_create_sync(account_role: str) -> dict[str, Any]:
    _cleanup_expired_sessions()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "缺少 playwright 依赖，请先执行: pip install playwright && playwright install chromium",
        ) from exc

    role = account_role.strip().lower() or "main"
    if role not in {"main", "secondary"}:
        role = "main"

    session_id = uuid.uuid4().hex
    profile_dir = _session_root_dir() / session_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    playwright = sync_playwright().start()
    browser_context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=True,
        viewport={"width": 1280, "height": 900},
    )
    page = browser_context.pages[0] if browser_context.pages else browser_context.new_page()
    page.goto(_LOGIN_URL, wait_until="domcontentloaded")
    qr_image_data_url = _extract_qr_data_url(page)

    session = BrowserQrcodeSession(
        session_id=session_id,
        account_role=role,
        profile_dir=profile_dir,
        playwright=playwright,
        browser_context=browser_context,
        page=page,
    )
    with _sessions_lock:
        _sessions[session_id] = session
    return {
        "code": 200,
        "session_id": session_id,
        "account_role": role,
        "login_url": _LOGIN_URL,
        "qr_image_data_url": qr_image_data_url,
        "message": "二维码已生成，请使用网易云音乐 App 或微信扫码",
    }


def _browser_qrcode_status_sync(session_id: str) -> dict[str, Any]:
    _cleanup_expired_sessions()
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session:
        raise ValueError("扫码会话不存在或已过期")

    cookies = session.browser_context.cookies()
    cookie_jar = _netease_cookies_from_browser(cookies)
    music_u = str(cookie_jar.get("MUSIC_U") or "").strip()
    csrf = str(cookie_jar.get("__csrf") or "").strip()
    if not music_u:
        state, message = _detect_qr_runtime_state(session.page)
        session.last_status = state
        if state == _QR_STATE_EXPIRED:
            qr_image_data_url = _refresh_qr_session(session)
            return {
                "code": 800,
                "state": _QR_STATE_EXPIRED,
                "message": "二维码已过期，已自动刷新",
                "session_id": session_id,
                "qr_image_data_url": qr_image_data_url,
                "refreshed": True,
            }
        if state == _QR_STATE_SCANNED:
            return {
                "code": 802,
                "state": _QR_STATE_SCANNED,
                "message": message,
                "session_id": session_id,
            }
        return {
            "code": 801,
            "state": _QR_STATE_WAITING,
            "message": message,
            "session_id": session_id,
        }

    if session.imported and session.user_id:
        return {
            "code": 803,
            "state": _QR_STATE_SUCCESS,
            "message": "授权登录成功",
            "logged_in": True,
            "session_id": session_id,
            "user_id": session.user_id,
            "cookies": cookie_jar,
        }

    storage_state = session.browser_context.storage_state()
    nickname = _nickname_from_storage_state(storage_state)
    user_id = upsert_user_from_login(
        music_u,
        csrf,
        account_role=session.account_role,
        cookies=cookie_jar,
        nickname=nickname,
    )
    _sync_account_role_to_ncmm(cookie_jar, session.account_role, user_id)
    session.user_id = user_id
    session.imported = True
    session.last_status = _QR_STATE_SUCCESS

    with _sessions_lock:
        _sessions.pop(session_id, None)
    _close_session(session)

    return {
        "code": 803,
        "state": _QR_STATE_SUCCESS,
        "message": "授权登录成功",
        "logged_in": True,
        "session_id": session_id,
        "user_id": user_id,
        "account_role": session.account_role,
        "nickname": nickname,
        "netease_user_id": "",
        "ncmm_home_dir": str(ncmm_workspace_dir_for_user_id(user_id).resolve()),
        "cookies": cookie_jar,
    }


async def browser_qrcode_create(account_role: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_playwright_executor, _browser_qrcode_create_sync, account_role)


async def browser_qrcode_status(session_id: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_playwright_executor, _browser_qrcode_status_sync, session_id)
    if result.get("code") == 803 and result.get("logged_in") and result.get("user_id"):
        synced_nickname, netease_user_id = await _extract_user_profile(str(result["user_id"]))
        if synced_nickname:
            result["nickname"] = synced_nickname
        if netease_user_id:
            result["netease_user_id"] = netease_user_id
    return result