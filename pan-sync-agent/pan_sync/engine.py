import os
import posixpath

from . import manifest, scanner
from .errors import AuthError, UploadError
from .uploader.base import retry


class SyncEngine:
    def __init__(self, config, uploader, log=print):
        self.config = config
        self.uploader = uploader
        self.log = log

    def _remote_path(self, rel_path):
        return posixpath.join(self.config.remote_root, rel_path)

    def run_once(self):
        stats = {
            "uploaded": 0,
            "conflict": 0,
            "failed": 0,
            "cleaned": 0,
            "unstable": 0,
            "errors": 0,
        }
        for abs_path, rel_path in scanner.iter_files(
            self.config.watch_dir,
            skip_dir_prefixes=self.config.skip_dir_prefixes,
        ):
            try:
                self._process(abs_path, rel_path, stats)
            except AuthError:
                raise
            except (OSError, UploadError) as e:
                # 仅隔离业务/网络异常；其他异常（如守卫注入的超时中断）必须穿透。
                self.log(f"[engine] 处理异常 {rel_path}: {e!r}")
                stats["errors"] += 1
        self.log(f"[engine] 本轮完成：{stats}")
        return stats

    def _process(self, abs_path, rel_path, stats):
        directory = os.path.dirname(abs_path)
        latest = manifest.latest_by_relpath(manifest.load_entries(directory)).get(rel_path)
        stat_result = os.stat(abs_path)
        remote_path = self._remote_path(rel_path)

        if (
            latest is not None
            and latest.status == "uploaded"
            and latest.size == stat_result.st_size
            and abs(latest.mtime - stat_result.st_mtime) < 0.001
            and scanner.md5_of_file(abs_path) == latest.md5
        ):
            if self.uploader.exists(latest.remote_path):
                os.remove(abs_path)
                stats["cleaned"] += 1
                return

        if not scanner.is_stable(abs_path, self.config.stable_seconds):
            stats["unstable"] += 1
            return

        parent = posixpath.dirname(remote_path) or "/"
        self.uploader.ensure_dir(parent)

        if self.uploader.exists(remote_path):
            manifest.append_entry(
                directory,
                manifest.make_entry(
                    rel_path, stat_result.st_size, stat_result.st_mtime, "",
                    remote_path, "conflict", "remote already exists",
                ),
            )
            stats["conflict"] += 1
            return

        digest = scanner.md5_of_file(abs_path)
        try:
            retry(
                lambda: self.uploader.upload(abs_path, remote_path),
                log=self.log,
            )
        except AuthError:
            raise
        except (OSError, UploadError) as e:
            manifest.append_entry(
                directory,
                manifest.make_entry(
                    rel_path, stat_result.st_size, stat_result.st_mtime, digest,
                    remote_path, "failed", str(e),
                ),
            )
            stats["failed"] += 1
            self.log(f"[engine] 上传失败 {rel_path}: {e}")
            return

        manifest.append_entry(
            directory,
            manifest.make_entry(
                rel_path, stat_result.st_size, stat_result.st_mtime, digest,
                remote_path, "uploaded",
            ),
        )
        os.remove(abs_path)
        stats["uploaded"] += 1
