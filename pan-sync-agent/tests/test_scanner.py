import hashlib
import os
import tempfile
import time
import unittest

from pan_sync.scanner import (
    is_stable,
    iter_files,
    iter_manifest_dirs,
    md5_of_file,
)


class ScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, rel, content=b"x"):
        path = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_iter_files_relpaths_sorted(self):
        self._touch("b.txt", b"b")
        self._touch("a/c.txt", b"c")
        found = [rel for _, rel in iter_files(self.root)]
        self.assertEqual(found, ["b.txt", "a/c.txt"])

    def test_manifest_files_skipped(self):
        self._touch("a/.uploaded.json", b"{}")
        self._touch("a/real.txt", b"r")
        found = [rel for _, rel in iter_files(self.root)]
        self.assertEqual(found, ["a/real.txt"])

    def test_md5_of_file(self):
        path = self._touch("f.bin", b"hello")
        self.assertEqual(md5_of_file(path), hashlib.md5(b"hello").hexdigest())

    def test_is_stable(self):
        path = self._touch("new.txt", b"n")
        st_mtime = os.stat(path).st_mtime
        self.assertFalse(is_stable(path, 60, now=st_mtime + 10))
        self.assertTrue(is_stable(path, 60, now=st_mtime + 60))
        self.assertTrue(is_stable(path, 60, now=st_mtime + 600))

    def test_iter_manifest_dirs(self):
        self._touch("a/.uploaded.json", b"{}")
        self._touch("a/b/.uploaded.json", b"{}")
        self._touch("a/b/keep.txt", b"k")
        dirs = sorted(os.path.relpath(d, self.root) for d in iter_manifest_dirs(self.root))
        self.assertEqual(dirs, [os.path.join("a"), os.path.join("a", "b")])


if __name__ == "__main__":
    unittest.main()
