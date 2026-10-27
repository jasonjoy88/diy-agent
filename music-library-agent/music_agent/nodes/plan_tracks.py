from __future__ import annotations

from dataclasses import asdict

from .. import catalog, dedup
from ..config import CONFIG
from ..format_meta import format_duration, format_size, platform_label


def _artist_dir(state: dict) -> str:
    return state["out_dir"]


def _format_track_line(t: dict) -> str:
    """dry-run 列表行：歌名 + 可下载标记/时长/大小/专辑/出处。"""
    dur = format_duration(int(t.get("duration_ms") or 0))
    size = format_size(int(t.get("size_bytes") or 0))
    album = (t.get("album") or "").strip() or "-"
    plat = platform_label(t.get("platform") or "netease")
    dl = (t.get("download_label") or "").strip()
    if not dl:
        dl = "可完整下载" if t.get("downloadable") else (
            "可能需VIP" if t.get("vip_likely") else "")
    meta = " · ".join(
        x for x in (dl or None, dur or None, size or None, f"专辑:{album}", f"出处:{plat}") if x
    )
    return f"  · {t.get('artist', '')} - {t.get('title', '')}（{meta}）"


def run(state: dict) -> dict:
    artist = state.get("artist") or state["singer"]
    artist_id = str(state.get("artist_id") or "")
    songs = state.get("songs") or []
    top_n = state.get("top_n", 30)
    platforms = state.get("platforms") or []
    out_dir = _artist_dir(state)
    watch_dir = CONFIG.watch_dir
    msgs: list[str] = []
    final_report = ""

    # 已下载集合 = 本地已有音频 + 曾上传网盘（.uploaded.json）
    downloaded = dedup.downloaded_titles(out_dir, watch_dir, artist)
    if downloaded:
        msgs.append(f"[plan_tracks] 已下载清单：{len(downloaded)} 首（本地+网盘）")

    if songs:
        # 单曲模式：精确命中优先；未命中不改下其它歌，但保留用户指定歌名交给 yt-dlp
        found, missing = catalog.match_songs(
            artist, songs, artist_id=artist_id, platforms=platforms or None)
        tracks = [asdict(t) for t in found]
        if missing:
            for title in missing:
                tracks.append(asdict(catalog.external_track(artist, title, artist_id=artist_id)))
            tip = (
                f"网易云未收录，改由 yt-dlp 检索（不会改下其它歌曲）：{', '.join(missing)}"
            )
            if not CONFIG.ytdlp_enable_youtube:
                tip += "；当前 MUSIC_YTDLP_ENABLE_YOUTUBE=0，仅 Bilibili（YouTube 需自行开启）"
            msgs.append(f"[plan_tracks] {tip}")
        new, skipped = dedup.filter_new_tracks(tracks, downloaded)
        if skipped:
            msgs.append(f"[plan_tracks] 已下载跳过 {len(skipped)} 首：{', '.join(t['title'] for t in skipped)}")
        tracks = new
        if not tracks:
            msgs.append("[plan_tracks] 指定歌曲均已下载，无新任务")
        else:
            msgs.append(f"[plan_tracks] 单曲模式：待下载 {len(tracks)} 首")
    else:
        # Top N 模式：去重后不足 top_n 时，自动扩大候选池补齐未下载的凑满 top_n
        # 有 artist_id 时热门列表长度固定，无需盲目翻倍搜索
        pool_size = top_n
        candidates: list[dict] = []
        seen_titles: set[str] = set()
        while True:
            pool = [asdict(t) for t in catalog.discover_tracks(
                artist, pool_size, artist_id=artist_id, platforms=platforms or None)]
            pool_unique = []
            for t in pool:
                key = dedup._norm(t.get("title", ""))
                if key and key not in seen_titles:
                    seen_titles.add(key)
                    pool_unique.append(t)
            candidates = pool_unique
            new, _ = dedup.filter_new_tracks(candidates, downloaded)
            if artist_id or len(new) >= top_n or pool_size >= top_n * 4 or len(pool) < pool_size:
                break
            pool_size *= 2
        if not candidates:
            tip = f"未检索到歌手「{artist}」的曲目资源，不会改下其它歌曲"
            msgs.append(f"[plan_tracks] {tip}")
            tracks = []
            final_report = tip
        else:
            tracks, skipped = dedup.fill_to_target(candidates, downloaded, top_n)
            if skipped:
                msgs.append(f"[plan_tracks] Top{top_n} 中已下载 {len(skipped)} 首，自动从 Top{pool_size} 补齐")
            if not tracks:
                msgs.append(f"[plan_tracks] 目标 Top{top_n} 均已下载，无新任务")
            else:
                msgs.append(f"[plan_tracks] 待下载 {len(tracks)} 首（目标 {top_n}，候选池 Top{pool_size}）")

    if state.get("dry_run"):
        msgs.insert(0, "[dry-run] 仅列出曲目，不下载（含时长/大小/专辑/出处）")
        for t in tracks:
            msgs.append(_format_track_line(t))

    out: dict = {"tracks": tracks, "messages": msgs}
    if final_report:
        out["final_report"] = final_report
    return out
