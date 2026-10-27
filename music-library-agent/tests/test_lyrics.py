import json
import os
import unittest
from unittest.mock import patch

from tests._base import TmpDirTestCase

from music_agent import lyrics as lyrics_mod
from music_agent.models import Track
from music_agent.nodes import fetch_lyrics as fetch_lyrics_node
from music_agent.sources.netease_source import NeteaseSource


def _lyric_payload(orig="[00:00.00]歌词", trans=""):
    return {"code": 200, "lrc": {"lyric": orig}, "tlyric": {"lyric": trans}}


class TestNeteaseFetchLyric(unittest.TestCase):
    def test_fetch_lyric_parses_lrc_and_tlyric(self):
        src = NeteaseSource(cookie="")
        payload = _lyric_payload("[00:01.00]晴天", "[00:01.00]Sunny")
        with patch.object(src, "_get", return_value=json.dumps(payload).encode()):
            got = src.fetch_lyric("347230")
        self.assertEqual(got["lrc"], "[00:01.00]晴天")
        self.assertEqual(got["tlyric"], "[00:01.00]Sunny")

    def test_fetch_lyric_without_cookie_allowed(self):
        # 歌词接口不需要 cookie，无 cookie 也应能调用
        src = NeteaseSource(cookie="")
        with patch.object(src, "_get", return_value=json.dumps(_lyric_payload()).encode()) as m:
            src.fetch_lyric("1")
        m.assert_called_once()


class TestLrcMerge(unittest.TestCase):
    def test_merge_bilingual_by_timestamp(self):
        orig = "[00:01.00]你好\n[00:03.00]世界"
        trans = "[00:01.00]Hello\n[00:03.00]World"
        out = lyrics_mod.merge_bilingual(orig, trans)
        self.assertIn("[00:01.00]你好 / Hello", out)
        self.assertIn("[00:03.00]世界 / World", out)

    def test_merge_missing_translation_keeps_original(self):
        orig = "[00:01.00]你好\n[00:03.00]世界"
        trans = "[00:01.00]Hello"
        out = lyrics_mod.merge_bilingual(orig, trans)
        self.assertIn("[00:01.00]你好 / Hello", out)
        # 无翻译的末行保持原样，不应拼上 "/"
        self.assertTrue(out.endswith("[00:03.00]世界"))

    def test_merge_empty_translation_returns_original(self):
        orig = "[00:01.00]你好"
        self.assertEqual(lyrics_mod.merge_bilingual(orig, ""), orig)

    def test_strips_existing_metadata_tag_lines(self):
        orig = "[ti:旧标题]\n[00:01.00]你好"
        out = lyrics_mod.merge_bilingual(orig, "")
        self.assertNotIn("[ti:", out)
        self.assertIn("[00:01.00]你好", out)

    def test_build_header(self):
        t = Track(song_id="1", title="晴天", artist="周杰伦", album="叶惠美")
        header = lyrics_mod.build_header(t)
        self.assertIn("[ti:晴天]", header)
        self.assertIn("[ar:周杰伦]", header)
        self.assertIn("[al:叶惠美]", header)
        self.assertIn("[by:music-library-agent]", header)


