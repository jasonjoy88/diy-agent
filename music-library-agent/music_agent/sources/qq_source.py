"""QQ 音乐：smartbox/musicu 检索；下载优先 CgiGetVkey 直链，回退 yt-dlp。"""
from __future__ import annotations

import glob
import os
import urllib.parse

from ..dedup import _norm
from ..format_meta import estimate_size_bytes
from ..models import DownloadResult, Track
from .base import Source
from .http_util import http_get_json, http_post_json, http_download
from .platform_id import make_id, parse_id

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://y.qq.com/",
    "Origin": "https://y.qq.com",
}

# CgiGetVkey 返回的 result 码：非 0 表示不可下（如 104003=无权限）
_VKEY_RESULT_OK = 0

# CgiGetVkey 音质优先级（从高到低），对应 midurlinfo 里的文件名前缀
# M800 = mp3 320k, M500 = mp3 128k, C400 = m4a aac 128k, A000 = 臻品全景声, F000 = flac 无损
_QUALITY_PRIORITY = ("F000", "A000", "M800", "M500", "C400")
# 每个前缀对应的码率（用于回写 bitrate 字段）
_QUALITY_BITRATE = {
    "F000": 900,
    "A000": 500,
    "M800": 320,
    "M500": 128,
    "C400": 128,
}


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore

        return yt_dlp
    except Exception:  # noqa: BLE001
        return None


def _load_cookie_header(cookie_file: str, cookies_from_browser: str) -> str:
    """从 cookie_file 或 browser 读出 Cookie 请求头字符串（用于直连请求）。"""
    path = (cookie_file or "").strip()
    if path and os.path.isfile(path):
        try:
            raw = open(path, encoding="utf-8", errors="replace").read().strip()
        except OSError:
            raw = ""
        if raw:
            # Netscape 格式（多行带 TAB）
            if raw.lstrip().startswith("# Netscape") or raw.lstrip().startswith("# HTTP Cookie File") or (
                "\t" in raw and "\n" in raw
            ):
                pairs = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        name, value = parts[5], parts[6]
                        if name:
                            pairs.append(f"{name}={value}")
                if pairs:
                    return "; ".join(pairs)
            # Cookie: 开头或纯 a=b; c=d 格式
            if raw.lower().startswith("cookie:"):
                raw = raw.split(":", 1)[1].strip()
            # 单行 a=1; b=2
            if ";" in raw and "=" in raw:
                # 可能是 header 格式
                if "\t" not in raw:
                    return raw.strip()
    # 从浏览器导入：暂不支持直读（需要 browser_cookie3 等库），留给 yt-dlp 路径
    _ = cookies_from_browser
    return ""


