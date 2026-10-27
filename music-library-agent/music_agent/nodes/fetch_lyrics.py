from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from .. import lyrics
from ..config import CONFIG
from ..models import Track

_MAX_WORKERS = 4


def _enabled(state: dict) -> bool:
    """state 开关覆盖 > .env CONFIG。"""
    flag = state.get("lyrics_enabled")
    if flag is None:
        return CONFIG.enable_lyrics
    return bool(flag)


def run(state: dict) -> dict:
    if not _enabled(state):
        return {"messages": ["[fetch_lyrics] 已禁用（MUSIC_ENABLE_LYRICS=0），跳过歌词获取"]}
    if state.get("dry_run"):
        return {"messages": ["[dry-run] 跳过歌词获取"]}

    results = dict(state.get("results", {}))
    tracks = {t["song_id"]: Track(**t) for t in state.get("tracks", [])}
    todo = [(tid, tracks[tid]) for tid, r in results.items()
            if r.get("status") == "ok" and tid in tracks]
    if not todo:
        return {"results": results,
                "messages": ["[fetch_lyrics] 无成功下载的曲目，跳过歌词获取"]}

    out_dir = state["out_dir"]
    src = lyrics.NeteaseSource(cookie=CONFIG.netease_cookie)

    def _job(item: tuple[str, Track]):
        tid, tr = item
        return tid, lyrics.fetch_track_lyric(tr, out_dir, src)

    if len(todo) == 1:
        done = [_job(todo[0])]
    else:
        done = []
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(todo))) as ex:
            futures = [ex.submit(_job, item) for item in todo]
            for f in as_completed(futures):
                done.append(f.result())

    ok_n = 0
    for tid, (path, status, reason) in done:
        r = results[tid]
        r["lyric_status"] = status
        r["lyric_source"] = "netease"
        if status == "ok":
            r["lyric_path"] = path
            r["lyric_fail_reason"] = ""
            ok_n += 1
        else:
            r["lyric_fail_reason"] = reason
    return {"results": results,
            "messages": [f"[fetch_lyrics] 歌词获取完成 ok={ok_n}/{len(todo)}"]}
