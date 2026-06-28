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

Open `http://127.0.0.1:8080/` after starting the server.

## 📖 API Documentation

`/docs` and `/redoc` require an admin session cookie. The same cookie is needed for `curl` calls to `/api/users/...`.

### Endpoint Details

#### 🌐 Browser QR login

The service now exposes a single login flow: a controlled browser opens the NetEase login page, extracts the QR code, and the current page displays it locally. After scan confirmation, the service exports the full cookie jar for the `music.163.com` domain and stores it in `user_data/{user_id}.json`.

A successful login response includes **`user_id`**; all sign-in, query, and `playids` calls use **`/api/users/{user_id}/...`**. Data is stored under **`user_data/`** by default (override with **`USER_DATA_DIR`**).

Set **`PROXY_URL`** in `.env` (e.g. `http://user:pass@host:port`) so post-login **WeAPI (httpx)** requests use the same proxy; omit it for a direct connection.

This flow is intended to stay as close as possible to a real `https://music.163.com/` browser login cookie set:

Fingerprint, UA, weblog URL, and other env vars are listed in `.env.example`.

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
- `count`: candidate song collection size; explicit `ids` mode usually gets aligned to the actual number of songs
- `daily_min` / `daily_max`: random daily target range
- `run_min` / `run_max`: random per-run target range
- `gap_min` / `gap_max`: random delay seconds between tracks
- `mix_enabled` / `mix_ratio`: whether to mix in daily recommendations and at what ratio

Priority rule: the current version only supports explicit song pools; you must provide `ids` or `ids_file`, and it no longer falls back to `playlist_id / track_pool`.

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

#### 🗂️ Playids batch

```
POST /api/playids/batch
{
  "config_path": "./playids_tasks.yaml"
}
```

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
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/check"
```

#### 2) Playids

```bash
curl -X POST "http://127.0.0.1:8080/api/users/YOUR_USER_ID/playids" \
  -H "Content-Type: application/json" \
  -d "{\"ids\":[3373818852,3373845775],\"mix_enabled\":false,\"gap_min\":5,\"gap_max\":10}"
```

#### 3) Query play record

```bash
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/play-record"
```

All-time record:

```bash
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/play-record?record_type=0"
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
