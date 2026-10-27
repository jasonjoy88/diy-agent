import os
import unittest
from dataclasses import asdict
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent.models import DownloadResult, Track
from music_agent.nodes import plan_tracks, validate as validate_node, write_manifest


def _tracks():
    return [asdict(Track(song_id="1", title="晴天", artist="周杰伦", duration_ms=269000))]


class TestNodes(TmpDirTestCase):
    def test_plan_tracks_top_n(self):
        with patch("music_agent.nodes.plan_tracks.catalog.discover_tracks",
                   return_value=[Track(song_id="1", title="晴天", artist="周杰伦")]):
            out = plan_tracks.run({"singer": "周杰伦", "songs": [], "top_n": 1,
                                   "artist": "周杰伦", "out_dir": self.tmp})
        self.assertEqual(out["tracks"][0]["title"], "晴天")

    def test_plan_tracks_specific_song(self):
        with patch("music_agent.nodes.plan_tracks.catalog.match_songs",
                   return_value=([Track(song_id="1", title="晴天", artist="周杰伦")], [])):
            out = plan_tracks.run({"singer": "周杰伦", "songs": ["晴天"], "top_n": 30,
                                   "artist": "周杰伦", "out_dir": self.tmp})
        self.assertEqual(len(out["tracks"]), 1)
        self.assertEqual(out["tracks"][0]["title"], "晴天")

    def test_validate_node_keeps_ok(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x" * 200000)
        state = {"tracks": _tracks(),
                 "results": {"1": asdict(DownloadResult(track_id="1", status="ok", path=p))},
                 "out_dir": self.tmp}
        out = validate_node.run(state)
        self.assertEqual(out["results"]["1"]["status"], "ok")

    def test_validate_node_marks_missing_failed(self):
        state = {"tracks": _tracks(),
                 "results": {"1": asdict(DownloadResult(track_id="1", status="ok", path=os.path.join(self.tmp, "none.mp3")))},
                 "out_dir": self.tmp}
        out = validate_node.run(state)
        self.assertEqual(out["results"]["1"]["status"], "failed")
        self.assertEqual(out["results"]["1"]["fail_reason"], "missing")

    def test_write_manifest(self):
        state = {"artist": "周杰伦", "out_dir": self.tmp, "tracks": _tracks(),
                 "results": {"1": asdict(DownloadResult(track_id="1", status="ok", path="/x.mp3",
                                                        format="mp3", source="netease"))}}
        out = write_manifest.run(state)
        self.assertIn("ok", out["final_report"])
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "manifest.json")))


if __name__ == "__main__":
    unittest.main()
