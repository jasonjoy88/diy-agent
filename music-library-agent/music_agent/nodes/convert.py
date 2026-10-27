from __future__ import annotations

import os

from .. import convert
from ..config import CONFIG


def run(state: dict) -> dict:
    results = dict(state.get("results", {}))
    ff = convert.find_ffmpeg(CONFIG.ffmpeg_bin)
    msgs: list[str] = []
    if not ff:
        msgs.append("[convert] 未找到 ffmpeg，保留原始格式（m4a/aac 兜底）")
    removed = 0
    for r in results.values():
        if r.get("status") != "ok" or not r.get("path"):
            continue
        old_path = r["path"]
        new_path, fmt = convert.to_mp3(old_path, CONFIG.bitrate, ffmpeg_path=ff)
        r["path"], r["format"] = new_path, fmt
        # 转码成功且产出新文件 → 删除中间产物（如 m4a），避免一首留两个文件
        if new_path != old_path and os.path.isfile(new_path) and os.path.isfile(old_path):
            try:
                os.remove(old_path)
                removed += 1
            except OSError:
                pass
    if removed:
        msgs.append(f"[convert] 清理转码中间产物 {removed} 个")
    msgs.append("[convert] 转码完成")
    return {"results": results, "messages": msgs}
