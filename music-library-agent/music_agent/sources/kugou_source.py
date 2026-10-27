"""酷狗音乐：公开搜索 + playInfo 直链（privilege≠0 时常需 VIP）。"""
from __future__ import annotations

import os
import re
import urllib.parse

from ..dedup import _norm
from ..models import DownloadResult, Track
from .base import Source
from .http_util import http_download, http_get_json
from .platform_id import make_id, parse_id

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kugou.com/",
}
_BAD = re.compile(
    r"(ktv|伴奏|铃声|喊麦|dj|ｄｊ|remix|夜店|蹦迪|串烧|翻唱|cover|カバー|club\s*mix)",
    re.I,
)


class KugouSource(Source):
    name = "kugou"

    def available(self) -> bool:
        return True

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        page = max(0, int(offset)) // max(1, int(limit)) + 1
        url = "https://mobilecdn.kugou.com/api/v3/search/song?" + urllib.parse.urlencode(
            {
                "format": "json",
                "keyword": keyword,
                "page": page,
                "pagesize": max(1, int(limit)),
            }
        )
        data = http_get_json(url, headers=_UA, timeout=15)
        out: list[Track] = []
        for s in ((data.get("data") or {}).get("info") or []):
            h320 = (s.get("320hash") or "").strip()
            h128 = (s.get("hash") or "").strip()
            h = h320 or h128
            if not h:
                continue
            title = (s.get("songname") or s.get("songname_original") or "").strip()
            artist = (s.get("singername") or "").strip()
            album = (s.get("album_name") or "").strip()
            try:
                dur_s = int(s.get("duration") or 0)
            except (TypeError, ValueError):
                dur_s = 0
            size = int(s.get("320filesize") or 0) if h320 else int(s.get("filesize") or 0)
            if size <= 0:
                size = int(s.get("filesize") or 0)
            bitrate = 320 if h320 and int(s.get("320filesize") or 0) > 0 else int(s.get("bitrate") or 128)
            privilege = int(s.get("privilege") or 0)
            out.append(
                Track(
                    song_id=make_id("kugou", h.lower()),
                    title=title,
                    artist=artist,
                    album=album,
                    duration_ms=dur_s * 1000,
                    size_bytes=size,
                    bitrate=bitrate,
                    platform="kugou",
                    vip_likely=privilege not in (0,),
                )
            )
            if len(out) >= limit:
                break
        return out

    def _pick_hash(self, track: Track) -> str | None:
        plat, hid = parse_id(track.song_id)
        if plat == "kugou" and hid:
            return hid
        try:
            hits = self.search_tracks(f"{track.artist} {track.title}", limit=8)
        except Exception:  # noqa: BLE001
            return None
        want_t, want_a = _norm(track.title), _norm(track.artist)
        ranked: list[tuple[int, Track]] = []
        for h in hits:
            ht, ha = _norm(h.title), _norm(h.artist)
            if want_t and want_t not in ht and ht not in want_t:
                continue
            if _BAD.search(h.title) and not _BAD.search(track.title or ""):
                continue
            score = 0
            if ht == want_t:
                score += 3
            elif want_t in ht:
                score += 1
            if want_a and want_a in ha:
                score += 2
            if not h.vip_likely:
                score += 2
            ranked.append((score, h))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0], reverse=True)
        _, best = ranked[0]
        _, hid = parse_id(best.song_id)
        return hid or None

    def _resolve_url(self, file_hash: str) -> tuple[str | None, str]:
        url = (
            "http://m.kugou.com/app/i/getSongInfo.php?"
            + urllib.parse.urlencode({"cmd": "playInfo", "hash": file_hash})
        )
        data = http_get_json(url, headers=_UA, timeout=15)
        play = (data.get("url") or "").strip()
        if play:
            return play, ""
        # privilege / 空 url：多为 VIP 或版权限制
        return None, "vip_required"

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        try:
            hid = self._pick_hash(track)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not hid:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r
        try:
            url, reason = self._resolve_url(hid)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not url:
            r.status, r.fail_reason = "failed", reason or "vip_required"
            return r
        try:
            os.makedirs(dest_dir, exist_ok=True)
            path = os.path.join(dest_dir, track.safe_filename() + ".mp3")
            nbytes = http_download(url, path, headers=_UA, timeout=60)
            if nbytes < 50_000:
                try:
                    os.remove(path)
                except OSError:
                    pass
                r.status, r.fail_reason = "failed", "too_small"
                return r
            r.status, r.path, r.format = "ok", path, "mp3"
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"download_error:{e}"
        return r
