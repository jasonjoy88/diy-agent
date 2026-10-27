"""咪咕音乐：MIGUM2.0 公开搜索 + listen-url 直链（免费曲可下，VIP 标 vip_required）。"""
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
        "Mozilla/5.0 (Linux; Android 12; Pixel 6) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
    ),
    "channel": "0146951",
    "Referer": "https://m.music.migu.cn/v3",
    "Accept": "application/json",
}
_BAD = re.compile(
    r"(ktv|伴奏|铃声|喊麦|dj|ｄｊ|remix|夜店|蹦迪|串烧|翻唱|cover|カバー|club\s*mix)",
    re.I,
)
# PQ≈128k / HQ≈320k / SQ≈flac
_TONE_BITRATE = {"PQ": 128, "HQ": 320, "SQ": 999, "ZQ": 999}
_SEARCH_SWITCH = urllib.parse.quote('{"song":1,"album":0,"singer":0,"tagSong":1,"mvSong":0}')


def _parse_length_ms(raw: str | None) -> int:
    """咪咕 length 常为 HH:MM:SS 或 MM:SS。"""
    text = (raw or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        h, m, s = nums
        return (h * 3600 + m * 60 + s) * 1000
    if len(nums) == 2:
        m, s = nums
        return (m * 60 + s) * 1000
    if len(nums) == 1:
        return nums[0] * 1000
    return 0


def _format_vip(fmt: dict) -> bool:
    tags = fmt.get("showTag") or fmt.get("showTagNew") or []
    return any(str(t).lower() == "vip" for t in tags)


def _pick_format(song: dict) -> tuple[str, int, int, bool]:
    """从 newRateFormats 选展示用音质：返回 (tone, size_bytes, bitrate, vip_likely)。

    vip_likely：PQ（标清）也需 VIP 才视为受限；HQ 带 vip 而 PQ 可免不标 VIP。
    """
    formats = song.get("newRateFormats") or song.get("rateFormats") or []
    by_type: dict[str, dict] = {}
    for fmt in formats:
        ft = (fmt.get("formatType") or "").strip().upper()
        if ft:
            by_type[ft] = fmt
    # 展示优先 HQ，否则 PQ
    display = by_type.get("HQ") or by_type.get("PQ") or by_type.get("SQ")
    if not display:
        return "PQ", 0, 128, False
    tone = (display.get("formatType") or "PQ").strip().upper()
    try:
        size = int(display.get("size") or display.get("androidSize") or 0)
    except (TypeError, ValueError):
        size = 0
    # 下载可得性看最低可用档：PQ 可免 → 非 VIP；无 PQ 则看展示档
    pq = by_type.get("PQ")
    if pq is not None:
        vip_likely = _format_vip(pq)
    else:
        vip_likely = _format_vip(display)
    return tone, size, _TONE_BITRATE.get(tone, 128), vip_likely


class MiguSource(Source):
    name = "migu"

    def available(self) -> bool:
        return True

    def search_tracks(self, keyword: str, limit: int = 10, offset: int = 0) -> list[Track]:
        page_size = max(1, int(limit))
        page_no = max(0, int(offset)) // page_size + 1
        url = (
            "https://pd.musicapp.migu.cn/MIGUM2.0/v1.0/content/search_all.do?"
            f"text={urllib.parse.quote(keyword)}"
            f"&pageNo={page_no}&pageSize={page_size}&isCopyright=1"
            f"&searchSwitch={_SEARCH_SWITCH}"
        )
        data = http_get_json(url, headers=_UA, timeout=15)
        if str(data.get("code") or "") not in ("000000", "0", ""):
            return []
        songs = ((data.get("songResultData") or {}).get("result")) or []
        out: list[Track] = []
        for s in songs:
            content_id = str(s.get("contentId") or "").strip()
            if not content_id:
                continue
            singers = s.get("singers") or []
            artist = "/".join(
                (a.get("name") or "").strip() for a in singers if (a.get("name") or "").strip()
            )
            albums = s.get("albums") or []
            album = ""
            if albums and isinstance(albums[0], dict):
                album = (albums[0].get("name") or "").strip()
            tone, size_bytes, bitrate, fmt_vip = _pick_format(s)
            duration_ms = _parse_length_ms(s.get("length"))
            if duration_ms <= 0 and size_bytes > 0 and bitrate > 0:
                # size / (bitrate_kbps * 1000 / 8) → 秒
                duration_ms = int(size_bytes * 8 / (bitrate * 1000) * 1000)
            if size_bytes <= 0 and duration_ms > 0:
                size_bytes = estimate_size_bytes(duration_ms, bitrate)
            # 以 PQ 档 showTag 为准（HQ 常标 vip 但 PQ 仍可听）
            vip_likely = fmt_vip
            out.append(
                Track(
                    song_id=make_id("migu", content_id),
                    title=(s.get("name") or "").strip(),
                    artist=artist,
                    album=album,
                    duration_ms=duration_ms,
                    size_bytes=size_bytes,
                    bitrate=bitrate,
                    platform="migu",
                    vip_likely=vip_likely,
                )
            )
            if len(out) >= limit:
                break
        return out

    def _pick_content_id(self, track: Track) -> str | None:
        plat, rid = parse_id(track.song_id)
        if plat == "migu" and rid:
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
            if not h.vip_likely:
                score += 2
            ranked.append((score, h))
        if not ranked:
            return None
        ranked.sort(key=lambda x: x[0], reverse=True)
        _, best = ranked[0]
        _, rid = parse_id(best.song_id)
        return rid or None

    def _resolve_url(self, content_id: str) -> tuple[str | None, str]:
        """优先 HQ，再 PQ；VIP/无权限时返回 vip_required。"""
        for tone in ("HQ", "PQ"):
            url = (
                "https://app.pd.nf.migu.cn/MIGUM2.0/v2.0/content/listen-url?"
                + urllib.parse.urlencode(
                    {
                        "toneFlag": tone,
                        "formatType": tone,
                        "resourceType": "E",
                        "netType": "00",
                        "contentId": content_id,
                    }
                )
            )
            try:
                data = http_get_json(url, headers=_UA, timeout=15)
            except Exception:  # noqa: BLE001
                continue
            code = str(data.get("code") or "")
            play = ((data.get("data") or {}).get("url") or "").strip()
            if code == "000000" and play.startswith("http"):
                return play, ""
            # 常见：需 VIP / 鉴权失败
            info = str(data.get("info") or "")
            if any(k in info for k in ("VIP", "vip", "会员", "权限", "鉴权")):
                return None, "vip_required"
        return None, "vip_required"

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(
            track_id=track.song_id, source=self.name, title=track.title, artist=track.artist
        )
        try:
            content_id = self._pick_content_id(track)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not content_id:
            r.status, r.fail_reason = "failed", "resource_not_found"
            return r
        try:
            url, reason = self._resolve_url(content_id)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not url:
            r.status, r.fail_reason = "failed", reason or "vip_required"
            return r
        try:
            os.makedirs(dest_dir, exist_ok=True)
            path_base = url.split("?")[0].lower()
            ext = ".m4a" if path_base.endswith(".m4a") else ".mp3"
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
