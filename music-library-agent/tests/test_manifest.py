import unittest

from tests._base import TmpDirTestCase

from music_agent import manifest
from music_agent.models import DownloadResult


class TestManifest(TmpDirTestCase):
    def test_roundtrip(self):
        m = manifest.Manifest(self.tmp, "周杰伦")
        m.upsert(DownloadResult(track_id="1", status="ok", path="/x.mp3", format="mp3",
                                source="netease", title="晴天", artist="周杰伦"))
        m.upsert(DownloadResult(track_id="2", status="failed", fail_reason="vip_required",
                                title="稻香", artist="周杰伦"))
        m.save()
        m2 = manifest.Manifest.load(self.tmp, "周杰伦")
        self.assertEqual(m2.get("1").status, "ok")
        self.assertEqual(m2.get("2").fail_reason, "vip_required")

    def test_todo_ids_excludes_ok(self):
        m = manifest.Manifest(self.tmp, "周杰伦")
        m.upsert(DownloadResult(track_id="1", status="ok", title="a"))
        m.upsert(DownloadResult(track_id="2", status="failed", title="b"))
        m.upsert(DownloadResult(track_id="3", status="pending", title="c"))
        self.assertEqual(set(m.todo_ids()), {"2", "3"})

    def test_summary(self):
        m = manifest.Manifest(self.tmp, "周杰伦")
        m.upsert(DownloadResult(track_id="1", status="ok", title="a"))
        m.upsert(DownloadResult(track_id="2", status="failed", title="b"))
        s = m.summary()
        self.assertEqual(s["ok"], 1)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["total"], 2)


if __name__ == "__main__":
    unittest.main()
