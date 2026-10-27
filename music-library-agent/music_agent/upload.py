"""网盘自动上传：把下载好的音频拷到 pan-sync 的 WATCH_DIR，由其常驻进程捡走上传。

与 pan-sync-agent 解耦：不调用其代码，只往共享目录写文件 + 读它的 .uploaded.json 清单。
上传成功后 pan-sync 会删 WATCH_DIR 里的本地副本（music/<歌手>/ 的原件保留）。
"""
from __future__ import annotations

import os
import shutil

from .dedup import AUDIO_EXTS


def stage_for_upload(files: list[str], watch_dir: str, artist: str) -> tuple[list[str], list[str]]:
    """把文件拷到 <watch_dir>/<artist>/，返回 (成功列表, 失败列表)。

    已存在同名文件（pan-sync 还没捡走）则跳过，避免重复。
    """
    dest_dir = os.path.join(watch_dir, artist)
    ok: list[str] = []
    failed: list[str] = []
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError:
        return [], list(files)
    for src in files:
        name = os.path.basename(src)
        dest = os.path.join(dest_dir, name)
        if os.path.exists(dest):
            ok.append(src)  # 已在待传队列，视为成功
            continue
        try:
            shutil.copy2(src, dest)
            ok.append(src)
        except OSError:
            failed.append(src)
    return ok, failed


def collect_ok_audio(results: dict[str, dict]) -> list[str]:
    """从下载结果里收集 status=ok 且文件存在的音频路径。"""
    out: list[str] = []
    for r in results.values():
        path = r.get("path", "")
        if r.get("status") == "ok" and path and path.lower().endswith(AUDIO_EXTS) and os.path.isfile(path):
            out.append(path)
    return out
