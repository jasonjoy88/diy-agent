"""网盘侧的歌曲检索与优先下载。

设计原则：
  - 与 pan-sync-agent 解耦：通过懒加载 import 调用其 downloader 和 quark_open，
    未安装/未配置时自动降级为"不启用网盘"，不影响音乐下载主流程。
  - 授权失效时抛 AuthError（pan_sync.errors.AuthError），
    上层捕获后可返回 auth_required 状态，由 GUI 唤起重新授权。
  - 匹配逻辑复用 dedup.is_same_track，保证本地去重和网盘匹配标准一致。

网盘结构约定（与 pan-sync 的 REMOTE_ROOT + 歌手子目录一致）：
  <remote_root>/<歌手>/<歌手 - 歌名>.mp3
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .dedup import _parse_filename, is_same_track
from .models import DownloadResult, Track


@dataclass
class PanMatchResult:
    """网盘匹配结果。"""
    found: bool
    # 命中的网盘文件信息（found=True 时有效）
    fid: str = ""
    filename: str = ""
    path: str = ""  # 网盘内完整路径
    size: int = 0
    artist: str = ""
    title: str = ""
    # 失败原因（found=False 时可能有值）
    fail_reason: str = ""
    # 是否因授权失败导致（是 → 上层应唤起重新授权）
    auth_required: bool = False


def _pan_available() -> bool:
    """检查网盘模块是否可用（有 pan_sync 依赖 + 有配置 + 有凭证）。"""
    try:
        from pan_sync.downloader import quark as _quarkdown  # noqa: F401
    except ImportError:
        return False
    try:
        _load_pan_config()
    except Exception:
        return False
    return True


def _load_pan_config():
    """加载 pan-sync 配置（.env）并返回 (token, remote_root, data_dir)。

    失败时抛出异常，由调用方捕获并视为网盘不可用。
    """
    from pan_sync.config import load_config
    from pan_sync.credentials import load_cookies

    # pan-sync-agent 目录从 music-library-agent 往上找
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    agent_root = os.path.dirname(pkg_root)
    pan_env = os.path.join(agent_root, "pan-sync-agent", ".env")
    pan_data = os.path.join(agent_root, "pan-sync-agent", "data")

    if not os.path.isfile(pan_env):
        raise FileNotFoundError(f"pan-sync .env 不存在：{pan_env}")

    cfg = load_config(pan_env)
    token = load_cookies(cfg.drive, pan_data) or {}
    return token, cfg.remote_root, pan_data, cfg.drive


def _fresh_token(token: dict, drive: str, data_dir: str) -> dict:
    """临期自动刷新并回写。返回有效 token，失败抛 AuthError。"""
    from pan_sync.credentials import save_cookies
    from pan_sync.quark_open import ensure_fresh_token

    fresh = ensure_fresh_token(token)
    # ensure_fresh_token 可能返回原对象或新对象（刷新时）
    if fresh is not token:
        save_cookies(drive, fresh, data_dir)
    return fresh


def search_pan_for_track(track: Track, artist: str) -> PanMatchResult:
    """在网盘音乐目录中搜索与 track 匹配的文件。

    返回 PanMatchResult：
      - found=True：找到匹配文件，fid/path/size 等字段有效
      - found=False + auth_required=True：授权失效，需重新登录
      - found=False + fail_reason：其它原因（未找到 / 网盘未配置 / 网络错误）
    """
    if not track or not track.title:
        return PanMatchResult(found=False, fail_reason="invalid_track")

    try:
        token, remote_root, data_dir, drive = _load_pan_config()
    except Exception as e:
        return PanMatchResult(found=False, fail_reason=f"pan_config_error:{type(e).__name__}")

    if not token or not token.get("access_token"):
        return PanMatchResult(found=False, fail_reason="no_pan_token", auth_required=True)

    try:
        token = _fresh_token(token, drive, data_dir)
    except Exception as e:
        # AuthError 或刷新失败 → 需要重新授权
        auth_required = _is_auth_error(e)
        return PanMatchResult(
            found=False,
            fail_reason=f"token_refresh_failed:{type(e).__name__}",
            auth_required=auth_required,
        )

    try:
        from pan_sync.downloader import quark as quarkdown
    except ImportError as e:
        return PanMatchResult(found=False, fail_reason=f"pan_import_error:{e}")

    # 只列该歌手目录，避免全库扫描
    artist_dir = f"{remote_root.rstrip('/')}/{artist}"
    try:
        items = quarkdown.list_dir(token, artist_dir, recursive=False)
    except Exception as e:
        auth_required = _is_auth_error(e)
        return PanMatchResult(
            found=False,
            fail_reason=f"pan_list_error:{type(e).__name__}",
            auth_required=auth_required,
        )

    if not items:
        return PanMatchResult(found=False, fail_reason="no_pan_dir")

    # 过滤音频文件并构建元数据
    candidates: list[dict] = []
    for it in items:
        # 跳过目录
        if str(it.get("file_type")) == "0" or it.get("file_type") == 0:
            continue
        fn = it.get("filename", "")
        low = fn.lower()
        if not any(low.endswith(ext) for ext in (".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wav")):
            continue
        art, title = _parse_filename(fn)
        candidates.append({
            "artist": art or artist,
            "title": title,
            "album": "",
            "size_bytes": int(it.get("size", 0) or 0),
            "duration_ms": 0,
            "fid": it.get("fid", ""),
            "filename": fn,
            "path": it.get("path", ""),
        })

    if not candidates:
        return PanMatchResult(found=False, fail_reason="no_audio_in_pan")

    # 多维度匹配，找第一个命中
    for entry in candidates:
        if is_same_track(track, entry):
            return PanMatchResult(
                found=True,
                fid=entry["fid"],
                filename=entry["filename"],
                path=entry["path"],
                size=entry["size_bytes"],
                artist=entry["artist"],
                title=entry["title"],
            )

    return PanMatchResult(found=False, fail_reason="no_match")


def download_from_pan(fid: str, dest_dir: str, filename: str) -> DownloadResult:
    """从网盘下载指定 fid 的文件到 dest_dir/filename。

    成功返回 status=ok 的 DownloadResult，失败返回 status=failed。
    授权失效时 fail_reason 以 "auth_error:" 开头，上层可据此唤起重新授权。
    """
    try:
        token, remote_root, data_dir, drive = _load_pan_config()
        token = _fresh_token(token, drive, data_dir)
    except Exception as e:
        reason = f"auth_error:{type(e).__name__}" if _is_auth_error(e) else f"pan_init_failed:{type(e).__name__}"
        return DownloadResult(
            track_id=f"pan:{fid}",
            status="failed",
            fail_reason=reason,
            source="pan",
        )

    try:
        from pan_sync.downloader import quark as quarkdown
    except ImportError as e:
        return DownloadResult(
            track_id=f"pan:{fid}",
            status="failed",
            fail_reason=f"pan_import_error:{e}",
            source="pan",
        )

    dest_path = os.path.join(dest_dir, filename)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        path = quarkdown.download_file(token, fid, dest_path)
        fmt = os.path.splitext(path)[1].lstrip(".").lower()
        return DownloadResult(
            track_id=f"pan:{fid}",
            status="ok",
            path=path,
            format=fmt,
            source="pan",
        )
    except Exception as e:
        if _is_auth_error(e):
            reason = f"auth_error:{type(e).__name__}"
        else:
            reason = f"pan_download_failed:{type(e).__name__}"
        # 清理半截文件
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass
        return DownloadResult(
            track_id=f"pan:{fid}",
            status="failed",
            fail_reason=reason,
            source="pan",
        )


def _is_auth_error(e: Exception) -> bool:
    """判断异常是否为授权失效类错误。"""
    try:
        from pan_sync.errors import AuthError
        if isinstance(e, AuthError):
            return True
    except ImportError:
        pass
    msg = str(e).lower()
    auth_keywords = ("auth", "token", "未授权", "未完成授权", "认证", "登录失效", "invalid", "expired")
    return any(k in msg for k in auth_keywords)
