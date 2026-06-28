from __future__ import annotations

import asyncio
import datetime as dt
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from app.config import NCMM_BIN, NCMM_HOME_DIR, NCMM_IDS_INLINE_LIMIT, NCMM_PROJECT_DIR, USER_DATA_DIR
from app.models.schemas import PlayidsAccountTask
from app.services.ncmm_runtime import run_ncmm_subprocess
from app.user_store import UserRecord, list_users_public, load_user, ncmm_workspace_dir_for_user_id

_RUN_TARGET_RE = re.compile(r"本次目标刷播=(\d+)首")
_SUCCESS_RE = re.compile(r"本次实际运行总上报数:\s*(\d+)，成功:\s*(\d+)")
_DAILY_RE = re.compile(r"今日风控目标: 已完成=(\d+)首, 今日随机上限=(\d+)首")
_ACCOUNT_ERROR_RE = re.compile(r"\[ERROR\]\s*账号 .* 模拟播放失败: (.+)")


@dataclass(slots=True)
class PlayidsOptions:
    count: int = 300
    ids: list[int] | None = None
    ids_file: str | list[str] | None = None
    playlist_id: int | None = None
    track_pool: str = "toplist"
    rotate_playlists: bool = False
    daily_min: int = 50
    daily_max: int = 200
    run_min: int = 0
    run_max: int = 0
    gap_min: int = 10
    gap_max: int = 30
    mix_enabled: bool = True
    mix_ratio: float = 0.3
    count_target_for_mix: bool = False
    source: str | None = None
    source_id: str | None = None
    content: str = ""
    content_empty: bool = False
    end: str = "playend"
    print_weblog_response: bool = False


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


def _build_bridge_workdir(user: UserRecord) -> Path:
    bridge_dir = USER_DATA_DIR / "ncmm_bridge" / user.user_id
    bridge_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
    workdir = bridge_dir / stamp
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def _ncmm_home_dir_for_user(user: UserRecord) -> Path:
    return ncmm_workspace_dir_for_user_id(user.user_id)


def _latest_bridge_dir(user: UserRecord) -> Path:
    latest_dir = USER_DATA_DIR / "ncmm_bridge" / user.user_id / "latest_playids"
    latest_dir.mkdir(parents=True, exist_ok=True)
    return latest_dir


def _persistent_bridge_database_dir(user: UserRecord) -> Path:
    database_dir = USER_DATA_DIR / "ncmm_bridge" / user.user_id / "state" / "database" / "badger"
    database_dir.mkdir(parents=True, exist_ok=True)
    return database_dir


async def _write_temp_cookie_file(user: UserRecord, workdir: Path) -> Path:
    path = workdir / f"{user.user_id}.cookie.txt"
    header = _build_cookie_header(user)
    await asyncio.to_thread(path.write_text, header, "utf-8")
    return path


async def _write_generated_ids_file(workdir: Path, ids: list[int]) -> Path:
    path = workdir / "generated-inline-ids.txt"
    text = "\n".join(str(track_id) for track_id in ids)
    await asyncio.to_thread(path.write_text, text, "utf-8")
    return path


async def _prepare_effective_playids_options(workdir: Path, opts: PlayidsOptions) -> PlayidsOptions:
    ids = list(opts.ids or [])
    if len(ids) <= NCMM_IDS_INLINE_LIMIT:
        return opts
    generated_ids_file = await _write_generated_ids_file(workdir, ids)
    if opts.ids_file is None:
        effective_ids_file: str | list[str] = str(generated_ids_file)
    elif isinstance(opts.ids_file, list):
        effective_ids_file = [str(generated_ids_file), *opts.ids_file]
    else:
        effective_ids_file = [str(generated_ids_file), opts.ids_file]
    return replace(opts, ids=None, ids_file=effective_ids_file)


def _normalized_cookie_output_path(cookie_file: Path) -> Path:
    return cookie_file.with_suffix(".normalized.json")


def _build_ncmm_login_command(home_dir: Path, cookie_input_file: Path, output_cookie_file: Path, config_path: Path) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
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


def _normalize_playids_values(ids: list[int] | None, ids_file: str | list[str] | None) -> tuple[str, list[str]]:
    ids_text = ""
    ids_files: list[str] = []

    if ids:
        ids_text = ",".join(str(value) for value in ids if int(value) > 0)
    if isinstance(ids_file, str):
        cleaned = ids_file.strip()
        if cleaned:
            ids_files.append(cleaned)
    elif isinstance(ids_file, list):
        for item in ids_file:
            cleaned = str(item).strip()
            if cleaned:
                ids_files.append(cleaned)

    return ids_text, ids_files


