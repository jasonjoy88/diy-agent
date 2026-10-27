from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _merge_dict(a: dict, b: dict) -> dict:
    out = dict(a)
    out.update(b)
    return out


def _append_list(a: list, b: list) -> list:
    return list(a) + list(b)


class MusicState(TypedDict, total=False):
    singer: str
    songs: list[str]                 # --song 指定的单曲（可空）
    top_n: int
    resume: bool
    dry_run: bool
    concurrency: int                 # 下载并发数（CLI / MUSIC_CONCURRENCY）
    pool: str                        # thread | process（CLI / MUSIC_POOL）
    lyrics_enabled: bool             # 是否同步检索歌词（CLI --no-lyrics / MUSIC_ENABLE_LYRICS）
    platforms: list[str]             # 限定检索/下载的平台列表（空=全部启用的源）
    artist: str                      # resolve_artist 解析后的权威歌手名
    artist_id: str                   # 网易云歌手 id（同名消歧后写入）
    tracks: list[dict[str, Any]]     # plan_tracks 产出的目标曲目（Track 序列化）
    results: Annotated[dict[str, dict], _merge_dict]  # track_id -> DownloadResult 序列化
    out_dir: str
    messages: Annotated[list[str], _append_list]
    final_report: str
