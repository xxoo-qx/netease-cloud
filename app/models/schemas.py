from typing import Literal, Optional

from pydantic import BaseModel, Field


AccountRole = Literal["main", "secondary"]


class BrowserQrcodeCreateRequest(BaseModel):
    account_role: AccountRole = Field("main", description="扫码登录后保存的账号角色：main 或 secondary")


class BrowserQrcodePollRequest(BaseModel):
    session_id: str = Field(..., description="浏览器扫码创建接口返回的会话 ID")


class APIResponse(BaseModel):
    code: int
    message: Optional[str] = None
    data: Optional[dict] = None


class DakaResponse(BaseModel):
    code: int = 200
    count: int = 0


class PlayidsRequest(BaseModel):
    count: int = Field(300, ge=1, le=1000, description="候选歌曲收集数量；显式 ids 模式下通常会被实际歌曲数覆盖")
    ids: list[int] = Field(default_factory=list, description="直接指定歌曲 ID 列表")
    ids_file: str | list[str] | None = Field(None, description="歌曲 ID 文件或 URL；支持字符串或字符串数组")
    playlist_id: int | None = Field(None, description="单个网易云歌单 ID；会在后端解析成歌曲 ID 列表")
    playlist_ids: list[int] = Field(default_factory=list, description="多个网易云歌单 ID；后端会合并解析并对歌曲去重")
    track_pool: str = Field("toplist", description="保留字段；当前 ncmm 收口模式下不再使用")
    rotate_playlists: bool = Field(False, description="保留字段；当前 ncmm 收口模式下不再使用")
    daily_min: int = Field(50, ge=1, description="每日随机目标最小值")
    daily_max: int = Field(200, ge=1, description="每日随机目标最大值")
    run_min: int = Field(0, ge=0, description="单次运行随机目标最小值，0 表示跟随 daily 剩余额度")
    run_max: int = Field(0, ge=0, description="单次运行随机目标最大值，0 表示跟随 daily 剩余额度")
    gap_min: int = Field(10, ge=0, description="两首歌之间随机间隔最小秒数")
    gap_max: int = Field(30, ge=0, description="两首歌之间随机间隔最大秒数")
    mix_enabled: bool = Field(True, description="是否启用日推混听")
    mix_ratio: float = Field(0.3, ge=0.0, le=1.0, description="日推混听占比")
    count_target_for_mix: bool = Field(False, description="混听歌曲是否计入目标完成数")
    source: str | None = Field(None, description="覆盖 weblog source")
    source_id: str | None = Field(None, description="覆盖 weblog sourceId")
    content: str = Field("", description="覆盖 weblog content")
    content_empty: bool = Field(False, description="强制 weblog content 为空")
    end: str = Field("playend", description="weblog 结束态")
    print_weblog_response: bool = Field(False, description="是否打印每次 weblog 响应")


class PlayidsBatchRequest(BaseModel):
    config_path: str = Field(..., description="批量任务配置文件路径，支持 YAML")
    only_user_ids: list[str] = Field(default_factory=list, description="可选：仅执行这些 user_id")
    use_all_users: bool = Field(False, description="仅对 ncmm-main 兼容模式有效：为 true 时扫描本地全部 user_id")
    strict_user_mapping: bool = Field(False, description="仅对 ncmm-main 兼容模式有效：要求配置里显式提供 user_id 映射")


class PlayidsAccountTask(BaseModel):
    user_id: str = Field(..., description="本地登录态 user_id")
    enabled: bool = Field(True, description="是否启用该账号任务")
    playids: PlayidsRequest = Field(default_factory=PlayidsRequest, description="该账号的 playids 任务配置")


class NcmmTaskRequest(BaseModel):
    sign: bool = Field(False, description="是否执行 ncmm sign")
    playids: bool = Field(False, description="是否执行 ncmm playids")
    musician_sign: bool = Field(False, description="是否执行 ncmm musician-sign")
    musician_vip: bool = Field(False, description="是否执行 ncmm musician-vip")
    note: bool = Field(False, description="是否执行 ncmm note")
    fansgroup: bool = Field(False, description="是否执行 ncmm fansgroup")
    playids_options: PlayidsRequest | None = Field(None, description="可选：为 ncmm task.playids 注入显式歌曲池和混听参数")


class NcmmDirectCommandRequest(BaseModel):
    command: str = Field(
        ...,
        description="直连执行的 ncmm 子命令：sign / note / fansgroup",
    )


class NcmmMusicianRequest(BaseModel):
    mode: str = Field(
        "musician",
        description="执行模式：musician / musician-sign / musician-vip",
    )
    playids_options: PlayidsRequest | None = Field(None, description="可选：为 musician-vip 提供主歌池和混听参数")
    enable_vip_note: bool = Field(False, description="是否允许音乐人 VIP 阶段自动发图文笔记")
    enable_vip_play: bool = Field(True, description="是否允许音乐人 VIP 阶段自动执行接力刷歌")

