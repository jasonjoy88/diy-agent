import os
import tempfile
import unittest

from pan_sync.config import Config, load_config
from pan_sync.errors import ConfigError


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        self.watch = os.path.join(self.base, "watch")
        os.makedirs(self.watch)
        self.env_path = os.path.join(self.base, ".env")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_env(self, body):
        with open(self.env_path, "w", encoding="utf-8") as f:
            f.write(body)

    def _minimal(self, **overrides):
        lines = [f"WATCH_DIR={self.watch}"]
        lines.extend(f"{k}={v}" for k, v in overrides.items())
        self._write_env("\n".join(lines))

    def test_defaults(self):
        self._minimal()
        cfg = load_config(self.env_path)
        self.assertEqual(cfg.watch_dir, self.watch)
        self.assertEqual(cfg.drive, "baidu")
        self.assertEqual(cfg.scan_interval_minutes, 30)
        self.assertEqual(cfg.start_hour, 8)
        self.assertEqual(cfg.end_hour, 23)
        self.assertEqual(cfg.remote_root, "/pan-sync")
        self.assertEqual(cfg.conflict_policy, "skip")
        self.assertEqual(cfg.chunk_size_mb, 4)
        self.assertEqual(cfg.chunk_size_bytes, 4 * 1024 * 1024)
        self.assertEqual(cfg.stable_seconds, 60)

    def test_missing_watch_dir_raises(self):
        self._write_env("DRIVE=baidu\n")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_nonexistent_watch_dir_raises(self):
        self._write_env(f"WATCH_DIR={os.path.join(self.base, 'nope')}\n")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_watch_dir_is_file_raises(self):
        file_path = os.path.join(self.base, "afile")
        with open(file_path, "w") as f:
            f.write("x")
        self._write_env(f"WATCH_DIR={file_path}\n")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_bad_drive_raises(self):
        self._minimal(DRIVE="onedrive")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_quark_drive_ok(self):
        self._minimal(DRIVE="quark")
        self.assertEqual(load_config(self.env_path).drive, "quark")

    def test_start_hour_zero_ok(self):
        self._minimal(START_HOUR=0, END_HOUR=23)
        self.assertEqual(load_config(self.env_path).start_hour, 0)

    def test_negative_hour_still_rejected(self):
        self._minimal(START_HOUR=-1)
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_bad_hours_raise(self):
        self._minimal(START_HOUR=23, END_HOUR=23)
        with self.assertRaises(ConfigError):
            load_config(self.env_path)
        self._minimal(START_HOUR=-1)
        with self.assertRaises(ConfigError):
            load_config(self.env_path)
        self._minimal(END_HOUR=24)
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_non_integer_interval_raises(self):
        self._minimal(SCAN_INTERVAL_MINUTES="soon")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_interval_must_be_positive(self):
        self._minimal(SCAN_INTERVAL_MINUTES=0)
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_remote_root_normalized(self):
        self._minimal(REMOTE_ROOT="backup/2026/")
        cfg = load_config(self.env_path)
        self.assertEqual(cfg.remote_root, "/backup/2026")

    def test_remote_root_single_slash(self):
        self._minimal(REMOTE_ROOT="/")
        self.assertEqual(load_config(self.env_path).remote_root, "")

    def test_unknown_conflict_policy_raises(self):
        self._minimal(CONFLICT_POLICY="overwrite")
        with self.assertRaises(ConfigError):
            load_config(self.env_path)

    def test_env_file_with_utf8_bom(self):
        with open(self.env_path, "w", encoding="utf-8-sig") as f:
            f.write(f"WATCH_DIR={self.watch}\nDRIVE=quark\n")
        cfg = load_config(self.env_path)
        self.assertEqual(cfg.watch_dir, self.watch)
        self.assertEqual(cfg.drive, "quark")

    def test_env_var_overrides_file(self):
        self._minimal(DRIVE="quark")
        old = os.environ.get("DRIVE")
        os.environ["DRIVE"] = "baidu"
        try:
            self.assertEqual(load_config(self.env_path).drive, "baidu")
        finally:
            if old is None:
                del os.environ["DRIVE"]
            else:
                os.environ["DRIVE"] = old


if __name__ == "__main__":
    unittest.main()
