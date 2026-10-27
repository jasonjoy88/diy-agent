"""汽水音乐（抖音音乐）：尽力检索；播放地址常需登录/解密，失败则 vip_required。

说明：官方流多加密，完整解密依赖设备签名与 PlayAuth。本源提供检索与
尽力直链；拿不到明文 URL 时标记 vip_required，由 fetch_loop 换源（酷我/B站等）。
"""
from __future__ import annotations

import os
import time
import urllib.parse

from ..dedup import _norm
from ..format_meta import estimate_size_bytes
from ..models import DownloadResult, Track
from .base import Source
from .http_util import http_download, http_get_json
from .platform_id import make_id, parse_id

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15; ABR-AL80) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://music.douyin.com/",
}


class QishuiSource(Source):
    name = "qishui"

    def available(self) -> bool:
        return True

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        cursor = max(0, int(offset))
        params = {
            "device_platform": "android",
            "os": "android",
            "aid": "386088",
            "app_name": "luna",
            "version_code": "100198030",
            "version_name": "19.8.0",
            "channel": "xiaomi_8478_64",
            "device_type": "ABR-AL80",
            "device_brand": "HUAWEI",
            "language": "zh",
            "os_api": "35",
            "os_version": "15",
            "ac": "wifi",
            "package": "com.luna.music",
            "iid": "2204957404569386",
            "device_id": "2204957404565290",
            "_rticket": str(int(time.time() * 1000)),
            "q": keyword,
            "cursor": str(cursor),
            "count": str(max(1, int(limit))),
        }
        url = "https://api.qishui.com/luna/search/track?" + urllib.parse.urlencode(params)
        try:
            data = http_get_json(url, headers=_UA, timeout=15)
        except Exception:  # noqa: BLE001
            # PC 接口有时更宽松（仅元数据）
            return self._search_pc(keyword, limit)
        if (data.get("extra") or {}).get("empty_search"):
            return self._search_pc(keyword, limit)
        return self._parse_groups(data.get("result_groups") or [], limit)

    def _search_pc(self, keyword: str, limit: int) -> list[Track]:
        url = "https://api.qishui.com/luna/pc/search/track?" + urllib.parse.urlencode(
            {
                "aid": "386088",
                "q": keyword,
                "cursor": "",
                "search_method": "input",
            }
        )
        try:
            data = http_get_json(
                url,
                headers={
                    **_UA,
                    "User-Agent": "LunaPC/3.4.0(388267242)",
                },
                timeout=15,
            )
        except Exception:  # noqa: BLE001
            return []
        return self._parse_groups(data.get("result_groups") or [], limit)

    def _parse_groups(self, groups: list, limit: int) -> list[Track]:
        out: list[Track] = []
        for g in groups:
            for item in g.get("data") or []:
                track = ((item.get("entity") or {}).get("track") or {})
                tid = track.get("id")
                if tid is None:
                    continue
                artists = track.get("artists") or []
                artist = "/".join(a.get("name", "") for a in artists if a.get("name"))
                album = ((track.get("album") or {}).get("name")) or ""
                try:
                    duration_ms = int(track.get("duration") or 0)
                except (TypeError, ValueError):
                    duration_ms = 0
                # 汽水时长字段有时已是 ms，有时是秒；>10000 当 ms
                if 0 < duration_ms < 10_000:
                    duration_ms *= 1000
                out.append(
                    Track(
                        song_id=make_id("qishui", str(tid)),
                        title=(track.get("name") or "").strip(),
                        artist=artist,
                        album=album,
                        duration_ms=duration_ms,
                        size_bytes=estimate_size_bytes(duration_ms, 320) if duration_ms else 0,
                        bitrate=320,
                        platform="qishui",
                        # 流多加密：由 is_likely_downloadable 判否，勿标 vip 以免被 VIP 过滤误杀
                        vip_likely=False,
                    )
                )
                if len(out) >= limit:
                    return out
        return out

    def _pick_id(self, track: Track) -> str | None:
        plat, tid = parse_id(track.song_id)
        if plat == "qishui" and tid:
            return tid
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
            _, tid = parse_id(h.song_id)
            if tid:
                return tid
        return None

    def _resolve_url(self, track_id: str) -> str | None:
        # 尽力调用 PC track_v2；加密流通常拿不到明文
        url = "https://api.qishui.com/luna/pc/track_v2?" + urllib.parse.urlencode(
            {
                "track_id": track_id,
                "media_type": "track",
                "queue_type": "search_one_track",
                "aid": "386088",
                "iid": "114514",
            }
        )
        data = http_get_json(
            url,
            headers={**_UA, "User-Agent": "LunaPC/3.4.0(388267242)"},
            timeout=15,
        )
        player = data.get("track_player") or data.get("player") or {}
        info = player.get("url_player_info") or player.get("urlPlayerInfo") or {}
        for key in ("MainPlayUrl", "main_play_url", "BackupPlayUrl", "backup_play_url", "url"):
            val = info.get(key) if isinstance(info, dict) else None
            if isinstance(val, str) and val.startswith("http"):
                return val
        # 少数响应把 url 放在顶层
        for key in ("url", "play_url", "playUrl"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        return None

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        tid = self._pick_id(track)
        if not tid:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r
        try:
            url = self._resolve_url(tid)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not url:
            r.status, r.fail_reason = "failed", "vip_required"
            return r
        try:
            os.makedirs(dest_dir, exist_ok=True)
            ext = ".m4a" if ".m4a" in url.split("?")[0].lower() else ".mp3"
            path = os.path.join(dest_dir, track.safe_filename() + ext)
            nbytes = http_download(url, path, headers=_UA, timeout=60)
            if nbytes < 50_000:
                try:
                    os.remove(path)
                except OSError:
                    pass
                r.status, r.fail_reason = "failed", "too_small"
                return r
            r.status, r.path, r.format = "ok", path, ext.lstrip(".")
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"download_error:{e}"
        return r
