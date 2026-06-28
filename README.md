<p align="center">
  <h1 align="center">🎵 网易云音乐升级 API</h1>
</p>

<p align="center">
  <b>通过调用官方接口，实现网易云音乐每日自动刷歌等功能</b>
</p>

<p align="center">
  <a href="README_EN.md">📝 English</a>&nbsp;&nbsp;|&nbsp;&nbsp;📝 中文
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/License-MIT-green" />
  <img src="https://img.shields.io/badge/Async-httpx-orange" />
</p>

---

## ✨ 功能特性

| 功能 | 描述 | 接口 |
|------|------|------|
| 🌐 浏览器扫码登录 | 受控浏览器获取二维码并导出完整 Cookie | `POST /api/login/browser-qrcode/create`、`POST /api/login/browser-qrcode/poll` |
| 👥 多用户 | 登录成功返回 `user_id`，会话写入 `user_data/{user_id}.json`；相同 `MUSIC_U` 再次登录会合并同一用户 | 见下表路径前缀 `/api/users/{user_id}` |
| ✅ 登录检查 | 校验某本地用户绑定的网易云会话 | `GET /api/users/{user_id}/check` |
| 📅 普通签到 | 模拟网页签到（自动 type 回退） | `POST /api/users/{user_id}/sign-test` |
| 📊 用户等级与听歌量 | 等级、听歌/登录进度 | `GET /api/users/{user_id}/level` |
| 👤 用户详情 | 查询用户信息 | `GET /api/users/{user_id}/detail/{uid}` |
| 🎧 Playids 刷歌 | 单账号真实播放 + weblog 上报 | `POST /api/users/{user_id}/playids` |
| 🗂️ Playids 批量任务 | 按 YAML 配置批量执行多个 `user_id` 任务 | `POST /api/playids/batch` |
| 🧩 Ncmm Task 编排 | 以当前 Web 用户登录态执行 `ncmm task` 子任务 | `POST /api/users/{user_id}/ncmm/task` |
| 🎖️ 音乐人任务 | 以当前 Web 用户登录态执行 `ncmm musician` / `musician-sign` / `musician-vip` | `POST /api/users/{user_id}/ncmm/musician` |
| 🌐 网页登录与后台 | `/` 登录；`/admin` 管理用户列表、备注、删除 | `GET /`、`GET /admin` |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- pip

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/Jesseovo/netease-cloud.git
cd netease-cloud

# 2. 安装依赖
pip install -r requirements.txt

# 3. (可选) 配置环境变量
cp .env.example .env

# 4. 启动服务
python run.py
```

服务启动后打开 `http://127.0.0.1:8080/`。

## 🐳 Docker 运行（复用官方 `ncmm` 镜像）

当前仓库里的 `ncmm` 桥接不是走 HTTP，而是直接在服务端执行 `NCMM_BIN` 或 `go run .`。因此 Docker 下最稳的方案不是把两个项目拆成两个容器互相调用，而是：

- 构建镜像时直接从官方镜像 `ghcr.io/3899/ncmm:latest` 提取 Linux 版 `ncmm` 二进制
- 在 `netease-cloud-main` 容器内直接调用这个二进制
- 把 `user_data` 和 `ncmm` 工作目录挂载到宿主机，保留登录态、桥接配置和运行缓存

仓库已附带：

- `Dockerfile`：从官方 `ncmm` 镜像复制二进制，并安装 Python + Playwright 运行环境
- `docker-compose.yml`：直接在当前仓库目录构建镜像
- `.env.docker.example`：Docker 专用环境模板，和本地 Windows `.env` 分离

### 仓库范围

这套 Docker 编排只依赖当前仓库，不再要求把 `ncmm-main` 一起上传到 GitHub：

```text
D:\py\netease-cloud-main
```

如果你用 GitHub Actions、Docker Hub、GHCR 或其他远程构建器生成镜像，只上传 `netease-cloud-main` 即可。

### GitHub 自动构建镜像

仓库已附带 [`.github/workflows/docker-image.yml`](.github/workflows/docker-image.yml)，用于通过 GitHub Actions 自动构建并推送 GHCR 镜像。

- `release created`：按 release tag 构建，并额外推送 `latest`
- `workflow_dispatch`：可手动触发，并可选传入自定义 tag

默认推送目标是：

```text
ghcr.io/<你的 GitHub 用户名或组织名>/netease-cloud-main
```

如果你想改镜像名，调整 [`.github/workflows/docker-image.yml`](.github/workflows/docker-image.yml) 里的 `IMAGE_NAME` 即可。

### 首次启动

在 `D:\py\netease-cloud-main` 下执行：

```bash
cp .env.docker.example .env.docker
```

然后至少修改 `.env.docker` 里的：

