import json
import unittest
from unittest.mock import patch

from music_agent import catalog


def _songs(*names):
    return {"result": {"songs": [
        {"id": str(i), "name": n, "artists": [{"name": "周杰伦"}],
         "album": {"name": "A"}, "duration": 200000 + i}
        for i, n in enumerate(names)
    ]}}


class TestCatalog(unittest.TestCase):
    def test_discover_top_n(self):
        with patch("music_agent.sources.netease_source.NeteaseSource._get",
                   return_value=json.dumps(_songs("晴天", "稻香", "告白气球")).encode()):
            tracks = catalog.discover_tracks("周杰伦", top_n=3)
        self.assertEqual([t.title for t in tracks], ["晴天", "稻香", "告白气球"])

    def test_match_songs_exact(self):
        # match_songs 对每首歌单独搜索；mock 让 "晴天" 命中、"不存在的歌" 也返回但取第一个
        def fake_get(self, url):
            return json.dumps(_songs("晴天", "稻香")).encode()
        with patch("music_agent.sources.netease_source.NeteaseSource._get", fake_get):
            found, missing = catalog.match_songs("周杰伦", ["晴天"])
        self.assertTrue(any(t.title == "晴天" for t in found))

    def test_itunes_alias_returns_name(self):
        payload = {"results": [{"artistId": 300117743, "artistName": "周杰倫"}]}
        with patch.object(catalog, "_http_get", return_value=json.dumps(payload).encode()):
            self.assertEqual(catalog.itunes_alias("Jay Chou"), "周杰倫")


if __name__ == "__main__":
    unittest.main()
