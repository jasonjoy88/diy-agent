"""歌手歌库获取 Agent CLI。

用法：
  python main.py run --singer "周杰伦" [--song "晴天" --song "稻香"] [--top 30] [--resume] [--dry-run]
  python main.py resume --thread-id music-周杰伦
  python main.py verify --singer "周杰伦"
  python main.py state --thread-id music-周杰伦
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# 接入 dsh-agent 全局配置（dsh-agent.config.json）：单轮超时中断等全局规则
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dsh_guard import TurnTimeoutInterrupt, turn_timeout_guard

from music_agent.config import CONFIG
from music_agent.graph import build_graph_with_sqlite
from music_agent.manifest import Manifest
from music_agent.nodes.resolve_artist import ArtistAmbiguousError
from music_agent.validate import check_file


def _artist_dir(artist: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|]', "_", artist).strip()
    return os.path.join(CONFIG.output_root, safe)


def cmd_verify_dir(out_dir: str) -> int:
    m = Manifest.load(out_dir, artist=os.path.basename(out_dir))
    if not m.results:
        print(f"未找到 manifest 或没有记录：{out_dir}")
        return 1
    ok = 0
    for r in m.results.values():
        good, _ = check_file(r.path, 0)
        if r.status == "ok" and good:
            ok += 1
    total = len(m.results)
    print(f"可正常访问：{ok}/{total}")
    return 0 if ok == total else 1


def cmd_run(args: argparse.Namespace) -> int:
    out_dir = _artist_dir(args.singer)
    graph = build_graph_with_sqlite(args.db)
    # --resume 复用固定 thread（同歌手续跑）；否则每次新会话用带时间戳的 thread，避免旧 checkpoint 污染
    if args.thread_id:
        thread_id = args.thread_id
    elif args.resume:
        thread_id = f"music-{args.singer}"
    else:
        import time
        thread_id = f"music-{args.singer}-{int(time.time())}"
    config = {"configurable": {"thread_id": thread_id}}
    concurrency = args.concurrency if args.concurrency is not None else CONFIG.concurrency
    pool = args.pool or CONFIG.pool or "thread"
    lyrics_enabled = CONFIG.enable_lyrics if args.lyrics is None else args.lyrics
    platforms = [p.strip() for p in (args.platforms or "").split(",") if p.strip()]
    initial = {
        "singer": args.singer,
        "songs": args.song or [],
        "top_n": args.top,
        "resume": args.resume,
        "dry_run": args.dry_run,
        "out_dir": out_dir,
        "artist_id": getattr(args, "artist_id", "") or "",
        "concurrency": concurrency,
        "pool": pool,
        "lyrics_enabled": lyrics_enabled,
        "platforms": platforms,
        "results": {},
        "messages": [],
    }
    print(
        f"[run] singer={args.singer} top={args.top} songs={args.song} out={out_dir}"
        f" concurrency={concurrency} pool={pool} lyrics={lyrics_enabled}"
        f" platforms={','.join(platforms) if platforms else 'all'}"
        + (f" artist_id={initial['artist_id']}" if initial["artist_id"] else "")
    )
    try:
        with turn_timeout_guard(
            agent="music-library-agent",
            turn=thread_id,
            extra={"command": "run", "singer": args.singer},
        ):
            final = graph.invoke(initial, config=config)
    except ArtistAmbiguousError as e:
        print(str(e))
        return 2
    except TurnTimeoutInterrupt as e:
        print(f"\n{e}\n可稍后通过 resume 续跑：python main.py resume --thread-id {thread_id}")
        return 3
    for msg in final.get("messages", []):
        print(msg)
    if final.get("final_report"):
        print("\n" + final["final_report"])
    # 检索失败 / 无待下载曲目：提示已在上方输出，不再走空目录校验
    if not final.get("tracks"):
        report = final.get("final_report") or ""
        if "未检索到相应资源" in report or "未检索到歌手" in report:
            return 4
        if args.song:
            return 0 if "均已下载" in " ".join(final.get("messages") or []) else 4
        return 0
    return cmd_verify_dir(final.get("out_dir") or out_dir)


def cmd_resume(args: argparse.Namespace) -> int:
    graph = build_graph_with_sqlite(args.db)
    config = {"configurable": {"thread_id": args.thread_id}}
    try:
        with turn_timeout_guard(
            agent="music-library-agent",
            turn=args.thread_id,
            extra={"command": "resume"},
        ):
            final = graph.invoke(None, config=config)
    except TurnTimeoutInterrupt as e:
        print(f"\n{e}\n可稍后再次 resume 续跑。")
        return 3
    for msg in final.get("messages", []):
        print(msg)
    if final.get("final_report"):
        print("\n" + final["final_report"])
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    return cmd_verify_dir(_artist_dir(args.singer))


def cmd_state(args: argparse.Namespace) -> int:
    graph = build_graph_with_sqlite(args.db)
    config = {"configurable": {"thread_id": args.thread_id}}
    snap = graph.get_state(config)
    v = snap.values or {}
    print(json.dumps({
        "next": snap.next, "singer": v.get("singer"), "artist": v.get("artist"),
        "artist_id": v.get("artist_id"),
        "tracks": len(v.get("tracks", [])), "out_dir": v.get("out_dir"),
        "final_report": v.get("final_report"),
    }, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """唤起平台登录窗口，后台抓取 Cookie 并写入 .cookies/。"""
    from music_agent.browser_login import login, list_platforms

    platform = (args.platform or "").strip().lower()
    if platform == "list":
        print("可用平台：" + "、".join(list_platforms()))
        return 0
    try:
        result = login(
            platform,
            out_path=args.out or None,
            timeout_minutes=args.timeout,
            config_path=args.config or None,
        )
    except Exception as e:  # noqa: BLE001
        print(f"登录失败：{e}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"\n已写入 {result['path']}，并设置环境变量："
        + "、".join(result.get("env_keys") or [])
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="music-agent", description="歌手歌库获取 Agent（LangGraph）")
    parser.add_argument("--db", default=CONFIG.checkpoint_db, help="checkpoint sqlite 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="抓取歌手歌库")
    p_run.add_argument("--singer", required=True, help="歌手名")
    p_run.add_argument("--song", action="append", help="指定单曲歌名（可多次）")
    p_run.add_argument("--top", type=int, default=CONFIG.top_n, help="Top N（默认 30）")
    p_run.add_argument("--artist-id", default="", help="网易云歌手 id（同名消歧时跳过交互）")
    p_run.add_argument("--resume", action="store_true", help="跳过已完成，补失败/未完成")
    p_run.add_argument("--dry-run", action="store_true", help="只列曲目不下载")
    p_run.add_argument("--thread-id", default="", help="自定义 thread_id")
    p_run.add_argument(
        "--concurrency", type=int, default=None,
        help=f"下载并发数（默认 MUSIC_CONCURRENCY={CONFIG.concurrency}）",
    )
    p_run.add_argument(
        "--pool", choices=["thread", "process"], default=None,
        help=f"并发模型：thread 多线程 / process 多进程（默认 MUSIC_POOL={CONFIG.pool}）",
    )
    p_run.add_argument(
        "--lyrics", dest="lyrics", action="store_true", default=None,
        help="同步检索歌词（默认开启，MUSIC_ENABLE_LYRICS 可改默认值）",
    )
    p_run.add_argument(
        "--no-lyrics", dest="lyrics", action="store_false",
        help="本次不检索/下载歌词",
    )
    p_run.add_argument(
        "--platforms", default="",
        help="限定检索和下载的平台，逗号分隔，如 netease,qq,kugou；空=全部启用的源（默认空）",
    )
    p_run.set_defaults(func=cmd_run)

    p_resume = sub.add_parser("resume", help="从 checkpoint 续跑")
    p_resume.add_argument("--thread-id", required=True)
    p_resume.set_defaults(func=cmd_resume)

    p_verify = sub.add_parser("verify", help="校验已下载文件可访问性")
    p_verify.add_argument("--singer", required=True)
    p_verify.set_defaults(func=cmd_verify)

    p_state = sub.add_parser("state", help="查看 checkpoint 状态")
    p_state.add_argument("--thread-id", required=True)
    p_state.set_defaults(func=cmd_state)

    p_login = sub.add_parser(
        "login",
        help="唤起平台登录界面，后台抓取 Cookie（bilibili/netease/qq/kugou/kuwo/qishui）",
    )
    p_login.add_argument(
        "--platform", required=True,
        help="平台名，或 list 查看可选列表",
    )
    p_login.add_argument("--out", default="", help="Cookie 输出路径（默认 .cookies/<平台>.txt）")
    p_login.add_argument("--timeout", type=float, default=5, help="等待登录超时分钟数（默认 5）")
    p_login.add_argument(
        "--config", default="",
        help="可选：同步更新的 config.txt 路径（默认尝试 dsh_player_tools/config.txt）",
    )
    p_login.set_defaults(func=cmd_login)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