def _build_temp_config(cookie_file: Path, database_dir: Path, opts: PlayidsOptions) -> dict[str, object]:
    ids_text, ids_files = _normalize_playids_values(opts.ids, opts.ids_file)
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
        "network": {
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
        },
        "database": {
            "driver": "badger",
            "path": str(database_dir.resolve()),
        },
        "playids": {
            "enableMain": True,
            "enableSecondaries": False,
            "daily_min": int(opts.daily_min),
            "daily_max": int(opts.daily_max),
            "run_min": int(opts.run_min),
            "run_max": int(opts.run_max),
            "gap_min": int(opts.gap_min),
            "gap_max": int(opts.gap_max),
            "ids": ids_text,
            "idsFile": ids_files,
        },
        "sign": {
            "enableMain": True,
            "enableSecondaries": False,
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
            "enableSecondaries": False,
        },
        "mixPlay": {
            "enabled": bool(opts.mix_enabled),
            "dailyRecommendRatio": float(opts.mix_ratio),
            "countTarget": bool(opts.count_target_for_mix),
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
        "task": {
            "sign": False,
            "playids": False,
            "musician-sign": False,
            "musician-vip": False,
            "note": False,
            "fansgroup": False,
        },
    }


async def _write_temp_config(config_path: Path, cookie_file: Path, database_dir: Path, opts: PlayidsOptions) -> None:
    text = yaml.safe_dump(_build_temp_config(cookie_file, database_dir, opts), allow_unicode=True, sort_keys=False)
    await asyncio.to_thread(config_path.write_text, text, "utf-8")


def _build_ncmm_command(home_dir: Path, cookie_file: Path, config_path: Path, opts: PlayidsOptions) -> list[str]:
    prefix = [str(NCMM_BIN)] if NCMM_BIN.is_file() else ["go", "run", "."]
    command = [
        *prefix,
        "--home",
        str(home_dir),
        "--config",
        str(config_path),
        "playids",
        "--cookie-file",
        str(cookie_file),
        "--run-min",
        str(opts.run_min),
        "--run-max",
        str(opts.run_max),
        "--gap-min",
        str(opts.gap_min),
        "--gap-max",
        str(opts.gap_max),
    ]
    if opts.daily_min > 0:
        command.extend(["--daily-min", str(opts.daily_min)])
    if opts.daily_max > 0:
        command.extend(["--daily-max", str(opts.daily_max)])
    if opts.ids:
        command.extend(["--ids", ",".join(str(track_id) for track_id in opts.ids)])
    if opts.ids_file:
        if isinstance(opts.ids_file, list):
            for ids_file in opts.ids_file:
                text = str(ids_file).strip()
                if text:
                    command.extend(["--ids-file", text])
        else:
            text = str(opts.ids_file).strip()
            if text:
                command.extend(["--ids-file", text])
    has_ids = bool(opts.ids)
    has_ids_file = bool(opts.ids_file and (opts.ids_file if not isinstance(opts.ids_file, list) else [str(item).strip() for item in opts.ids_file if str(item).strip()]))
    if not has_ids and not has_ids_file:
        raise RuntimeError("当前 playids 已收口为 ncmm 显式歌曲池模式，请传 ids 或 ids_file")
    return command


async def _run_ncmm_command(command: list[str]) -> tuple[int, str, str]:
    completed = await run_ncmm_subprocess(command, cwd=NCMM_PROJECT_DIR)
    return completed.returncode, completed.stdout, completed.stderr


async def _persist_latest_run_artifacts(workdir: Path, latest_dir: Path) -> None:
    await asyncio.to_thread(shutil.rmtree, latest_dir, True)
    await asyncio.to_thread(shutil.copytree, workdir, latest_dir)


def _parse_ncmm_output(stdout: str) -> dict[str, int | None]:
    run_target = None
    submitted = None
    success = None
    daily_completed = None
    daily_target = None

    if match := _RUN_TARGET_RE.search(stdout):
        run_target = int(match.group(1))
    if match := _SUCCESS_RE.search(stdout):
        submitted = int(match.group(1))
        success = int(match.group(2))
    daily_matches = list(_DAILY_RE.finditer(stdout))
    if daily_matches:
        last = daily_matches[-1]
        daily_completed = int(last.group(1))
        daily_target = int(last.group(2))
    return {
        "run_target": run_target,
        "submitted": submitted,
        "success": success,
        "daily_completed": daily_completed,
        "daily_target": daily_target,
    }


