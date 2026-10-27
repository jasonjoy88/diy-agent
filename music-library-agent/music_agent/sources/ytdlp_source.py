from __future__ import annotations

import glob
import http.cookiejar
import json
import os
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..dedup import _norm
from ..models import DownloadResult, Track
from .base import Source

# B 站对无 UA/Referer 的请求更易 412；与浏览器接近的默认头更稳
_BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}

_COOKIE_HEADER_HINTS = ("SESSDATA=", "bili_jct=", "DedeUserID=", "buvid3=")
# yt-dlp bilisearch 仍走旧接口 /x/web-interface/search/type（返回 HTML → JSON 解析失败）
# 登录态下 WBI 搜索可用，故自研搜索后再用 BV 链接交给 yt-dlp 下载
_BILI_WBI_SEARCH = "https://api.bilibili.com/x/web-interface/wbi/search/type"
_TAG_RE = re.compile(r"<[^>]+>")


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
        return yt_dlp
    except Exception:  # noqa: BLE001
        return None


def _detect_js_runtimes() -> dict:
    """yt-dlp 2025+ 默认只认 deno；本机有 node 时显式启用，降低 YouTube 403/缺格式。"""
    import shutil

    runtimes: dict = {}
    deno = shutil.which("deno")
    if deno:
        runtimes["deno"] = {"path": deno}
    node = shutil.which("node")
    if node:
        runtimes["node"] = {"path": node}
    return runtimes


def _parse_cookies_from_browser(spec: str) -> tuple | None:
    """解析 MUSIC_YTDLP_COOKIES_FROM_BROWSER，如 chrome / chrome:Default / edge。"""
    spec = (spec or "").strip()
    if not spec:
        return None
    browser, _, rest = spec.partition(":")
    if not browser:
        return None
    if not rest:
        return (browser,)
    if "::" in rest:
        profile, _, container = rest.partition("::")
        return (browser, None, profile or None, container or None)
    return (browser, None, rest or None)


def _looks_like_cookie_header(text: str) -> bool:
    """浏览器开发者工具 / 扩展误导出的 `a=1; b=2` 单行格式。"""
    s = text.strip()
    if not s or s.startswith("# Netscape") or s.startswith("# HTTP Cookie File"):
        return False
    if "\t" in s:
        return False
    return ";" in s and any(h in s for h in _COOKIE_HEADER_HINTS)


def _cookie_header_to_netscape(text: str, domain: str = ".bilibili.com") -> str:
    """把 Cookie 请求头转换成 yt-dlp 可读的 Netscape cookies.txt。"""
    lines = [
        "# Netscape HTTP Cookie File",
        "# Converted from Cookie header by music-library-agent",
    ]
    blob = text.strip()
    if blob.lower().startswith("cookie:"):
        blob = blob.split(":", 1)[1].strip()
    for part in blob.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not name:
            continue
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def resolve_cookiefile(path: str) -> str | None:
    """返回可供 yt-dlp cookiefile 使用的路径；Header 格式会转成临时 Netscape 文件。"""
    path = (path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    if not _looks_like_cookie_header(raw):
        return path
    converted = _cookie_header_to_netscape(raw)
    fd, tmp = tempfile.mkstemp(prefix="bili_cookies_", suffix=".txt")
    os.close(fd)
    Path(tmp).write_text(converted, encoding="utf-8")
    return tmp


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # 部分公司代理会做 TLS 拦截；与本机其它探测脚本保持一致
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _pick_matching_hit(hits: list[dict], track: Track) -> dict | None:
    """在搜索结果中选标题真正包含目标歌名的条目；没有则返回 None（禁止改下其它视频）。"""
    want = _norm(track.title)
    if not want or not hits:
        return None
    artist = _norm(track.artist)
    ranked: list[tuple[int, dict]] = []
    for h in hits:
        ht = _norm(h.get("title") or "")
        if want not in ht:
            continue
        # 短歌名（≤2）必须同时出现歌手名，降低误匹配
        if len(want) <= 2 and artist and artist not in ht:
            continue
        score = 2 if artist and artist in ht else 1
        if ht == want or ht.endswith(want) or f"{artist}{want}" in ht:
            score += 1
        ranked.append((score, h))
    if not ranked:
        return None
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def bilibili_wbi_search(query: str, cookiefile: str | None, limit: int = 5) -> list[dict]:
    """用 WBI 搜索接口查视频，返回 [{bvid, title, url}, ...]。"""
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:80] if e.fp else ""
        raise RuntimeError(f"bilibili_search_http_{e.code}:{body}") from e
    if not raw or raw.lstrip().startswith("<"):
        raise RuntimeError("bilibili_search_empty_or_html")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError("bilibili_search_bad_json") from e
    if payload.get("code") not in (0, None):
        raise RuntimeError(f"bilibili_search_code_{payload.get('code')}:{payload.get('message')}")
    results = (payload.get("data") or {}).get("result") or []
    out: list[dict] = []
    for item in results:
        bvid = item.get("bvid") or ""
        if not bvid:
            continue
        title = _TAG_RE.sub("", item.get("title") or "")
        out.append({
            "bvid": bvid,
            "title": title,
            "url": f"https://www.bilibili.com/video/{bvid}",
        })
        if len(out) >= limit:
            break
    return out


