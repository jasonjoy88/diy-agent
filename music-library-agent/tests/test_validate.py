import os
import unittest

from tests._base import TmpDirTestCase

from music_agent import validate


class TestValidate(TmpDirTestCase):
    def test_reject_missing(self):
        ok, reason = validate.check_file(os.path.join(self.tmp, "none.mp3"), 0)
        self.assertFalse(ok)
        self.assertEqual(reason, "missing")

    def test_reject_too_small(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x" * 1000)
        ok, reason = validate.check_file(p, 0)
        self.assertFalse(ok)
        self.assertEqual(reason, "too_small")

    def test_accept_large_enough(self):
        p = os.path.join(self.tmp, "a.mp3")
        open(p, "wb").write(b"x" * 200000)
        ok, reason = validate.check_file(p, 0)
        self.assertTrue(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
