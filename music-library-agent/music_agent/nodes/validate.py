from __future__ import annotations

from .. import convert, validate
from ..config import CONFIG


def run(state: dict) -> dict:
    results = dict(state.get("results", {}))
    expected = {t["song_id"]: t.get("duration_ms", 0) for t in state.get("tracks", [])}
    ffprobe = convert.find_ffprobe(CONFIG.ffmpeg_bin) or ""
    rejected = 0
    for tid, r in results.items():
        if r.get("status") != "ok":
            continue
        ok, reason = validate.check_file(
            r.get("path", ""), expected.get(tid, 0), ffprobe_bin=ffprobe
        )
        if not ok:
            r["status"] = "failed"
            r["fail_reason"] = reason
            rejected += 1
    msgs = ["[validate] 校验完成"]
    if rejected:
        msgs.append(f"[validate] {rejected} 个资源被判为试听/残缺片段或损坏，已标记失败")
    return {"results": results, "messages": msgs}
