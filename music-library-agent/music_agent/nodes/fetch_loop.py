from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import asdict

from .. import llm, prompts, validate
from ..config import CONFIG, load_netease_cookie
from ..models import DownloadResult, Track
from ..retry import fetch_with_retries
from ..sources.apple_source import AppleSource
from ..sources.kugou_source import KugouSource
from ..sources.kuwo_source import KuwoSource
from ..sources.migu_source import MiguSource
from ..sources.netease_source import NeteaseSource
from ..sources.platform_id import track_platform
from ..sources.qq_source import QQSource
from ..sources.qishui_source import QishuiSource
from ..sources.ytdlp_source import YtdlpSource

# 无 LLM 时的默认源优先级（免费可得性优先）
_DEFAULT_ORDER = ("ytdlp", "kuwo", "migu", "kugou", "qq", "netease", "qishui", "apple")


def _build_sources(platforms: list[str] | None = None) -> list:
    """构建可用音源列表。

    - platforms 为 None 或空：使用所有启用的源（默认行为）
    - platforms 指定列表：只构建指定平台的源（注意 ytdlp 对应 bilibili/youtube）
    """
    sources = []
    # 将 bilibili/youtube 归一到 ytdlp
    want: set[str] | None = None
    if platforms:
        want = set()
        for p in platforms:
            if p in ("bilibili", "youtube", "ytdlp"):
                want.add("ytdlp")
            else:
                want.add(p)

    if CONFIG.enable_ytdlp and (want is None or "ytdlp" in want):
        ytdlp = YtdlpSource(
            ffmpeg_bin=CONFIG.ffmpeg_bin,
            cookie_file=os.environ.get("MUSIC_YTDLP_COOKIE_FILE") or CONFIG.ytdlp_cookie_file,
            cookies_from_browser=CONFIG.ytdlp_cookies_from_browser,
            enable_youtube=CONFIG.ytdlp_enable_youtube,
            sleep_interval=CONFIG.ytdlp_sleep_interval,
            sleep_requests=CONFIG.ytdlp_sleep_requests,
            proxy=CONFIG.ytdlp_proxy,
        )
        if ytdlp.available():
            sources.append(ytdlp)
    if CONFIG.enable_kuwo and (want is None or "kuwo" in want):
        sources.append(KuwoSource())
    if CONFIG.enable_migu and (want is None or "migu" in want):
        sources.append(MiguSource())
    if CONFIG.enable_kugou and (want is None or "kugou" in want):
        sources.append(KugouSource())
    if CONFIG.enable_qq and (want is None or "qq" in want):
        qq = QQSource(
            # 登录后可能只改了环境变量，优先读最新 env
            cookie_file=os.environ.get("MUSIC_QQ_COOKIE_FILE") or CONFIG.qq_cookie_file,
            cookies_from_browser=CONFIG.qq_cookies_from_browser,
            ffmpeg_bin=CONFIG.ffmpeg_bin,
        )
        if qq.available():
            sources.append(qq)
    if CONFIG.enable_netease and (want is None or "netease" in want):
        # 每次重建时重读 cookie 文件，避免 GUI 登录后仍用进程启动时的旧值
        fresh = load_netease_cookie(
            cookie_file=os.environ.get("NETEASE_COOKIE_FILE") or CONFIG.netease_cookie_file,
            inline=os.environ.get("NETEASE_COOKIE", ""),
        )
        netease = NeteaseSource(cookie=fresh)
        if netease.available():
            sources.append(netease)
    if CONFIG.enable_qishui and (want is None or "qishui" in want):
        sources.append(QishuiSource())
    if CONFIG.enable_apple and (want is None or "apple" in want):
        sources.append(AppleSource(storefront=CONFIG.apple_storefront))
    # 按默认优先级排序（保留已启用集合）
    order = {name: i for i, name in enumerate(_DEFAULT_ORDER)}
    sources.sort(key=lambda s: order.get(s.name, 99))
    return sources


def _sources_for_track(track: Track, sources: list) -> list:
    """按曲目平台偏好重排；外源任务跳过 netease。"""
    usable = list(sources)
    if str(track.song_id or "").startswith("ext:"):
        usable = [s for s in usable if s.name != "netease"]
    preferred = track_platform(track)
    if preferred:
        # 平台名与 source.name 对齐（bilibili → ytdlp）
        alias = {"bilibili": "ytdlp", "youtube": "ytdlp"}
        want = alias.get(preferred, preferred)
        head = [s for s in usable if s.name == want]
        tail = [s for s in usable if s.name != want]
        usable = head + tail
    return usable


