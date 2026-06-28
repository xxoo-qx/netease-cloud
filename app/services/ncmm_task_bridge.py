from __future__ import annotations

import asyncio
import datetime as dt
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.config import NCMM_BIN, NCMM_HOME_DIR, NCMM_PROJECT_DIR, USER_DATA_DIR
from app.services.ncmm_runtime import CapturedProcessResult, run_ncmm_subprocess
from app.user_store import UserRecord, ncmm_workspace_dir_for_user_id

_TASK_SUCCESS_RE = re.compile(r"\[task\]\s*✅\s*\[(.+?)\]\s*执行\s*成功")
_TASK_FAILURE_RE = re.compile(r"\[task\]\s*❌\s*\[(.+?)\]\s*执行失败: (.+)")


@dataclass(slots=True)
class NcmmTaskOptions:
    sign: bool = False
    playids: bool = False
    musician_sign: bool = False
    musician_vip: bool = False
    note: bool = False
    fansgroup: bool = False


@dataclass(slots=True)
class BridgePlayPoolOptions:
    ids: list[int] | None = None
    ids_file: str | list[str] | None = None
    daily_min: int = 50
    daily_max: int = 100
    run_min: int = 0
    run_max: int = 0
    gap_min: int = 0
    gap_max: int = 0
    mix_enabled: bool = True
    mix_ratio: float = 0.3
    count_target_for_mix: bool = False


@dataclass(slots=True)
class NcmmMusicianBridgeOptions:
    play_pool: BridgePlayPoolOptions | None = None
    enable_vip_note: bool = False
    enable_vip_play: bool = False


def _build_cookie_header(user: UserRecord) -> str:
    cookies = dict(user.cookies or {})
    music_u = user.music_u.strip()
    if music_u:
        cookies["MUSIC_U"] = music_u
    csrf = (user.csrf or "").strip()
    if csrf:
        cookies["__csrf"] = csrf
    parts: list[str] = []
    for name in sorted(cookies):
        value = str(cookies[name]).strip()
        if not value:
            continue
        parts.append(f"{name}={value}")
    return ";".join(parts)


async def _write_temp_cookie_file(user: UserRecord, workdir: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    path = workdir / f"{user.user_id}-{stamp}.cookie.txt"
    header = _build_cookie_header(user)
    await asyncio.to_thread(path.write_text, header, "utf-8")
    return path


def _ncmm_home_dir_for_user(user: UserRecord) -> Path:
    return ncmm_workspace_dir_for_user_id(user.user_id)


def _normalized_cookie_output_path(cookie_file: Path) -> Path:
    return cookie_file.with_suffix(".normalized.json")


def _build_ncmm_login_command(home_dir: Path, cookie_input_file: Path, output_cookie_file: Path, config_path: Path) -> list[str]:
    binary = str(NCMM_BIN) if NCMM_BIN.is_file() else "go"
    prefix = [binary] if NCMM_BIN.is_file() else ["go", "run", "."]
    return [
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
        "--main",
    ]


def _default_network_user_agent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )


def _normalize_ids(ids: list[int] | None) -> str:
    values = [str(track_id).strip() for track_id in (ids or []) if int(track_id) > 0]
    return ",".join(values)


def _normalize_ids_file(ids_file: str | list[str] | None) -> list[str]:
    if ids_file is None:
        return []
    if isinstance(ids_file, str):
        text = ids_file.strip()
        return [text] if text else []
    return [str(item).strip() for item in ids_file if str(item).strip()]


