<p align="center">
  <h1 align="center">🎵 NetEase Cloud Music API</h1>
</p>

<p align="center">
  <b>Automate daily song listening and more via NetEase Cloud Music's official interface</b>
</p>

<p align="center">
  📝 English&nbsp;&nbsp;|&nbsp;&nbsp;<a href="README.md">📝 中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-green" />
  <img src="https://img.shields.io/badge/Async-httpx-orange" />
</p>

---

## ✨ Features

| Feature | Description | Endpoint |
|---------|-------------|----------|
| 🌐 Browser QR Login | Controlled browser fetches the QR code and exports the full cookie jar | `POST /api/login/browser-qrcode/create`, `POST /api/login/browser-qrcode/poll` |
| 👥 Multi-user | Successful login returns `user_id`; sessions stored under `user_data/{user_id}.json`; same `MUSIC_U` merges the same user | All business APIs under `/api/users/{user_id}/...` |
| ✅ Login Check | Verify NetEase session for a stored user | `GET /api/users/{user_id}/check` |
| 📅 Normal sign-in | Simulate web sign-in (auto type fallback) | `POST /api/users/{user_id}/sign-test` |
| 📊 User Level & Plays | Level, play/login progress | `GET /api/users/{user_id}/level` |
| 👤 User Detail | Query user profile | `GET /api/users/{user_id}/detail/{uid}` |
| 🎧 Playids | Real playback + weblog reporting for one account | `POST /api/users/{user_id}/playids` |
| 🗂️ Playids batch | Run YAML-defined tasks for multiple `user_id`s | `POST /api/playids/batch` |
| 🧩 Ncmm Task Orchestration | Run `ncmm task` subtasks with the current Web user's login state | `POST /api/users/{user_id}/ncmm/task` |
| 🎖️ Musician Tasks | Run `ncmm musician` / `musician-sign` / `musician-vip` with the current Web user's login state | `POST /api/users/{user_id}/ncmm/musician` |
| 🌐 Web UI & admin | `/` login; `/admin` lists users, remarks, delete | `GET /`, `GET /admin` |

## 🚀 Quick Start

### Requirements

- Python 3.10+
- pip

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Jesseovo/netease-cloud.git
cd netease-cloud

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Configure environment
cp .env.example .env

# 4. Start the server
python run.py
```

Open `http://127.0.0.1:18473/` after starting the server.

## 🐳 Docker Runtime

The current `ncmm` bridge does not call a remote HTTP service. It executes `NCMM_BIN` directly, or falls back to `go run .` on the server side. For Docker, the most stable approach is therefore:

- copy the Linux `ncmm` binary from the upstream image `ghcr.io/3899/ncmm:latest`
- run that binary directly inside the `netease-cloud-main` container
- mount both `user_data` and the `ncmm` workspace root to the host so login state, bridge config, and runtime cache persist

This repository already includes:

- `Dockerfile`: installs Python + Playwright and copies the upstream `ncmm` binary
- `docker-compose.yml`: builds directly from the current repository
- `.env.docker.example`: Docker-specific environment template, separate from local Windows `.env`

### Repository Scope

The Docker setup only depends on this repository. You do not need to upload `ncmm-main` alongside it:

```text
C:\projects\netease-cloud-main
```

### First Start

All local paths below are examples. Replace them with your own real directories.

From `C:\projects\netease-cloud-main`:

```bash
cp .env.docker.example .env.docker
docker compose up --build -d
```

Before starting, at minimum update these values in `.env.docker`:

- `ADMIN_PASSWORD`
- `SESSION_SECRET`
- `PROXY_URL` if your WeAPI or post-login requests must use a proxy

Then visit:

```text
http://127.0.0.1:18473/
```

### Docker Environment Notes

- Local Windows runtime: keep using `.env`
- Docker container runtime: use `.env.docker`

`docker-compose.yml` explicitly loads `.env.docker`, so host-side Windows paths from `.env` are not accidentally injected into the container.

`NCMM_PROJECT_DIR` stays `/opt/ncmm` inside the container. This is not a source dependency; the current bridge only uses it as the subprocess working directory, so the container pre-creates that empty directory.

### Default Container Paths

Inside the container, these Linux paths are used instead of Windows paths:

```env
USER_DATA_DIR=/data/user_data
NCMM_PROJECT_DIR=/opt/ncmm
NCMM_BIN=/usr/local/bin/ncmm
NCMM_HOME_DIR=/data/ncmm-home
```

