"""酷我音乐：公开搜索 + antiserver 直链下载（多数曲目无需登录）。"""
from __future__ import annotations

import os
import re
import urllib.parse

from ..dedup import _norm
from ..format_meta import estimate_size_bytes
from ..models import DownloadResult, Track
from .base import Source
from .http_util import http_download, http_get_json
from .platform_id import make_id, parse_id

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.kuwo.cn/",
}
_BAD = re.compile(
    r"(ktv|伴奏|铃声|喊麦|dj|ｄｊ|remix|夜店|蹦迪|串烧|翻唱|cover|カバー|club\s*mix)",
    re.I,
)


class KuwoSource(Source):
    name = "kuwo"

    def available(self) -> bool:
        return True

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        page = max(0, int(offset)) // max(1, int(limit))
        url = "https://search.kuwo.cn/r.s?" + urllib.parse.urlencode(
            {
                "all": keyword,
                "ft": "music",
                "rformat": "json",
                "encoding": "utf8",
                "rn": max(1, int(limit)),
                "pn": page,
                "mobi": 1,
            }
        )
        data = http_get_json(url, headers=_UA, timeout=15)
        out: list[Track] = []
        for s in data.get("abslist") or []:
            rid = str(s.get("MUSICRID") or "").replace("MUSIC_", "").strip()
            if not rid:
                continue
            title = (s.get("SONGNAME") or s.get("NAME") or "").strip()
            artist = (s.get("ARTIST") or "").strip()
            album = (s.get("ALBUM") or "").strip()
            try:
                dur_s = int(float(s.get("DURATION") or 0))
            except (TypeError, ValueError):
                dur_s = 0
            duration_ms = dur_s * 1000
            # SIZE 偶发缺失：按 320k 估算
            size_bytes = 0
            raw_size = s.get("SIZE") or s.get("size") or ""
            if isinstance(raw_size, (int, float)):
                size_bytes = int(raw_size)
            elif isinstance(raw_size, str) and raw_size.strip().isdigit():
                size_bytes = int(raw_size.strip())
            if size_bytes <= 0 and duration_ms > 0:
                size_bytes = estimate_size_bytes(duration_ms, 320)
            vip = str(s.get("PAY") or "0") not in ("0", "", "None")
            out.append(
                Track(
                    song_id=make_id("kuwo", rid),
                    title=title,
                    artist=artist,
                    album=album,
                    duration_ms=duration_ms,
                    size_bytes=size_bytes,
                    bitrate=320,
                    platform="kuwo",
                    vip_likely=vip,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _pick_rid(self, track: Track) -> str | None:
        plat, rid = parse_id(track.song_id)
        if plat == "kuwo" and rid:
            return rid
        # 按歌手+歌名检索后挑最佳命中
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
            ranked.append((score, h))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0], reverse=True)
        _, best = ranked[0]
        _, rid = parse_id(best.song_id)
        return rid or None

    def _resolve_url(self, rid: str) -> str | None:
        for br in ("320kmp3", "192kmp3", "128kmp3"):
            url = (
                "https://antiserver.kuwo.cn/anti.s?"
                + urllib.parse.urlencode(
                    {
                        "type": "convert_url3",
                        "rid": rid,
                        "format": "mp3",
                        "response": "url",
                        "br": br,
                    }
                )
            )
            try:
                data = http_get_json(url, headers=_UA, timeout=15)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(data, dict) and data.get("url"):
                return str(data["url"])
            if isinstance(data, str) and data.startswith("http"):
                return data
        return None

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        try:
            rid = self._pick_rid(track)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not rid:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r
        try:
            url = self._resolve_url(rid)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not url:
            r.status, r.fail_reason = "failed", "vip_required"
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
