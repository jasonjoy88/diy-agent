import json
import os
import tempfile
import unittest
from email.message import Message
from unittest.mock import patch

from pan_sync.errors import AuthError, UploadError
from pan_sync.uploader.baidu import BaiduUploader


def _resp(status, payload):
    return status, Message(), json.dumps(payload).encode()


class BaiduUploaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _uploader(self, chunk=4 * 1024 * 1024):
        return BaiduUploader({"BDUSS": "b"}, chunk, log=lambda *_: None)

    def _fake_http(self, mapping):
        def fake(method, url, headers=None, data=None, timeout=30):
            self.calls.append((method, url))
            for key, response in mapping:
                if key in url:
                    return response
            raise AssertionError(f"未配置的 URL：{url}")
        return fake

    def _file(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_check_cookies_valid(self):
        mapping = [("/api/list", _resp(200, {"errno": 0, "list": []}))]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            self.assertTrue(self._uploader().check_cookies_valid())

    def test_check_cookies_invalid(self):
        mapping = [("/api/list", _resp(200, {"errno": -6}))]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            self.assertFalse(self._uploader().check_cookies_valid())

    def test_exists_finds_file(self):
        mapping = [("/api/list", _resp(200, {"errno": 0, "list": [
            {"server_filename": "a.txt", "isdir": 0},
            {"server_filename": "sub", "isdir": 1},
        ]}))]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            up = self._uploader()
            self.assertTrue(up.exists("/pan-sync/a.txt"))
        mapping = [("/api/list", _resp(200, {"errno": 0, "list": []}))]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            self.assertFalse(self._uploader().exists("/pan-sync/missing.txt"))

    def test_upload_single_block_flow(self):
        path = self._file("a.txt", b"hello")
        mapping = [
            ("/api/list", _resp(200, {"errno": 0, "list": []})),
            ("/api/precreate", _resp(200, {"errno": 0, "uploadid": "uid-1"})),
            ("superfile2", _resp(200, {"error_code": 0})),
            ("/api/create", _resp(200, {"errno": 0})),
        ]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            self._uploader().upload(path, "/pan-sync/a.txt")
        urls = [u for _, u in self.calls]
        self.assertEqual(len(urls), 4)
        self.assertIn("/api/precreate?app_id=250528", urls[1])
        self.assertTrue(urls[2].startswith("https://d.pcs.baidu.com/rest/2.0/pcs/superfile2"))
        self.assertIn("partseq=0", urls[2])
        self.assertIn("/api/create?app_id=250528", urls[3])

    def test_upload_multi_block(self):
        path = self._file("a.bin", b"x" * 9)
        mapping = [
            ("/api/list", _resp(200, {"errno": 0, "list": []})),
            ("/api/precreate", _resp(200, {"errno": 0, "uploadid": "uid-2"})),
            ("superfile2", _resp(200, {"error_code": 0})),
            ("/api/create", _resp(200, {"errno": 0})),
        ]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            self._uploader(chunk=4).upload(path, "/pan-sync/a.bin")
        superfile_urls = [u for _, u in self.calls if "superfile2" in u]
        self.assertEqual(len(superfile_urls), 3)
        self.assertTrue(any("partseq=0" in u for u in superfile_urls))
        self.assertTrue(any("partseq=2" in u for u in superfile_urls))

    def test_precreate_error_raises(self):
        path = self._file("a.txt", b"hello")
        mapping = [
            ("/api/list", _resp(200, {"errno": 0, "list": []})),
            ("/api/precreate", _resp(200, {"errno": 31034})),
        ]
        with patch("pan_sync.uploader.baidu.http_request", side_effect=self._fake_http(mapping)):
            with self.assertRaises(UploadError):
                self._uploader().upload(path, "/pan-sync/a.txt")

    def test_ensure_dir_creates_missing(self):
        list_empty = _resp(200, {"errno": 0, "list": []})
        create_ok = _resp(200, {"errno": 0})
        responses = iter([list_empty, create_ok, list_empty, create_ok])
        def fake_http(method, url, headers=None, data=None, timeout=30):
            self.calls.append((method, url))
            return next(responses)

        with patch("pan_sync.uploader.baidu.http_request",
                   side_effect=fake_http):
            self._uploader().ensure_dir("/pan-sync/deep")
        urls = [u for _, u in self.calls]
        self.assertEqual(sum("/api/create?app_id=250528" in u for u in urls), 2)


if __name__ == "__main__":
    unittest.main()