These are already set in `docker-compose.yml`, so do not copy host Windows paths directly into the container environment.

### Persistent Data

Compose mounts these paths by default:

- `./user_data:/data/user_data`: Web login state and user data
- `./docker-data/ncmm-home:/data/ncmm-home`: `ncmm` workspace, converted cookies, and runtime cache, separated by `user_id`

### Migrate Older Layouts

If you ran an older version before, the `ncmm` workspace may still be under `user_data/ncmm_workspaces/<user_id>`. After moving to the new image, migrate it into `NCMM_HOME_DIR` first:

```bash
mkdir -p ./docker-data/ncmm-home
cp -a ./user_data/ncmm_workspaces/. ./docker-data/ncmm-home/
```

### Logs, Stop, and Update

```bash
docker compose logs -f
docker compose down
docker compose build --pull
docker compose up -d
```

If you want to pin a specific upstream `ncmm` version, replace `ghcr.io/3899/ncmm:latest` in `Dockerfile` with a fixed tag.

## 📖 API Documentation

`/docs` and `/redoc` require an admin session cookie. The same cookie is needed for `curl` calls to `/api/users/...`.

### Endpoint Details

#### 🌐 Browser QR login

The service now exposes a single login flow: a controlled browser opens the NetEase login page, extracts the QR code, and the current page displays it locally. After scan confirmation, the service exports the full cookie jar for the `music.163.com` domain and stores it in `user_data/{user_id}.json`.

A successful login response includes **`user_id`**; all sign-in, query, and `playids` calls use **`/api/users/{user_id}/...`**. Data is stored under **`user_data/`** by default (override with **`USER_DATA_DIR`**).

Set **`PROXY_URL`** in `.env` (e.g. `http://user:pass@host:port`) so post-login **WeAPI (httpx)** requests use the same proxy; omit it for a direct connection.

This flow is intended to stay as close as possible to a real `https://music.163.com/` browser login cookie set:

Fingerprint, UA, weblog URL, and other env vars are listed in `.env.example`.

#### 🌐 Browser QR login and full cookie export

1. Create a controlled-browser QR session:

```
POST /api/login/browser-qrcode/create
```

You can optionally send an account role; the default is `main`:

```json
{ "account_role": "main" }
```

- `main`: primary account
- `secondary`: secondary account

The response contains **`session_id`**. The server opens the NetEase login page in a controlled browser and returns the extracted QR code for display.

2. Poll the login status:

```
POST /api/login/browser-qrcode/poll
{ "session_id": "<session_id>" }
```

When **`code` is `803`**, the service has exported the full `music.163.com` cookie jar from the browser context and stored it in `user_data/{user_id}.json`. The response also returns a **`cookies`** field.

Before first use, install the Playwright browser runtime:

```bash
pip install -r requirements.txt
playwright install chromium
```

#### ✅ Check Login Status

```
GET /api/users/{user_id}/check
```

#### 📅 Normal sign-in (auto fallback)

```
POST /api/users/{user_id}/sign-test
```

Falls back from `type=0` to `type=1` when needed. Response `status`: `signed_today` / `already_signed` / `unsupported` / `failed`.

#### 👤 User Detail

```
GET /api/users/{user_id}/detail/12345678
```

#### 🎧 Playids

```
POST /api/users/{user_id}/playids
```

Single-account `playids` is now fully routed through the `ncmm-main` bridge, so requests should explicitly provide `ids` or `ids_file`.

Typical request fields:

- `ids`: explicit song ID list
- `ids_file`: local text file or `http/https` URL containing song IDs
- `idsFile`: compatible YAML field name for batch configs; treated the same as `ids_file`
- `playlist_id`: a single NetEase playlist ID; the backend resolves it into an explicit song pool first
- `playlist_ids`: multiple NetEase playlist IDs; the backend resolves and de-duplicates them before execution
- `count`: candidate song collection size; explicit `ids` mode usually gets aligned to the actual number of songs
- `daily_min` / `daily_max`: random daily target range
- `run_min` / `run_max`: random per-run target range
- `gap_min` / `gap_max`: random delay seconds between tracks
- `mix_enabled` / `mix_ratio`: whether to mix in daily recommendations and at what ratio

Priority rules:

