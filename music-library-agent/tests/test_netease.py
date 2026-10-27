import json
import unittest
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent.models import Track
from music_agent.sources.netease_source import NeteaseSource


def _search_payload():
    return {"result": {"songs": [
        {"id": 347230, "name": "晴天", "artists": [{"name": "周杰伦"}],
         "album": {"name": "叶惠美"}, "duration": 269000}
    ]}}


class TestNetease(TmpDirTestCase):
    def test_search_tracks_parses(self):
        src = NeteaseSource(cookie="x")
        with patch.object(src, "_get", return_value=json.dumps(_search_payload()).encode()):
            tracks = src.search_tracks("周杰伦", 5)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "晴天")
        self.assertEqual(tracks[0].song_id, "347230")
        self.assertEqual(tracks[0].artist, "周杰伦")
        self.assertEqual(tracks[0].duration_ms, 269000)

    def test_available_false_without_cookie(self):
        self.assertFalse(NeteaseSource(cookie="").available())

    def test_available_true_with_cookie(self):
        self.assertTrue(NeteaseSource(cookie="MUSIC_U=abc").available())

    def test_fetch_no_url_marks_failed(self):
        src = NeteaseSource(cookie="x")
        t = Track(song_id="347230", title="晴天", artist="周杰伦")
        with patch.object(src, "_get", return_value=json.dumps({"data": [{"url": None, "code": -110}]}).encode()):
            r = src.fetch(t, self.tmp)
        self.assertEqual(r.status, "failed")
        self.assertIn(r.fail_reason, ("vip_required", "no_url"))


if __name__ == "__main__":
    unittest.main()
