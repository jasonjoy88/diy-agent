"""多平台资源检索：网易云 / QQ / 酷狗 / 酷我 / 汽水 / 咪咕 / Apple Music，可选 LLM 选平台。"""
from __future__ import annotations

import json
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from .. import llm, prompts
from ..config import CONFIG, load_netease_cookie
from ..dedup import _norm
from ..format_meta import estimate_size_bytes, format_duration, format_size, platform_label
from ..models import Track
from .apple_source import AppleSource
from .bilibili_source import BilibiliSource
from .http_util import http_timeout_override
from .kugou_source import KugouSource
from .kuwo_source import KuwoSource
from .migu_source import MiguSource
from .netease_source import NeteaseSource
from .qq_source import QQSource
from .qishui_source import QishuiSource

_ALL = ("netease", "qq", "kugou", "kuwo", "qishui", "migu", "apple", "bilibili")

# 检索加速：平台并行 + 单源短超时（可用环境变量覆盖）
_SEARCH_HTTP_TIMEOUT = float(os.environ.get("MUSIC_SEARCH_TIMEOUT", "5") or "5")
_SEARCH_WORKERS = max(1, int(os.environ.get("MUSIC_SEARCH_WORKERS", "8") or "8"))
_ARTIST_CHECK_WORKERS = max(1, int(os.environ.get("MUSIC_ARTIST_CHECK_WORKERS", "8") or "8"))
# 网易云正式歌手磁盘缓存 TTL（秒），默认 7 天
_ARTIST_DISK_TTL = int(os.environ.get("MUSIC_ARTIST_CACHE_TTL", str(7 * 24 * 3600)) or "0")

# 平台梯队（数值越小越好）
# 第一梯队：YouTube / Bilibili / 网易云 / Apple Music / 咪咕
# 第二梯队：酷狗 / QQ / 汽水
# 第三梯队：酷我
_PLATFORM_FREE_RANK = {
    "youtube": 0,
    "bilibili": 0,
    "ytdlp": 0,
    "netease": 0,
    "apple": 0,
    "migu": 0,
    "kugou": 1,
    "qq": 1,
    "qishui": 1,
    "kuwo": 2,
}

# 时长范围（毫秒）：过短（如铃声/片段）和过长（现场/串烧）都过滤
_MIN_DURATION_MS = 2 * 60 * 1000 + 30 * 1000  # 2 分 30 秒
_MAX_DURATION_MS = 6 * 60 * 1000                # 6 分钟

# 下载必须具备 Cookie 的平台（无 Cookie 时标注「需Cookie」，不视为可完整下载）
_COOKIE_REQUIRED_PLATFORMS = frozenset({"netease", "qq"})

# 标题含这些时，虽可下也更像非完整原曲（排序略靠后）
_PARTIAL_TITLE = re.compile(
    r"(试听|片段|preview|30秒|铃声|彩铃|伴奏|消音|ktv|喊麦)",
    re.I,
)

# 伴奏 / 纯音乐 / 卡拉OK 等无人声版本：默认从检索结果中屏蔽（查询本身含伴奏时放行）
_ACCOMPANIMENT = re.compile(
    r"(?:^|[\s\(\[【\-_|／/])"
    r"(?:伴奏|纯伴奏|原版伴奏|官方伴奏|高品质伴奏|消音|消音版|纯音乐|无人声|instrumental|"
    r"inst\.?\b|backing\s*track|karaoke|ktv|卡拉ok|卡拉OK)"
    r"(?:$|[\s\)\]】\-_|／/：:])",
    re.I,
)
# 标题里出现伴奏等（宽松兜底，如「晴天伴奏」「伴奏-晴天」）
_ACCOMPANIMENT_LOOSE = re.compile(
    r"(伴奏|纯伴奏|原版伴奏|官方伴奏|高品质伴奏|消音|消音版|纯音乐|无人声|"
    r"instrumental|karaoke|ktv|卡拉ok)",
    re.I,
)

