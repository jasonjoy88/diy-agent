import os
import unittest
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent.graph import build_graph
from music_agent.models import DownloadResult, Track


class TestGraph(TmpDirTestCase):
    def test_graph_runs_end_to_end(self):
        fake_track = Track(song_id="1", title="晴天", artist="周杰伦", duration_ms=269000)
        audio = os.path.join(self.tmp, "a.mp3")
        open(audio, "wb").write(b"x" * 200000)
        fake_ok = DownloadResult(track_id="1", status="ok", path=audio,
                                 format="mp3", source="netease", title="晴天", artist="周杰伦")
        fake_lrc = os.path.join(self.tmp, "a.lrc")
        with patch("music_agent.nodes.plan_tracks.catalog.discover_tracks", return_value=[fake_track]), \
             patch("music_agent.nodes.fetch_loop._build_sources", return_value=[object()]), \
             patch("music_agent.nodes.fetch_loop._fetch_one", return_value=fake_ok), \
             patch("music_agent.nodes.fetch_lyrics.lyrics.fetch_track_lyric",
                   return_value=(fake_lrc, "ok", "")), \
             patch("music_agent.nodes.resolve_artist.catalog.itunes_alias", return_value=None), \
             patch("music_agent.nodes.resolve_artist.llm.ask", return_value=None):
            g = build_graph()
            out = g.invoke({"singer": "周杰伦", "songs": [], "top_n": 1,
                            "out_dir": self.tmp, "results": {}, "messages": []})
        self.assertIn("ok", out["final_report"])
        self.assertEqual(out["results"]["1"]["status"], "ok")

    def test_graph_marks_failed_when_no_source(self):
        fake_track = Track(song_id="1", title="晴天", artist="周杰伦", duration_ms=269000)
        with patch("music_agent.nodes.plan_tracks.catalog.discover_tracks", return_value=[fake_track]), \
             patch("music_agent.nodes.fetch_loop._build_sources", return_value=[]), \
             patch("music_agent.nodes.resolve_artist.catalog.itunes_alias", return_value=None), \
             patch("music_agent.nodes.resolve_artist.llm.ask", return_value=None):
            g = build_graph()
            out = g.invoke({"singer": "周杰伦", "songs": [], "top_n": 1,
                            "out_dir": self.tmp, "results": {}, "messages": []})
        self.assertEqual(out["results"]["1"]["status"], "failed")
        self.assertEqual(out["results"]["1"]["fail_reason"], "no_source")


if __name__ == "__main__":
    unittest.main()
