"""去重：判断歌曲是否已下载（本地文件存在 / 曾上传网盘 / 网盘已有同名资源），
并支持 Top N 自动补齐与多维度精确匹配。

对接 pan-sync-agent：上传成功后本地文件被删，但会留 .uploaded.json 清单
（status=="uploaded" 的 rel_path 即"曾下载过"）。据此实现跨会话去重。

多维度去重（is_same_track）：
  - 宽松匹配：归一化歌名一致（旧逻辑，兼容现有调用）
  - 严格匹配：同时校验 歌手 + 歌名 + 专辑 + 文件大小 + 时长
  - 文件元数据通过 ffprobe / 文件名约定 / .uploaded.json 的 size 字段获取
"""
from __future__ import annotations

import json
import os

from .models import Track

UPLOADED_MANIFEST = ".uploaded.json"
AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".webm", ".opus", ".flac", ".ogg", ".wav")

# 文件大小容差：同一首歌不同编码/压制版本体积略有差异，允许 ±8% 或 ±200KB
_SIZE_REL_TOLERANCE = 0.08
_SIZE_ABS_TOLERANCE = 200 * 1024
# 时长容差：±3 秒
_DURATION_TOLERANCE_MS = 3000


def _norm(text: str) -> str:
    """归一化：去空白、转小写，用于宽松匹配。"""
    return "".join((text or "").split()).lower()


def _parse_filename(fn: str) -> tuple[str, str]:
    """从 "歌手 - 歌名.mp3" 提取 (artist, title)。
    解析失败返回 ("", 纯文件名主干)。
    """
    stem = os.path.splitext(fn)[0]
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return "", stem


def _size_close(a: int, b: int) -> bool:
    """两个文件大小是否接近（视为同一资源的可能压制版本）。"""
    if a <= 0 or b <= 0:
        return False
    diff = abs(a - b)
    if diff <= _SIZE_ABS_TOLERANCE:
        return True
    smaller = min(a, b)
    return diff / smaller <= _SIZE_REL_TOLERANCE


def _duration_close(a: int, b: int) -> bool:
    """两个时长是否接近（毫秒）。任一为 0 视为未知，跳过比较。"""
    if a <= 0 or b <= 0:
        return True  # 未知时不拒
    return abs(a - b) <= _DURATION_TOLERANCE_MS


# ── 本地扫描：仅歌名集合（旧 API，保持兼容）────────────────────

def local_downloaded_titles(out_dir: str) -> set[str]:
    """扫描 out_dir 下已有的音频文件，返回归一化歌名集合。"""
    titles: set[str] = set()
    if not os.path.isdir(out_dir):
        return titles
    for fn in os.listdir(out_dir):
        if fn.lower().endswith(AUDIO_EXTS):
            _artist, title = _parse_filename(fn)
            titles.add(_norm(title))
    return titles


def uploaded_titles(watch_dir: str, artist: str) -> set[str]:
    """读 pan-sync 的 .uploaded.json，返回该歌手已上传（status=uploaded）的归一化歌名集合。"""
    titles: set[str] = set()
    artist_dir = os.path.join(watch_dir, artist)
    manifest_path = os.path.join(artist_dir, UPLOADED_MANIFEST)
    if not os.path.isfile(manifest_path):
        return titles
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return titles
    for entry in data.get("entries", []):
        if entry.get("status") != "uploaded":
            continue
        rel = entry.get("rel_path", "")
        base = os.path.basename(rel)
        _art, title = _parse_filename(base)
        titles.add(_norm(title))
    return titles


def downloaded_titles(out_dir: str, watch_dir: str, artist: str) -> set[str]:
    """合并"本地已有" + "曾上传网盘"的已下载歌名集合。"""
    return local_downloaded_titles(out_dir) | uploaded_titles(watch_dir, artist)


def filter_new_tracks(tracks: list[dict], downloaded: set[str]) -> tuple[list[dict], list[dict]]:
    """把曲目分为 (未下载需下载, 已下载跳过)。按归一化歌名匹配（旧 API）。"""
    new, skipped = [], []
    for t in tracks:
        (skipped if _norm(t.get("title", "")) in downloaded else new).append(t)
    return new, skipped


def fill_to_target(candidates: list[dict], downloaded: set[str], target: int) -> tuple[list[dict], list[dict]]:
    """从候选池按顺序取未下载的歌，凑满 target 首。

    返回 (要下载的 tracks, 因已下载而跳过的 tracks)。
    候选池不足 target 时返回全部未下载的。
    """
    new, skipped = filter_new_tracks(candidates, downloaded)
    return new[:target], skipped


# ── 多维度去重：本地已下载文件索引 ──────────────────────────────