# 任意 DJ / 夜店混音版：默认从检索结果中屏蔽（查询本身含 DJ 时放行）
_DJ_BLOCK = re.compile(
    r"(?:^|[\s\(\[【\-_|／/])"
    r"(?:dj|ｄｊ|dj版|dj混音|夜店|蹦迪|串烧|club\s*mix|extended\s*mix|"
    r"bootleg|mashup|remix|重混|改版混音|抖音热播)"
    r"(?:$|[\s\)\]】\-_|／/：:])",
    re.I,
)
# 标题里单独出现 DJ（无边界时的兜底，如「晴天DJ版」「DJ晴天」）
_DJ_LOOSE = re.compile(
    r"(?:dj\s*版|dj版|\bdj\b|ｄｊ|remix|夜店|蹦迪|串烧|club\s*mix)",
    re.I,
)

# 非录音室：现场/演唱会等（不屏蔽，但排序靠后于录音室专辑版）
_LIVE_NON_STUDIO = re.compile(
    r"(live|现场|演唱会|音乐会|concert|巡回|不插电|acoustic\s*live|录音棚花絮)",
    re.I,
)

# 专辑名像合集/DJ 碟时，不算录音室专辑
_ALBUM_NON_STUDIO = re.compile(
    r"(dj|remix|夜店|串烧|热播|精选合辑|抖音|铃声|伴奏|live|现场|演唱会)",
    re.I,
)

# 翻唱 / Cover 标记（仅用于录音室原版判定，不再用于过滤）
_COVER_MARK = re.compile(
    r"(翻唱|翻唱版|翻自|翻唱者|\bcover\b|カバー|covered\s+by|cover\s*by)",
    re.I,
)
# 标题中标注原唱（结果艺人≠原唱 → 视为翻唱）
_ORIGINAL_SINGER = re.compile(
    r"(?:原唱|原曲|原版)\s*[:：]\s*([^\s\|/／\[\]【】\(\)（）]+)",
)

# 网易云「正式歌手」内存缓存：归一化艺人名 → 是否命中
_NETEASE_ARTIST_CACHE: dict[str, bool] = {}
_ARTIST_DISK_LOADED = False


