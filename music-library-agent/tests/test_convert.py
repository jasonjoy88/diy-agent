import os
import unittest
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent import convert


class TestConvert(TmpDirTestCase):
    def test_find_ffmpeg_none_when_missing(self):
        self.assertIsNone(convert.find_ffmpeg(os.path.join(self.tmp, "nope")))

    def test_find_ffmpeg_in_bin(self):
        exe = os.path.join(self.tmp, "bin", "ffmpeg.exe")
        os.makedirs(os.path.dirname(exe))
        open(exe, "w").write("x")
        self.assertEqual(convert.find_ffmpeg(os.path.join(self.tmp, "bin")), exe)

    def test_to_mp3_passthrough_when_already_mp3(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x" * 200000)
        out, fmt = convert.to_mp3(p, "320k", ffmpeg_path=None)
        self.assertEqual(out, p)
        self.assertEqual(fmt, "mp3")

    def test_to_mp3_fallback_when_no_ffmpeg(self):
        p = os.path.join(self.tmp, "a.m4a")
        open(p, "wb").write(b"x" * 200000)
        out, fmt = convert.to_mp3(p, "320k", ffmpeg_path=None)
        self.assertEqual(out, p)      # 无 ffmpeg → 保留原格式兜底
        self.assertEqual(fmt, "m4a")

    def test_to_mp3_converts_with_ffmpeg(self):
        src = os.path.join(self.tmp, "a.m4a")
        open(src, "wb").write(b"x" * 200000)
        dst = os.path.join(self.tmp, "a.mp3")

        def fake_run(cmd, **kw):
            open(dst, "wb").write(b"mp3")

            class R:
                returncode = 0
            return R()

        with patch("subprocess.run", side_effect=fake_run):
            out, fmt = convert.to_mp3(src, "320k", ffmpeg_path="ffmpeg")
        self.assertEqual(out, dst)
        self.assertEqual(fmt, "mp3")


if __name__ == "__main__":
    unittest.main()