- `ADMIN_PASSWORD`
- `SESSION_SECRET`
- `PROXY_URL`（如果你的 WeAPI 或扫码后的请求必须走代理）

再执行：

```bash
docker compose up --build -d
```

启动后访问：

```text
http://127.0.0.1:8080/
```

### Docker 环境文件说明

- 本地开发 / Windows 直跑：继续使用 `.env`
- Docker 容器：使用 `.env.docker`

`docker-compose.yml` 已改为显式加载 `.env.docker`，这样不会误把宿主机 `.env` 里的 Windows 路径带进容器。

`NCMM_PROJECT_DIR` 在容器里仍然保留为 `/opt/ncmm`。这不是源码目录依赖，而是当前桥接实现会把它当作子进程工作目录使用，所以容器里会预先创建这个空目录。

### 默认容器内桥接路径

容器里会自动使用下面这些 Linux 路径，不再使用 Windows 的 `D:\...`：

```env
USER_DATA_DIR=/data/user_data
NCMM_PROJECT_DIR=/opt/ncmm
NCMM_BIN=/usr/local/bin/ncmm
NCMM_HOME_DIR=/data/ncmm-home
```

这几项已经写进 `docker-compose.yml`，所以不要把宿主机 `.env` 里的 Windows 路径原样搬进容器环境。

### 数据持久化

Compose 默认挂载：

- `./user_data:/data/user_data`：Web 登录态与用户数据
- `./docker-data/ncmm-home:/data/ncmm-home`：`ncmm` 的桥接工作目录、cookie 转换结果和运行缓存

### 需要修改的配置

启动前至少应调整 `.env.docker` 中这些环境变量：

- `ADMIN_PASSWORD`
- `SESSION_SECRET`
- `PROXY_URL`（如果你的 WeAPI 或扫码后的请求必须走代理）

### 查看日志与停止

```bash
docker compose logs -f
docker compose down
```

### 更新 `ncmm`

当前镜像默认复用上游官方 `ghcr.io/3899/ncmm:latest`。如果你要拉取上游最新版本，直接重新构建即可：

```bash
docker compose build --pull
docker compose up -d
```

如果你想锁定版本，可以把 [Dockerfile](Dockerfile) 里的 `ghcr.io/3899/ncmm:latest` 改成具体标签后再构建。

## 📖 API 文档

`/docs`、`/redoc` 需先登录管理端（同一会话 Cookie）。命令行调用 `/api/users/...` 时同样需要管理员 Cookie。

### 接口详情

#### 🌐 浏览器扫码登录

当前服务只保留这一条登录链路：由服务端受控浏览器打开网易云登录页，提取登录二维码并在本地页面展示；扫码确认成功后，导出 `music.163.com` 域完整 Cookie jar，写入 `user_data/{user_id}.json`。

登录成功响应中带 **`user_id`**（32 位十六进制），后续签到、查询、`playids` 刷歌等接口均须使用该路径前缀 **`/api/users/{user_id}/`**。数据默认保存在项目目录 **`user_data/`**（可用环境变量 **`USER_DATA_DIR`** 覆盖）。

在 `.env` 中配置 **`PROXY_URL`**（例如 `http://user:pass@host:port`）后，浏览器扫码成功后的 **WeAPI（httpx）** 请求也会经该代理访问网易；不配置则直连。

#### 🌐 浏览器扫码并导出完整 Cookie

这条链路会尽量还原 `https://music.163.com/` 浏览器登录后的完整 Cookie：

1. 创建受控浏览器扫码会话：

```
POST /api/login/browser-qrcode/create
```

响应含 **`session_id`**，服务端会在后台受控浏览器里打开网易云登录页，并把提取到的二维码返回给当前页面展示。

2. 轮询受控浏览器登录状态：

```
POST /api/login/browser-qrcode/poll
{ "session_id": "<session_id>" }
```

当返回里 **`code` 为 `803`** 时，表示已从浏览器上下文导出 `music.163.com` 域完整 Cookie jar，并写入本地 `user_data/{user_id}.json`。响应同时会返回 **`cookies`** 字段。

首次使用前需要额外安装浏览器内核：

```bash
pip install -r requirements.txt
playwright install chromium
```

指纹、UA、播放日志上报等环境变量见 `.env.example`。

#### ✅ 检查登录状态

```
GET /api/users/{user_id}/check
```

#### 📅 普通签到（自动回退）

```
POST /api/users/{user_id}/sign-test
```

`type=0` 失败时回退 `type=1`。响应 `status`：`signed_today` / `already_signed` / `unsupported` / `failed`。

#### 👤 用户详情

```
GET /api/users/{user_id}/detail/12345678
```

#### 🎧 Playids 刷歌

