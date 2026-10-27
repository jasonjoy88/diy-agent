"""歌词检索与 LRC 处理。

- 歌词来源：网易云歌词接口（无需 cookie/VIP）。
- 产出与音频同名的 .lrc，播放器可自动关联。
- 有翻译歌词时按时间轴合并为双语 LRC。

另含独立小工具 fetch_lrc/write_lrc（UTF-8，无 BOM）：不依赖 langgraph 主流程，
由 dsh_player_tools 在转码完成后挂载，也可单独为本地库补歌词。
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import catalog
from .models import Track
from .sources.netease_source import NeteaseSource

_LYRIC = "https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class LrcResult:
    song_id: str
    status: str = "error"        # ok | no_lyric | error
    lrc_text: str = ""
    fail_reason: str = ""


def _default_get(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://music.163.com",
    }
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=15, context=_CTX).read()


def _norm_lrc(text: str) -> str:
    """统一换行并去除首尾空行；纯音乐歌词体可能只有空白。"""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def fetch_lrc(song_id: str, getter=_default_get) -> LrcResult:
    """按网易云歌曲 id 拉取标准 lrc 文本。"""
    sid = str(song_id or "")
    if not sid.isdigit():
        return LrcResult(song_id=sid, status="error", fail_reason="no_netease_id")
    url = _LYRIC.format(sid=urllib.parse.quote(sid))
    try:
        data = json.loads(getter(url).decode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        reason = f"request_error:{type(e).__name__}:{e}"[:200]
        return LrcResult(song_id=sid, status="error", fail_reason=reason)
    if data.get("nolyric") or not data.get("lrc"):
        return LrcResult(song_id=sid, status="no_lyric")
    text = _norm_lrc((data.get("lrc") or {}).get("lyric", ""))
    if not text:
        return LrcResult(song_id=sid, status="no_lyric")
    return LrcResult(song_id=sid, status="ok", lrc_text=text)


def write_lrc(dest_dir: str, filename_base: str, lrc_text: str) -> str:
    """歌词文本落盘：<dest_dir>/<filename_base>.lrc。"""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, filename_base + ".lrc")
    with open(path, "w", encoding="utf-8") as f:
        f.write(lrc_text.rstrip("\n") + "\n")
    return path


# 时间轴标签 [mm:ss.xx]（兼容 , 与三位/两位毫秒）
_TS_RE = re.compile(r"\[\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?\]")
# 元信息标签行，如 [ti:晴天]
_META_RE = re.compile(r"^\s*(?:\[[A-Za-z]+:[^\]]*\]\s*)+$")


def _timestamp_map(trans_lrc: str) -> dict[str, str]:
    """翻译 LRC → {时间戳标签: 译文}。"""
    m: dict[str, str] = {}
    for line in (trans_lrc or "").splitlines():
        tags = _TS_RE.findall(line)
        if not tags:
            continue
        text = _TS_RE.sub("", line).strip()
        if text:
            m[tags[0]] = text
    return m


def merge_bilingual(orig_lrc: str, trans_lrc: str) -> str:
    """按时间戳把翻译拼到原文同行；无翻译则原样返回。过滤已有的元信息标签行。"""
    lines = [ln for ln in (orig_lrc or "").splitlines() if not _META_RE.match(ln)]
    trans = _timestamp_map(trans_lrc)
    if not trans:
        return "\n".join(lines).strip("\n")
    out: list[str] = []
    for line in lines:
        tags = _TS_RE.findall(line)
        text = trans.get(tags[0], "") if tags else ""
        out.append(f"{line} / {text}" if text else line)
    return "\n".join(out).strip("\n")


def build_header(track: Track) -> str:
    """LRC 文件头：ti/ar/al/by。"""
    def esc(s: str) -> str:
        return (s or "").replace("[", "(").replace("]", ")").replace("\n", " ")

    return (
        f"[ti:{esc(track.title)}]\n"
        f"[ar:{esc(track.artist)}]\n"
        f"[al:{esc(track.album)}]\n"
        "[by:music-library-agent]"
    )


# 翻唱/伴奏/改编等标记：宽松匹配阶段排除，避免把别人的翻唱当正版歌词
_COVER_MARKERS = ("翻唱", "cover", "remix", "现场", "live", "试听", "伴奏",
                  "karaoke", "inst", "纯音乐", "翻奏")


def _is_cover_title(title: str) -> bool:
    low = (title or "").lower()
    return any(m.lower() in low for m in _COVER_MARKERS)


def _lyric_id_candidates(track: Track, src: NeteaseSource) -> list[str]:
    """搜索候选的网易云 id，按优先级去重排列：

    1. 歌手+歌名严格匹配（同一首歌）；
    2. 仅歌名匹配、排除翻唱/伴奏等（兼容繁简体歌手名等写法差异）。
    """
    try:
        hits = src.search_tracks(f"{track.artist} {track.title}", 10)
    except Exception:  # noqa: BLE001
        return []
    strict = [h.song_id for h in hits
              if catalog._artist_matches(track.artist, h.artist)
              and catalog.title_matches(track.title, h.title)]
    relaxed = [h.song_id for h in hits
               if catalog.title_matches(track.title, h.title)
               and not _is_cover_title(h.title)]
    seen: set[str] = set()
    ordered: list[str] = []
    for sid in strict + relaxed:
        if sid and sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    return ordered


def fetch_track_lyric(
    track: Track, out_dir: str, src: NeteaseSource
) -> tuple[str, str, str]:
    """为单曲获取并写入 .lrc。返回 (path, status, reason)。

    status: ok | failed；目标文件已存在时直接 ok（幂等）。
    数字 id 直接取；ext 外源曲目按候选顺序依次尝试，直到拿到非空歌词。
    """
    path = os.path.join(out_dir, track.safe_filename() + ".lrc")
    if os.path.isfile(path):
        return path, "ok", ""
    sid = str(track.song_id or "")
    candidates = [sid] if sid.isdigit() else _lyric_id_candidates(track, src)
    if not candidates:
        return path, "failed", "not_found"
    last_error = ""
    for song_id in candidates:
        try:
            got = src.fetch_lyric(song_id)
        except Exception as e:  # noqa: BLE001
            last_error = f"resolve_error:{e}"[:200]
            continue
        orig, trans = got.get("lrc", ""), got.get("tlyric", "")
        if not (orig or "").strip():
            last_error = "no_lyric"
            continue
        body = merge_bilingual(orig, trans)
        os.makedirs(out_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_header(track) + "\n" + body + "\n")
        return path, "ok", ""
    return path, "failed", last_error or "no_lyric"