def _pick_source(track: Track, sources: list, tried: list[str]):
    remaining = [s for s in sources if s.name not in tried]
    if not remaining:
        return None
    if len(remaining) == 1:
        return remaining[0]
    # 已有明确平台偏好时，优先尚未尝试的首选源
    preferred = track_platform(track)
    alias = {"bilibili": "ytdlp", "youtube": "ytdlp"}
    want = alias.get(preferred, preferred)
    if want:
        for s in remaining:
            if s.name == want:
                return s
    choice = llm.ask(prompts.PICK_SOURCE.format(
        artist=track.artist, title=track.title,
        sources="、".join(s.name for s in remaining)))
    for s in remaining:
        if choice and s.name in choice:
            return s
    return remaining[0]


def _try_local_dedup(track: Track, out_dir: str) -> DownloadResult | None:
    """本地多维度去重：若本地已存在同一首歌，直接复用，不重新下载。"""
    from ..dedup import find_local_match

    match = find_local_match(track, out_dir)
    if match and match.get("path") and os.path.isfile(match["path"]):
        fmt = match.get("format", "")
        if not fmt:
            fmt = os.path.splitext(match["path"])[1].lstrip(".").lower()
        return DownloadResult(
            track_id=track.song_id,
            status="ok",
            path=match["path"],
            format=fmt,
            source="local_dedup",
            title=track.title,
            artist=track.artist,
        )
    return None


def _try_pan_download(track: Track, out_dir: str, artist: str) -> DownloadResult | None:
    """尝试从网盘下载（优先于音乐平台）。

    - 找到匹配资源 → 下载并返回 status=ok
    - 网盘未配置/无匹配/下载失败 → 返回 None（让主流程继续走音乐平台）
    - 授权失效 → 返回 status=failed + fail_reason 以 "auth_error:" 开头
    """
    try:
        from ..pan_lookup import download_from_pan, search_pan_for_track
    except ImportError:
        return None

    match = search_pan_for_track(track, artist)
    if not match.found:
        if match.auth_required:
            # 授权失效：返回明确错误，由上层处理
            return DownloadResult(
                track_id=track.song_id,
                status="failed",
                fail_reason=f"auth_error:pan:{match.fail_reason}",
                source="pan",
                title=track.title,
                artist=track.artist,
            )
        # 未找到或其它错误 → 让主流程继续
        return None

    # 找到匹配：从网盘下载
    result = download_from_pan(match.fid, out_dir, match.filename)
    # 保留原始 track_id，便于后续节点识别
    result.track_id = track.song_id
    result.title = track.title
    result.artist = track.artist
    # 网盘下载失败且非授权类错误 → 回退到音乐平台
    if result.status != "ok" and not (result.fail_reason or "").startswith("auth_error"):
        return None
    return result


def _fetch_one(track: Track, sources: list, out_dir: str, artist: str = "") -> DownloadResult:
    # ① 本地多维度去重：已下载过直接复用
    local_hit = _try_local_dedup(track, out_dir)
    if local_hit is not None:
        return local_hit

    # ② 网盘优先下载：找到相同资源则从网盘取，不走音乐平台
    if artist and CONFIG.enable_upload:
        # enable_upload 作为"网盘已绑定"的开关标志
        pan_result = _try_pan_download(track, out_dir, artist)
        if pan_result is not None:
            # 网盘成功 or 授权失效（需上层处理） → 直接返回
            # 网盘下载失败（非授权类）会返回 None，继续走音乐平台
            return pan_result

    tried: list[str] = []
    usable = _sources_for_track(track, sources)
    last = DownloadResult(track_id=track.song_id, status="failed", fail_reason="no_source",
                          title=track.title, artist=track.artist)
    while True:
        src = _pick_source(track, usable, tried)
        if src is None:
            return last
        tried.append(src.name)
        result = fetch_with_retries(
            lambda s=src: s.fetch(track, out_dir),
            retries=CONFIG.fetch_retries,
            backoff=CONFIG.fetch_retry_backoff,
        )
        if result.status == "ok":
            # 平台拦截常返回 HTTP 200 的试听/残缺片段（十几秒），体积也可能不小，
            # 必须按真实时长复核：命中则删除该文件、按本源失败处理并继续换源
            reason = validate.reject_short_resource(
                result.path, track.duration_ms, ffprobe_bin=CONFIG.ffmpeg_bin
            )
            if not reason:
                return result
            if result.path and os.path.isfile(result.path):
                try:
                    os.remove(result.path)
                except OSError:
                    pass
            result.status = "failed"
            result.fail_reason = reason
        last = result
        remaining = [s.name for s in usable if s.name not in tried]
        if not remaining:
            return last
        decision = llm.ask(prompts.ON_FAIL.format(
            artist=track.artist, title=track.title, reason=result.fail_reason,
            tried="、".join(tried),
            remaining="、".join(remaining) or "无"))
        if decision and "giveup" in decision.lower():
            return last
        # LLM 点名下一源时，把它挪到剩余列表前端（仍在下一轮 _pick_source 里生效）
        if decision:
            for s in usable:
                if s.name in decision and s.name not in tried:
                    # 通过暂时调整 tried 顺序：把其它未试源先标记再取消——更简单：重排 usable
                    usable = [s] + [x for x in usable if x is not s]
                    break


