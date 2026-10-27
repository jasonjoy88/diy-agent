import time
import unittest
from unittest.mock import patch

from pan_sync.errors import AuthError, UploadError
from pan_sync.uploader.base import (
    encode_multipart,
    format_cookie,
    http_request,
    retry,
)


class BaseTest(unittest.TestCase):
    def test_format_cookie(self):
        self.assertEqual(format_cookie({"a": "1", "b": "2"}), "a=1; b=2")

    def test_encode_multipart_shape(self):
        body, content_type = encode_multipart({"file": ("a.txt", b"abc")})
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b"name=\"file\"", body)
        self.assertIn(b"filename=\"a.txt\"", body)
        self.assertTrue(body.endswith(b"--\r\n"))

    @patch("pan_sync.uploader.base.urlopen")
    def test_http_request_returns_status_headers_body(self, mock_urlopen):
        from email.message import Message

        headers = Message()
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"ok"
        mock_urlopen.return_value.__enter__.return_value.headers = headers
        mock_urlopen.return_value.__enter__.return_value.status = 200
        status, resp_headers, body = http_request("GET", "https://x.test")
        self.assertEqual(status, 200)
        self.assertIs(resp_headers, headers)
        self.assertEqual(body, b"ok")

    def test_retry_succeeds_second_time(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise UploadError("boom")
            return "done"

        result = retry(flaky, attempts=3, base_delay=0, sleep=lambda _: None)
        self.assertEqual(result, "done")
        self.assertEqual(calls["n"], 2)

    def test_retry_gives_up_after_attempts(self):
        with self.assertRaises(UploadError):
            retry(lambda: (_ for _ in ()).throw(UploadError("x")),
                  attempts=3, base_delay=0, sleep=lambda _: None)

    def test_retry_does_not_retry_auth_error(self):
        calls = {"n": 0}

        def bad_auth():
            calls["n"] += 1
            raise AuthError("login required")

        with self.assertRaises(AuthError):
            retry(bad_auth, attempts=3, base_delay=0, sleep=lambda _: None)
        self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
