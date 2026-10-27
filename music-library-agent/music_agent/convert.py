from __future__ import annotations

import os
import subprocess


def _hidden_kwargs() -> dict:
    """子进程隐藏控制台窗口参数（仅 Windows）。

    GUI（windowed，无控制台）调用 ffmpeg 时，若不隐藏会弹出一个 cmd 黑窗。
    - CREATE_NO_WINDOW：根本不创建控制台窗口；
    - STARTF_USESHOWWINDOW + SW_HIDE：双保险（对部分沿用 startinfo 的场景）。
    非 Windows 返回空 dict，行为完全不变。
    """
    if os.name != "nt":
        return {}
    kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo
    return kwargs


def find_ffmpeg(ffmpeg_bin: str = "") -> str | None:
    """在配置目录或 PATH 中定位 ffmpeg 可执行文件。"""
    names = ["ffmpeg.exe", "ffmpeg"]
    candidates: list[str] = []
    if ffmpeg_bin:
        candidates += [os.path.join(ffmpeg_bin, n) for n in names]
        candidates += [os.path.join(ffmpeg_bin, "bin", n) for n in names]
    for c in candidates:
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ffmpeg")


def find_ffprobe(ffmpeg_bin: str = "") -> str | None:
    """在配置目录或 PATH 中定位 ffprobe 可执行文件（与 ffmpeg 同目录）。"""
    names = ["ffprobe.exe", "ffprobe"]
    candidates: list[str] = []
    if ffmpeg_bin:
        candidates += [os.path.join(ffmpeg_bin, n) for n in names]
        candidates += [os.path.join(ffmpeg_bin, "bin", n) for n in names]
    for c in candidates:
        if os.path.isfile(c):
            return c
    from shutil import which
    return which("ffprobe")


def to_mp3(src_path: str, bitrate: str = "320k", ffmpeg_path: str | None = None) -> tuple[str, str]:
    """尽量转为 mp3；已是 mp3 / 无 ffmpeg / 转码失败 → 返回原文件与真实格式。"""
    ext = os.path.splitext(src_path)[1].lstrip(".").lower()
    if ext == "mp3":
        return src_path, "mp3"
    ff = ffmpeg_path or find_ffmpeg("")
    if not ff:
        return src_path, ext
    dst = os.path.splitext(src_path)[0] + ".mp3"
    try:
        res = subprocess.run(
            [ff, "-y", "-i", src_path, "-codec:a", "libmp3lame", "-b:a", bitrate, dst],
            capture_output=True, timeout=180, **_hidden_kwargs(),
        )
        if res.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0:
            return dst, "mp3"
    except Exception:  # noqa: BLE001
        pass
    return src_path, ext