async def run_playids_via_ncmm(user: UserRecord, opts: PlayidsOptions) -> dict[str, object]:
    if not NCMM_BIN.is_file() and not NCMM_PROJECT_DIR.is_dir():
        raise RuntimeError(f"ncmm 项目目录不存在: {NCMM_PROJECT_DIR}")
    if not (user.music_u or "").strip():
        raise RuntimeError("当前用户缺少 MUSIC_U，无法转调 ncmm")

    workdir = _build_bridge_workdir(user)
    home_dir = _ncmm_home_dir_for_user(user)
    latest_dir = _latest_bridge_dir(user)
    database_dir = _persistent_bridge_database_dir(user)
    cookie_import_file = await _write_temp_cookie_file(user, workdir)
    cookie_file = _normalized_cookie_output_path(cookie_import_file)
    config_path = workdir / "config.yaml"
    effective_opts = await _prepare_effective_playids_options(workdir, opts)
    await _write_temp_config(config_path, cookie_file, database_dir, effective_opts)
    login_command = _build_ncmm_login_command(home_dir, cookie_import_file, cookie_file, config_path)
    command = _build_ncmm_command(home_dir, cookie_file, config_path, effective_opts)
    ncmm_log_path = workdir / "ncmm.log"
    try:
        login_code, login_stdout, login_stderr = await _run_ncmm_command(login_command)
        if login_code != 0:
            await _persist_latest_run_artifacts(workdir, latest_dir)
            raise RuntimeError(
                f"ncmm login 执行失败(exit={login_code})\nSTDOUT:\n{login_stdout}\nSTDERR:\n{login_stderr}"
            )
        returncode, stdout, stderr = await _run_ncmm_command(command)
        await _persist_latest_run_artifacts(workdir, latest_dir)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass

    if returncode != 0:
        raise RuntimeError(
            f"ncmm 执行失败(exit={returncode})\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
        )
    if match := _ACCOUNT_ERROR_RE.search(stdout):
        raise RuntimeError(f"ncmm 账号执行失败: {match.group(1)}")

    parsed = _parse_ncmm_output(stdout)
    submitted = int(parsed["submitted"] or 0)
    success = int(parsed["success"] or 0)
    return {
        "code": 200,
        "status": "ok",
        "backend": "ncmm",
        "mode": "explicit_ids" if opts.ids else "ids_file",
        "run_target": parsed["run_target"],
        "submitted": submitted,
        "success": success,
        "failed": max(0, submitted - success),
        "counted_success": success,
        "total_success": success,
        "daily_completed": parsed["daily_completed"],
        "daily_target": parsed["daily_target"],
        "generated_ids_file": str((latest_dir / "generated-inline-ids.txt").resolve()) if len(list(opts.ids or [])) > NCMM_IDS_INLINE_LIMIT else None,
        "login_command": login_command,
        "stdout": stdout,
        "stderr": stderr,
        "command": command,
        "log_path": str((latest_dir / "ncmm.log").resolve()),
        "config_path": str((latest_dir / "config.yaml").resolve()),
        "cookie_path": str((latest_dir / cookie_file.name).resolve()),
        "runtime_log_path": str(ncmm_log_path.resolve()),
        "ncmm_home_dir": str(home_dir.resolve()),
    }


def _normalize_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_track_ids_from_text(raw: str) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for line in raw.splitlines():
        segment = line.split("#", 1)[0].strip()
        if not segment:
            continue
        for token in re.split(r"[,\s]+", segment):
            if not token:
                continue
            try:
                value = int(token)
            except ValueError:
                continue
            if value not in seen:
                seen.add(value)
                out.append(value)
    return out


