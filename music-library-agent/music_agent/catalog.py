from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request

from . import dedup, llm, prompts
from .models import ArtistCandidate, Track
from .sources.netease_source import NeteaseSource

_BLURB_MAX = 50

# 简介里常见的地区/国籍关键词（长词优先匹配）
_REGION_KEYS = (
    "中国香港", "中国台湾", "中国澳门", "中国大陆",
    "香港", "台湾", "澳门", "日本", "韩国", "美国", "英国",
    "加拿大", "澳大利亚", "新加坡", "马来西亚", "泰国",
    "法国", "德国", "意大利", "西班牙", "瑞典", "挪威",
    "俄罗斯", "印度", "菲律宾", "印尼", "越南", "巴西",
    "墨西哥", "荷兰", "爱尔兰", "新西兰", "中国",
)


def _http_get(url: str) -> bytes:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15, context=ctx).read()


def discover_tracks(
    artist: str,
    top_n: int,
    netease: NeteaseSource | None = None,
    artist_id: str = "",
    platforms: list[str] | None = None,
) -> list[Track]:
    """拉该歌手 Top N。有 artist_id 时按 id 精确取热门曲，避免同名串歌。

    - platforms 为空或仅含 netease：走网易云原生接口（artist_top_tracks / search_tracks）
    - platforms 含其他平台：走 multi_search 多平台检索
    """
    # 纯网易云路径：优先用 artist_top_tracks（有 artist_id 时质量最高）
    if not platforms or (len(platforms) == 1 and platforms[0] == "netease"):
        src = netease or NeteaseSource()
        if artist_id:
            tracks = src.artist_top_tracks(artist_id, top_n)
            # 归一到目标歌手目录/文件名
            for t in tracks:
                t.artist = artist
            return tracks
        return src.search_tracks(artist, top_n)

    # 多平台路径：走 multi_search.search_candidates
    from .sources.multi_search import search_candidates

    raw = search_candidates(artist=artist, limit=top_n, platforms=platforms)
    tracks: list[Track] = []
    for item in raw:
        tracks.append(Track(
            song_id=str(item.get("song_id") or ""),
            title=str(item.get("title") or ""),
            artist=artist,  # 归一到目标歌手
            album=str(item.get("album") or ""),
            duration_ms=int(item.get("duration_ms") or 0),
            artist_id=str(artist_id or item.get("artist_id") or ""),
            size_bytes=int(item.get("size_bytes") or 0),
            bitrate=int(item.get("bitrate") or 0),
            platform=str(item.get("platform") or item.get("source") or ""),
            vip_likely=bool(item.get("vip_likely")),
        ))
    return tracks


def _artist_matches(wanted: str, got: str) -> bool:
    """目标歌手是否出现在结果歌手字段（支持合唱分隔）。"""
    w, g = dedup._norm(wanted), dedup._norm(got)
    if not w or not g:
        return False
    if w == g or w in g:
        return True
    return any(dedup._norm(p) == w for p in re.split(r"[/／,&，、]", got))


def title_matches(wanted: str, got: str) -> bool:
    """歌名是否命中：归一化全等，或正式名匹配「歌名(Live)」等变体。

    绝不把完全不同的歌当成命中（禁止「随便下一首搜索结果」）。
    """
    w, g = dedup._norm(wanted), dedup._norm(got)
    if not w or not g:
        return False
    if w == g:
        return True
    # 变体：结果以目标歌名开头（晴天live / 晴天伴奏），且多出来的不是另一首歌的主体
    if g.startswith(w) and len(g) > len(w):
        return True
    return False


def external_track(artist: str, title: str, artist_id: str = "") -> Track:
    """网易云未收录时，为用户显式指定的 --song 构造外源检索任务（yt-dlp 等）。"""
    a, t = (artist or "").strip(), (title or "").strip()
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", f"{a}_{t}").strip("_") or "unknown"
    return Track(
        song_id=f"ext:{safe}"[:160],
        title=t,
        artist=a,
        artist_id=str(artist_id or ""),
    )


