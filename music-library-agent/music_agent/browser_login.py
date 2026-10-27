"""唤起平台登录页，用户自行登录后后台轮询抓取 Cookie/Token。

依赖 pywebview（与 pan-sync-agent 相同）。Windows 上走 Edge WebView2。
流程：开窗口 → 轮询 Cookie → 检测到登录凭证 → 落盘 Netscape/Header → 注入环境变量。
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Callable

_PKG_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_COOKIE_DIR = _PKG_ROOT / ".cookies"


@dataclass(frozen=True)
class PlatformLogin:
    key: str
    title: str
    login_url: str
    domains: tuple[str, ...]
    # 任一命中即视为已登录（主凭证）
    required_any: tuple[str, ...]
    # URL 辅助判定（可选）
    url_hints: tuple[str, ...] = ()
    # 登录成功后写入的环境变量（文件路径）
    env_keys: tuple[str, ...] = ()
    # config.txt 中同步更新的 KEY
    config_keys: tuple[str, ...] = ()
    filename: str = "cookies.txt"


PLATFORMS: dict[str, PlatformLogin] = {
    "bilibili": PlatformLogin(
        key="bilibili",
        title="Bilibili",
        login_url="https://passport.bilibili.com/login",
        domains=(".bilibili.com",),
        required_any=("SESSDATA",),
        url_hints=("bilibili.com", "www.bilibili.com"),
        env_keys=("MUSIC_YTDLP_COOKIE_FILE", "BILIBILI_COOKIE_FILE"),
        config_keys=("BILIBILI_COOKIE_FILE",),
        filename="bilibili.txt",
    ),
    "netease": PlatformLogin(
        key="netease",
        title="网易云音乐",
        login_url="https://music.163.com/#/login",
        domains=(".music.163.com", ".163.com"),
        required_any=("MUSIC_U",),
        url_hints=("music.163.com",),
        env_keys=("NETEASE_COOKIE_FILE",),
        config_keys=("NETEASE_COOKIE_FILE",),
        filename="netease.txt",
    ),
    "qq": PlatformLogin(
        key="qq",
        title="QQ音乐",
        login_url="https://y.qq.com/",
        domains=(".qq.com", ".y.qq.com", ".tencentmusic.com"),
        required_any=("qm_keyst", "qqmusic_key", "wxopenid", "uin"),
        url_hints=("y.qq.com",),
        env_keys=("MUSIC_QQ_COOKIE_FILE",),
        config_keys=("MUSIC_QQ_COOKIE_FILE",),
        filename="qq.txt",
    ),
    "kugou": PlatformLogin(
        key="kugou",
        title="酷狗音乐",
        login_url="https://www.kugou.com/",
        domains=(".kugou.com",),
        required_any=("KuGoo", "kg_token", "t", "token"),
        url_hints=("kugou.com",),
        env_keys=("MUSIC_KUGOU_COOKIE_FILE",),
        config_keys=("MUSIC_KUGOU_COOKIE_FILE",),
        filename="kugou.txt",
    ),
    "kuwo": PlatformLogin(
        key="kuwo",
        title="酷我音乐",
        login_url="https://www.kuwo.cn/",
        domains=(".kuwo.cn",),
        required_any=("userid", "kw_token", "Hm_lvt_usr"),
        url_hints=("kuwo.cn",),
        env_keys=("MUSIC_KUWO_COOKIE_FILE",),
        config_keys=("MUSIC_KUWO_COOKIE_FILE",),
        filename="kuwo.txt",
    ),
    "qishui": PlatformLogin(
        key="qishui",
        title="汽水音乐",
        login_url="https://music.douyin.com/",
        domains=(".douyin.com", ".qishui.com", ".bytedance.com"),
        required_any=("sessionid", "sessionid_ss", "sid_tt", "odin_tt"),
        url_hints=("music.douyin.com", "douyin.com"),
        env_keys=("MUSIC_QISHUI_COOKIE_FILE",),
        config_keys=("MUSIC_QISHUI_COOKIE_FILE",),
        filename="qishui.txt",
    ),
    "migu": PlatformLogin(
        key="migu",
        title="咪咕音乐",
        login_url="https://music.migu.cn/",
        domains=(".migu.cn", ".music.migu.cn"),
        required_any=("miguToken", "token", "SessionId", "sessionid", "UserInfo"),
        url_hints=("music.migu.cn", "m.music.migu.cn"),
        env_keys=("MUSIC_MIGU_COOKIE_FILE",),
        config_keys=("MUSIC_MIGU_COOKIE_FILE",),
        filename="migu.txt",
    ),
    "apple": PlatformLogin(
        key="apple",
        title="Apple Music",
        login_url="https://music.apple.com/",
        domains=(".apple.com", ".itunes.apple.com", ".mzstatic.com"),
        required_any=("media-user-token", "itspod", "dslang"),
        url_hints=("music.apple.com", "itunes.apple.com"),
        env_keys=("MUSIC_APPLE_COOKIE_FILE",),
        config_keys=("MUSIC_APPLE_COOKIE_FILE",),
        filename="apple.txt",
    ),
}


def list_platforms() -> list[str]:
    return list(PLATFORMS.keys())


def _ensure_webview_path() -> None:
    """优先使用 pan-sync-agent/.vendor 中的 pywebview（离线安装常见）。"""
    agent_root = _PKG_ROOT.parent
    vendor = agent_root / "pan-sync-agent" / ".vendor"
    if vendor.is_dir():
        p = str(vendor)
        if p not in sys.path:
            sys.path.insert(0, p)


def _import_webview():
    _ensure_webview_path()
    try:
        import webview  # type: ignore

        return webview
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "缺少 pywebview，无法唤起登录窗口。"
            "请先安装：pip install pywebview"
            "（或确保 pan-sync-agent/.vendor 可用）"
        ) from e


def cookies_to_dict(raw_cookies) -> dict[str, str]:
    """兼容 pywebview 的 SimpleCookie 列表 / name-value 对象。"""
    result: dict[str, str] = {}
    for item in raw_cookies or []:
        if isinstance(item, SimpleCookie):
            for key, morsel in item.items():
                result[key] = morsel.value
            continue
        name = getattr(item, "name", None) or getattr(item, "key", None)
        value = getattr(item, "value", None)
        if name is not None and value is not None:
            result[str(name)] = str(value)
    return result


def cookies_ready(plat: PlatformLogin, cookies: dict[str, str]) -> bool:
    if not cookies:
        return False
    # QQ：uin 太常见（未登录也可能有），需搭配登录态 key
    if plat.key == "qq":
        has_uin = any(k in cookies for k in ("uin", "wxuin"))
        has_key = any(k in cookies for k in ("qm_keyst", "qqmusic_key", "wxopenid"))
        return bool(has_uin and has_key) or bool(cookies.get("qm_keyst") or cookies.get("qqmusic_key"))
    # 酷狗 token 名太泛，优先 KuGoo / kg_token
    if plat.key == "kugou":
        if cookies.get("KuGoo") or cookies.get("kg_token"):
            return True
        # 退一步：同时有 userid 类 + token
        return bool(cookies.get("token") and (cookies.get("Kugoo") or cookies.get("kg_mid")))
    return any(name in cookies and cookies[name] for name in plat.required_any)


def to_netscape(cookies: dict[str, str], domains: tuple[str, ...]) -> str:
    lines = [
        "# Netscape HTTP Cookie File",
        "# Generated by music-library-agent browser_login",
    ]
    domain = domains[0] if domains else ".local"
    for name, value in cookies.items():
        if not name:
            continue
        # domain FLAG path secure expiry name value
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def to_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k and v is not None)


def default_cookie_path(platform: str, cookie_dir: str | Path | None = None) -> Path:
    plat = PLATFORMS[platform]
    base = Path(cookie_dir) if cookie_dir else _DEFAULT_COOKIE_DIR
    return base / plat.filename


def apply_env(plat: PlatformLogin, path: Path) -> None:
    abs_path = str(path.resolve())
    for key in plat.env_keys:
        os.environ[key] = abs_path
    # B 站同时清掉字符串形态，避免旧字符串覆盖文件
    if plat.key == "bilibili":
        os.environ.pop("BILIBILI_COOKIE", None)


def upsert_config_txt(config_path: Path, updates: dict[str, str]) -> bool:
    """在 config.txt 中更新 KEY=VALUE，保留注释与其它行。返回是否写入。"""
    if not updates:
        return False
    if not config_path.is_file():
        return False
    try:
        text = config_path.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    lines = text.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    try:
        config_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def login(
    platform: str,
    *,
    out_path: str | Path | None = None,
    cookie_dir: str | Path | None = None,
    timeout_minutes: float = 5,
    poll_seconds: float = 1.0,
    config_path: str | Path | None = None,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """打开登录窗口并抓取 Cookie。

    返回 {"status":"ok","platform":...,"path":...,"cookie_count":N,"keys":[...]}
    失败抛 RuntimeError。
    """
    key = (platform or "").strip().lower()
    if key not in PLATFORMS:
        raise ValueError(f"未知平台：{platform}；可选：{', '.join(PLATFORMS)}")
    plat = PLATFORMS[key]
    webview = _import_webview()

    path = Path(out_path) if out_path else default_cookie_path(key, cookie_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    holder: dict = {}
    state = {"errors": 0, "hinted": False}

    window = webview.create_window(
        f"请登录 {plat.title} — 登录成功后窗口将自动关闭",
        plat.login_url,
        width=1100,
        height=760,
    )

    def poll() -> None:
        deadline = time.time() + max(1.0, float(timeout_minutes)) * 60
        log(f"[login:{plat.key}] 请在打开的窗口中完成登录（超时 {timeout_minutes:g} 分钟）…")
        while time.time() < deadline:
            sleep(max(0.3, float(poll_seconds)))
            try:
                url = str(window.get_current_url() or "")
            except Exception:  # noqa: BLE001
                url = ""
            if (
                not state["hinted"]
                and plat.url_hints
                and any(h in url for h in plat.url_hints)
                and "login" not in url.lower()
                and "passport" not in url.lower()
            ):
                state["hinted"] = True
                log(f"[login:{plat.key}] 检测到已离开登录页，正在读取 Cookie…")

            try:
                cookies = cookies_to_dict(window.get_cookies())
            except Exception as e:  # noqa: BLE001
                state["errors"] += 1
                if state["errors"] == 1 or state["errors"] % 20 == 0:
                    log(
                        f"[login:{plat.key}] 读取 Cookie 失败（{type(e).__name__}: {e}），"
                        "将持续重试…"
                    )
                continue

            if not cookies_ready(plat, cookies):
                continue

            # 落盘：Netscape（yt-dlp）+ 同行 Header（网易云等）
            netscape = to_netscape(cookies, plat.domains)
            header = to_header(cookies)
            # 文件内容：Netscape 优先（yt-dlp / 网易云加载器均能识别）
            # 同时写一份 .header.txt 便于排查
            path.write_text(netscape, encoding="utf-8")
            header_path = path.with_suffix(path.suffix + ".header.txt")
            try:
                header_path.write_text(header, encoding="utf-8")
            except OSError:
                pass

            apply_env(plat, path)
            cfg_updates = {k: str(path.resolve()) for k in plat.config_keys}
            if config_path:
                upsert_config_txt(Path(config_path), cfg_updates)
            else:
                # 约定：dsh_player_tools/config.txt
                guess = _PKG_ROOT.parent / "dsh_player_tools" / "config.txt"
                if guess.is_file():
                    upsert_config_txt(guess, cfg_updates)

            holder["cookies"] = cookies
            holder["path"] = str(path.resolve())
            holder["header_path"] = str(header_path) if header_path.is_file() else ""
            log(
                f"[login:{plat.key}] 已获取登录凭证（{len(cookies)} 个 Cookie）→ {path}"
            )
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
            return

        log(f"[login:{plat.key}] 超时未检测到登录凭证")

    webview.start(poll)

    if "cookies" not in holder:
        raise RuntimeError(
            f"未能在 {timeout_minutes:g} 分钟内获取 {plat.title} 登录凭证"
            "（窗口可能已关闭，或尚未完成登录）"
        )
    cookies = holder["cookies"]
    return {
        "status": "ok",
        "platform": plat.key,
        "title": plat.title,
        "path": holder["path"],
        "header_path": holder.get("header_path", ""),
        "cookie_count": len(cookies),
        "keys": sorted(cookies.keys()),
        "env_keys": list(plat.env_keys),
    }
