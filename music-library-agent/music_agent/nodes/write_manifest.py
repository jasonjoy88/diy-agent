from __future__ import annotations

from ..manifest import Manifest
from ..models import DownloadResult


def run(state: dict) -> dict:
    artist = state.get("artist") or state["singer"]
    out_dir = state["out_dir"]
    m = Manifest(out_dir, artist)
    for tid, rd in state.get("results", {}).items():
        m.upsert(DownloadResult(track_id=tid, **{k: v for k, v in rd.items() if k != "track_id"}))
    m.save()
    s = m.summary()
    lyric_ok = sum(1 for r in m.results.values() if r.lyric_status == "ok")
    report = (f"[完成] 歌手={artist} 共{s['total']}首：ok={s['ok']} "
              f"failed={s['failed']} pending={s['pending']}；歌词 ok={lyric_ok}/{s['ok']}；"
              f"manifest={m.path}")
    prev = state.get("final_report") or ""
    if prev and "未检索到" in prev:
        report = f"{prev}；{report}"
    return {"final_report": report, "messages": [report]}