```
POST /api/users/{user_id}/playids
```

当前单账号 `playids` 已完全收口为 `ncmm-main` 桥接模式，请求体应显式提供 `ids` 或 `ids_file`。

请求体支持这些典型字段：

- `ids`：直接指定歌曲 ID 列表
- `ids_file`：从本地文本文件或 `http/https` URL 读取歌曲 ID
- `idsFile`：批量 YAML 配置里的兼容写法，等价于 `ids_file`
- `count`：候选歌曲收集数量；显式 `ids` 模式下通常会自动对齐到歌曲数
- `daily_min` / `daily_max`：每日随机目标范围
- `run_min` / `run_max`：本次运行随机目标范围
- `gap_min` / `gap_max`：两首歌之间随机间隔秒数
- `mix_enabled` / `mix_ratio`：是否混入日推与混入比例

优先级说明：当前版本只支持显式歌曲池；必须传 `ids` 或 `ids_file`，不再回退到 `playlist_id / track_pool`。

`ids` 支持两种常见形式：

- API 请求体里直接传数组：`[12345, 67890]`
- `ncmm-main` 风格配置里传字符串：`"12345,67890\n24680"`

`ids_file` / `idsFile` 支持：

- 本地文本文件路径
- `http/https` 远程文本 URL
- 批量配置里传单个字符串或字符串数组

文本内容格式要求很宽松：按行、空格或逗号分隔都可以，`#` 后面的内容会被当作注释忽略。例如：

```text
12345,67890
24680
13579 # 这一行后半段会被忽略
```

如果显式歌曲池在去重后数量小于本次需要收集的 `count`，接口会直接报错，而不会再回退到歌单池。

#### 🗂️ Playids 批量任务

```
POST /api/playids/batch
{
  "config_path": "./playids_tasks.yaml"
}
```

配置文件示例：

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

也兼容 `ncmm-main` 的顶层配置风格：

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

#### 🧩 Ncmm Task 编排

```
POST /api/users/{user_id}/ncmm/task
```

请求体示例：

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

说明：

- 这个接口会把当前 Web 用户的登录态临时转换成 `ncmm-main` 可识别的 cookie 文件。
- 服务端会临时生成一份最小 `config.yaml`，然后执行 `ncmm task`。
- 如果 `.env` 配置了 `NCMM_BIN` 且文件存在，会优先直接调用编译好的 `ncmm.exe`；否则回退到 `go run .`。
- 至少要开启一个子任务，否则会返回 `400`。
- 返回体里会带 `successful_tasks`、`failed_tasks`、`stdout`、`stderr`，便于排查。

#### 🎖️ 音乐人任务

```
POST /api/users/{user_id}/ncmm/musician
```

请求体示例：

```json
{
  "mode": "musician-sign"
}
```

`mode` 支持：

- `musician`
- `musician-sign`
- `musician-vip`

说明：

- 这条接口与上面的 `task` 一样，复用当前 Web 用户登录态桥接到 `ncmm-main`。
- 如果当前账号不是音乐人，`ncmm-main` 会返回对应业务错误，接口会转成 `400`。

#### 🧰 Ncmm Bridge 运行方式

默认桥接目录：

- `NCMM_PROJECT_DIR` 默认指向 `../ncmm-main`
- `NCMM_HOME_DIR` 默认指向 `NCMM_PROJECT_DIR/.work`
- `NCMM_BIN` 默认指向 `NCMM_PROJECT_DIR/bin/ncmm.exe`

推荐做法是在 `ncmm-main` 下先编译 exe：

```powershell
cd D:\py\ncmm-main
go build -o bin/ncmm.exe .
```

然后在当前项目 `.env` 中显式配置：

```env
NCMM_PROJECT_DIR=D:\py\ncmm-main
NCMM_BIN=D:\py\ncmm-main\bin\ncmm.exe
NCMM_HOME_DIR=D:\py\ncmm-main\.work
```

这样 Web 端桥接 `playids`、`task`、`musician*` 时会优先直调 exe，不再依赖请求时即时 `go run` 编译。
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

另外，当前服务也支持通过环境变量 `NCMM_USER_AGENT_CONFIG` 注入 `ncmm-main` 风格的三层 UA 配置，例如：

```json
{"network":{"user_agent":{"default":"Mozilla/5.0 ...","weapi":"Mozilla/5.0 ...","eapi":"NeteaseMusic 9.4.95/6806 (iPhone; iOS 16.6.1; zh_CN)"}}}
```

其中：

- `default`：覆盖全局默认 UA
- `weapi`：作用于网页端 WeAPI 请求
- `eapi`：作用于 `player/url/v1` 这类 EAPI 请求

Windows PowerShell 示例：

