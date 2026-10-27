import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from main import build_uploader, login_or_none, run_cycle
from pan_sync.config import Config
from pan_sync.uploader.baidu import BaiduUploader
from pan_sync.uploader.quark import QuarkUploader


def cfg(drive):
    return Config(
        watch_dir=os.path.dirname(os.path.abspath(__file__)),
        drive=drive,
        scan_interval_minutes=30,
        start_hour=8,
        end_hour=23,
        remote_root="/pan-sync",
        conflict_policy="skip",
        chunk_size_mb=4,
        stable_seconds=60,
    )


class MainTest(unittest.TestCase):
    def test_build_baidu_uploader(self):
        self.assertIsInstance(build_uploader(cfg("baidu"), {"BDUSS": "b"}), BaiduUploader)

    def test_build_quark_uploader(self):
        token = {"access_token": "AT", "device_id": "d"}
        self.assertIsInstance(build_uploader(cfg("quark"), token), QuarkUploader)

    def test_run_cycle_wraps_with_timeout_guard(self):
        tmp = tempfile.TemporaryDirectory()
        empty_cfg = Config(
            watch_dir=tmp.name,
            drive="baidu",
            scan_interval_minutes=30,
            start_hour=8,
            end_hour=23,
            remote_root="/pan-sync",
            conflict_policy="skip",
            chunk_size_mb=4,
            stable_seconds=60,
        )
        with patch("main.turn_timeout_guard") as mock_guard:
            mock_guard.return_value.__enter__.return_value = None
            mock_guard.return_value.__exit__.return_value = False
            run_cycle(empty_cfg, MagicMock(), "once")
        mock_guard.assert_called_once()
        self.assertEqual(mock_guard.call_args.kwargs["agent"], "pan-sync-agent")
        self.assertEqual(mock_guard.call_args.kwargs["extra"], {"command": "once"})
        tmp.cleanup()

    def test_login_or_none_returns_none_on_oserror(self):
        with patch("main.ensure_login", side_effect=ConnectionError("net down")):
            self.assertIsNone(login_or_none(cfg("baidu")))


if __name__ == "__main__":
    unittest.main()