def _resolve_batch_config_path(config_path: str) -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _build_options_from_mapping(mapping: dict[str, object], mix_mapping: dict[str, object] | None = None) -> PlayidsOptions:
    mix_mapping = mix_mapping or {}
    raw_ids = mapping.get("ids")
    ids: list[int]
    if isinstance(raw_ids, list):
        ids = [
            int(item)
            for item in raw_ids
            if str(item).strip().isdigit()
        ]
    elif isinstance(raw_ids, str):
        ids = _parse_track_ids_from_text(raw_ids)
    else:
        ids = []
    return PlayidsOptions(
        count=_normalize_int(mapping.get("count"), 300),
        ids=ids,
        ids_file=mapping.get("ids_file") or mapping.get("idsFile"),
        playlist_id=_normalize_int(mapping.get("playlist_id"), 0) or None,
        track_pool=str(mapping.get("track_pool") or "toplist").strip() or "toplist",
        rotate_playlists=bool(mapping.get("rotate_playlists", False)),
        daily_min=_normalize_int(mapping.get("daily_min"), 50),
        daily_max=_normalize_int(mapping.get("daily_max"), 200),
        run_min=_normalize_int(mapping.get("run_min"), 0),
        run_max=_normalize_int(mapping.get("run_max"), 0),
        gap_min=_normalize_int(mapping.get("gap_min"), 10),
        gap_max=_normalize_int(mapping.get("gap_max"), 30),
        mix_enabled=bool(mapping.get("mix_enabled", mix_mapping.get("enabled", True))),
        mix_ratio=float(mapping.get("mix_ratio", mix_mapping.get("dailyRecommendRatio", 0.3)) or 0.3),
        count_target_for_mix=bool(mapping.get("count_target_for_mix", mix_mapping.get("countTarget", False))),
        source=str(mapping.get("source") or "").strip() or None,
        source_id=str(mapping.get("source_id") or "").strip() or None,
        content=str(mapping.get("content") or ""),
        content_empty=bool(mapping.get("content_empty", False)),
        end=str(mapping.get("end") or "playend").strip() or "playend",
        print_weblog_response=bool(mapping.get("print_weblog_response", False)),
    )


def _load_batch_tasks_from_user_list(payload: dict[str, object]) -> list[PlayidsAccountTask]:
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        return []
    tasks: list[PlayidsAccountTask] = []
    for item in accounts:
        if not isinstance(item, dict):
            continue
        tasks.append(PlayidsAccountTask.model_validate(item))
    return tasks


def _extract_user_id_from_account_entry(entry: object) -> str:
    if isinstance(entry, dict):
        for key in ("user_id", "userId", "uid"):
            value = str(entry.get(key) or "").strip()
            if value:
                return value
    return ""


def _extract_enabled_account_entries(accounts_cfg: dict[str, object]) -> tuple[object, list[object]]:
    main_entry = accounts_cfg.get("main") or accounts_cfg.get("primary") or ""
    secondary_raw = accounts_cfg.get("secondary") or []
    secondary_entries = secondary_raw if isinstance(secondary_raw, list) else []
    return main_entry, secondary_entries


def _resolve_ncmm_user_mapping(accounts_cfg: dict[str, object]) -> tuple[str, list[str]]:
    main_entry, secondary_entries = _extract_enabled_account_entries(accounts_cfg)
    main_user_id = str(accounts_cfg.get("main_user_id") or accounts_cfg.get("primary_user_id") or "").strip()
    if not main_user_id:
        main_user_id = _extract_user_id_from_account_entry(main_entry)

    secondary_user_ids_raw = accounts_cfg.get("secondary_user_ids") or []
    if isinstance(secondary_user_ids_raw, str):
        secondary_user_ids = [secondary_user_ids_raw.strip()] if secondary_user_ids_raw.strip() else []
    elif isinstance(secondary_user_ids_raw, list):
        secondary_user_ids = [str(item).strip() for item in secondary_user_ids_raw if str(item).strip()]
    else:
        secondary_user_ids = []
    if not secondary_user_ids:
        secondary_user_ids = [
            user_id
            for user_id in (_extract_user_id_from_account_entry(item) for item in secondary_entries)
            if user_id
        ]
    return main_user_id, secondary_user_ids