def _fetch_job(track_dict: dict, out_dir: str, artist: str = "", platforms: list[str] | None = None) -> dict:
    """线程/进程共用入口：每任务独立构建音源，避免共享实例竞态。"""
    track = Track(**track_dict)
    sources = _build_sources(platforms)
    return asdict(_fetch_one(track, sources, out_dir, artist=artist))


def _resolve_pool(state: dict) -> tuple[int, str]:
    """并发数与池类型：state 覆盖 > .env CONFIG。"""
    raw_n = state.get("concurrency")
    try:
        n = int(raw_n) if raw_n is not None else int(CONFIG.concurrency)
    except (TypeError, ValueError):
        n = 1
    n = max(1, n)
    pool = str(state.get("pool") or CONFIG.pool or "thread").strip().lower()
    if pool not in ("thread", "process"):
        pool = "thread"
    return n, pool


def _run_parallel(
    todo: list[Track],
    out_dir: str,
    workers: int,
    pool: str,
    artist: str = "",
    platforms: list[str] | None = None,
) -> list[dict]:
    """按 pool 类型并行下载；workers=1 时走串行，便于排障。"""
    jobs = [(asdict(t), out_dir, artist, platforms) for t in todo]
    if workers <= 1 or len(jobs) <= 1:
        return [_fetch_job(td, od, art, plats) for td, od, art, plats in jobs]

    max_workers = min(workers, len(jobs))
    executor_cls = ProcessPoolExecutor if pool == "process" else ThreadPoolExecutor
    results: list[dict | None] = [None] * len(jobs)
    with executor_cls(max_workers=max_workers) as ex:
        future_map = {
            ex.submit(_fetch_job, td, od, art, plats): idx
            for idx, (td, od, art, plats) in enumerate(jobs)
        }
        for fut in as_completed(future_map):
            idx = future_map[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:  # noqa: BLE001
                t = todo[idx]
                results[idx] = asdict(DownloadResult(
                    track_id=t.song_id, status="failed",
                    fail_reason=f"worker_error:{type(e).__name__}:{e}"[:200],
                    title=t.title, artist=t.artist,
                ))
    return [r for r in results if r is not None]


def run(state: dict) -> dict:
    tracks = [Track(**t) for t in state.get("tracks", [])]
    out_dir = state["out_dir"]
    platforms = state.get("platforms") or []
    if state.get("dry_run"):
        return {"results": {}, "messages": ["[dry-run] 跳过下载"]}
    msgs: list[str] = []

    # resume：读取 manifest，已 ok 的直接沿用、不重新下载
    preexisting: dict[str, dict] = {}
    todo = tracks
    if state.get("resume"):
        from ..manifest import Manifest
        artist = state.get("artist") or state["singer"]
        old = Manifest.load(out_dir, artist)
        todo = []
        for t in tracks:
            prev = old.get(t.song_id)
            if prev is not None and prev.status == "ok":
                preexisting[t.song_id] = asdict(prev)
            else:
                todo.append(t)
        skipped = len(tracks) - len(todo)
        if skipped:
            msgs.append(f"[fetch_loop] resume：跳过已完成 {skipped} 首，待处理 {len(todo)} 首")

    sources = _build_sources(platforms or None)
    if not sources:
        msgs.append(
            "[fetch_loop] 无可用音源（请安装 yt-dlp 或启用 kuwo/migu/kugou/qq/netease/qishui/apple 之一）"
        )
        results = dict(preexisting)
        for t in todo:
            results[t.song_id] = asdict(DownloadResult(
                track_id=t.song_id, status="failed", fail_reason="no_source",
                title=t.title, artist=t.artist))
        return {"results": results, "messages": msgs}

    workers, pool = _resolve_pool(state)
    if todo:
        names = "、".join(s.name for s in sources)
        msgs.append(
            f"[fetch_loop] 并发下载：workers={min(workers, len(todo))} pool={pool} "
            f"待处理={len(todo)} 音源=[{names}] retries={CONFIG.fetch_retries}"
        )

    results: dict[str, dict] = dict(preexisting)
    artist = state.get("artist") or state.get("singer", "")
    fetched = _run_parallel(todo, out_dir, workers, pool, artist=artist, platforms=platforms or None)
    for result in fetched:
        results[result["track_id"]] = result
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    msgs.append(f"[fetch_loop] 下载完成 {ok}/{len(tracks)}")
    return {"results": results, "messages": msgs}
