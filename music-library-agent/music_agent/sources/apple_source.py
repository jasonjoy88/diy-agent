"""Apple Music / iTunes：公开 Search API 检索元数据；完整曲受 DRM，下载多需换源。

说明：
- 检索走 itunes.apple.com（按国家码轮询，国内环境 US 常为空，默认 TW/HK）。
- 完整音轨有 DRM，本源不把 30s preview 当成功；fetch 返回 vip_required，
  由 fetch_loop 换酷我/B 站等。若配置了 MUSIC_APPLE_STOREFRONT，可固定首选店面。
"""
from __future__ import annotations

import os
import re
import urllib.parse

from ..dedup import _norm
from ..format_meta import estimate_size_bytes
from ..models import DownloadResult, Track
from .base import Source
from .http_util import has_http_timeout_override, http_get_json
from .platform_id import make_id, parse_id

_UA = {
    "User-Agent": (
        "iTunes/12.12.9 (Windows; Microsoft Windows 10 x64) "
        "AppleWebKit/605.1.15"
    ),
    "Accept": "application/json",
}
_BAD = re.compile(
    r"(ktv|伴奏|铃声|喊麦|dj|ｄｊ|remix|夜店|蹦迪|串烧|翻唱|cover|カバー|club\s*mix)",
    re.I,
)
# 国内直连时 US/空 country 常 resultCount=0；港台日更稳
_DEFAULT_STOREFRONTS = ("TW", "HK", "JP", "US", "CN")


class AppleSource(Source):
    name = "apple"

    def __init__(self, storefront: str = "") -> None:
        raw = (storefront or os.environ.get("MUSIC_APPLE_STOREFRONT", "") or "").strip().upper()
        if raw:
            # 用户指定的店面优先，其余作回退
            rest = [c for c in _DEFAULT_STOREFRONTS if c != raw]
            self._storefronts = (raw, *rest)
        else:
            self._storefronts = _DEFAULT_STOREFRONTS

    def available(self) -> bool:
        return True

    def _search_storefront(
        self, keyword: str, country: str, limit: int, offset: int
    ) -> list[dict]:
        params = {
            "term": keyword,
            "media": "music",
            "entity": "song",
            "limit": max(1, min(200, int(limit) + max(0, int(offset)))),
        }
        if country:
            params["country"] = country
        url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(params)
        data = http_get_json(url, headers=_UA, timeout=15)
        results = data.get("results") or []
        if offset:
            results = results[int(offset) :]
        return results[: max(1, int(limit))]

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        # 检索快检模式只试前 2 个店面，避免串行轮询拖满超时
        storefronts = self._storefronts[:2] if has_http_timeout_override() else self._storefronts
        raw_hits: list[dict] = []
        for country in storefronts:
            try:
                raw_hits = self._search_storefront(keyword, country, limit, offset)
            except Exception:  # noqa: BLE001
                continue
            if raw_hits:
                break
        out: list[Track] = []
        for s in raw_hits:
            tid = s.get("trackId")
            if tid is None:
                continue
            duration_ms = int(s.get("trackTimeMillis") or 0)
            # iTunes 无完整文件体积；按 AAC ~256k 估算便于列表展示
            bitrate = 256
            size_bytes = estimate_size_bytes(duration_ms, bitrate) if duration_ms else 0
            out.append(
                Track(
                    song_id=make_id("apple", str(tid)),
                    title=(s.get("trackName") or "").strip(),
                    artist=(s.get("artistName") or "").strip(),
                    album=(s.get("collectionName") or "").strip(),
                    duration_ms=duration_ms,
                    size_bytes=size_bytes,
                    bitrate=bitrate,
                    platform="apple",
                    # DRM 不可直下：由 is_likely_downloadable 判否，勿标 vip 以免被 VIP 过滤误杀
                    vip_likely=False,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _pick_track_id(self, track: Track) -> str | None:
        plat, rid = parse_id(track.song_id)
        if plat == "apple" and rid:
            return rid
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

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        """Apple Music 完整音轨受 DRM，不把 preview 当成功；交给其它音源。"""
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        # 确认曲目存在（便于日志/排障）；即便命中也因 DRM 无法完整下载
        tid = self._pick_track_id(track)
        if not tid:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r
        r.status, r.fail_reason = "failed", "vip_required"
        return r