def _load_batch_tasks_from_ncmm_style(payload: dict[str, object], *, use_all_users: bool, strict_user_mapping: bool) -> list[PlayidsAccountTask]:
    accounts_cfg = payload.get("accounts")
    playids_cfg = payload.get("playids")
    mix_cfg = payload.get("mixPlay")
    if not isinstance(accounts_cfg, dict) or not isinstance(playids_cfg, dict):
        return []

    selected_user_ids: list[str] = []
    main_entry, secondary_entries = _extract_enabled_account_entries(accounts_cfg)
    main_user_id, secondary_user_ids = _resolve_ncmm_user_mapping(accounts_cfg)
    if use_all_users:
        selected_user_ids = [str(item.get("user_id") or "").strip() for item in list_users_public() if str(item.get("user_id") or "").strip()]
    else:
        if playids_cfg.get("enableMain") and main_user_id:
            selected_user_ids.append(main_user_id)
        if playids_cfg.get("enableSecondaries") and secondary_user_ids:
            selected_user_ids.extend(secondary_user_ids)

        if strict_user_mapping:
            missing_parts: list[str] = []
            if playids_cfg.get("enableMain") and not main_user_id:
                missing_parts.append("main")
            if playids_cfg.get("enableSecondaries") and secondary_entries and len(secondary_user_ids) < len(secondary_entries):
                missing_parts.append("secondary")
            if missing_parts:
                joined = ", ".join(missing_parts)
                raise RuntimeError(
                    "strict_user_mapping=true 时，启用的账号必须显式提供 user_id 映射；缺失映射的分组: "
                    f"{joined}。可使用 accounts.main_user_id / secondary_user_ids，或在 accounts.main / secondary 条目内直接填写 user_id"
                )

        if not selected_user_ids:
            main_path = str(main_entry).strip() if isinstance(main_entry, str) else ""
            secondary_count = len(secondary_entries)
            user_rows = list_users_public()
            if playids_cfg.get("enableMain") and user_rows:
                selected_user_ids.append(str(user_rows[0].get("user_id") or "").strip())
            if playids_cfg.get("enableSecondaries") and secondary_count > 0:
                for row in user_rows[1 : 1 + secondary_count]:
                    uid = str(row.get("user_id") or "").strip()
                    if uid:
                        selected_user_ids.append(uid)
            if not selected_user_ids and main_path and user_rows:
                selected_user_ids.append(str(user_rows[0].get("user_id") or "").strip())

    selected_user_ids = [uid for uid in selected_user_ids if uid]
    if not selected_user_ids:
        return []

    task_mapping: dict[str, object] = {
        "count": _normalize_int(playids_cfg.get("run_max"), 0) or 300,
        "ids": playids_cfg.get("ids"),
        "ids_file": playids_cfg.get("idsFile"),
        "daily_min": _normalize_int(playids_cfg.get("daily_min"), 50),
        "daily_max": _normalize_int(playids_cfg.get("daily_max"), 200),
        "run_min": _normalize_int(playids_cfg.get("run_min"), 0),
        "run_max": _normalize_int(playids_cfg.get("run_max"), 0),
        "gap_min": _normalize_int(playids_cfg.get("gap_min"), 10),
        "gap_max": _normalize_int(playids_cfg.get("gap_max"), 30),
        "track_pool": "toplist",
        "mix_enabled": bool((mix_cfg or {}).get("enabled", True)) if isinstance(mix_cfg, dict) else True,
        "mix_ratio": (mix_cfg or {}).get("dailyRecommendRatio", 0.3) if isinstance(mix_cfg, dict) else 0.3,
        "count_target_for_mix": bool((mix_cfg or {}).get("countTarget", False)) if isinstance(mix_cfg, dict) else False,
    }
    options = _build_options_from_mapping(task_mapping, mix_cfg if isinstance(mix_cfg, dict) else None)
    return [
        PlayidsAccountTask(
            user_id=user_id,
            enabled=True,
            playids=options,
        )
        for user_id in selected_user_ids
    ]


def load_playids_batch_tasks(config_path: str, *, use_all_users: bool = False, strict_user_mapping: bool = False) -> list[PlayidsAccountTask]:
    path = _resolve_batch_config_path(config_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"配置文件不是对象结构: {path}")
    tasks = _load_batch_tasks_from_user_list(payload)
    if not tasks:
        tasks = _load_batch_tasks_from_ncmm_style(payload, use_all_users=use_all_users, strict_user_mapping=strict_user_mapping)
    if not tasks:
        raise RuntimeError("配置文件既不是 accounts 任务列表，也未能解析为 ncmm-main 风格 playids 配置")
    return tasks


async def run_playids_batch_via_ncmm(config_path: str, only_user_ids: list[str] | None = None, *, use_all_users: bool = False, strict_user_mapping: bool = False) -> dict[str, object]:
    tasks = load_playids_batch_tasks(config_path, use_all_users=use_all_users, strict_user_mapping=strict_user_mapping)
    selected = set((only_user_ids or []))
    outputs: list[dict[str, object]] = []

    for task in tasks:
        if not task.enabled:
            continue
        if selected and task.user_id not in selected:
            continue
        user = load_user(task.user_id)
        if user is None:
            outputs.append({
                "user_id": task.user_id,
                "code": 404,
                "status": "user_not_found",
            })
            continue
        result = await run_playids_via_ncmm(
            user,
            PlayidsOptions(**task.playids.model_dump(exclude={"backend"})),
        )
        outputs.append({"user_id": task.user_id, **result})

    return {"code": 200, "accounts": outputs, "config_path": str(_resolve_batch_config_path(config_path))}