def _build_task_config(
    cookie_file: Path,
    opts: NcmmTaskOptions,
    *,
    play_pool: BridgePlayPoolOptions | None = None,
    musician_options: NcmmMusicianBridgeOptions | None = None,
) -> dict[str, object]:
    network: dict[str, object] = {
        "debug": False,
        "timeout": "60s",
        "retry": 3,
        "cookie": {
            "filepath": str(cookie_file),
        },
        "user_agent": {
            "default": _default_network_user_agent(),
            "weapi": _default_network_user_agent(),
            "eapi": "NeteaseMusic 9.4.95/6806 (iPhone; iOS 16.6.1; zh_CN)",
        },
    }
    return {
        "version": "1.0",
        "accounts": {
            "main": str(cookie_file),
            "secondary": [],
        },
        "log": {
            "app": "ncm",
            "format": "text",
            "level": "info",
            "stdout": False,
            "rotate": {
                "filename": str((cookie_file.parent / "ncmm.log").resolve()),
                "maxsize": 20,
                "maxage": 3,
                "maxbackups": 2,
                "localtime": True,
                "compress": False,
            },
        },
        "network": network,
        "database": {
            "driver": "badger",
            "path": str((cookie_file.parent / "database" / "badger").resolve()),
        },
        "task": {
            "sign": opts.sign,
            "playids": opts.playids,
            "musician-sign": opts.musician_sign,
            "musician-vip": opts.musician_vip,
            "note": opts.note,
            "fansgroup": opts.fansgroup,
        },
        "sign": {
            "enableMain": True,
            "enableSecondaries": False,
        },
        "playids": {
            "enableMain": True,
            "enableSecondaries": False,
            "daily_min": max(1, play_pool.daily_min if play_pool else 50),
            "daily_max": max(1, play_pool.daily_max if play_pool else 100),
            "run_min": max(0, play_pool.run_min if play_pool else 0),
            "run_max": max(0, play_pool.run_max if play_pool else 0),
            "gap_min": max(0, play_pool.gap_min if play_pool else 0),
            "gap_max": max(0, play_pool.gap_max if play_pool else 0),
            "ids": _normalize_ids(play_pool.ids if play_pool else None),
            "idsFile": _normalize_ids_file(play_pool.ids_file if play_pool else None),
        },
        "musician": {
            "enableMain": True,
            "enableSecondaries": False,
            "identityCacheDays": 0,
            "enableVipNote": bool(musician_options.enable_vip_note) if musician_options else False,
            "enableVipPlay": bool(musician_options.enable_vip_play) if musician_options else False,
            "play": {
                "ids": _normalize_ids((musician_options.play_pool.ids if musician_options and musician_options.play_pool else None)),
                "idsFile": _normalize_ids_file(musician_options.play_pool.ids_file if musician_options and musician_options.play_pool else None),
                "run_min": max(0, musician_options.play_pool.run_min if musician_options and musician_options.play_pool else 0),
                "run_max": max(0, musician_options.play_pool.run_max if musician_options and musician_options.play_pool else 0),
                "gap_min": max(0, musician_options.play_pool.gap_min if musician_options and musician_options.play_pool else 0),
                "gap_max": max(0, musician_options.play_pool.gap_max if musician_options and musician_options.play_pool else 0),
            },
        },
        "fansgroup": {
            "enableMain": True,
            "enableSecondaries": False,
        },
        "mixPlay": {
            "enabled": bool(play_pool.mix_enabled) if play_pool else False,
            "dailyRecommendRatio": float(play_pool.mix_ratio) if play_pool else 0.0,
            "countTarget": bool(play_pool.count_target_for_mix) if play_pool else False,
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


async def _write_task_config(
    config_path: Path,
    cookie_file: Path,
    opts: NcmmTaskOptions,
    *,
    play_pool: BridgePlayPoolOptions | None = None,
    musician_options: NcmmMusicianBridgeOptions | None = None,
) -> None:
    payload = _build_task_config(
        cookie_file,
        opts,
        play_pool=play_pool,
        musician_options=musician_options,
    )
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    await asyncio.to_thread(config_path.write_text, text, "utf-8")


async def _run_ncmm_command(command: list[str]) -> CapturedProcessResult:
    return await run_ncmm_subprocess(command, cwd=NCMM_PROJECT_DIR)


def _build_task_command(home_dir: Path, config_path: Path) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
    return [
        *prefix,
        "--home",
        str(home_dir),
        "--config",
        str(config_path),
        "task",
    ]


def _build_musician_command(home_dir: Path, config_path: Path, subcommand: str) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
    return [
        *prefix,
        "--home",
        str(home_dir),
        "--config",
        str(config_path),
        subcommand,
    ]


def _build_direct_command(home_dir: Path, config_path: Path, subcommand: str) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
    return [
        *prefix,
        "--home",
        str(home_dir),
        "--config",
        str(config_path),
        subcommand,
    ]


def _summarize_command_failure(action: str, result: CapturedProcessResult) -> str:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    parts = [f"{action} 执行失败(exit={result.returncode})"]
    if stdout:
        parts.append(f"STDOUT:\n{stdout}")
    if stderr:
        parts.append(f"STDERR:\n{stderr}")
    if len(parts) == 1:
        parts.append("命令未输出任何内容")
    return "\n".join(parts)


def _parse_task_stdout(output: str) -> dict[str, object]:
    successes = [match.group(1) for match in _TASK_SUCCESS_RE.finditer(output)]
    failures = [
        {"task": match.group(1), "message": match.group(2).strip()}
        for match in _TASK_FAILURE_RE.finditer(output)
    ]
    return {
        "successful_tasks": successes,
        "failed_tasks": failures,
        "all_succeeded": not failures,
    }


def _build_bridge_workdir(user: UserRecord) -> Path:
    bridge_dir = USER_DATA_DIR / "ncmm_bridge" / user.user_id
    bridge_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    workdir = bridge_dir / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


async def run_ncmm_task_for_user(
    user: UserRecord,
    opts: NcmmTaskOptions,
    *,
    play_pool: BridgePlayPoolOptions | None = None,
) -> dict[str, object]:
    if not NCMM_BIN.is_file() and not NCMM_PROJECT_DIR.is_dir():
        raise RuntimeError(f"ncmm 项目目录不存在: {NCMM_PROJECT_DIR}")
    if not (user.music_u or "").strip():
        raise RuntimeError("当前用户缺少 MUSIC_U，无法转调 ncmm task")

    workdir = _build_bridge_workdir(user)
    home_dir = _ncmm_home_dir_for_user(user)
    cookie_import_file = await _write_temp_cookie_file(user, workdir)
    cookie_file = _normalized_cookie_output_path(cookie_import_file)
    config_path = workdir / "config.yaml"
    await _write_task_config(config_path, cookie_file, opts, play_pool=play_pool)
    login_command = _build_ncmm_login_command(home_dir, cookie_import_file, cookie_file, config_path)
    task_command = _build_task_command(home_dir, config_path)
    try:
        login_result = await _run_ncmm_command(login_command)
        if login_result.returncode != 0:
            raise RuntimeError(_summarize_command_failure("ncmm login", login_result))
        result = await _run_ncmm_command(task_command)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(_summarize_command_failure("ncmm task", result))
    parsed = _parse_task_stdout("\n".join(part for part in [result.stdout, result.stderr] if part))
    return {
        "code": 200,
        "status": "ok",
        "backend": "ncmm",
        "mode": "task",
        "login_command": login_result.command,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ncmm_home_dir": str(home_dir.resolve()),
        **parsed,
    }


async def run_ncmm_musician_for_user(
    user: UserRecord,
    subcommand: str,
    options: NcmmMusicianBridgeOptions | None = None,
) -> dict[str, object]:
    if subcommand not in {"musician", "musician-sign", "musician-vip"}:
        raise RuntimeError(f"不支持的 musician 子命令: {subcommand}")
    if not NCMM_BIN.is_file() and not NCMM_PROJECT_DIR.is_dir():
        raise RuntimeError(f"ncmm 项目目录不存在: {NCMM_PROJECT_DIR}")
    if not (user.music_u or "").strip():
        raise RuntimeError("当前用户缺少 MUSIC_U，无法转调 ncmm musician")

    workdir = _build_bridge_workdir(user)
    home_dir = _ncmm_home_dir_for_user(user)
    cookie_import_file = await _write_temp_cookie_file(user, workdir)
    cookie_file = _normalized_cookie_output_path(cookie_import_file)
    config_path = workdir / "config.yaml"
    await _write_task_config(
        config_path,
        cookie_file,
        NcmmTaskOptions(),
        play_pool=options.play_pool if options else None,
        musician_options=options,
    )
    login_command = _build_ncmm_login_command(home_dir, cookie_import_file, cookie_file, config_path)
    command = _build_musician_command(home_dir, config_path, subcommand)
    try:
        login_result = await _run_ncmm_command(login_command)
        if login_result.returncode != 0:
            raise RuntimeError(_summarize_command_failure("ncmm login", login_result))
        result = await _run_ncmm_command(command)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(_summarize_command_failure(f"ncmm {subcommand}", result))
    return {
        "code": 200,
        "status": "ok",
        "backend": "ncmm",
        "mode": subcommand,
        "login_command": login_result.command,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ncmm_home_dir": str(home_dir.resolve()),
    }


async def run_ncmm_direct_command_for_user(
    user: UserRecord,
    subcommand: str,
) -> dict[str, object]:
    allowed = {"sign", "note", "fansgroup"}
    if subcommand not in allowed:
        raise RuntimeError(f"不支持的 ncmm 子命令: {subcommand}")
    if not NCMM_BIN.is_file() and not NCMM_PROJECT_DIR.is_dir():
        raise RuntimeError(f"ncmm 项目目录不存在: {NCMM_PROJECT_DIR}")
    if not (user.music_u or "").strip():
        raise RuntimeError(f"当前用户缺少 MUSIC_U，无法转调 ncmm {subcommand}")

    workdir = _build_bridge_workdir(user)
    home_dir = _ncmm_home_dir_for_user(user)
    cookie_import_file = await _write_temp_cookie_file(user, workdir)
    cookie_file = _normalized_cookie_output_path(cookie_import_file)
    config_path = workdir / "config.yaml"
    await _write_task_config(config_path, cookie_file, NcmmTaskOptions())
    login_command = _build_ncmm_login_command(home_dir, cookie_import_file, cookie_file, config_path)
    command = _build_direct_command(home_dir, config_path, subcommand)
    try:
        login_result = await _run_ncmm_command(login_command)
        if login_result.returncode != 0:
            raise RuntimeError(_summarize_command_failure("ncmm login", login_result))
        result = await _run_ncmm_command(command)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass

    if result.returncode != 0:
        raise RuntimeError(_summarize_command_failure(f"ncmm {subcommand}", result))
    return {
        "code": 200,
        "status": "ok",
        "backend": "ncmm",
        "mode": subcommand,
        "login_command": login_result.command,
        "command": result.command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "ncmm_home_dir": str(home_dir.resolve()),
    }