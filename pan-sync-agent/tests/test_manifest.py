import os
import tempfile
import unittest

from pan_sync.manifest import (
    MANIFEST_FILENAME,
    append_entry,
    latest_by_relpath,
    load_entries,
    make_entry,
)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_filename(self):
        self.assertEqual(MANIFEST_FILENAME, ".uploaded.json")

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_entries(self.dir), [])

    def test_append_then_load(self):
        entry = make_entry("a/b.txt", 10, 1000.0, "md5x", "/pan-sync/a/b.txt", "uploaded")
        append_entry(self.dir, entry)
        loaded = load_entries(self.dir)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].rel_path, "a/b.txt")
        self.assertEqual(loaded[0].status, "uploaded")
        self.assertEqual(loaded[0].remote_path, "/pan-sync/a/b.txt")
        self.assertIsNone(loaded[0].fail_reason)

    def test_append_is_additive(self):
        append_entry(self.dir, make_entry("a", 1, 1.0, "m1", "/r/a", "failed", "net"))
        append_entry(self.dir, make_entry("a", 1, 2.0, "m2", "/r/a", "uploaded"))
        self.assertEqual(len(load_entries(self.dir)), 2)

    def test_latest_by_relpath_keeps_last(self):
        append_entry(self.dir, make_entry("a", 1, 1.0, "m1", "/r/a", "failed", "net"))
        append_entry(self.dir, make_entry("a", 1, 2.0, "m2", "/r/a", "uploaded"))
        latest = latest_by_relpath(load_entries(self.dir))
        self.assertEqual(set(latest), {"a"})
        self.assertEqual(latest["a"].status, "uploaded")
        self.assertEqual(latest["a"].md5, "m2")

    def test_no_tmp_file_left(self):
        append_entry(self.dir, make_entry("a", 1, 1.0, "m", "/r/a", "conflict", "remote exists"))
        self.assertEqual(sorted(os.listdir(self.dir)), [".uploaded.json"])


if __name__ == "__main__":
    unittest.main()
