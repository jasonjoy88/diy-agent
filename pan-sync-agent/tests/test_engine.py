import hashlib
import os
import tempfile
import time
import unittest

from pan_sync import manifest, scanner
from pan_sync.config import Config
from pan_sync.engine import SyncEngine
from pan_sync.errors import AuthError, UploadError


class FakeUploader:
    def __init__(self, existing=None, fail_paths=()):
        self.existing = existing or set()
        self.fail_paths = set(fail_paths)
        self.uploaded = []
        self.ensured = []

    def ensure_dir(self, remote_path):
        self.ensured.append(remote_path)

    def exists(self, remote_path):
        return remote_path in self.existing

    def upload(self, local_path, remote_path):
        if remote_path in self.fail_paths:
            raise UploadError("network down")
        self.uploaded.append(remote_path)


def make_cfg(watch_dir, stable_seconds=60):
    return Config(
        watch_dir=watch_dir,
        drive="baidu",
        scan_interval_minutes=30,
        start_hour=8,
        end_hour=23,
        remote_root="/pan-sync",
        conflict_policy="skip",
        chunk_size_mb=4,
        stable_seconds=stable_seconds,
    )


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.watch = os.path.join(self.tmp.name, "watch")
        os.makedirs(self.watch)

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, rel, content=b"x", old=True):
        path = os.path.join(self.watch, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        if old:
            past = time.time() - 600
            os.utime(path, (past, past))
        return path

    def test_upload_writes_manifest_and_deletes_local(self):
        path = self._put("a.txt", b"hello")
        engine = SyncEngine(make_cfg(self.watch), FakeUploader())
        stats = engine.run_once()
        self.assertEqual(stats["uploaded"], 1)
        self.assertFalse(os.path.exists(path))
        entries = manifest.load_entries(self.watch)
        self.assertEqual(entries[0].status, "uploaded")
        self.assertEqual(entries[0].md5, hashlib.md5(b"hello").hexdigest())

    def test_conflict_keeps_local(self):
        path = self._put("a.txt")
        up = FakeUploader(existing={"/pan-sync/a.txt"})
        stats = SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertEqual(stats["conflict"], 1)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(manifest.load_entries(self.watch)[0].status, "conflict")

    def test_failure_records_failed_and_keeps_local(self):
        path = self._put("a.txt")
        up = FakeUploader(fail_paths={"/pan-sync/a.txt"})
        stats = SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertEqual(stats["failed"], 1)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(manifest.load_entries(self.watch)[0].status, "failed")

    def test_unstable_file_skipped(self):
        path = self._put("a.txt", old=False)
        stats = SyncEngine(make_cfg(self.watch), FakeUploader()).run_once()
        self.assertEqual(stats["unstable"], 1)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(manifest.load_entries(self.watch), [])

    def test_previously_uploaded_file_gets_cleaned(self):
        path = self._put("a.txt", b"same")
        st = os.stat(path)
        digest = scanner.md5_of_file(path)
        manifest.append_entry(
            self.watch,
            manifest.make_entry("a.txt", st.st_size, st.st_mtime, digest,
                                "/pan-sync/a.txt", "uploaded"),
        )
        up = FakeUploader(existing={"/pan-sync/a.txt"})
        stats = SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertEqual(stats["cleaned"], 1)
        self.assertFalse(os.path.exists(path))

    def test_same_name_new_file_uploaded_again(self):
        path = self._put("a.txt", b"new-content")
        old_time = time.time() - 100000
        manifest.append_entry(
            self.watch,
            manifest.make_entry("a.txt", 1, old_time, "oldmd5",
                                "/pan-sync/a.txt", "uploaded"),
        )
        up = FakeUploader()
        stats = SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertEqual(stats["uploaded"], 1)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(up.uploaded, ["/pan-sync/a.txt"])

    def test_remote_dir_mapping_with_subfolders(self):
        self._put("sub/deep/a.txt")
        up = FakeUploader()
        SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertEqual(up.uploaded, ["/pan-sync/sub/deep/a.txt"])
        self.assertIn("/pan-sync/sub/deep", up.ensured)

    def test_auth_error_propagates_without_failed_record(self):
        path = self._put("a.txt")
        up = FakeUploader()

        def raise_auth(local, remote):
            raise AuthError("login expired")

        up.upload = raise_auth
        with self.assertRaises(AuthError):
            SyncEngine(make_cfg(self.watch), up).run_once()
        self.assertTrue(os.path.exists(path))
        self.assertEqual(manifest.load_entries(self.watch), [])

    def test_non_business_exception_propagates(self):
        # 模拟 dsh_guard 注入的超时中断：仅继承 Exception
        class FakeTimeout(Exception):
            pass

        self._put("a.txt")
        up = FakeUploader()

        def raise_timeout(local, remote):
            raise FakeTimeout()

        up.upload = raise_timeout
        with self.assertRaises(FakeTimeout):
            SyncEngine(make_cfg(self.watch), up).run_once()


if __name__ == "__main__":
    unittest.main()
