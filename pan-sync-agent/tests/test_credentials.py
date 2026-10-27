import os
import sys
import tempfile
import unittest

from pan_sync.credentials import load_cookies, save_cookies


@unittest.skipUnless(sys.platform == "win32", "DPAPI 仅 Windows 可用")
class CredentialsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "data")

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_cookies("baidu", self.data_dir))

    def test_save_then_load_roundtrip(self):
        cookies = {"BDUSS": "abc-secret", "STOKEN": "xyz"}
        save_cookies("baidu", cookies, self.data_dir)
        self.assertEqual(load_cookies("baidu", self.data_dir), cookies)

    def test_file_is_not_plaintext(self):
        cookies = {"__puus": "quark-secret-value"}
        save_cookies("quark", cookies, self.data_dir)
        path = os.path.join(self.data_dir, "cookies.quark.enc")
        with open(path, "rb") as f:
            blob = f.read()
        self.assertNotIn(b"quark-secret-value", blob)

    def test_drives_use_separate_files(self):
        save_cookies("baidu", {"BDUSS": "b"}, self.data_dir)
        save_cookies("quark", {"__puus": "q"}, self.data_dir)
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "cookies.baidu.enc")))
        self.assertTrue(os.path.exists(os.path.join(self.data_dir, "cookies.quark.enc")))


if __name__ == "__main__":
    unittest.main()