class TestTrackLyrics(TmpDirTestCase):
    def _track(self, song_id="347230"):
        return Track(song_id=song_id, title="晴天", artist="周杰伦", album="叶惠美")

    def test_fetch_numeric_writes_lrc(self):
        src = NeteaseSource(cookie="")
        payload = _lyric_payload("[00:01.00]晴天的歌词", "[00:01.00]Sunny day")
        with patch.object(src, "fetch_lyric", return_value={"lrc": payload["lrc"]["lyric"],
                                                            "tlyric": payload["tlyric"]["lyric"]}):
            path, status, reason = lyrics_mod.fetch_track_lyric(self._track(), self.tmp, src)
        self.assertEqual(status, "ok")
        self.assertEqual(reason, "")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(path.endswith("周杰伦 - 晴天.lrc"))
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("晴天的歌词 / Sunny day", content)

    def test_fetch_empty_lyric_marks_no_lyric(self):
        src = NeteaseSource(cookie="")
        with patch.object(src, "fetch_lyric", return_value={"lrc": "", "tlyric": ""}):
            _path, status, reason = lyrics_mod.fetch_track_lyric(self._track(), self.tmp, src)
        self.assertEqual(status, "failed")
        self.assertEqual(reason, "no_lyric")

    def test_fetch_ext_track_searches_match(self):
        t = Track(song_id="ext:jay_晴天", title="晴天", artist="周杰伦")
        src = NeteaseSource(cookie="")
        matched = Track(song_id="347230", title="晴天", artist="周杰伦")
        with patch.object(src, "search_tracks", return_value=[matched]), \
             patch.object(src, "fetch_lyric", return_value={"lrc": "[00:01.00]词", "tlyric": ""}):
            path, status, _ = lyrics_mod.fetch_track_lyric(t, self.tmp, src)
        self.assertEqual(status, "ok")
        self.assertTrue(os.path.isfile(path))

    def test_fetch_ext_track_no_match(self):
        t = Track(song_id="ext:jay_xxx", title="夜雨", artist="周杰伦")
        src = NeteaseSource(cookie="")
        other = Track(song_id="9", title=" completely different", artist="其他人")
        with patch.object(src, "search_tracks", return_value=[other]):
            _path, status, reason = lyrics_mod.fetch_track_lyric(t, self.tmp, src)
        self.assertEqual(status, "failed")
        self.assertEqual(reason, "not_found")

    def test_ext_fallback_relaxed_after_empty(self):
        # 严格候选（同名歌手）无歌词 → 继续尝试宽松候选（繁体歌手名的正版）
        t = Track(song_id="ext:demo3", title="Lemon", artist="米津玄师")
        src = NeteaseSource(cookie="")
        strict_hit = Track(song_id="100", title="Lemon（Live）", artist="米津玄师")
        canon = Track(song_id="200", title="Lemon", artist="米津玄師")

        def fake_fetch(song_id):
            return {"lrc": "" if song_id == "100" else "[00:01.00]词", "tlyric": ""}

        with patch.object(src, "search_tracks", return_value=[strict_hit, canon]), \
             patch.object(src, "fetch_lyric", side_effect=fake_fetch):
            path, status, reason = lyrics_mod.fetch_track_lyric(t, self.tmp, src)
        self.assertEqual(status, "ok")
        self.assertTrue(os.path.isfile(path))

    def test_existing_lrc_is_idempotent(self):
        src = NeteaseSource(cookie="")
        existing = os.path.join(self.tmp, "周杰伦 - 晴天.lrc")
        open(existing, "w", encoding="utf-8").write("old")
        with patch.object(src, "fetch_lyric") as m:
            path, status, _ = lyrics_mod.fetch_track_lyric(self._track(), self.tmp, src)
        m.assert_not_called()
        self.assertEqual(status, "ok")
        self.assertEqual(path, existing)


class TestFetchLyricsNode(TmpDirTestCase):
    def _state(self, results, lyrics_enabled=True):
        return {"singer": "周杰伦", "artist": "周杰伦", "out_dir": self.tmp,
                "tracks": [{"song_id": "1", "title": "晴天", "artist": "周杰伦",
                            "album": "", "duration_ms": 0, "artist_id": ""}],
                "results": results, "messages": [], "lyrics_enabled": lyrics_enabled}

    def test_node_fetches_for_ok_only(self):
        from dataclasses import asdict
        from music_agent.models import DownloadResult
        results = {"1": asdict(DownloadResult(track_id="1", status="ok",
                                               path=os.path.join(self.tmp, "a.mp3"),
                                               title="晴天", artist="周杰伦"))}
        with patch("music_agent.lyrics.NeteaseSource") as MS:
            MS.return_value.fetch_lyric.return_value = {"lrc": "[00:01.00]词", "tlyric": ""}
            out = fetch_lyrics_node.run(self._state(results))
        r = out["results"]["1"]
        self.assertEqual(r["lyric_status"], "ok")
        self.assertTrue(r["lyric_path"].endswith(".lrc"))
        self.assertEqual(r["lyric_source"], "netease")

    def test_node_skips_failed_audio(self):
        from dataclasses import asdict
        from music_agent.models import DownloadResult
        results = {"1": asdict(DownloadResult(track_id="1", status="failed", fail_reason="no_source"))}
        out = fetch_lyrics_node.run(self._state(results))
        self.assertEqual(out["results"]["1"]["lyric_status"], "")

    def test_node_disabled(self):
        from dataclasses import asdict
        from music_agent.models import DownloadResult
        results = {"1": asdict(DownloadResult(track_id="1", status="ok"))}
        out = fetch_lyrics_node.run(self._state(results, lyrics_enabled=False))
        self.assertIn("禁用", out["messages"][0])

    def test_node_dry_run(self):
        state = self._state({})
        state["dry_run"] = True
        out = fetch_lyrics_node.run(state)
        self.assertIn("dry-run", out["messages"][0])


if __name__ == "__main__":
    unittest.main()