```powershell
$env:NCMM_USER_AGENT_CONFIG = '{"network":{"user_agent":{"default":"Mozilla/5.0 ...","weapi":"Mozilla/5.0 ...","eapi":"NeteaseMusic 9.4.95/6806 (iPhone; iOS 16.6.1; zh_CN)"}}}'
python -m app.main
```

如果你已经有 `ncmm-main` 的 `config.yaml`，可以自行把其中 `network.user_agent` 这段转成上面的 JSON 后注入环境变量，当前版本会按这三个层级分别消费。

也支持保持 `ncmm-main` 原始 cookie 写法不变，同时额外补顶层映射：

```yaml
accounts:
  main: "./cookie.json"
  main_user_id: "your_main_user_id"
  secondary:
    - "./fan1.json"
    - "./fan2.json"
  secondary_user_ids:
    - "your_secondary_user_id_1"
    - "your_secondary_user_id_2"
```

如果使用这种 `ncmm-main` 风格配置，建议请求体里额外传：

```json
{
  "config_path": "./config.yaml",
  "strict_user_mapping": true
}
```

这样会优先使用 `main_user_id` 和 `secondary_user_ids` 做明确账号绑定，并复用 `playids + mixPlay` 的通用参数。

如果你暂时还没补 `main_user_id / secondary_user_ids`，也可以继续使用：

```json
{
  "config_path": "./config.yaml",
  "use_all_users": true
}
```

这时会扫描本地 `user_data/` 中已有账号，但这只是兼容兜底，不如显式 user_id 映射稳定。

#### 📊 查询听歌记录

```
GET /api/users/{user_id}/play-record?record_type=1
```

- `uid`：用户 ID（可选，不传则自动使用当前登录账号）
- `record_type`：`0=全部时间`，`1=最近一周`（默认 1）

### 🧪 curl 调用示例（Windows CMD）

将 **`YOUR_USER_ID`** 换成登录返回的 `user_id`，并带上管理员 Cookie（例如 `-b` 指定保存的 cookie 文件）。

#### 1) 检查该用户网易云会话

```bash
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/check"
```

#### 2) Playids 刷歌

```bash
curl -X POST "http://127.0.0.1:8080/api/users/YOUR_USER_ID/playids" ^
  -H "Content-Type: application/json" ^
  -d "{\"ids\":[3373818852,3373845775],\"mix_enabled\":false,\"gap_min\":5,\"gap_max\":10}"
```

#### 3) 查询听歌记录

```bash
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/play-record"
```

查全部时间：

```bash
curl "http://127.0.0.1:8080/api/users/YOUR_USER_ID/play-record?record_type=0"
```

## 🏗️ 项目结构

```
netease-cloud/
├── app/
│   ├── main.py          # FastAPI 应用入口
│   ├── config.py        # 配置常量
│   ├── crypto.py        # WeAPI 加密模块
│   ├── client.py        # 共享 httpx + 按用户 WeAPI 请求
│   ├── user_store.py    # 多用户 JSON 持久化
│   ├── deps.py          # 路径 user_id 依赖
│   ├── templates/       # 网页模板
│   ├── routers/
│   │   ├── auth.py      # 登录（无 user_id）
│   │   ├── user.py      # /api/users/{user_id}/check、level、detail
│   │   ├── music.py     # playids、签到相关音乐接口
│   │   └── ui.py        # 网页与 /admin/api/*
│   └── models/
│       └── schemas.py   # 数据模型
├── user_data/           # 默认用户数据目录（.gitignore）
├── run.py               # 启动脚本
├── requirements.txt     # 依赖列表
├── .env.example         # 环境变量示例
└── README.md
```

## 🔧 对比旧版的改进

| 维度 | 旧版 (PHP) | 新版 (Python/FastAPI) |
|------|-----------|----------------------|
| ⚡ 并发 | curl_multi 同步阻塞 | asyncio + httpx 真正异步 |
| 📦 结构 | 单文件 ~600 行 | 模块化分层架构 |
| 🔒 类型 | 无类型检查 | Pydantic 模型校验 |
| 📖 文档 | 无 API 文档 | 自动生成 Swagger / ReDoc |
| 🛡️ 错误 | 几乎没有 | 统一异常处理中间件 |
| 🔑 安全 | Cookie 明文传递 | 按用户落盘 JSON，接口必须带 `user_id` |

## 📜 灵感来源

- [Binaryify/NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [ZainCheung/netease-cloud-api](https://github.com/ZainCheung/netease-cloud-api)

## ⚠️ 声明

本项目的所有脚本及软件**仅用于个人学习开发测试**，所有 `网易云` 相关字样版权属于网易公司，勿用于商业及非法用途，如产生法律纠纷与本人无关。

## 📄 开源协议

[MIT License](LICENSE)