def match_songs(
    artist: str,
    song_titles: list[str],
    netease: NeteaseSource | None = None,
    artist_id: str = "",
    platforms: list[str] | None = None,
) -> tuple[list[Track], list[str]]:
    """按 --song 精确匹配单曲。未命中绝不回退到其它搜索结果。

    返回 (命中的 Track 列表, 未命中的歌名列表)。
    未命中项由 plan_tracks 转为外源 Track，交给 yt-dlp/YouTube，不在此阶段 abort。

    - platforms 为空或仅含 netease：只用网易云搜索
    - platforms 含其他平台：走 multi_search 多平台搜索，按标题精确匹配
    """
    # 纯网易云路径
    if not platforms or (len(platforms) == 1 and platforms[0] == "netease"):
        src = netease or NeteaseSource()
        found: list[Track] = []
        missing: list[str] = []
        for title in song_titles:
            try:
                results = src.search_tracks(f"{artist} {title}", 10)
            except Exception:  # noqa: BLE001
                results = []
            if artist_id:
                results = [t for t in results if t.artist_id == str(artist_id)]
            else:
                results = [t for t in results if _artist_matches(artist, t.artist)]
            hit = next((t for t in results if title_matches(title, t.title)), None)
            if hit:
                hit.artist = artist  # 归一到目标歌手目录/文件名
                hit.artist_id = str(artist_id or hit.artist_id)
                found.append(hit)
            else:
                missing.append(title)
        return found, missing

    # 多平台路径：走 multi_search.search_candidates 按歌名搜索
    from .sources.multi_search import search_candidates

    found: list[Track] = []
    missing: list[str] = []
    for title in song_titles:
        try:
            raw = search_candidates(
                artist=artist,
                song=title,
                limit=10,
                platforms=platforms,
            )
        except Exception:  # noqa: BLE001
            raw = []
        # 按标题精确匹配
        hit = next((item for item in raw if title_matches(title, str(item.get("title", "")))), None)
        if hit:
            found.append(Track(
                song_id=str(hit.get("song_id") or ""),
                title=str(hit.get("title") or ""),
                artist=artist,
                album=str(hit.get("album") or ""),
                duration_ms=int(hit.get("duration_ms") or 0),
                artist_id=str(artist_id or hit.get("artist_id") or ""),
                size_bytes=int(hit.get("size_bytes") or 0),
                bitrate=int(hit.get("bitrate") or 0),
                platform=str(hit.get("platform") or hit.get("source") or ""),
                vip_likely=bool(hit.get("vip_likely")),
            ))
        else:
            missing.append(title)
    return found, missing


def itunes_alias(term: str) -> str | None:
    """iTunes 搜索返回的权威 artistName（用于别名参考/展示）。失败返回 None。

    国内直连时无 country / US 常为空，按 TW→HK→JP→US 回退。
    """
    q = urllib.parse.quote(term)
    for country in ("TW", "HK", "JP", "US", ""):
        try:
            url = (
                f"https://itunes.apple.com/search?term={q}"
                f"&media=music&entity=musicArtist&limit=1"
            )
            if country:
                url += f"&country={country}"
            data = json.loads(_http_get(url))
            results = data.get("results", [])
            if results:
                return results[0].get("artistName")
        except Exception:  # noqa: BLE001
            continue
    return None


