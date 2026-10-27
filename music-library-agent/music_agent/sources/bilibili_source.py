"""Bilibili 音源：WBI 搜索拿 BV，下载走 yt-dlp（与 YtdlpSource 共用下载链路）。

作为检索源加入 multi_search 多平台并行检索；下载侧与 YtdlpSource 共享（fetch_loop
里 platform="bilibili" 会被别名映射到 name="ytdlp" 的源）。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

from ..models import DownloadResult, Track
from .base import Source
from .platform_id import make_id

_BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}

_BILI_WBI_SEARCH = "https://api.bilibili.com/x/web-interface/wbi/search/type"
_TAG_RE = re.compile(r"<[^>]+>")


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _duration_str_to_ms(dur: str) -> int:
    """把 B 站时长字符串（如 '03:45'、'1:02:30'）转毫秒；失败返回 0。"""
    s = (dur or "").strip()
    if not s:
        return 0
    parts = s.split(":")
    try:
        parts_int = [int(p) for p in parts]
    except (TypeError, ValueError):
        return 0
    if len(parts_int) == 2:
        return (parts_int[0] * 60 + parts_int[1]) * 1000
    if len(parts_int) == 3:
        return (parts_int[0] * 3600 + parts_int[1] * 60 + parts_int[2]) * 1000
    return 0


def _bili_search_full(query: str, cookiefile: str | None, limit: int = 10) -> list[dict]:
    """B 站 WBI 视频搜索，返回完整字段：bvid, title, author, duration, play, url。"""
    params = urllib.parse.urlencode({
        "search_type": "video",
        "keyword": query,
        "page": 1,
    })
    url = f"{_BILI_WBI_SEARCH}?{params}"
    handlers: list = [urllib.request.HTTPSHandler(context=_ssl_context())]
    if cookiefile and os.path.isfile(cookiefile):
        jar = http.cookiejar.MozillaCookieJar(cookiefile)
        try:
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception:  # noqa: BLE001
            pass
        else:
            handlers.insert(0, urllib.request.HTTPCookieProcessor(jar))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers=dict(_BILI_HEADERS))
    try:
        with opener.open(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return []
    if not raw or raw.lstrip().startswith("<"):
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if payload.get("code") not in (0, None):
        return []
    results = (payload.get("data") or {}).get("result") or []
    out: list[dict] = []
    for item in results:
        bvid = item.get("bvid") or ""
        if not bvid:
            continue
        title = _TAG_RE.sub("", item.get("title") or "").strip()
        author = (item.get("author") or "").strip()
        duration_str = str(item.get("duration") or "")
        out.append({
            "bvid": bvid,
            "title": title,
            "author": author,
            "duration": duration_str,
            "play": int(item.get("play") or 0),
            "url": f"https://www.bilibili.com/video/{bvid}",
        })
        if len(out) >= limit:
            break
    return out


class BilibiliSource(Source):
    """Bilibili 检索源（下载由 YtdlpSource 统一处理，fetch_loop 别名映射）。

    搜索使用 B 站 WBI 接口，需要登录态 Cookie（SESSDATA 等）才能稳定返回结果；
    无 Cookie 时可能 412 或空结果，但仍可尝试。
    """

    name = "bilibili"

    def __init__(self, cookie_file: str = ""):
        self.cookie_file = (cookie_file or "").strip()
        # 用 ytdlp 同一路径下的 cookie（B 站 cookie 存放在 ytdlp_cookie_file 配置项）
        self._cookiefile = self._resolve_cookie()

    def _resolve_cookie(self) -> str | None:
        """解析 B 站 Cookie 文件路径，支持 Netscape 格式和 Header 单行格式。"""
        from .ytdlp_source import resolve_cookiefile

        return resolve_cookiefile(self.cookie_file)

    def available(self) -> bool:
        return True

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        """B 站视频搜索，转成 Track 列表。

        B 站 WBI 接口只有单页搜索，offset 通过结果切片实现。
        时长过滤由调用方 multi_search 统一处理（_MIN_DURATION_MS / _MAX_DURATION_MS）。
        """
        if not keyword.strip():
            return []
        if offset < 0:
            offset = 0
        # 多拉一些，给过滤/分页留余量
        fetch_limit = max(limit + offset, limit * 2, 20)
        try:
            hits = _bili_search_full(keyword, self._cookiefile, limit=fetch_limit)
        except Exception:  # noqa: BLE001
            return []

        out: list[Track] = []
        for h in hits:
            bvid = h.get("bvid") or ""
            title = h.get("title") or ""
            if not bvid or not title:
                continue
            author = h.get("author") or "Bilibili"
            duration_ms = _duration_str_to_ms(h.get("duration") or "")
            out.append(
                Track(
                    song_id=make_id("bilibili", bvid),
                    title=title,
                    artist=author,
                    album="",
                    duration_ms=duration_ms,
                    size_bytes=0,
                    bitrate=0,  # B 站视频搜索时不知道码率
                    platform="bilibili",
                    vip_likely=False,  # B 站视频基本都能看，下载不受 VIP 限制
                )
            )
            if len(out) >= limit + offset:
                break
        return out[offset:]

    # ── 下载：交由 YtdlpSource 统一处理 ──
    # fetch_loop 中 platform="bilibili" 会被映射到 name="ytdlp" 的源。
    # 这里仅提供一个占位实现，以防被直接调用时报错。
    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        r.status, r.fail_reason = "failed", "use_ytdlp_source_for_download"
        return r