class QQSource(Source):
    name = "qq"

    def __init__(self, cookie_file: str = "", cookies_from_browser: str = "", ffmpeg_bin: str = ""):
        self.cookie_file = (cookie_file or "").strip()
        self.cookies_from_browser = (cookies_from_browser or "").strip()
        self.ffmpeg_bin = ffmpeg_bin
        # 预加载 cookie header（用于 CgiGetVkey / 直链下载）
        self._cookie_header = _load_cookie_header(self.cookie_file, self.cookies_from_browser)

    def _has_cookie(self) -> bool:
        """是否有可用的登录态 Cookie（直链下载需要）。"""
        if self._cookie_header:
            # 判定有登录态的关键字段（与 browser_login 保持一致）
            for key in ("qm_keyst", "qqmusic_key", "wxopenid"):
                if f"{key}=" in self._cookie_header:
                    return True
        return False

    def available(self) -> bool:
        # 检索始终可用；无 cookie 时下载多半 vip/login，但仍可尝试（部分免费曲）
        return True

    # ── 检索 ──────────────────────────────────────────────

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        # 优先 Desktop CGI；失败回退 smartbox（无分页，offset>0 返回空）
        hits = self._search_musicu(keyword, limit=limit, page=max(0, offset) // max(1, limit) + 1)
        if not hits and offset == 0:
            hits = self._search_smartbox(keyword, limit=limit)
        return hits[:limit]

    def _search_smartbox(self, keyword: str, limit: int) -> list[Track]:
        url = "https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?" + urllib.parse.urlencode(
            {"key": keyword, "format": "json"}
        )
        data = http_get_json(url, headers=_UA, timeout=15)
        items = ((data.get("data") or {}).get("song") or {}).get("itemlist") or []
        out: list[Track] = []
        for s in items:
            mid = (s.get("mid") or "").strip()
            if not mid:
                continue
            out.append(
                Track(
                    song_id=make_id("qq", mid),
                    title=(s.get("name") or "").strip(),
                    artist=(s.get("singer") or "").strip(),
                    album="",
                    duration_ms=0,
                    size_bytes=0,
                    platform="qq",
                    # Cookie 需求由 multi_search.platform_requires_cookie 单独标注，不与 VIP 混用
                    vip_likely=False,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _search_musicu(self, keyword: str, limit: int, page: int) -> list[Track]:
        payload = {
            "comm": {"ct": 24, "cv": 0},
            "req_1": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "remoteplace": "txt.yqq.center",
                    "search_type": 0,
                    "query": keyword,
                    "page_num": max(1, page),
                    "num_per_page": max(1, limit),
                },
            },
        }
        try:
            data = http_post_json(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                payload,
                headers=_UA,
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            return []
        body = ((data.get("req_1") or {}).get("data") or {}).get("body") or {}
        songs = ((body.get("song") or {}).get("list") or [])
        out: list[Track] = []
        for s in songs:
            mid = (s.get("mid") or s.get("songmid") or "").strip()
            if not mid:
                continue
            singers = s.get("singer") or []
            artist = "/".join(x.get("name", "") for x in singers if x.get("name"))
            album = ((s.get("album") or {}).get("name")) or ""
            try:
                interval = int(s.get("interval") or 0)
            except (TypeError, ValueError):
                interval = 0
            size320 = int(s.get("size320") or 0)
            size128 = int(s.get("size128") or 0)
            size = size320 or size128
            if size <= 0 and interval > 0:
                size = estimate_size_bytes(interval * 1000, 320 if size320 else 128)
            vip = bool(s.get("pay") and (s.get("pay") or {}).get("pay_play"))
            out.append(
                Track(
                    song_id=make_id("qq", mid),
                    title=(s.get("title") or s.get("name") or "").strip(),
                    artist=artist,
                    album=album,
                    duration_ms=interval * 1000,
                    size_bytes=size,
                    bitrate=320 if size320 else 128,
                    platform="qq",
                    vip_likely=vip,
                )
            )
            if len(out) >= limit:
                break
        return out

    # ── 播放链接（CgiGetVkey 直链） ──────────────────────

    def _get_vkey_urls(self, mid: str) -> list[tuple[str, int, str]]:
        """调用 CgiGetVkey 拿直链，返回 [(url, bitrate, format)]，按音质从高到低排序。"""
        if not mid:
            return []
        payload = {
            "req": {
                "module": "CDN.SrfCdnDispatchServer",
                "method": "GetCdnDispatch",
                "param": {"guid": "10000", "calltype": 0, "userip": ""},
            },
            "req_0": {
                "module": "vkey.GetVkeyServer",
                "method": "CgiGetVkey",
                "param": {
                    "guid": "10000",
                    "songmid": [mid],
                    "songtype": [0],
                    "uin": "0",
                    "loginflag": 1,
                    "platform": "20",
                },
            },
            "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
        }
        headers = dict(_UA)
        if self._cookie_header:
            headers["Cookie"] = self._cookie_header
        try:
            data = http_post_json(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                payload,
                headers=headers,
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            return []
        req0 = data.get("req_0") or {}
        d0 = req0.get("data") or {}
        midurlinfo = d0.get("midurlinfo") or []
        sip = d0.get("sip") or []
        if not midurlinfo or not sip:
            return []

        # 提取所有可用的 purl（一条 mid 对应一个文件名，但我们按音质前缀排序）
        results: list[tuple[str, int, str]] = []  # (url, bitrate, format)
        seen = set()
        for info in midurlinfo:
            if int(info.get("result") or -1) != _VKEY_RESULT_OK:
                continue
            purl = (info.get("purl") or "").strip()
            filename = (info.get("filename") or "").strip()
            if not purl or not filename:
                continue
            # 音质前缀匹配
            prefix = filename[:4]
            bitrate = _QUALITY_BITRATE.get(prefix, 128)
            # 格式后缀
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "m4a"
            for base in sip:
                url = base + purl
                if url in seen:
                    continue
                seen.add(url)
                results.append((url, bitrate, ext))
        # 按音质从高到低排序
        results.sort(key=lambda x: -x[1])
        return results

    def _download_direct(self, mid: str, dest_dir: str, filename_base: str) -> tuple[bool, str, str]:
        """走 CgiGetVkey 直链下载。返回 (ok, path, format)。"""
        urls = self._get_vkey_urls(mid)
        if not urls:
            return False, "", ""
        os.makedirs(dest_dir, exist_ok=True)
        # 从最高音质开始试，第一个成功的就用
        for url, _br, fmt in urls:
            out_path = os.path.join(dest_dir, f"{filename_base}.{fmt}")
            try:
                headers = dict(_UA)
                if self._cookie_header:
                    headers["Cookie"] = self._cookie_header
                written = http_download(url, out_path, headers=headers, timeout=60)
                if written > 10 * 1024:  # 至少 10KB，排除空文件
                    return True, out_path, fmt
            except Exception:  # noqa: BLE001
                continue
        return False, "", ""

    # ── yt-dlp 兜底 ──────────────────────────────────────

    def _download_ytdlp(self, mid: str, dest_dir: str, filename_base: str,
                        track: Track) -> tuple[bool, str, str, str]:
        """走 yt-dlp 下载。返回 (ok, path, format, fail_reason)。"""
        yt_dlp = _import_ytdlp()
        if yt_dlp is None:
            return False, "", "", "not_installed"
        outtmpl = os.path.join(dest_dir, filename_base + ".%(ext)s")
        opts: dict = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 3,
            "socket_timeout": 30,
            "http_headers": dict(_UA),
        }
        if self.ffmpeg_bin:
            opts["ffmpeg_location"] = self.ffmpeg_bin
        if self.cookie_file and os.path.isfile(self.cookie_file):
            opts["cookiefile"] = self.cookie_file
        elif self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser.split(":")[0],)
        page = f"https://y.qq.com/n/ryqq/songDetail/{mid}"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([page])
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "registered users" in msg or "premium" in msg.lower() or "only available" in msg:
                return False, "", "", "vip_required"
            return False, "", "", f"qq_error:{msg}"[:200]
        produced = sorted(glob.glob(os.path.join(dest_dir, filename_base + ".*")))
        _AUDIO_EXTS = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac", ".webm")
        produced = [p for p in produced if p.lower().endswith(_AUDIO_EXTS)]
        if not produced:
            return False, "", "", "no_file"
        fmt = os.path.splitext(produced[0])[1].lstrip(".").lower()
        return True, produced[0], fmt, ""

    # ── 主入口 ────────────────────────────────────────────

    def _pick_mid(self, track: Track) -> str | None:
        plat, mid = parse_id(track.song_id)
        if plat == "qq" and mid:
            return mid
        try:
            hits = self.search_tracks(f"{track.artist} {track.title}", limit=8)
        except Exception:  # noqa: BLE001
            return None
        want_t, want_a = _norm(track.title), _norm(track.artist)
        for h in hits:
            ht, ha = _norm(h.title), _norm(h.artist)
            if want_t and want_t not in ht and ht not in want_t:
                continue
            if want_a and want_a not in ha and ha not in want_a:
                continue
            _, mid = parse_id(h.song_id)
            if mid:
                return mid
        return None

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        mid = self._pick_mid(track)
        if not mid:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r

        filename_base = track.safe_filename()

        # 路径 1：CgiGetVkey 直链（有 cookie 时优先，轻量、快速、不依赖 yt-dlp/ffmpeg）
        if self._has_cookie():
            ok, path, fmt = self._download_direct(mid, dest_dir, filename_base)
            if ok and path:
                r.status = "ok"
                r.path = path
                r.format = fmt
                return r
            # 直链失败时继续尝试 yt-dlp（可能直链接口波动但网页版仍可）

        # 路径 2：yt-dlp 兜底（兼容 cookie_file / cookies_from_browser 两种登录方式）
        ok, path, fmt, reason = self._download_ytdlp(mid, dest_dir, filename_base, track)
        if ok and path:
            r.status = "ok"
            r.path = path
            r.format = fmt
            return r
        r.status = "failed"
        r.fail_reason = reason or "qq_download_failed"
        return r
