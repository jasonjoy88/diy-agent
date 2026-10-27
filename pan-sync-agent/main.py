import argparse
import json
import os
import sys
import time
from datetime import datetime

# ── 路径引导 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 1) 兼容项目内 vendored 依赖（pywebview）：.vendor 存在则优先加入；
#    用户已全局安装依赖时该目录不存在，此段无副作用。
_VENDOR = os.path.join(PROJECT_ROOT, ".vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

# 2) 接入 dsh-agent 根目录共享包 dsh_guard（全局契约 AGENT.md 强制要求）。
_AGENT_ROOT = os.path.dirname(PROJECT_ROOT)
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

from dsh_guard import TurnTimeoutInterrupt, turn_timeout_guard
from pan_sync import downloader
from pan_sync.downloader import quark as _downloader_quark  # noqa: F401  显式加载子模块，使 downloader.quark 可用
from pan_sync import manifest, scanner
from pan_sync.config import load_config
from pan_sync.credentials import load_cookies, save_cookies
from pan_sync.engine import SyncEngine
from pan_sync.errors import AuthError, PanSyncError
from pan_sync import quark_cli
from pan_sync.login_window import login_with_fallback
from pan_sync.quark_open import ensure_fresh_token
from pan_sync.scheduler import in_window, next_interval_delay, seconds_until_start
from pan_sync.uploader.baidu import BaiduUploader
from pan_sync.uploader.quark import QuarkUploader
from pan_sync.uploader.quark_skill import QuarkSkillUploader

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# 只读 ls/pull 使用的夸克网盘模块别名（测试可替换，与 uploader 解耦）。
quarkdown = downloader.quark


def build_uploader(config, cookies):
    if config.drive == "baidu":
        return BaiduUploader(cookies, config.chunk_size_bytes)
    if quark_cli.cli_available():
        return QuarkSkillUploader(cookies, config.chunk_size_bytes)
    return QuarkUploader(cookies, config.chunk_size_bytes)


def ensure_login(config, auth_code=None):
    if config.drive == "quark" and quark_cli.cli_available():
        if quark_cli.authorized():
            return QuarkSkillUploader()
        print("[login] 夸克官方 Skill 未授权，开始登录……")
        _quark_skill_login(auth_code)
        return QuarkSkillUploader()
    cookies = load_cookies(config.drive, DATA_DIR)
    uploader = build_uploader(config, cookies or {})
    if cookies and uploader.check_cookies_valid():
        return uploader
    print(f"[login] 需要登录 {config.drive}，即将弹出官方登录页……")
    cookies = login_with_fallback(config.drive)
    save_cookies(config.drive, cookies, DATA_DIR)
    print("[login] 登录成功，凭证已加密保存。")
    return build_uploader(config, cookies)


def _quark_skill_login(auth_code=None):
    quark_cli.set_session_input("将以上skill整合到pan-sync-agent内")
    try:
        result = quark_cli.login(token=auth_code)
    except AuthError as e:
        if quark_cli.authorized():
            print(f"[login] {e}；检测到本机已有有效 Skill 授权，继续使用。")
            return {"code": -118, "msg": str(e)}
        raise
    msg = result.get("msg") or ""
    if result.get("code") == -118:
        print(msg or "[login] 当前授权仍然有效。")
        return result
    print("[login] 夸克官方 Skill 授权成功。")
    data = result.get("data") or {}
    if data.get("status") == "install_confirmed" and data.get("msg"):
        print(data["msg"])
    return result


def login_or_none(config):
    """开窗首轮可能遇瞬时网络故障：网络异常时本轮跳过、下一轮重试，
    绝不让常驻进程因未捕获 OSError 而退出。"""
    try:
        return ensure_login(config)
    except OSError as e:
        print(f"[start] 登录探活网络异常：{e}；本轮跳过，下个间隔重试。")
        return None


def run_cycle(config, uploader, command):
    """在全局 turn_timeout 守卫下执行单轮扫描上传。

    一次 run_once 即全局契约定义的「单轮执行」；超时会在根目录留下
    timeout-interrupt-*.json 记录并抛出 TurnTimeoutInterrupt。
    """
    turn = datetime.now().strftime("%Y%m%d-%H%M%S")
    with turn_timeout_guard(
        agent="pan-sync-agent",
        turn=turn,
        extra={"command": command},
    ):
        return SyncEngine(config, uploader).run_once()


def cmd_once(config):
    uploader = ensure_login(config)
    try:
        run_cycle(config, uploader, "once")
    except TurnTimeoutInterrupt as e:
        print(e)
        return 3
    return 0


def cmd_login(config, auth_code=None):
    if config.drive == "quark" and quark_cli.cli_available():
        _quark_skill_login(auth_code)
        return 0
    cookies = login_with_fallback(config.drive)
    save_cookies(config.drive, cookies, DATA_DIR)
    print("[login] 已重新登录并保存凭证。")
    return 0


def cmd_status(config):
    print(f"网盘 DRIVE：{config.drive}")
    if config.drive == "quark" and quark_cli.cli_available():
        print(f"夸克 Skill CLI：{'可用' if quark_cli.cli_available() else '缺失'}")
        print(f"Skill 授权：{'有效' if quark_cli.authorized() else '缺失/失效'}")
    path = os.path.join(DATA_DIR, f"cookies.{config.drive}.enc")
    print(f"本地凭证：{'存在' if os.path.exists(path) else '缺失（需登录）'}")
    print(f"监控目录：{config.watch_dir}")
    counts = {}
    for directory in scanner.iter_manifest_dirs(
        config.watch_dir, skip_dir_prefixes=config.skip_dir_prefixes
    ):
        for entry in manifest.latest_by_relpath(manifest.load_entries(directory)).values():
            counts[entry.status] = counts.get(entry.status, 0) + 1
    print(f"清单最新状态统计：{counts or '（无）'}")
    return 0


def _fresh_quark_token():
    """加载夸克凭证，临期自动刷新并回写（rotate 会使旧 refresh_token 失效）。"""
    token = load_cookies("quark", DATA_DIR) or {}
    fresh = ensure_fresh_token(token)
    if fresh is not token:
        save_cookies("quark", fresh, DATA_DIR)
    return fresh


def _require_quark(config):
    if config.drive != "quark":
        raise PanSyncError(f"列目录/下载仅支持夸克（当前 DRIVE={config.drive}）")


def cmd_ls(config, args):
    _require_quark(config)
    remote_path = args.remote_path or (config.remote_root + "/Music")
    entries = quarkdown.list_dir(_fresh_quark_token(), remote_path, recursive=args.recursive)
    print(json.dumps(entries, ensure_ascii=False))
    return 0


def cmd_pull(config, args):
    _require_quark(config)
    if not args.fid or not args.dest:
        raise PanSyncError("pull 需要 --fid 与 --dest")
    path = quarkdown.download_file(_fresh_quark_token(), args.fid, args.dest)
    print(json.dumps({"ok": True, "path": path}, ensure_ascii=False))
    return 0


def cmd_start(config):
    print(f"[start] pan-sync-agent 启动；{config.start_hour}-{config.end_hour} 点，"
          f"每 {config.scan_interval_minutes} 分钟一轮。")
    uploader = None
    while True:
        now = datetime.now()
        if not in_window(now, config.start_hour, config.end_hour):
            delay = seconds_until_start(now, config.start_hour)
            print(f"[start] 当前非运行窗口，{delay / 3600:.1f} 小时后开窗。")
            time.sleep(delay)
            continue
        if uploader is None:
            uploader = login_or_none(config)
        if uploader is None:
            time.sleep(config.scan_interval_minutes * 60)
            continue
        try:
            run_cycle(config, uploader, "start")
        except TurnTimeoutInterrupt as e:
            print(f"[start] {e}；本轮中断，进入下一间隔（本地文件不丢）。")
        except AuthError:
            print("[start] 登录已失效，下一轮重新登录。")
            uploader = None
        delay = next_interval_delay(
            datetime.now(), config.scan_interval_minutes,
            config.start_hour, config.end_hour,
        )
        print(f"[start] 休眠 {delay / 60:.0f} 分钟。")
        time.sleep(delay)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="定时网盘同步工具")
    parser.add_argument("command", choices=["start", "login", "once", "status", "ls", "pull"])
    parser.add_argument("--env", default=ENV_PATH, help="配置文件路径（默认项目根 .env）")
    parser.add_argument(
        "--token",
        default=None,
        help="夸克官方 Skill 授权码（CAC-… / AAC-…），仅 login 使用",
    )
    parser.add_argument("--remote-path", default="", help="ls：网盘目录（默认 REMOTE_ROOT/Music）")
    parser.add_argument("--recursive", action="store_true", help="ls：递归子目录")
    parser.add_argument("--fid", default="", help="pull：网盘文件 fid")
    parser.add_argument("--dest", default="", help="pull：本地落盘路径")
    args = parser.parse_args(argv)

    config = load_config(args.env)

    if args.command == "start":
        return cmd_start(config)
    if args.command == "login":
        return cmd_login(config, auth_code=args.token)
    if args.command == "once":
        return cmd_once(config)
    if args.command == "ls":
        return cmd_ls(config, args)
    if args.command == "pull":
        return cmd_pull(config, args)
    return cmd_status(config)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PanSyncError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"错误：网络异常：{e}", file=sys.stderr)
        sys.exit(1)
