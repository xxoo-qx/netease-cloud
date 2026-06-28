"""共享 httpx 客户端 + 按用户会话发起 WeAPI 请求。"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import httpx

from app.config import (
    BASE_COOKIE,
    COOKIE_FINGERPRINT_POOL,
    FINGERPRINT_MODE,
    NETEASE_EAPI_USER_AGENT,
    NETEASE_REFERER,
    NETEASE_USER_AGENT,
    NETEASE_WEAPI_USER_AGENT,
    PROXY_URL,
    USER_AGENT_MODE,
    USER_AGENT_POOL,
    WEAPI_MAX_RETRIES,
    WEAPI_RETRY_BASE_DELAY_SEC,
)
from app.crypto import weapi_encrypt
from app.user_store import UserRecord, save_user

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 15.0

# 可重试的瞬态传输错误（不含 4xx/5xx，那些由 response 正常返回后处理）
_RETRYABLE_REQUEST_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)


def _should_reset_shared_client_after(exc: BaseException) -> bool:
    """连接被对端直接掐断、读半包失败或无法建连时，关闭共享客户端以便下次重建连接池。"""
    return isinstance(
        exc,
        (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError),
    )

_shared_client: httpx.AsyncClient | None = None


async def get_shared_httpx() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT,
            verify=False,
            proxy=PROXY_URL,
            headers={
                "Referer": NETEASE_REFERER,
                    "User-Agent": NETEASE_WEAPI_USER_AGENT,
            },
        )
    return _shared_client


def _pick_user_agent() -> str:
    if USER_AGENT_MODE == "fixed":
        return NETEASE_WEAPI_USER_AGENT
    return random.choice(USER_AGENT_POOL or [NETEASE_WEAPI_USER_AGENT])


def get_eapi_user_agent() -> str:
    return NETEASE_EAPI_USER_AGENT


def _build_cookie_header(user: UserRecord) -> str:
    if FINGERPRINT_MODE == "fixed":
        base_cookie = BASE_COOKIE
    else:
        base_cookie = random.choice(COOKIE_FINGERPRINT_POOL or [BASE_COOKIE])
    parts = [base_cookie]
    if csrf := (user.csrf or "").strip():
        parts.append(f"__csrf={csrf}")
    if music_u := (user.music_u or "").strip():
        parts.append(f"MUSIC_U={music_u}")
    return "; ".join(parts)


async def weapi_request(
    user: UserRecord,
    url: str,
    payload: dict[str, Any],
    *,
    extract_cookies: bool = False,
    cookie_header_override: str | None = None,
    user_agent_override: str | None = None,
) -> dict[str, Any]:
    """以指定用户的 Cookie 调用 WeAPI；可选写回 Set-Cookie 到磁盘。"""
    if not user.music_u.strip():
        return {"code": 401, "message": "用户未绑定 MUSIC_U"}

    client = await get_shared_httpx()
    encrypted = weapi_encrypt(payload)

    cookie_header = (cookie_header_override or "").strip() or _build_cookie_header(user)
    user_agent = (user_agent_override or "").strip() or _pick_user_agent()
    post_headers: dict[str, str] = {
        "Cookie": cookie_header,
        "Origin": "https://music.163.com",
        "Referer": "https://music.163.com/",
        "User-Agent": user_agent,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    # 与网页 DevTools 中 clientlogusf feedback/weblog 请求一致，缺省时部分埋点链路可能权重不同
    if "feedback/weblog" in url:
        post_headers["Nm-GCore-Status"] = "1"

    max_attempts = 1 + WEAPI_MAX_RETRIES
    response: httpx.Response | None = None
    last_error: BaseException | None = None

    for attempt in range(max_attempts):
        client = await get_shared_httpx()
        try:
            response = await client.post(
                url,
                data=encrypted,
                headers=post_headers,
            )
            last_error = None
            break
        except _RETRYABLE_REQUEST_ERRORS as e:
            last_error = e
            if attempt + 1 >= max_attempts:
                logger.error(
                    "WeAPI POST 在 %d 次尝试后仍失败: %s %s",
                    max_attempts,
                    type(e).__name__,
                    e,
                )
                raise
            if _should_reset_shared_client_after(e):
                await close_shared_http()
            # 指数退避 + 少量抖动，减轻代理/服务端同一时间窗口内的突发压力
            delay = WEAPI_RETRY_BASE_DELAY_SEC * (2**attempt) + random.uniform(
                0.0,
                0.25,
            )
            logger.warning(
                "WeAPI POST 失败 (%s)，%d/%d 次尝试后将重试，约等待 %.2fs: %s",
                type(e).__name__,
                attempt + 1,
                max_attempts,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    if response is None:
        assert last_error is not None
        raise last_error

    if extract_cookies:
        changed = False
        merged_cookies = dict(user.cookies or {})
        for key in ("MUSIC_U", "__csrf"):
            if val := response.cookies.get(key):
                if key == "MUSIC_U" and val != user.music_u:
                    user.music_u = val
                    changed = True
                if key == "__csrf" and val != user.csrf:
                    user.csrf = val
                    changed = True
                if merged_cookies.get(key) != val:
                    merged_cookies[key] = val
                    changed = True
        for cookie in response.cookies.jar:
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "").strip()
            if not name or not value:
                continue
            if merged_cookies.get(name) != value:
                merged_cookies[name] = value
                changed = True
        if merged_cookies:
            user.cookies = merged_cookies
        if changed:
            save_user(user)

    try:
        return response.json()
    except json.JSONDecodeError:
        text = response.text
        if "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            return json.loads(text[start:end])
        return {
            "code": 500,
            "message": "Invalid response from server",
            "status_code": response.status_code,
            "response_text": text[:500],
        }


async def weapi_request_many(
    user: UserRecord,
    url: str,
    payloads: list[dict[str, Any]],
    *,
    concurrency: int = 50,
    cookie_header_override: str | None = None,
    user_agent_override: str | None = None,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def _one(p: dict) -> dict:
        async with sem:
            return await weapi_request(
                user,
                url,
                p,
                cookie_header_override=cookie_header_override,
                user_agent_override=user_agent_override,
            )

    return await asyncio.gather(*[_one(p) for p in payloads])


async def close_shared_http() -> None:
    global _shared_client
    if _shared_client and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None
