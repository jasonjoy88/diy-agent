import os
import tempfile
import unittest
from email.message import Message
from unittest.mock import patch

from pan_sync.errors import AuthError, UploadError
from pan_sync.uploader.quark import (
    QuarkUploader,
    _hash_file,
    _part_size,
    _plan_parts,
)

TOKEN = {"access_token": "AT", "refresh_token": "RT", "device_id": "dev"}


class FakeApi:
    """开放平台业务接口的假 request：按 path 分派。"""

    def __init__(self, handlers):
        self.calls = []
        self.handlers = handlers

    def __call__(self, method, path, body=None, params=None,
                 access_token=None, device_id=None):
        self.calls.append((method, path, body, params))
        if path not in self.handlers:
            raise AssertionError(f"未配置的 path：{path}")
        return self.handlers[path](method, body)

    def paths(self):
        return [p for _m, p, _b, _q in self.calls]


def etag_response(value='"etag"', status=200):
    msg = Message()
    msg["ETag"] = value
    return status, msg, b""


class PlanPartsTest(unittest.TestCase):
    def test_part_size_last_part_smaller(self):
        self.assertEqual(_part_size(1, 9, 4), 4)
        self.assertEqual(_part_size(2, 9, 4), 4)
        self.assertEqual(_part_size(3, 9, 4), 1)
        self.assertEqual(_part_size(4, 9, 4), 0)

    def test_plan_parts(self):
        self.assertEqual(
            _plan_parts(9, 4),
            [
                {"part_number": 1, "part_size": 4},
                {"part_number": 2, "part_size": 4},
                {"part_number": 3, "part_size": 1},
            ],
        )
        self.assertEqual(
            _plan_parts(4, 1024), [{"part_number": 1, "part_size": 4}]
        )


class QuarkUploaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.puts = []

    def tearDown(self):
        self.tmp.cleanup()

    def _file(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def _uploader(self, api, chunk=1024):
        return QuarkUploader(dict(TOKEN), chunk, log=lambda *_: None, request=api)

    def _patch_put(self, respond=None):
        def fake_http(method, url, headers=None, data=None, timeout=30):
            self.puts.append((url, headers, data))
            if respond is not None:
                return respond(url, headers, data)
            return etag_response()

        return patch("pan_sync.uploader.quark.http_request", side_effect=fake_http)

    # ── 有效性 ───────────────────────────────────────────────
    def test_check_valid(self):
        api = FakeApi({"/open/v1/user/info": lambda m, b: {}})
        self.assertTrue(self._uploader(api).check_cookies_valid())
        self.assertIn("/open/v1/user/info", api.paths())

    def test_check_invalid_on_auth_error(self):
        def fail(m, b):
            raise AuthError("expired")

        api = FakeApi({"/open/v1/user/info": fail})
        self.assertFalse(self._uploader(api).check_cookies_valid())

    # ── 目录 / exists ────────────────────────────────────────
    def test_ensure_root_and_nested_dir(self):
        api = FakeApi({"/open/v1/dir": lambda m, b: {"fid": "fA"}})
        up = self._uploader(api)
        self.assertEqual(up.ensure_dir("/"), "0")
        self.assertEqual(up.ensure_dir("/pan-sync/sub"), "fA")
        # 第二次走缓存，不再请求
        before = len(api.calls)
        self.assertEqual(up.ensure_dir("/pan-sync/sub"), "fA")
        self.assertEqual(len(api.calls), before)

    def test_exists_true_and_false(self):
        def sort_handler(m, b):
            return {"list": [
                {"filename": "a.txt", "file_type": 1},
                {"filename": "folder", "file_type": 0},
            ]}

        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/sort": sort_handler,
        })
        up = self._uploader(api)
        self.assertTrue(up.exists("/pan-sync/a.txt"))
        self.assertFalse(up.exists("/pan-sync/b.txt"))

    # ── 上传：秒传 ───────────────────────────────────────────
    def test_instant_upload_finishes_without_put(self):
        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/upload_pre": lambda m, b: {"finish": 1, "fid": "F"},
        })
        path = self._file("a.txt", b"hello")
        with self._patch_put():
            self._uploader(api).upload(path, "/pan-sync/a.txt")
        self.assertEqual(self.puts, [])
        self.assertNotIn("/open/v1/file/get_upload_urls", api.paths())
        self.assertNotIn("/open/v1/file/upload_finish", api.paths())

    # ── 上传：单片 ───────────────────────────────────────────
    def test_single_part_upload_signs_put_and_finishes(self):
        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/upload_pre": lambda m, b: {
                "finish": 0, "task_id": "T", "part_size": 1024},
            "/open/v1/file/get_upload_urls": lambda m, b: {"upload_urls": [{
                "part_number": 1, "upload_url": "https://oss/u1",
                "signature_info": {"signature": "SIG1"}}]},
            "/open/v1/file/upload_finish": lambda m, b: {},
        })
        path = self._file("a.txt", b"hello")
        with self._patch_put():
            self._uploader(api).upload(path, "/pan-sync/a.txt")

        self.assertEqual(len(self.puts), 1)
        url, headers, data = self.puts[0]
        self.assertEqual(url, "https://oss/u1")
        self.assertEqual(headers["Authorization"], "SIG1")
        self.assertEqual(data, b"hello")
        # finish 携带去引号的 etag
        finish_body = api.calls[-1][2]
        self.assertEqual(
            finish_body["part_info_list"], [{"part_number": 1, "etag": "etag"}]
        )

    # ── 上传：多片 ───────────────────────────────────────────
    def test_multipart_upload_three_parts(self):
        counter = {"n": 0}

        def put_respond(url, headers, data):
            counter["n"] += 1
            return etag_response(f'"e{counter["n"]}"')

        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/upload_pre": lambda m, b: {
                "finish": 0, "task_id": "T", "part_size": 4},
            "/open/v1/file/get_upload_urls": lambda m, b: {"upload_urls": [
                {"part_number": i, "upload_url": f"https://oss/u{i}",
                 "signature_info": {"signature": f"SIG{i}"}}
                for i in (1, 2, 3)
            ]},
            "/open/v1/file/upload_finish": lambda m, b: {},
        })
        path = self._file("a.bin", b"x" * 9)
        with self._patch_put(respond=put_respond):
            self._uploader(api, chunk=4).upload(path, "/pan-sync/a.bin")

        self.assertEqual(len(self.puts), 3)
        self.assertEqual([d for _u, _h, d in self.puts],
                         [b"x" * 4, b"x" * 4, b"x"])
        self.assertEqual([h["Authorization"] for _u, h, _d in self.puts],
                         ["SIG1", "SIG2", "SIG3"])
        finish_body = api.calls[-1][2]
        self.assertEqual(
            finish_body["part_info_list"],
            [
                {"part_number": 1, "etag": "e1"},
                {"part_number": 2, "etag": "e2"},
                {"part_number": 3, "etag": "e3"},
            ],
        )

    # ── 异常 ────────────────────────────────────────────────
    def test_put_failure_raises_upload_error(self):
        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/upload_pre": lambda m, b: {
                "finish": 0, "task_id": "T", "part_size": 1024},
            "/open/v1/file/get_upload_urls": lambda m, b: {"upload_urls": [{
                "part_number": 1, "upload_url": "https://oss/u1",
                "signature_info": {"signature": "SIG"}}]},
        })
        path = self._file("a.txt", b"hello")
        with self._patch_put(respond=lambda *a: etag_response(status=403)):
            with self.assertRaises(UploadError):
                self._uploader(api).upload(path, "/pan-sync/a.txt")

    def test_auth_error_propagates_from_pre(self):
        def fail(m, b):
            raise AuthError("bad token")

        api = FakeApi({
            "/open/v1/dir": lambda m, b: {"fid": "p"},
            "/open/v1/file/upload_pre": fail,
        })
        path = self._file("a.txt", b"hello")
        with self._patch_put():
            with self.assertRaises(AuthError):
                self._uploader(api).upload(path, "/pan-sync/a.txt")

    def test_hash_file_computes_both(self):
        import hashlib

        path = self._file("b.bin", b"abc")
        sha1, md5 = _hash_file(path)
        self.assertEqual(sha1, hashlib.sha1(b"abc").hexdigest())
        self.assertEqual(md5, hashlib.md5(b"abc").hexdigest())


if __name__ == "__main__":
    unittest.main()
