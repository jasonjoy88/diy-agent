import json
import os
import unittest

from tests._base import TmpDirTestCase

from music_agent import dedup


def _track(tid, title):
    return {"song_id": tid, "title": title, "artist": "周杰伦", "album": "", "duration_ms": 0}


def _write_uploaded(watch_artist_dir, entries):
    os.makedirs(watch_artist_dir, exist_ok=True)
    payload = {"version": 1, "entries": entries}
    with open(os.path.join(watch_artist_dir, ".uploaded.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class TestDedup(TmpDirTestCase):
    def test_local_downloaded_titles(self):
        open(os.path.join(self.tmp, "周杰伦 - 晴天.mp3"), "wb").write(b"x" * 200000)
        open(os.path.join(self.tmp, "周杰伦 - 稻香.m4a"), "wb").write(b"x" * 200000)
        titles = dedup.local_downloaded_titles(self.tmp)
        self.assertEqual(titles, {"晴天", "稻香"})

    def test_uploaded_titles_reads_manifest(self):
        watch = os.path.join(self.tmp, "watch")
        _write_uploaded(os.path.join(watch, "周杰伦"), [
            {"rel_path": "周杰伦/周杰伦 - 晴天.mp3", "size": 1, "mtime": 1, "md5": "x",
             "remote_path": "/pan-sync/周杰伦/周杰伦 - 晴天.mp3", "status": "uploaded", "recorded_at": "t"},
            {"rel_path": "周杰伦/周杰伦 - 失败歌.mp3", "size": 1, "mtime": 1, "md5": "x",
             "remote_path": "", "status": "failed", "recorded_at": "t"},  # failed 不计入
        ])
        titles = dedup.uploaded_titles(watch, "周杰伦")
        self.assertEqual(titles, {"晴天"})

    def test_filter_new_tracks(self):
        tracks = [_track("1", "晴天"), _track("2", "稻香"), _track("3", "新歌")]
        new, skipped = dedup.filter_new_tracks(tracks, {"晴天", "稻香"})
        self.assertEqual([t["title"] for t in new], ["新歌"])
        self.assertEqual(len(skipped), 2)

    def test_fill_to_target(self):
        tracks = [_track(str(i), f"歌{i}") for i in range(5)]
        new, skipped = dedup.fill_to_target(tracks, {"歌0", "歌1"}, target=3)
        self.assertEqual([t["title"] for t in new], ["歌2", "歌3", "歌4"][:3])
        self.assertEqual(len(new), 3)

    def test_fill_to_target_pool_exhausted(self):
        tracks = [_track(str(i), f"歌{i}") for i in range(2)]
        new, _ = dedup.fill_to_target(tracks, set(), target=5)
        self.assertEqual(len(new), 2)  # 候选不足则全取


if __name__ == "__main__":
    unittest.main()
