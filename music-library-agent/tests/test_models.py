import unittest

from music_agent.models import DownloadResult, Track


class TestModels(unittest.TestCase):
    def test_track_fields(self):
        t = Track(song_id="347230", title="晴天", artist="周杰伦", album="叶惠美", duration_ms=269000)
        self.assertEqual(t.title, "晴天")
        self.assertEqual(t.duration_ms, 269000)
        self.assertEqual(t.artist, "周杰伦")

    def test_track_safe_filename(self):
        t = Track(song_id="1", title='a/b\\c:d*e', artist="x", album="", duration_ms=0)
        fn = t.safe_filename()
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, fn)

    def test_download_result_defaults(self):
        r = DownloadResult(track_id="1", status="pending")
        self.assertEqual(r.status, "pending")
        self.assertEqual(r.format, "")
        self.assertEqual(r.source, "")
        self.assertEqual(r.fail_reason, "")


if __name__ == "__main__":
    unittest.main()
