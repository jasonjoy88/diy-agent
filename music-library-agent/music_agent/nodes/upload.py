from __future__ import annotations

import os

from .. import upload
from ..config import CONFIG


def run(state: dict) -> dict:
    results = dict(state.get("results", {}))
    msgs: list[str] = []
    if not CONFIG.enable_upload:
        msgs.append("[upload] 已禁用（MUSIC_ENABLE_UPLOAD=0），跳过网盘上传")
        return {"messages": msgs}
    artist = state.get("artist") or state["singer"]
    files = upload.collect_ok_audio(results)
    if not files:
        msgs.append("[upload] 无成功下载的音频，跳过上传")
        return {"messages": msgs}
    ok, failed = upload.stage_for_upload(files, CONFIG.watch_dir, artist)
    msgs.append(f"[upload] 已拷入网盘待传目录 {len(ok)}/{len(files)} 首 -> {CONFIG.watch_dir}/{artist}")
    if failed:
        msgs.append(f"[upload] 拷贝失败 {len(failed)} 首：{', '.join(os.path.basename(f) for f in failed)}")
    msgs.append("[upload] pan-sync 将自动上传夸克网盘（成功后删待传副本，本地原件保留）")
    return {"messages": msgs}
