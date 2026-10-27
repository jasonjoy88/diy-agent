from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent

# 当 NETEASE_COOKIE_FILE 指向目录时，按此顺序查找 cookie 文件
_NETEASE_COOKIE_NAMES = (
    "wangyiyun.txt",
    "netease_cookies.txt",
    "netease.txt",
    "music.163.com_cookies.txt",
    "cookies.txt",
)


def _load_dotenv(path: Path) -> None:
    """极简 .env 解析：KEY=VALUE，忽略注释与空行。

    - 不覆盖进程里已有的非空环境变量（便于外部注入）。
    - 同文件重复 KEY：允许「后面的非空值」覆盖「前面的空值」（避免先写空再写路径失效）。

    本机 pip install 被网络限制装不上 python-dotenv，故手写解析，零第三方依赖。
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            # 非法行（如全角冒号开头的注释残留）：warn 后跳过，不中断加载
            print(f"[dotenv] {path.name} 存在非法行（缺少 =，请修正或改为 # 注释）：{line}",
                  file=sys.stderr)
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not key:
            continue
        existing = os.environ.get(key)
        if existing is None or (existing == "" and value != ""):
            os.environ[key] = value


def _resolve_netease_cookie_path(raw: str) -> Path | None:
    """解析 NETEASE_COOKIE_FILE：可为文件，或为目录（自动找约定文件名）。"""
    raw = (raw or "").strip().strip('"').strip("'")
    if not raw:
        return None
    p = Path(raw).expanduser()
    if p.is_file():
        return p
    if p.is_dir():
        for name in _NETEASE_COOKIE_NAMES:
            cand = p / name
            if cand.is_file():
                return cand
    return None


def _netscape_to_cookie_header(text: str, domains: tuple[str, ...] = ("163.com", "music.163.com")) -> str:
    """Netscape cookies.txt → Cookie 请求头（只取网易云相关域）。"""
    pairs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _expiry, name, value = parts[:7]
        domain = domain.lstrip(".").lower()
        if not name:
            continue
        if domains and not any(domain == d or domain.endswith("." + d) or d.endswith(domain) for d in domains):
            # 宽松：域名包含 163
            if "163.com" not in domain:
                continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def load_netease_cookie(cookie_file: str = "", inline: str = "") -> str:
    """优先从 cookie 文件读取；支持 Cookie 头文本与 Netscape 格式。文件无效时回退 inline。"""
    path = _resolve_netease_cookie_path(cookie_file)
    if path is not None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            raw = ""
        if raw:
            if raw.lower().startswith("cookie:"):
                raw = raw.split(":", 1)[1].strip()
            # Netscape 多行带 TAB
            if raw.lstrip().startswith("# Netscape") or raw.lstrip().startswith("# HTTP Cookie File") or (
                "\t" in raw and "\n" in raw
            ):
                header = _netscape_to_cookie_header(raw)
                if header:
                    return header
            # 浏览器复制的「a=1; b=2」或纯文本
            return " ".join(raw.splitlines()).strip()
    return (inline or "").strip()


_load_dotenv(_PKG_ROOT / ".env")


def _anchor(raw: str, default_rel: str) -> str:
    """把路径解析为稳定绝对路径。

    - 空值 → 包根 / default_rel；
    - 相对路径 → 锚定到包根（而不是进程 CWD）：
      .env 用相对路径（如 music）时，从仓库根或其它目录启动也能稳定落到
      music-library-agent/music，避免随启动目录漂移；
    - 绝对路径 → 原样保留（允许外部显式指定任意位置）。
    """
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return str(_PKG_ROOT / default_rel)
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = _PKG_ROOT / p
    return str(p)


def _detect_system_proxy() -> str:
    """探测本机 HTTP/SOCKS 代理（供 yt-dlp 访问 YouTube）。

    顺序：标准代理环境变量（ALL_PROXY/HTTPS_PROXY/HTTP_PROXY）→ Windows 系统代理（注册表）。
    无 scheme 的值按 http:// 补全（Windows 系统代理标准语义；SOCKS 端口请用
    MUSIC_YTDLP_PROXY 显式写 socks5://...）。探测不到返回空串（直连）。
    """
    for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY",
                "all_proxy", "https_proxy", "http_proxy"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v if "://" in v else f"http://{v}"
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as key:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if not enabled:
                    return ""
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            server = str(server).strip()
            # 高级形式 "http=h1:1080;https=h2:1081" → 优先取 https 条目
            if "=" in server and ";" in server:
                parts = dict(
                    p.split("=", 1) for p in server.split(";") if "=" in p
                )
                server = (parts.get("https") or parts.get("http") or "").strip()
            if not server:
                return ""
            return server if "://" in server else f"http://{server}"
        except OSError:
            return ""
    return ""


@dataclass(frozen=True)
class Config:
    ark_api_key: str = os.environ.get("ARK_API_KEY", "")
    ark_model: str = os.environ.get("ARK_MODEL", "")
    ark_base_url: str = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    # 网易云：优先 NETEASE_COOKIE_FILE（文件或目录），回退 NETEASE_COOKIE 内联字符串
    netease_cookie_file: str = os.environ.get("NETEASE_COOKIE_FILE", "")
    netease_cookie: str = ""  # 由 __post_init__ 填充；dataclass frozen 需用 object.__setattr__
    output_root: str = _anchor(os.environ.get("MUSIC_OUTPUT_ROOT", ""), "music")
    # 默认 1：B 站并发过高易 412；需要时可自行调高
    concurrency: int = int(os.environ.get("MUSIC_CONCURRENCY", "1"))
    # 下载并发模型：thread（多线程，默认，适合 IO）| process（多进程，隔离 yt-dlp/ffmpeg）
    pool: str = os.environ.get("MUSIC_POOL", "thread").strip().lower() or "thread"
    top_n: int = int(os.environ.get("MUSIC_TOP_N", "30"))

    bitrate: str = os.environ.get("MUSIC_BITRATE", "320k")
    ffmpeg_bin: str = _anchor(os.environ.get("MUSIC_FFMPEG_BIN", ""),
                              os.path.join("tools", "ffmpeg", "bin"))
    checkpoint_db: str = _anchor(os.environ.get("MUSIC_CHECKPOINT_DB", ""),
                                 os.path.join(".music-agent", "checkpoints.sqlite"))
    enable_ytdlp: bool = os.environ.get("MUSIC_ENABLE_YTDLP", "1") == "1"
    enable_netease: bool = os.environ.get("MUSIC_ENABLE_NETEASE", "1") == "1"
    enable_qq: bool = os.environ.get("MUSIC_ENABLE_QQ", "1") == "1"
    enable_kugou: bool = os.environ.get("MUSIC_ENABLE_KUGOU", "1") == "1"
    enable_kuwo: bool = os.environ.get("MUSIC_ENABLE_KUWO", "1") == "1"
    enable_qishui: bool = os.environ.get("MUSIC_ENABLE_QISHUI", "1") == "1"
    enable_migu: bool = os.environ.get("MUSIC_ENABLE_MIGU", "1") == "1"
    enable_apple: bool = os.environ.get("MUSIC_ENABLE_APPLE", "1") == "1"
    # Apple / iTunes 店面优先码（TW/HK/JP/US/CN）；空则按 TW→HK→JP→US→CN 回退
    apple_storefront: str = os.environ.get("MUSIC_APPLE_STOREFRONT", "").strip().upper()
    # yt-dlp / B 站：cookie 文件优先于浏览器导入；默认开启 YouTube 回退（无网络时自动失败回退，不影响其它源）
    ytdlp_cookie_file: str = os.environ.get("MUSIC_YTDLP_COOKIE_FILE", "")
    ytdlp_cookies_from_browser: str = os.environ.get("MUSIC_YTDLP_COOKIES_FROM_BROWSER", "")
    ytdlp_enable_youtube: bool = os.environ.get("MUSIC_YTDLP_ENABLE_YOUTUBE", "1") == "1"
    # YouTube 回退专用代理：MUSIC_YTDLP_PROXY 显式配置（如 socks5://127.0.0.1:10808）优先，
    # 留空时自动探测系统代理；仅对 YouTube 请求生效，B 站等国内源始终直连
    ytdlp_proxy: str = os.environ.get("MUSIC_YTDLP_PROXY", "").strip() or _detect_system_proxy()
    ytdlp_sleep_interval: float = float(os.environ.get("MUSIC_YTDLP_SLEEP_INTERVAL", "2"))
    ytdlp_sleep_requests: float = float(os.environ.get("MUSIC_YTDLP_SLEEP_REQUESTS", "1"))
    # QQ 音乐 cookie（yt-dlp qqmusic 下载常用；检索可不依赖）
    qq_cookie_file: str = os.environ.get("MUSIC_QQ_COOKIE_FILE", "")
    qq_cookies_from_browser: str = os.environ.get("MUSIC_QQ_COOKIES_FROM_BROWSER", "")
    # 单源瞬时失败重试（412/超时/连接重置等）；默认 2 次额外重试
    fetch_retries: int = int(os.environ.get("MUSIC_FETCH_RETRIES", "2"))
    fetch_retry_backoff: float = float(os.environ.get("MUSIC_FETCH_RETRY_BACKOFF", "1.5"))
    # 网盘自动上传：下载到 music/<歌手> 保留本地，另拷到 pan-sync 的 WATCH_DIR 由其上传
    watch_dir: str = os.environ.get("MUSIC_WATCH_DIR", r"E:\sync-watch")
    enable_upload: bool = os.environ.get("MUSIC_ENABLE_UPLOAD", "1") == "1"
    # 歌词同步检索（歌词接口无需 cookie），默认开启；CLI --no-lyrics 可关
    enable_lyrics: bool = os.environ.get("MUSIC_ENABLE_LYRICS", "1") == "1"

    def __post_init__(self) -> None:
        cookie = load_netease_cookie(
            cookie_file=self.netease_cookie_file,
            inline=os.environ.get("NETEASE_COOKIE", ""),
        )
        object.__setattr__(self, "netease_cookie", cookie)


CONFIG = Config()