- prefer explicit song pools: `ids` or `ids_file`
- if no explicit song pool is provided, you can still pass `playlist_id` or `playlist_ids`, and the backend will resolve them into explicit track IDs first
- `track_pool` and `rotate_playlists` are still accepted for compatibility, but they are no longer the main input path in the current `ncmm`-based flow

`ids` supports two common forms:

- array form in the API body: `[12345, 67890]`
- `ncmm-main` style string form in YAML: `"12345,67890\n24680"`

`ids_file` / `idsFile` supports:

- local text file paths
- remote `http/https` text URLs
- a single string or a list of strings in batch YAML

The text format is intentionally loose: line breaks, whitespace, and commas are all accepted as separators, and anything after `#` is ignored as a comment. Example:

```text
12345,67890
24680
13579 # trailing text is ignored
```

If the explicit song pool contains fewer unique songs than the requested `count`, the request fails directly instead of falling back to playlist-based collection.

Playlist-based example:

```json
{
  "playlist_ids": [1234567890, 2234567890],
  "count": 200,
  "mix_enabled": false
}
```

#### 🗂️ Playids batch

```
POST /api/playids/batch
{
  "config_path": "./playids_tasks.yaml",
  "only_user_ids": ["your_user_id_1"],
  "strict_user_mapping": true
}
```

Request fields:

- `config_path`: YAML batch config path
- `only_user_ids`: optional list of local `user_id`s to run
- `strict_user_mapping`: in `ncmm-main` compatibility mode, require explicit `user_id` mapping in the config
- `use_all_users`: in `ncmm-main` compatibility mode, scan all local `user_id`s as a fallback mode

Example batch config:

```yaml
accounts:
  - user_id: "your_user_id_1"
    enabled: true
    playids:
      ids:
        - 3373818852
        - 3373845775
      daily_min: 80
      daily_max: 150
      run_min: 20
      run_max: 40
      gap_min: 10
      gap_max: 25
      mix_enabled: true
      mix_ratio: 0.3

  - user_id: "your_user_id_2"
    enabled: true
    playids:
      ids_file: "https://example.com/song_ids.txt"
      count: 200
      mix_enabled: false
```

The bridge also supports an `ncmm-main`-style top-level config:

```yaml
accounts:
  main:
    cookie: "./cookie.json"
    user_id: "your_main_user_id"
  secondary:
    - cookie: "./fan1.json"
      user_id: "your_secondary_user_id_1"
    - cookie: "./fan2.json"
      user_id: "your_secondary_user_id_2"

playids:
  enableMain: false
  enableSecondaries: true
  daily_min: 50
  daily_max: 200
  run_min: 0
  run_max: 0
  gap_min: 10
  gap_max: 30
  idsFile:
    - "https://example.com/song_ids.txt"

mixPlay:
  enabled: true
  dailyRecommendRatio: 0.3
  countTarget: false
```

#### 🧩 Ncmm task orchestration

```
POST /api/users/{user_id}/ncmm/task
```

Request example:

```json
{
  "sign": true,
  "playids": false,
  "musician_sign": false,
  "musician_vip": false,
  "note": false,
  "fansgroup": false
}
```

Notes:

- this endpoint temporarily converts the current Web user's login state into an `ncmm-main` compatible cookie file
- the server generates a minimal `config.yaml` and then runs `ncmm task`
- if `.env` defines `NCMM_BIN` and the file exists, the bridge uses the compiled binary directly; otherwise it falls back to `go run .`
- at least one subtask must be enabled, or the endpoint returns `400`
- if `playids` is enabled, `playids_options` must also provide an explicit song pool or playlist-resolution parameters
- the response includes `successful_tasks`, `failed_tasks`, `stdout`, and `stderr` for troubleshooting

#### 🧪 Ncmm direct subcommands

```
POST /api/users/{user_id}/ncmm/command
```

Request example:

```json
{
  "command": "sign"
}
```

Currently supported subcommands:

- `sign`
- `note`
- `fansgroup`

This endpoint directly bridges a single `ncmm` subcommand using the current Web user's login state.

#### 🎖️ Musician tasks

```
POST /api/users/{user_id}/ncmm/musician
```

Request example:

```json
{
  "mode": "musician-sign"
}
```

Supported `mode` values:

- `musician`
- `musician-sign`
- `musician-vip`

Notes:

