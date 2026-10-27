import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent.manifest import Manifest
from music_agent.models import DownloadResult, Track
from music_agent.nodes import fetch_loop


class TestResume(TmpDirTestCase):
    def _state(self, tracks):
        return {"singer": "周杰伦", "artist": "周杰伦", "songs": [], "top_n": 2,
                "resume": True, "out_dir": self.tmp,
                "tracks": [asdict(t) for t in tracks], "results": {}, "messages": []}

    def test_resume_skips_ok(self):
        # 预置 manifest：song 1 已 ok
        done_file = os.path.join(self.tmp, "周杰伦 - 已完成.mp3")
        open(done_file, "wb").write(b"x" * 200000)
        m = Manifest(self.tmp, "周杰伦")
        m.upsert(DownloadResult(track_id="1", status="ok", path=done_file, format="mp3",
                                source="netease", title="已完成", artist="周杰伦"))
        m.save()

        tracks = [Track(song_id="1", title="已完成", artist="周杰伦"),
                  Track(song_id="2", title="新歌", artist="周杰伦")]
        new_ok = DownloadResult(track_id="2", status="ok", path=os.path.join(self.tmp, "新歌.mp3"),
                                format="mp3", source="netease", title="新歌", artist="周杰伦")

        # _fetch_one 只应被调用一次（song 2）；song 1 应直接沿用 manifest
        calls = []

        def fake_fetch_one(track, sources, out_dir):
            calls.append(track.song_id)
            return new_ok

        with patch("music_agent.nodes.fetch_loop._build_sources", return_value=[object()]), \
             patch("music_agent.nodes.fetch_loop._fetch_one", side_effect=fake_fetch_one):
            out = fetch_loop.run(self._state(tracks))

        self.assertEqual(calls, ["2"], "已 ok 的 song 1 不应重新下载")
        self.assertEqual(out["results"]["1"]["status"], "ok")
        self.assertEqual(out["results"]["1"]["path"], done_file)  # 沿用旧路径
        self.assertEqual(out["results"]["2"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
