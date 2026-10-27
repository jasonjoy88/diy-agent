import hashlib
import os
import time

from .manifest import MANIFEST_FILENAME

_MD5_BUF = 1024 * 1024
DEFAULT_SKIP_DIR_PREFIXES = ("_",)


def _skip_dir_name(name, prefixes):
    return any(name.startswith(p) for p in prefixes if p)


def _prune_dirs(dirs, prefixes):
    dirs[:] = [d for d in dirs if not _skip_dir_name(d, prefixes)]
    dirs.sort()


def iter_files(watch_dir, skip_dir_prefixes=DEFAULT_SKIP_DIR_PREFIXES):
    """递归列出待上传文件。

    名称匹配 skip_dir_prefixes 的子目录整棵跳过（默认以下划线开头，
    如 music/_pool_smoke、_probe_dj、_probe_yt，不当作歌手目录）。
    监控根下的散文件也不上传，歌手歌应在 <WATCH_DIR>/<歌手>/ 下。
    """
    prefixes = tuple(skip_dir_prefixes or ())
    for root, dirs, files in os.walk(watch_dir):
        _prune_dirs(dirs, prefixes)
        if os.path.abspath(root) == os.path.abspath(watch_dir):
            continue
        for name in sorted(files):
            if name == MANIFEST_FILENAME:
                continue
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, watch_dir).replace(os.sep, "/")
            yield abs_path, rel_path


def iter_manifest_dirs(watch_dir, skip_dir_prefixes=DEFAULT_SKIP_DIR_PREFIXES):
    prefixes = tuple(skip_dir_prefixes or ())
    for root, dirs, files in os.walk(watch_dir):
        _prune_dirs(dirs, prefixes)
        if os.path.abspath(root) == os.path.abspath(watch_dir):
            continue
        if MANIFEST_FILENAME in files:
            yield root


def md5_of_file(path):
    digest = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_MD5_BUF)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_stable(path, stable_seconds, now=None):
    mtime = os.stat(path).st_mtime
    if now is None:
        now = time.time()
    return now - mtime >= stable_seconds