def _artist_disk_path() -> Path:
    raw = (os.environ.get("MUSIC_ARTIST_CACHE_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    try:
        root = Path(CONFIG.output_root).expanduser().resolve().parent
    except Exception:  # noqa: BLE001
        root = Path(__file__).resolve().parent.parent.parent
    return root / ".netease_artist_cache.json"


def _load_artist_disk_cache() -> None:
    """把未过期的磁盘缓存灌进内存（进程内只加载一次）。"""
    global _ARTIST_DISK_LOADED
    if _ARTIST_DISK_LOADED:
        return
    _ARTIST_DISK_LOADED = True
    path = _artist_disk_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    ttl = _ARTIST_DISK_TTL if _ARTIST_DISK_TTL > 0 else 7 * 24 * 3600
    for k, v in data.items():
        key = _norm(str(k))
        if not key or key in _NETEASE_ARTIST_CACHE:
            continue
        if isinstance(v, bool):
            _NETEASE_ARTIST_CACHE[key] = v
            continue
        if not isinstance(v, dict):
            continue
        ts = float(v.get("ts") or 0)
        if ts and now - ts > ttl:
            continue
        if "ok" in v:
            _NETEASE_ARTIST_CACHE[key] = bool(v["ok"])


def _persist_artist_disk_cache(updates: dict[str, bool]) -> None:
    if not updates:
        return
    path = _artist_disk_path()
    store: dict = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                store = raw
        except Exception:  # noqa: BLE001
            store = {}
    now = time.time()
    for k, ok in updates.items():
        store[k] = {"ok": bool(ok), "ts": now}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _enabled_platforms() -> list[str]:
    cfg = CONFIG
    mapping = {
        "netease": cfg.enable_netease,
        "qq": cfg.enable_qq,
        "kugou": cfg.enable_kugou,
        "kuwo": cfg.enable_kuwo,
        "qishui": cfg.enable_qishui,
        "migu": cfg.enable_migu,
        "apple": cfg.enable_apple,
        # B 站检索和 yt-dlp 下载共用一个能力开关
        "bilibili": cfg.enable_ytdlp,
    }
    return [p for p in _ALL if mapping.get(p, False)]


def _build_searchers(platforms: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for p in platforms:
        if p == "netease":
            out[p] = NeteaseSource(cookie=CONFIG.netease_cookie)
        elif p == "qq":
            out[p] = QQSource(
                cookie_file=CONFIG.qq_cookie_file,
                cookies_from_browser=CONFIG.qq_cookies_from_browser,
                ffmpeg_bin=CONFIG.ffmpeg_bin,
            )
        elif p == "kugou":
            out[p] = KugouSource()
        elif p == "kuwo":
            out[p] = KuwoSource()
        elif p == "qishui":
            out[p] = QishuiSource()
        elif p == "migu":
            out[p] = MiguSource()
        elif p == "apple":
            out[p] = AppleSource(storefront=CONFIG.apple_storefront)
        elif p == "bilibili":
            out[p] = BilibiliSource(cookie_file=CONFIG.ytdlp_cookie_file)
    return out


def _pick_platforms(query: str, enabled: list[str]) -> list[str]:
    if len(enabled) <= 1:
        return list(enabled)
    choice = llm.ask(
        prompts.PICK_PLATFORMS.format(
            query=query,
            platforms="、".join(enabled),
        )
    )
    if not choice:
        return list(enabled)
    picked = [p for p in enabled if p in choice.lower() or platform_label(p) in choice]
    # LLM 可能返回中文名
    label_map = {platform_label(p): p for p in enabled}
    for label, p in label_map.items():
        if label in choice and p not in picked:
            picked.append(p)
    return picked or list(enabled)


def _dedupe_key(t: Track) -> str:
    return f"{_norm(t.artist)}|{_norm(t.title)}|{t.platform or ''}"


def _same_song_key(t: Track) -> str:
    """跨平台同曲指纹：同歌手 + 同名 + 同专辑 + 同时长（秒）。"""
    dur_s = int(t.duration_ms // 1000) if t.duration_ms else 0
    return f"{_norm(t.artist)}|{_norm(t.title)}|{_norm(t.album or '')}|{dur_s}"


def collapse_same_songs(
    tracks: list[Track],
    query: str = "",
    max_keep: int = 2,
) -> list[Track]:
    """同名同专辑同时长同歌手：只留可直接下载的最优源，最多 max_keep 首。

    - 仅一条时原样保留（哪怕暂不可下）。
    - 多条重复时：丢掉不可直接下载的，按 download_sort_key 取前 max_keep 首。
    - 多条但全不可下：整组不展示。
    """
    groups: OrderedDict[str, list[Track]] = OrderedDict()
    for t in tracks:
        groups.setdefault(_same_song_key(t), []).append(t)

    out: list[Track] = []
    for items in groups.values():
        if len(items) == 1:
            out.append(items[0])
            continue
        downloadable = [t for t in items if is_likely_downloadable(t)]
        if not downloadable:
            continue
        downloadable.sort(key=lambda t: download_sort_key(t, query))
        out.extend(downloadable[:max_keep])
    return out


def _has_platform_auth(platform: str) -> bool:
    """当前环境是否具备该平台登录态（提高完整下载概率）。"""
    plat = (platform or "").strip().lower()
    if plat == "netease":
        cookie = load_netease_cookie(
            cookie_file=os.environ.get("NETEASE_COOKIE_FILE") or CONFIG.netease_cookie_file,
            inline=os.environ.get("NETEASE_COOKIE", ""),
        )
        return bool(cookie)
    if plat == "qq":
        path = os.environ.get("MUSIC_QQ_COOKIE_FILE") or CONFIG.qq_cookie_file
        return bool(path and os.path.isfile(path)) or bool(CONFIG.qq_cookies_from_browser)
    if plat in ("bilibili", "ytdlp"):
        path = os.environ.get("MUSIC_YTDLP_COOKIE_FILE") or CONFIG.ytdlp_cookie_file
        return bool(path and os.path.isfile(path)) or bool(CONFIG.ytdlp_cookies_from_browser)
    # 酷我/酷狗检索侧已用 privilege/PAY 标记；无 cookie 也可尝试
    return True


def query_wants_dj(query: str) -> bool:
    """用户查询是否明确要 DJ 版（此时不屏蔽）。"""
    return bool(_DJ_LOOSE.search(query or ""))


def is_dj_version(t: Track) -> bool:
    """歌名或专辑是否为 DJ / 夜店混音版。"""
    blob = f"{t.title or ''} {t.album or ''}"
    if _DJ_BLOCK.search(blob):
        return True
    return bool(_DJ_LOOSE.search(blob))


def query_wants_accompaniment(query: str) -> bool:
    """用户查询是否明确要伴奏/纯音乐（此时不屏蔽）。"""
    return bool(_ACCOMPANIMENT_LOOSE.search(query or ""))


def is_accompaniment_version(t: Track) -> bool:
    """歌名或专辑是否为伴奏 / 纯音乐 / 卡拉OK 等无人声版本。"""
    blob = f"{t.title or ''} {t.album or ''}"
    if _ACCOMPANIMENT.search(blob):
        return True
    return bool(_ACCOMPANIMENT_LOOSE.search(blob))


def _artist_tokens(artist: str) -> list[str]:
    """合唱艺人拆分并归一化。"""
    parts = re.split(r"[/／,&，、|]", artist or "")
    return [_norm(p) for p in parts if _norm(p)]


def _artist_raw_parts(artist: str) -> list[str]:
    """合唱艺人拆分（保留原始写法，供网易云检索）。"""
    parts = re.split(r"[/／,&，、|]", artist or "")
    return [p.strip() for p in parts if p.strip()]


def _is_netease_formal_artist_hit(raw: dict) -> bool:
    """单条网易云歌手搜索结果是否算正式歌手（有作品，或入驻认证标记）。"""
    if int(raw.get("albumSize") or 0) > 0 or int(raw.get("musicSize") or 0) > 0:
        return True
    try:
        if int(raw.get("accountId") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if (raw.get("identityIconUrl") or "").strip():
        return True
    return False


def _lookup_one_artist(part: str, src: NeteaseSource) -> tuple[str, bool]:
    """查单个艺人名是否正式歌手；返回 (norm_key, ok)。异常视为放行。"""
    key = _norm(part)
    if not key:
        return key, False
    try:
        with http_timeout_override(_SEARCH_HTTP_TIMEOUT):
            raw_list = src.search_artists(part, limit=10)
        for a in raw_list:
            name = (a.get("name") or "").strip()
            if not name or _norm(name) != key:
                continue
            if _is_netease_formal_artist_hit(a):
                return key, True
        return key, False
    except Exception:  # noqa: BLE001
        return key, True


def prefetch_verified_artists(
    artists: list[str],
    netease: NeteaseSource | None = None,
) -> None:
    """对一批艺人名去重后并行校验，写入内存 + 磁盘缓存。"""
    _load_artist_disk_cache()
    src = netease or NeteaseSource(cookie=CONFIG.netease_cookie)
    pending: dict[str, str] = {}  # norm_key -> raw part
    for artist in artists:
        for part in _artist_raw_parts(artist):
            key = _norm(part)
            if not key or key in _NETEASE_ARTIST_CACHE or key in pending:
                continue
            pending[key] = part
    if not pending:
        return
    updates: dict[str, bool] = {}
    workers = min(_ARTIST_CHECK_WORKERS, len(pending))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_lookup_one_artist, part, src) for part in pending.values()]
        for fut in as_completed(futs):
            try:
                key, ok = fut.result()
            except Exception:  # noqa: BLE001
                continue
            if not key:
                continue
            _NETEASE_ARTIST_CACHE[key] = ok
            updates[key] = ok
    _persist_artist_disk_cache(updates)


def is_netease_verified_artist(
    artist: str,
    netease: NeteaseSource | None = None,
) -> bool:
    """歌手是否能在网易云歌手搜索中精确命中为正式/认证歌手。

    口径：type=100 精确同名命中，且有作品量（album/music）或入驻标记
    （accountId / identityIconUrl）。大牌艺人常无 accountId，故以作品量为准。
    合唱时任一主唱命中即可。网易云接口异常时放行，避免检索被打空。
    优先读内存/磁盘缓存；未命中缓存时同步查询（检索路径应先 prefetch）。
    """
    _load_artist_disk_cache()
    parts = _artist_raw_parts(artist)
    if not parts:
        return False
    src = netease or NeteaseSource(cookie=CONFIG.netease_cookie)
    for part in parts:
        key = _norm(part)
        cached = _NETEASE_ARTIST_CACHE.get(key)
        if cached is not None:
            if cached:
                return True
            continue
        k2, ok = _lookup_one_artist(part, src)
        if k2:
            _NETEASE_ARTIST_CACHE[k2] = ok
            _persist_artist_disk_cache({k2: ok})
        if ok:
            return True
    return False


def _search_platform(
    name: str,
    src: object,
    query: str,
    per: int,
) -> tuple[str, list[Track]]:
    """单平台检索（供线程池调用）；失败返回空列表。"""
    try:
        with http_timeout_override(_SEARCH_HTTP_TIMEOUT):
            hits = src.search_tracks(query, per, 0)  # type: ignore[attr-defined]
        return name, list(hits or [])
    except Exception:  # noqa: BLE001
        return name, []


def is_cover_version(t: Track) -> bool:
    """是否翻唱/Cover（标题标记，或标注原唱且与结果艺人不同）。"""
    blob = f"{t.title or ''} {t.album or ''}"
    if _COVER_MARK.search(blob):
        return True
    m = _ORIGINAL_SINGER.search(t.title or "")
    if not m:
        return False
    original = _norm(m.group(1))
    arts = _artist_tokens(t.artist or "")
    if not original or not arts:
        return False
    # 原唱名未出现在结果艺人中 → 视为他人翻唱
    return all(original != a and original not in a and a not in original for a in arts)


def is_studio_album_version(t: Track) -> bool:
    """是否更像录音室专辑原版（非 DJ / 非翻唱 / 非伴奏 / 非现场 / 非试听铃声）。"""
    if is_dj_version(t) or is_cover_version(t) or is_accompaniment_version(t):
        return False
    title = t.title or ""
    album = (t.album or "").strip()
    if _PARTIAL_TITLE.search(title):
        return False
    if _LIVE_NON_STUDIO.search(title):
        return False
    if album and _LIVE_NON_STUDIO.search(album):
        return False
    if album and _ALBUM_NON_STUDIO.search(album):
        return False
    # 有正经专辑名，或歌名干净（无括号装饰）→ 视为录音室向
    if album:
        return True
    # 无专辑时：标题无 Live/Remix 类括号也算较干净
    if re.search(r"[\(（\[【].+?[\)）\]】]", title):
        return False
    return True


def platform_requires_cookie(platform: str) -> bool:
    """该平台完整下载是否必须 Cookie。

    - netease：无 Cookie 时播放/下载直链常为 null
    - qq：下载通常需登录 Cookie
    其余平台（酷我/酷狗免费曲/咪咕免费曲等）检索侧不强制 Cookie；
    Bilibili/YouTube 有 Cookie 更稳，但不作为硬性门槛。
    """
    return (platform or "").strip().lower() in _COOKIE_REQUIRED_PLATFORMS


def is_likely_downloadable(t: Track) -> bool:
    """检索侧启发式：当前是否更可能完整下载。

    VIP 曲一律否；须 Cookie 的平台在无登录态时否；Apple/汽水不可完整下。
    """
    plat = (t.platform or "").strip().lower()
    if t.vip_likely:
        return False
    if is_dj_version(t) or is_accompaniment_version(t):
        return False
    if _PARTIAL_TITLE.search(t.title or ""):
        return False
    if plat == "qishui":
        return False
    if plat == "apple":
        # Apple Music 完整曲 DRM，检索侧不可完整下载
        return False
    if platform_requires_cookie(plat) and not _has_platform_auth(plat):
        return False
    if plat in ("bilibili", "youtube", "ytdlp", "kuwo", "migu", "kugou", "netease", "qq"):
        return True
    return True


def _title_relevance(t: Track, query: str) -> int:
    """歌名与查询相关度（越小越相关）。"""
    qn = _norm(query)
    tn = _norm(t.title)
    if not tn or not qn:
        return 3
    if tn == qn or qn.endswith(tn) or tn in qn:
        return 0
    # 查询分词命中歌名（如「周杰伦 晴天」）
    parts = [p for p in re.split(r"\s+", (query or "").strip()) if p]
    if parts and any(_norm(p) == tn or tn in _norm(p) or _norm(p) in tn for p in parts):
        return 1
    if any(_norm(p) and _norm(p) in tn for p in parts):
        return 2
    return 3


def download_sort_key(t: Track, query: str = "") -> tuple:
    """排序键（越小越靠前）：可完整下载 → VIP 降权 → 录音室原版 → 标题相关 → 平台梯队 → 码率。"""
    downloadable = 0 if is_likely_downloadable(t) else 1
    # VIP 不丢弃，仅降权排后
    vip = 1 if t.vip_likely else 0
    studio = 0 if is_studio_album_version(t) else 1
    # 无登录态的网易云/QQ 再降一档（须 Cookie）
    auth_penalty = 0
    plat = (t.platform or "").strip().lower()
    if platform_requires_cookie(plat) and not _has_platform_auth(plat):
        auth_penalty = 1
    plat_rank = _PLATFORM_FREE_RANK.get(plat, 9)
    partial = 1 if _PARTIAL_TITLE.search(t.title or "") else 0
    rel = _title_relevance(t, query)
    album_missing = 0 if (t.album or "").strip() else 1
    # 有时长/体积的排前面；高码率优先；稳定次序用标题
    meta_missing = 0 if t.duration_ms else 1
    size_missing = 0 if t.size_bytes else 1
    br = -int(t.bitrate or 0)
    return (
        downloadable,
        vip,
        studio,
        auth_penalty,
        partial,
        rel,
        album_missing,
        plat_rank,
        meta_missing,
        size_missing,
        br,
        _norm(t.title),
    )


def _fetch_artist_top_tracks(
    artist_name: str,
    artist_id: str,
    netease_src: NeteaseSource,
    limit: int,
    offset: int,
) -> list[Track]:
    """按歌手从网易云拉热门歌曲，返回 Track 列表（应用时长过滤）。

    数据来源：
      1. 歌手详情接口 hotSongs（最多 50 首，按网易云热度排序）
      2. 搜索接口按歌手名搜索补充更多歌曲（过滤出该歌手参与的曲目）

    合并策略：hotSongs 优先（保留热度排序），搜索结果去重后追加。
    歌手热门歌曲不做多源合并，仅使用网易云数据源，因为：
      1. 歌手热门曲目的概念是平台相关的，其他平台没有统一的"热门50首"接口
      2. 网易云曲目最全，作为基准源足够
      3. 用户下载时会自动走多源下载，不局限于网易云
    """
    if not artist_id and not artist_name:
        return []

    artist_norm = _norm(artist_name)
    target_aid = str(artist_id or "")

    # ① hotSongs（最多 50 首，按热度排）
    hot_tracks: list[Track] = []
    try:
        with http_timeout_override(_SEARCH_HTTP_TIMEOUT):
            hot_tracks = netease_src.artist_top_tracks(artist_id, limit=50)
    except Exception:  # noqa: BLE001
        hot_tracks = []

    # ② 搜索接口补充（分页抓取，过滤出该歌手参与的歌曲）
    search_tracks: list[Track] = []
    if artist_name:
        # 搜索总上限：取 200 首原始结果，过滤后通常足够
        search_total = 200
        page_size = 30
        for off in range(0, search_total, page_size):
            try:
                with http_timeout_override(_SEARCH_HTTP_TIMEOUT):
                    page = netease_src.search_tracks(artist_name, limit=page_size, offset=off)
            except Exception:  # noqa: BLE001
                break
            if not page:
                break
            for t in page:
                # 过滤：该歌手为主唱（artist_id 匹配）或歌手名出现在 artist 字段中
                is_primary = target_aid and str(t.artist_id or "") == target_aid
                arts_norm = _norm(t.artist or "")
                is_featured = bool(artist_norm and artist_norm in arts_norm)
                if is_primary or is_featured:
                    search_tracks.append(t)
            # 如果本页结果少于 page_size，说明已到末尾
            if len(page) < page_size:
                break

    # ③ 合并去重：hotSongs 优先，搜索结果去重后追加
    seen_ids: set[str] = set()
    merged: list[Track] = []
    for t in hot_tracks:
        if t.song_id and t.song_id in seen_ids:
            continue
        if t.song_id:
            seen_ids.add(t.song_id)
        merged.append(t)
    for t in search_tracks:
        if t.song_id and t.song_id in seen_ids:
            continue
        if t.song_id:
            seen_ids.add(t.song_id)
        merged.append(t)

    # ④ 时长过滤 + DJ/伴奏过滤
    filtered: list[Track] = []
    for t in merged:
        if is_dj_version(t):
            continue
        if is_accompaniment_version(t):
            continue
        if t.duration_ms and (t.duration_ms < _MIN_DURATION_MS or t.duration_ms > _MAX_DURATION_MS):
            continue
        filtered.append(t)
    return filtered


def _resolve_artist_id(
    artist_name: str,
    netease_src: NeteaseSource,
) -> tuple[str, str] | None:
    """将用户显式输入的歌手名解析为网易云正式歌手，返回 (artist_name, artist_id)。

    精确匹配口径：type=100 搜索结果中歌手名归一化后与输入完全一致，
    且满足「正式歌手」条件（有作品量 / 入驻认证 / accountId），同名取热度首位。
    网络异常或无正式歌手命中时返回 None，调用方回退为按歌手名普通搜索。
    """
    q = (artist_name or "").strip()
    if not q:
        return None
    qn = _norm(q)
    if not qn:
        return None
    try:
        with http_timeout_override(_SEARCH_HTTP_TIMEOUT):
            raw_list = netease_src.search_artists(q, limit=10)
    except Exception:  # noqa: BLE001
        return None
    for a in raw_list:
        a_name = (a.get("name") or "").strip()
        if a_name and _norm(a_name) == qn and _is_netease_formal_artist_hit(a):
            return a_name, str(a.get("id") or "")
    return None


def search_candidates(
    artist: str = "",
    song: str = "",
    limit: int = 10,
    offset: int = 0,
    platforms: list[str] | None = None,
) -> list[dict]:
    """多平台检索，返回带展示字段的 dict 列表。

    歌手/歌名由调用方显式给出，不做意图猜测或自动拆分：
    - 仅 artist：先解析为网易云正式歌手并拉其歌曲（hotSongs + 搜索补充），
      解析不到或结果为空时，回退为按歌手名多平台搜索（只保留该歌手的结果）；
    - 仅 song：按歌名多平台搜索；
    - 两者都有：AND 检索，搜索词 "artist song" 且只保留该歌手的结果，不回退。

    - platforms 为空时按配置启用源；有 LLM 时可缩窄平台集合。
      显式指定 platforms（非 None）时严格按指定集合检索，不经 LLM 缩窄。
    - offset/limit 作用于合并去重后的结果切片。
    - 默认屏蔽：DJ 版、伴奏/纯音乐版、非网易云正式歌手、时长 > 6 分钟。
    - 用户查询词含「伴奏/纯音乐/karaoke」等关键词时，自动放行伴奏版。
    - VIP 不丢弃，仅排序降权；优先「可完整下载的录音室专辑版」，平台按三梯队。
    - 同歌手/歌名/专辑/时长：只留可直接下载的最优源，最多 2 首。
    """
    artist = (artist or "").strip()
    song = (song or "").strip()
    if not artist and not song:
        return []

    enabled = platforms or _enabled_platforms()
    if not enabled:
        enabled = ["netease"]
    query_text = f"{artist} {song}".strip()
    allow_dj = query_wants_dj(query_text)
    allow_accompaniment = query_wants_accompaniment(query_text)
    netease_checker = NeteaseSource(cookie=CONFIG.netease_cookie)

    # 内部辅助：执行一次多平台检索并处理过滤/排序
    def _do_search(search_q: str, filter_artist: str = "") -> list[Track]:
        # 显式指定平台时尊重调用方选择；否则走 LLM 缩窄（未配置 LLM 时原样返回）
        chosen = list(enabled) if platforms else _pick_platforms(search_q, enabled)
        searchers = _build_searchers(chosen)
        per = max((limit + offset) * 2, limit * 2, 20)
        raw_hits: list[Track] = []
        if searchers:
            workers = min(_SEARCH_WORKERS, len(searchers))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [
                    pool.submit(_search_platform, name, src, search_q, per)
                    for name, src in searchers.items()
                ]
                for fut in as_completed(futs):
                    try:
                        name, hits = fut.result()
                    except Exception:  # noqa: BLE001
                        continue
                    for t in hits:
                        if not t.platform:
                            t.platform = name
                        raw_hits.append(t)
        candidates: list[Track] = []
        for t in raw_hits:
            if not allow_dj and is_dj_version(t):
                continue
            if not allow_accompaniment and is_accompaniment_version(t):
                continue
            if t.duration_ms and (t.duration_ms < _MIN_DURATION_MS or t.duration_ms > _MAX_DURATION_MS):
                continue
            # 指定了歌手过滤时，只保留该歌手的结果
            if filter_artist:
                arts_norm = _norm(t.artist or "")
                artist_norm = _norm(filter_artist)
                if artist_norm and artist_norm not in arts_norm:
                    parts_ok = any(
                        _norm(p) == artist_norm
                        for p in re.split(r"[/／,&，、|]", t.artist or "")
                    )
                    if not parts_ok:
                        continue
            candidates.append(t)
        prefetch_verified_artists(
            [t.artist or "" for t in candidates],
            netease=netease_checker,
        )
        merged: list[Track] = []
        seen: set[str] = set()
        for t in candidates:
            if not is_netease_verified_artist(t.artist or "", netease=netease_checker):
                continue
            if t.size_bytes <= 0 and t.duration_ms > 0:
                t.size_bytes = estimate_size_bytes(t.duration_ms, t.bitrate or 320)
            key = _dedupe_key(t)
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)
        merged.sort(key=lambda t: download_sort_key(t, search_q))
        merged = collapse_same_songs(merged, search_q, max_keep=2)
        return merged

    merged: list[Track] = []
    used_artist_hot = False

    if artist and not song:
        # ① 仅歌手：优先解析为正式歌手并拉其歌曲（hotSongs + 搜索补充）。
        # 该路径仅产出网易云数据：启用源（含显式 platforms）不含 netease 时跳过，
        # 直接走多平台搜索，保证平台过滤生效。
        info = _resolve_artist_id(artist, netease_checker) if "netease" in enabled else None
        if info:
            a_name, a_id = info
            merged = _fetch_artist_top_tracks(a_name, a_id, netease_checker, limit, offset)
            used_artist_hot = bool(merged)
        if not merged:
            # 解析不到正式歌手或热门为空 → 回退按歌手名多平台搜索
            used_artist_hot = False
            merged = _do_search(artist, filter_artist=artist)
    elif song and not artist:
        # ② 仅歌名
        merged = _do_search(song)
    else:
        # ③ 歌手 + 歌名：严格 AND（搜索词 "artist song" 且只保留该歌手），不回退
        merged = _do_search(query_text, filter_artist=artist)

    # 歌手热门路径已按热度排好序；其余路径统一排序后分页
    if not used_artist_hot:
        merged.sort(key=lambda t: download_sort_key(t, query_text))
    page = merged[offset : offset + limit]
    return [track_to_display(t) for t in page]


def track_to_display(t: Track) -> dict:
    d = asdict(t)
    downloadable = is_likely_downloadable(t)
    studio = is_studio_album_version(t)
    plat = (t.platform or "").strip().lower()
    need_cookie = platform_requires_cookie(plat) and not _has_platform_auth(plat)
    d["platform_label"] = platform_label(t.platform or "netease")
    d["duration_label"] = format_duration(t.duration_ms)
    d["size_label"] = format_size(t.size_bytes)
    d["source"] = t.platform or "netease"
    d["downloadable"] = downloadable
    d["studio_album"] = studio
    d["cookie_required"] = platform_requires_cookie(plat)
    if downloadable and studio:
        d["download_label"] = "可完整下载·专辑版"
    elif downloadable:
        d["download_label"] = "可完整下载"
    elif t.vip_likely:
        d["download_label"] = "需VIP"
    elif need_cookie:
        d["download_label"] = "需Cookie"
    else:
        d["download_label"] = "下载受限"
    return d
