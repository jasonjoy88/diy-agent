"""检索/展示用的元数据格式化。"""
from __future__ import annotations


def format_duration(ms: int) -> str:
    """毫秒 → mm:ss；无效则空串。"""
    try:
        total = int(ms or 0) // 1000
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    return f"{total // 60}:{total % 60:02d}"


def format_size(nbytes: int) -> str:
    """字节 → 人类可读；无效则空串。"""
    try:
        n = int(nbytes or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def estimate_size_bytes(duration_ms: int, bitrate_kbps: int = 320) -> int:
    """按时长×码率估算体积（无平台 size 时的兜底）。"""
    try:
        secs = max(0, int(duration_ms or 0)) / 1000.0
        br = max(64, int(bitrate_kbps or 320))
    except (TypeError, ValueError):
        return 0
    if secs <= 0:
        return 0
    return int(secs * br * 1000 / 8)


def platform_label(platform: str) -> str:
    """平台内部名 → 中文出处标签。"""
    mapping = {
        "netease": "网易云",
        "qq": "QQ音乐",
        "kugou": "酷狗",
        "kuwo": "酷我",
        "qishui": "汽水音乐",
        "migu": "咪咕",
        "apple": "Apple Music",
        "bilibili": "Bilibili",
        "youtube": "YouTube",
        "ytdlp": "Bilibili/YouTube",
    }
    key = (platform or "").strip().lower()
    return mapping.get(key, key or "未知")
