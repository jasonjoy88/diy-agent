import os
import unittest

from tests._base import TmpDirTestCase

from music_agent import upload


class TestUpload(TmpDirTestCase):
    def test_stage_for_upload(self):
        src = os.path.join(self.tmp, "周杰伦 - 晴天.mp3")
        open(src, "wb").write(b"x" * 200000)
        watch = os.path.join(self.tmp, "watch")
        ok, failed = upload.stage_for_upload([src], watch, "周杰伦")
        self.assertEqual(ok, [src])
        self.assertEqual(failed, [])
        self.assertTrue(os.path.isfile(os.path.join(watch, "周杰伦", "周杰伦 - 晴天.mp3")))

    def test_stage_skips_existing(self):
        src = os.path.join(self.tmp, "a.mp3")
        open(src, "wb").write(b"x" * 200000)
        watch = os.path.join(self.tmp, "watch")
        dest_dir = os.path.join(watch, "周杰伦")
        os.makedirs(dest_dir)
        open(os.path.join(dest_dir, "a.mp3"), "wb").write(b"y" * 200000)  # 已存在
        ok, failed = upload.stage_for_upload([src], watch, "周杰伦")
        self.assertEqual(ok, [src])  # 视为成功（已在待传队列）
        self.assertEqual(failed, [])

    def test_collect_ok_audio(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x" * 200000)
        results = {
            "1": {"status": "ok", "path": p},
            "2": {"status": "failed", "path": ""},
            "3": {"status": "ok", "path": os.path.join(self.tmp, "missing.mp3")},  # 文件不存在
        }
        files = upload.collect_ok_audio(results)
        self.assertEqual(files, [p])


if __name__ == "__main__":
    unittest.main()
