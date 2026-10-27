"""统一 song_id 前缀约定：platform:raw_id。"""
from __future__ import annotations

# 无前缀的纯数字视为网易云
_KNOWN = (
    "qq", "kugou", "kuwo", "qishui", "migu", "apple",
    "bilibili", "youtube", "ext", "netease",
)


def make_id(platform: str, raw_id: str) -> str:
    plat = (platform or "").strip().lower()
    rid = str(raw_id or "").strip()
    if not rid:
        return ""
    if plat in ("", "netease") and rid.isdigit():
        return rid
    if plat == "netease":
        return rid
    return f"{plat}:{rid}"


def parse_id(song_id: str) -> tuple[str, str]:
    """返回 (platform, raw_id)。纯数字 → netease。"""
    sid = str(song_id or "").strip()
    if not sid:
        return "", ""
    if sid.isdigit():
        return "netease", sid
    if ":" in sid:
        plat, _, rest = sid.partition(":")
        plat = plat.strip().lower()
        if plat in _KNOWN and rest:
            return plat, rest
    return "", sid


def track_platform(track) -> str:
    """从 Track.platform 或 song_id 前缀推断平台。"""
    plat = (getattr(track, "platform", None) or "").strip().lower()
    if plat:
        return plat
    return parse_id(getattr(track, "song_id", "") or "")[0]