- this endpoint reuses the current Web user's login state and bridges it into `ncmm-main`
- if the current account is not a musician account, `ncmm-main` returns the business error and the API converts it into `400`

#### 🧰 Ncmm bridge runtime

Default bridge directories:

- `NCMM_PROJECT_DIR` defaults to `../ncmm-main`
- `NCMM_HOME_DIR` defaults to `NCMM_PROJECT_DIR/.work` and is used as the multi-user workspace root for `ncmm`
- `NCMM_BIN` defaults to `NCMM_PROJECT_DIR/bin/ncmm.exe`

Recommended workflow: build the executable in `ncmm-main` first:

```powershell
cd C:\projects\ncmm-main
go build -o bin/ncmm.exe .
```

Then configure these variables in the current project's `.env`:

```env
NCMM_PROJECT_DIR=C:\projects\ncmm-main
NCMM_BIN=C:\projects\ncmm-main\bin\ncmm.exe
NCMM_HOME_DIR=C:\projects\ncmm-main\.work
```

`NCMM_HOME_DIR` now means the workspace root rather than a single-account directory. The service automatically uses `NCMM_HOME_DIR/<user_id>` as each account's `ncmm --home` directory.

To keep bridge resource usage under control, the runtime also provides these optional environment variables:

- `NCMM_MAX_CONCURRENT`: max concurrent `ncmm` subprocesses in a single process; default `2`
- `NCMM_MAX_OUTPUT_CHARS`: max `stdout/stderr` characters retained in API responses per subprocess; default `12000`
- `NCMM_IDS_INLINE_LIMIT`: when explicit song IDs exceed this count, the bridge writes them to a temporary `ids_file` to avoid oversized command lines; default `1000`

#### 📊 Query Play Record

```
GET /api/users/{user_id}/play-record?record_type=1
```

- `uid`: user ID (optional; if omitted, uses current logged-in account)
- `record_type`: `0=all time`, `1=last week` (default: 1)

### 🧪 curl Examples (Windows CMD)

Replace **`YOUR_USER_ID`** with the login `user_id` and send the admin cookie (e.g. `-b` with a saved cookie file).

#### 1) Check NetEase session for that user

```bash
curl "http://127.0.0.1:18473/api/users/YOUR_USER_ID/check"
```

#### 2) Playids

```bash
curl -X POST "http://127.0.0.1:18473/api/users/YOUR_USER_ID/playids" \
  -H "Content-Type: application/json" \
  -d "{\"ids\":[3373818852,3373845775],\"mix_enabled\":false,\"gap_min\":5,\"gap_max\":10}"
```

#### 3) Query play record

```bash
curl "http://127.0.0.1:18473/api/users/YOUR_USER_ID/play-record"
```

All-time record:

```bash
curl "http://127.0.0.1:18473/api/users/YOUR_USER_ID/play-record?record_type=0"
```

## 🏗️ Project Structure

```
netease-cloud/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── crypto.py
│   ├── client.py
│   ├── user_store.py
│   ├── deps.py
│   ├── templates/
│   ├── routers/
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── music.py
│   │   ├── ncmm_tasks.py
│   │   ├── playids_batch.py
│   │   └── ui.py
│   └── models/
│       └── schemas.py
├── user_data/
├── run.py
├── requirements.txt
├── .env.example
└── README.md
```

## 🔧 Improvements Over Legacy

| Aspect | Legacy (PHP) | New (Python/FastAPI) |
|--------|-------------|----------------------|
| ⚡ Concurrency | curl_multi (blocking) | asyncio + httpx (true async) |
| 📦 Structure | Single file ~600 lines | Modular layered architecture |
| 🔒 Type Safety | None | Pydantic model validation |
| 📖 Documentation | None | Auto-generated Swagger / ReDoc |
| 🛡️ Error Handling | Almost none | Unified exception middleware |
| 🔑 Security | Plain-text cookies | Per-user JSON on disk + path-scoped APIs |

## 📜 Inspired By

- [Binaryify/NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [ZainCheung/netease-cloud-api](https://github.com/ZainCheung/netease-cloud-api)

## ⚠️ Disclaimer

All scripts and software in this project are **for personal learning and development testing only**. All `NetEase Cloud` related trademarks belong to NetEase, Inc. Do not use for commercial or illegal purposes. The author is not responsible for any legal disputes.

## 📄 License

[MIT License](LICENSE)
