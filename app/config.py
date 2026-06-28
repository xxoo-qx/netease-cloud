import os
from pathlib import Path
import json

from dotenv import load_dotenv

# 项目根目录下的 .env（与从何处启动 python、cwd 无关）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# 多用户登录态 JSON 存储目录（每个用户一个 {user_id}.json）
_default_user_data = Path(__file__).resolve().parent.parent / "user_data"
USER_DATA_DIR = Path(os.getenv("USER_DATA_DIR", str(_default_user_data))).resolve()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
PROXY_URL = os.getenv("PROXY_URL")
NCMM_PROJECT_DIR = Path(
    os.getenv("NCMM_PROJECT_DIR", str(_PROJECT_ROOT.parent / "ncmm-main"))
).resolve()
NCMM_BIN = Path(
    os.getenv("NCMM_BIN", str(NCMM_PROJECT_DIR / "bin" / "ncmm.exe"))
).resolve()
NCMM_HOME_DIR = Path(
    os.getenv("NCMM_HOME_DIR", str(NCMM_PROJECT_DIR / ".work"))
).resolve()

# WeAPI 请求在代理断连、远端空响应等瞬态错误时的额外重试次数（首次请求不计入）
WEAPI_MAX_RETRIES = max(0, int(os.getenv("WEAPI_MAX_RETRIES", "3")))
# 首次重试前的基础等待（秒），后续按指数退避倍增
WEAPI_RETRY_BASE_DELAY_SEC = float(os.getenv("WEAPI_RETRY_BASE_DELAY_SEC", "0.5"))

WEBLOG_BASE_URL = os.getenv(
    "WEBLOG_BASE_URL",
    "https://music.163.com/weapi/feedback/weblog",
)

NETEASE_REFERER = "https://music.163.com"
NETEASE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
NETEASE_WEAPI_USER_AGENT = os.getenv("NETEASE_WEAPI_USER_AGENT", NETEASE_USER_AGENT).strip() or NETEASE_USER_AGENT
NETEASE_EAPI_USER_AGENT = os.getenv(
    "NETEASE_EAPI_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36 Chrome/91.0.4472.164 NeteaseMusicDesktop/2.10.2.200154",
).strip()


def _load_ncmm_user_agent_overrides() -> dict[str, str]:
    raw = os.getenv("NCMM_USER_AGENT_CONFIG", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    network = payload.get("network")
    if not isinstance(network, dict):
        return {}
    ua_cfg = network.get("user_agent")
    if isinstance(ua_cfg, str):
        value = ua_cfg.strip()
        return {"default": value, "weapi": value, "eapi": value} if value else {}
    if not isinstance(ua_cfg, dict):
        return {}
    overrides: dict[str, str] = {}
    for key in ("default", "weapi", "eapi"):
        value = str(ua_cfg.get(key) or "").strip()
        if value:
            overrides[key] = value
    return overrides


_ua_overrides = _load_ncmm_user_agent_overrides()
if _ua_overrides.get("default"):
    NETEASE_USER_AGENT = _ua_overrides["default"]
if _ua_overrides.get("weapi"):
    NETEASE_WEAPI_USER_AGENT = _ua_overrides["weapi"]
if _ua_overrides.get("eapi"):
    NETEASE_EAPI_USER_AGENT = _ua_overrides["eapi"]

DEFAULT_USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
]

# fixed: 使用 NETEASE_USER_AGENT；random: 从 UA 池随机选择
USER_AGENT_MODE = os.getenv("USER_AGENT_MODE", "random").strip().lower()
_ua_pool_raw = os.getenv("USER_AGENT_POOL", "").strip()
if _ua_pool_raw:
    USER_AGENT_POOL = [item.strip() for item in _ua_pool_raw.split("||") if item.strip()]
else:
    USER_AGENT_POOL = DEFAULT_USER_AGENT_POOL

BASE_COOKIE = "os=pc; osver=Microsoft-Windows-10-Professional-build-10586-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;"

# 内置指纹池（可通过 COOKIE_FINGERPRINT_POOL 覆盖）
# 仅 Windows 桌面（os=pc），与 NETEASE_USER_AGENT 的 Windows Chrome 一致；不再混入安卓/Mac。
DEFAULT_COOKIE_FINGERPRINTS = [
    "os=pc; osver=Microsoft-Windows-10-Professional-build-10586-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;",
    "os=pc; osver=Microsoft-Windows-10-Pro-build-19045-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;",
    "os=pc; osver=Microsoft-Windows-10-Home-build-19044-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;",
    "os=pc; osver=Microsoft-Windows-11-Professional-build-22631-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;",
    "os=pc; osver=Microsoft-Windows-11-Home-Single-Language-build-26100-64bit; appver=2.10.11.201101; channel=netease; __remember_me=true;",
]

# fixed: 使用 BASE_COOKIE；random: 从指纹池随机选择
FINGERPRINT_MODE = os.getenv("FINGERPRINT_MODE", "random").strip().lower()

# 自定义指纹池，使用 "||" 分隔多条 cookie 片段
_pool_raw = os.getenv("COOKIE_FINGERPRINT_POOL", "").strip()
if _pool_raw:
    COOKIE_FINGERPRINT_POOL = [item.strip() for item in _pool_raw.split("||") if item.strip()]
else:
    COOKIE_FINGERPRINT_POOL = DEFAULT_COOKIE_FINGERPRINTS

# Web 管理后台（/admin）与会话 Cookie；生产环境务必修改
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "dev-only-change-SESSION_SECRET-in-production-min-16-chars",
).strip()