def _name_equal(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def find_same_name_artists(
    singer: str,
    netease: NeteaseSource | None = None,
    limit: int = 20,
) -> list[ArtistCandidate]:
    """网易云搜索同名歌手（名称完全相等，忽略大小写）。"""
    src = netease or NeteaseSource()
    try:
        raw = src.search_artists(singer, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    seen: set[str] = set()
    out: list[ArtistCandidate] = []
    for a in raw:
        name = (a.get("name") or "").strip()
        aid = a.get("id")
        if aid is None or not name or not _name_equal(name, singer):
            continue
        key = str(aid)
        if key in seen:
            continue
        seen.add(key)
        try:
            profile = src.artist_profile(key)
        except Exception:  # noqa: BLE001
            profile = {
                "artist_id": key, "name": name, "brief_desc": "", "intro_text": "",
                "hot_songs": [], "album_size": int(a.get("albumSize") or 0),
                "music_size": int(a.get("musicSize") or 0),
            }
        cand = ArtistCandidate(
            artist_id=str(profile.get("artist_id") or key),
            name=profile.get("name") or name,
            brief_desc=profile.get("brief_desc") or "",
            intro_text=profile.get("intro_text") or "",
            hot_songs=list(profile.get("hot_songs") or []),
            album_size=int(profile.get("album_size") or 0),
            music_size=int(profile.get("music_size") or 0),
        )
        cand.blurb = build_artist_blurb(cand)
        out.append(cand)
    return out


def _clip_blurb(text: str, max_len: int = _BLURB_MAX) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _compose_rule_blurb(region: str, founded_part: str, works: str) -> str:
    if region == "国籍不详":
        return f"国籍不详，{founded_part}，{works}"
    return f"{region}艺人，{founded_part}，{works}"


def _guess_region(text: str) -> str:
    for key in _REGION_KEYS:
        if key in text:
            if key == "香港":
                return "中国香港"
            if key == "台湾":
                return "中国台湾"
            if key == "澳门":
                return "中国澳门"
            return key
    return "国籍不详"


def _guess_founded(text: str) -> str:
    # 优先「YYYY年…成立/组建」
    m = re.search(r"(19|20)\d{2}\s*年[^。；;\n]{0,12}(成立|组建|组成)", text)
    if m:
        year = re.search(r"((19|20)\d{2})", m.group(0))
        if year:
            return f"{year.group(1)}年"
    m = re.search(r"(成立|组建|组成)[^。；;\n]{0,12}((19|20)\d{2})\s*年", text)
    if m:
        return f"{m.group(2)}年"
    m = re.search(r"((19|20)\d{2})\s*年", text)
    if m:
        return f"{m.group(1)}年"
    return "成立时间不详"


def _repr_works(hot_songs: list[str], max_n: int = 2) -> str:
    titles = [t.strip() for t in hot_songs if t and t.strip()][:max_n]
    if not titles:
        return "代表作不详"
    return "代表作" + "".join(f"《{t}》" for t in titles)


def build_artist_blurb(cand: ArtistCandidate) -> str:
    """生成 ≤50 字简介，含国籍、成立时间、代表作。优先 LLM，失败则规则拼接。"""
    corpus = "\n".join(x for x in (cand.brief_desc, cand.intro_text) if x)
    hot = ", ".join(cand.hot_songs or [])
    suggestion = llm.ask(prompts.ARTIST_BLURB.format(
        name=cand.name,
        brief_desc=cand.brief_desc or "（无）",
        intro_text=(cand.intro_text[:800] if cand.intro_text else "（无）"),
        hot_songs=hot or "（无）",
        max_len=_BLURB_MAX,
    ))
    if suggestion:
        blurb = _clip_blurb(suggestion, _BLURB_MAX)
        # 粗检三要素是否大致覆盖；不满足则走规则兜底
        if blurb and ("代表作" in blurb or "《" in blurb):
            return blurb

    region = _guess_region(corpus)
    founded = _guess_founded(corpus)
    founded_part = "成立时间不详" if founded == "成立时间不详" else f"{founded}成立"
    # 尽量塞进 50 字：先完整，超长则减代表作/歌名
    for n_works in (2, 1, 0):
        works = _repr_works(cand.hot_songs or [], max_n=n_works) if n_works else "代表作不详"
        blurb = _compose_rule_blurb(region, founded_part, works)
        if len(blurb) <= _BLURB_MAX:
            return _clip_blurb(blurb)
        titles = [t.strip() for t in (cand.hot_songs or []) if t and t.strip()][:n_works]
        if not titles:
            continue
        short = []
        prefix = _compose_rule_blurb(region, founded_part, "代表作")
        budget = _BLURB_MAX - len(prefix) - 2 * len(titles)
        per = max(2, budget // max(len(titles), 1))
        for t in titles:
            short.append(t if len(t) <= per else t[: per - 1] + "…")
        works = "代表作" + "".join(f"《{t}》" for t in short)
        blurb = _compose_rule_blurb(region, founded_part, works)
        if len(blurb) <= _BLURB_MAX:
            return _clip_blurb(blurb)
    return _clip_blurb(_compose_rule_blurb(region, founded_part, "代表作不详"))
