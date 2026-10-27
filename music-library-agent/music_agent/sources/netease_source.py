from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request

from ..format_meta import estimate_size_bytes
from ..models import DownloadResult, Track
from .base import Source

_SEARCH = "https://music.163.com/api/search/get?s={q}&type=1&limit={n}&offset={o}"
_SEARCH_ARTIST = "https://music.163.com/api/search/get?s={q}&type=100&limit={n}"
_ARTIST = "https://music.163.com/api/v1/artist/{aid}"
_ARTIST_INTRO = "https://music.163.com/api/artist/introduction?id={aid}"
_URL = "https://music.163.com/api/song/enhance/player/url?ids=[{sid}]&br=320000"
_LYRIC = "https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1"


class NeteaseSource(Source):
    """网易云兜底源。搜索无需 cookie；直链解析无 cookie 时返回 url=null（需 VIP），
    故 available() 以是否配置 cookie 为准。"""

    name = "netease"

    def __init__(self, cookie: str = ""):
        self.cookie = cookie
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def available(self) -> bool:
        return bool(self.cookie)

    def _get(self, url: str) -> bytes:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://music.163.com",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        from .http_util import effective_timeout

        req = urllib.request.Request(url, headers=headers)
        return urllib.request.urlopen(
            req, timeout=effective_timeout(15), context=self._ctx
        ).read()

    def search_tracks(self, keyword: str, limit: int, offset: int = 0) -> list[Track]:
        q = urllib.parse.quote(keyword)
        data = json.loads(self._get(_SEARCH.format(q=q, n=limit, o=max(0, offset))))
        out: list[Track] = []
        for s in data.get("result", {}).get("songs", []):
            arts = s.get("artists") or []
            artists = "/".join(a["name"] for a in arts)
            primary_id = str(arts[0]["id"]) if arts and arts[0].get("id") is not None else ""
            duration_ms = int(s.get("duration") or 0)
            out.append(Track(
                song_id=str(s["id"]), title=s["name"], artist=artists,
                album=s.get("album", {}).get("name", ""), duration_ms=duration_ms,
                artist_id=primary_id,
                size_bytes=estimate_size_bytes(duration_ms, 320),
                bitrate=320,
                platform="netease",
            ))
        return out

    def search_artists(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜索歌手（type=100），返回原始 artist dict 列表。"""
        q = urllib.parse.quote(keyword)
        data = json.loads(self._get(_SEARCH_ARTIST.format(q=q, n=limit)))
        return list(data.get("result", {}).get("artists") or [])

    def artist_top_tracks(self, artist_id: str, limit: int) -> list[Track]:
        """按歌手 id 拉热门曲目（消歧后精确拉取，避免同名串歌）。"""
        data = json.loads(self._get(_ARTIST.format(aid=artist_id)))
        artist_name = (data.get("artist") or {}).get("name") or ""
        out: list[Track] = []
        for s in (data.get("hotSongs") or [])[:limit]:
            arts = s.get("artists") or s.get("ar") or []
            artists = "/".join(a.get("name", "") for a in arts) or artist_name
            duration_ms = int(s.get("duration") or s.get("dt") or 0)
            out.append(Track(
                song_id=str(s["id"]), title=s["name"], artist=artists or artist_name,
                album=(s.get("album") or s.get("al") or {}).get("name", ""),
                duration_ms=duration_ms,
                artist_id=str(artist_id),
                size_bytes=estimate_size_bytes(duration_ms, 320),
                bitrate=320,
                platform="netease",
            ))
        return out

    def artist_profile(self, artist_id: str) -> dict:
        """歌手详情：briefDesc / 简介文本 / 热门歌名 / 规模。"""
        detail = json.loads(self._get(_ARTIST.format(aid=artist_id)))
        artist = detail.get("artist") or {}
        hot = [s.get("name", "") for s in (detail.get("hotSongs") or [])[:5] if s.get("name")]
        intro_text = ""
        try:
            intro = json.loads(self._get(_ARTIST_INTRO.format(aid=artist_id)))
            parts = []
            for block in intro.get("introduction") or []:
                ti = (block.get("ti") or "").strip()
                txt = (block.get("txt") or "").strip()
                if ti == "简介" and txt:
                    parts.append(txt)
                elif ti and txt and ti not in ("成员",):
                    # 保留含成立/国籍线索的段落，跳过冗长成员页
                    if any(k in txt for k in ("成立", "组建", "国籍", "香港", "台湾", "日本", "韩国", "美国", "英国", "中国")):
                        parts.append(txt)
            intro_text = "\n".join(parts)
        except Exception:  # noqa: BLE001
            intro_text = ""
        return {
            "artist_id": str(artist.get("id") or artist_id),
            "name": artist.get("name") or "",
            "brief_desc": (artist.get("briefDesc") or "").replace("\xa0", " ").strip(),
            "intro_text": intro_text.replace("\xa0", " ").strip(),
            "hot_songs": hot,
            "album_size": int(artist.get("albumSize") or 0),
            "music_size": int(artist.get("musicSize") or 0),
        }

    def fetch_lyric(self, song_id: str) -> dict:
        """取歌词：返回 {"lrc": 原文LRC, "tlyric": 翻译LRC}。歌词接口无需 cookie/VIP。"""
        data = json.loads(self._get(_LYRIC.format(sid=song_id)))
        return {
            "lrc": (data.get("lrc") or {}).get("lyric", "") or "",
            "tlyric": (data.get("tlyric") or {}).get("lyric", "") or "",
        }

    def _resolve_url(self, song_id: str) -> tuple[str | None, str]:
        """返回 (直链, 失败原因)。平台拦截时 url 可能仍存在但只是 freeTrialInfo
        划定的试听片段（通常十几到几十秒），此时按 preview_clip 拒绝。"""
        data = json.loads(self._get(_URL.format(sid=song_id)))
        items = data.get("data", [])
        if not items:
            return None, "resource_not_found"
        item = items[0]
        url = item.get("url")
        if not url:
            return None, "vip_required"
        if item.get("freeTrialInfo"):
            return None, "preview_clip"
        return url, ""

    def fetch(self, track: Track, dest_dir: str) -> DownloadResult:
        r = DownloadResult(track_id=track.song_id, source=self.name, title=track.title, artist=track.artist)
        # 外源任务（ext:...）无网易云 song id，直接跳过
        if not str(track.song_id or "").isdigit():
            r.status, r.fail_reason = "failed", "no_netease_id"
            return r
        try:
            url, resolve_reason = self._resolve_url(track.song_id)
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"resolve_error:{e}"
            return r
        if not url:
            r.status, r.fail_reason = "failed", resolve_reason or "vip_required"
            return r
        try:
            os.makedirs(dest_dir, exist_ok=True)
            ext = ".mp3" if url.split("?")[0].lower().endswith(".mp3") else ".m4a"
            path = os.path.join(dest_dir, track.safe_filename() + ext)
            dl_req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com"})
            with urllib.request.urlopen(dl_req, timeout=30, context=self._ctx) as resp, open(path, "wb") as f:
                f.write(resp.read())
            r.status, r.path, r.format = "ok", path, ext.lstrip(".")
        except Exception as e:  # noqa: BLE001
            r.status, r.fail_reason = "failed", f"download_error:{e}"
        return r