class YtdlpSource(Source):
    """yt-dlp 主路源。国内：WBI 搜索拿 BV → yt-dlp 下载；可选 YouTube 回退。"""

    name = "ytdlp"

    def __init__(
        self,
        ffmpeg_bin: str = "",
        cookie_file: str = "",
        cookies_from_browser: str = "",
        enable_youtube: bool = False,
        sleep_interval: float = 2.0,
        sleep_requests: float = 1.0,
        proxy: str = "",
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.cookie_file = cookie_file
        self.cookies_from_browser = cookies_from_browser
        self.enable_youtube = enable_youtube
        self.sleep_interval = sleep_interval
        self.sleep_requests = sleep_requests
        # 仅用于 YouTube 请求（B 站等国内源直连，避免被代理分流拖慢/阻断）
        self.proxy = (proxy or "").strip()
        self._temp_cookiefiles: list[str] = []

    def available(self) -> bool:
        return _import_ytdlp() is not None

    def search_query(self, track: Track) -> str:
        return f"{track.artist} {track.title}"

    def build_opts(self, outtmpl: str, *, for_youtube: bool = False) -> dict:
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "socket_timeout": 30,
            "sleep_interval": self.sleep_interval,
            "max_sleep_interval": max(self.sleep_interval, 5.0),
            "sleep_interval_requests": self.sleep_requests,
            "extractor_args": {
                "bilibili": {"prefer_multi_flv": ["false"]},
            },
        }
        js = _detect_js_runtimes()
        if js:
            opts["js_runtimes"] = js
        if self.ffmpeg_bin:
            opts["ffmpeg_location"] = self.ffmpeg_bin
        # YouTube 不要带 B 站 Referer/Cookie，避免污染请求；B 站才需要
        if for_youtube:
            opts["http_headers"] = {
                "User-Agent": _BILI_HEADERS["User-Agent"],
            }
            # YouTube 走代理（socks5:// 需 PySocks，yt-dlp 环境已内置）
            if self.proxy:
                opts["proxy"] = self.proxy
            return opts
        opts["http_headers"] = dict(_BILI_HEADERS)
        cookie_path = resolve_cookiefile(self.cookie_file)
        if cookie_path:
            if cookie_path != self.cookie_file:
                self._temp_cookiefiles.append(cookie_path)
            opts["cookiefile"] = cookie_path
        browser = _parse_cookies_from_browser(self.cookies_from_browser)
        if browser is not None and "cookiefile" not in opts:
            opts["cookiesfrombrowser"] = browser
        return opts

    def _cleanup_temp_cookies(self) -> None:
        for p in self._temp_cookiefiles:
            try:
                os.remove(p)
            except OSError:
                pass
        self._temp_cookiefiles.clear()

    def _download_url(self, yt_dlp, url: str, opts: dict) -> None:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(track_id=track.song_id, source=self.name, title=track.title, artist=track.artist)
        yt_dlp = _import_ytdlp()
        if yt_dlp is None:
            r.status, r.fail_reason = "failed", "not_installed"
            return r
        configured = (self.cookie_file or "").strip()
        if configured and not os.path.isfile(configured) and not self.cookies_from_browser.strip():
            r.status, r.fail_reason = "failed", f"cookie_file_missing:{configured}"
            return r
        os.makedirs(dest_dir, exist_ok=True)
        outtmpl = os.path.join(dest_dir, track.safe_filename() + ".%(ext)s")
        try:
            bili_opts = self.build_opts(outtmpl, for_youtube=False)
            cookiefile = bili_opts.get("cookiefile")
            errors: list[str] = []
            query = self.search_query(track)

            # 1) B 站：WBI 搜索 → 仅下载标题命中目标歌名的结果（禁止改下其它视频）
            try:
                hits = bilibili_wbi_search(query, cookiefile, limit=8)
                hit = _pick_matching_hit(hits, track)
                if hit is None:
                    raise RuntimeError("resource_not_found")
                self._download_url(yt_dlp, hit["url"], bili_opts)
            except Exception as e:  # noqa: BLE001
                errors.append(f"bilibili:{e}")
                if self.sleep_requests > 0:
                    time.sleep(self.sleep_requests)
                # 2) 可选 YouTube（独立 opts，不用 B 站 cookie/Referer）
                if self.enable_youtube:
                    try:
                        yt_opts = self.build_opts(outtmpl, for_youtube=True)
                        self._download_url(yt_dlp, f"ytsearch1:{query}", yt_opts)
                    except Exception as e2:  # noqa: BLE001
                        errors.append(f"ytsearch:{e2}")
                        r.status, r.fail_reason = "failed", "ytdlp_error:" + " | ".join(errors)[:200]
                        return r
                else:
                    reason = " | ".join(errors)[:200]
                    if "resource_not_found" in reason:
                        r.status, r.fail_reason = "failed", "resource_not_found"
                        return r
                    if "412" in reason or "empty_or_html" in reason or "Failed to parse JSON" in reason:
                        reason = "bilibili_blocked:" + reason
                    r.status, r.fail_reason = "failed", "ytdlp_error:" + reason
                    return r

            produced = sorted(glob.glob(os.path.join(dest_dir, track.safe_filename() + ".*")))
            # 只保留音频文件，排除 .lrc 歌词、.part 临时文件等
            _AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".webm")
            produced = [p for p in produced if p.lower().endswith(_AUDIO_EXTS)]
            if not produced:
                r.status, r.fail_reason = "failed", "no_file"
                return r
            r.status = "ok"
            r.path = produced[0]
            r.format = os.path.splitext(produced[0])[1].lstrip(".").lower()
            return r
        finally:
            self._cleanup_temp_cookies()
