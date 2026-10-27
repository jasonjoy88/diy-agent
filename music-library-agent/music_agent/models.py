from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Track:
    song_id: str
    title: str
    artist: str
    album: str = ""
    duration_ms: int = 0
    artist_id: str = ""  # 网易云歌手 id（消歧后用于精确拉歌）
    size_bytes: int = 0  # 资源体积（字节；未知时可为估算值）
    bitrate: int = 0  # kbps；0 表示未知
    platform: str = ""  # netease|qq|kugou|kuwo|qishui|migu|apple|bilibili|youtube
    vip_likely: bool = False  # 检索侧提示：下载可能需 VIP/登录

    def safe_filename(self) -> str:
        name = f"{self.artist} - {self.title}"
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


@dataclass
class ArtistCandidate:
    """同名歌手候选，供用户选择。"""
    artist_id: str
    name: str
    blurb: str = ""          # ≤50 字简介（国籍/成立时间/代表作）
    brief_desc: str = ""
    intro_text: str = ""
    hot_songs: list[str] | None = None
    album_size: int = 0
    music_size: int = 0

    def __post_init__(self) -> None:
        if self.hot_songs is None:
            self.hot_songs = []


@dataclass
class DownloadResult:
    track_id: str
    status: str = "pending"          # pending | ok | failed
    path: str = ""
    format: str = ""                 # mp3 | m4a | aac | webm | opus | ""
    source: str = ""                 # ytdlp | netease | ""
    fail_reason: str = ""
    title: str = ""
    artist: str = ""
    # 歌词（fetch_lyrics 节点填充；"" 表示未尝试）
    lyric_status: str = ""           # "" | ok | failed
    lyric_path: str = ""
    lyric_source: str = ""           # netease | ""
    lyric_fail_reason: str = ""