def scan_local_library(root_dir: str) -> list[dict]:
    """扫描本地音乐目录，返回所有音频的元数据列表。

    支持两种目录结构：
      - 歌手目录（直接放音频文件）：root_dir/<歌手 - 歌名>.mp3
      - 音乐库根目录（按歌手分子目录）：root_dir/<歌手>/<歌手 - 歌名>.mp3

    自动判断：若 root_dir 下有子目录则视为库根，否则视为歌手目录。
    每个条目为 dict: {path, artist, title, album, size_bytes, duration_ms, format}。
    album/duration_ms 若无法获取则为 "" / 0。
    只解析文件名 + 文件大小，不读 ID3（避免大量文件时拖慢；需要时再单独 probe）。
    """
    items: list[dict] = []
    if not os.path.isdir(root_dir):
        return items

    # 判断是否有子目录（有则视为库根，递归扫描歌手子目录）
    has_subdirs = any(
        os.path.isdir(os.path.join(root_dir, name))
        for name in os.listdir(root_dir)
    )

    dirs_to_scan: list[tuple[str, str]] = []  # (目录路径, 默认歌手名)
    if has_subdirs:
        for artist_name in os.listdir(root_dir):
            artist_dir = os.path.join(root_dir, artist_name)
            if os.path.isdir(artist_dir):
                dirs_to_scan.append((artist_dir, artist_name))
    else:
        # 直接就是歌手目录；目录名作为默认歌手
        default_artist = os.path.basename(root_dir.rstrip(os.sep)) or ""
        dirs_to_scan.append((root_dir, default_artist))

    for artist_dir, default_artist in dirs_to_scan:
        try:
            filenames = os.listdir(artist_dir)
        except OSError:
            continue
        for fn in filenames:
            low = fn.lower()
            ext = ""
            for e in AUDIO_EXTS:
                if low.endswith(e):
                    ext = e.lstrip(".")
                    break
            if not ext:
                continue
            full_path = os.path.join(artist_dir, fn)
            try:
                size = os.path.getsize(full_path)
            except OSError:
                continue
            file_artist, title = _parse_filename(fn)
            artist = file_artist or default_artist
            items.append({
                "path": full_path,
                "artist": artist,
                "title": title,
                "album": "",  # 文件名不含专辑，按需用 ffprobe 补充
                "size_bytes": size,
                "duration_ms": 0,  # 同上，懒获取
                "format": ext,
            })
    return items


def is_same_track(track: Track, entry: dict) -> bool:
    """多维度判断：entry 是否与 track 指向同一首歌。

    匹配规则（同时满足）：
      1. 歌手归一化一致（任一方为空时跳过）
      2. 歌名归一化一致（必须）
      3. 专辑归一化一致（双方都非空才校验）
      4. 文件大小接近（双方都 >0 才校验）
      5. 时长接近（双方都 >0 才校验）
    """
    # 歌名必须匹配
    if not _norm(track.title) or not _norm(entry.get("title", "")):
        return False
    if _norm(track.title) != _norm(entry.get("title", "")):
        return False

    # 歌手：双方都非空才校验
    track_artist = _norm(track.artist)
    entry_artist = _norm(entry.get("artist", ""))
    if track_artist and entry_artist and track_artist != entry_artist:
        return False

    # 专辑：双方都非空才校验
    track_album = _norm(track.album)
    entry_album = _norm(entry.get("album", ""))
    if track_album and entry_album and track_album != entry_album:
        return False

    # 文件大小：双方都 >0 才校验
    t_size = int(getattr(track, "size_bytes", 0) or 0)
    e_size = int(entry.get("size_bytes", 0) or 0)
    if t_size > 0 and e_size > 0 and not _size_close(t_size, e_size):
        return False

    # 时长：双方都 >0 才校验
    t_dur = int(getattr(track, "duration_ms", 0) or 0)
    e_dur = int(entry.get("duration_ms", 0) or 0)
    if t_dur > 0 and e_dur > 0 and not _duration_close(t_dur, e_dur):
        return False

    return True


def find_local_match(track: Track, out_dir: str) -> dict | None:
    """在本地音乐库里查找与 track 匹配的文件。找到返回其元数据 dict，否则 None。"""
    for entry in scan_local_library(out_dir):
        if is_same_track(track, entry):
            return entry
    return None


# ── 已上传清单的多维度版本 ──────────────────────────────────────

def uploaded_entries(watch_dir: str, artist: str) -> list[dict]:
    """读 .uploaded.json，返回该歌手已上传条目的元数据列表（含 size/remote_path）。"""
    entries: list[dict] = []
    artist_dir = os.path.join(watch_dir, artist)
    manifest_path = os.path.join(artist_dir, UPLOADED_MANIFEST)
    if not os.path.isfile(manifest_path):
        return entries
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return entries
    for e in data.get("entries", []):
        if e.get("status") != "uploaded":
            continue
        rel = e.get("rel_path", "")
        base = os.path.basename(rel)
        art, title = _parse_filename(base)
        entries.append({
            "artist": art or artist,
            "title": title,
            "album": "",
            "size_bytes": int(e.get("size", 0) or 0),
            "duration_ms": 0,
            "remote_path": e.get("remote_path", ""),
            "md5": e.get("md5", ""),
            "rel_path": rel,
        })
    return entries


def find_uploaded_match(track: Track, watch_dir: str, artist: str) -> dict | None:
    """在已上传清单里查找与 track 匹配的条目。找到返回元数据 dict，否则 None。"""
    for entry in uploaded_entries(watch_dir, artist):
        if is_same_track(track, entry):
            return entry
    return None
