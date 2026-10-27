import hashlib
import json
import unittest
from email.message import Message

from pan_sync import quark_open
from pan_sync.errors import AuthError, UploadError

FIXED_TM = "1700000000000"
INFO_PATH = "/open/v1/user/info"


def make_envelope(data=None, status=0, errno=None, error_info=None):
    return {
        "status": status,
        "errno": errno,
        "error_info": error_info,
        "data": data,
    }


def http_ok(payload, headers=None):
    return 200, headers or Message(), payload


class RecordingHttp:
    """记录入参的假 http，默认返回成功空 data。"""

    def __init__(self, respond=None):
        self.calls = []
        self.respond = respond

    def __call__(self, method, url, headers=None, data=None, timeout=30):
        self.calls.append({
            "method": method, "url": url,
            "headers": headers, "data": data,
        })
        if self.respond is not None:
            return self.respond(method, url, headers, data)
        return http_ok(json.dumps(make_envelope(data={})).encode())


class PanTokenTest(unittest.TestCase):
    def test_known_vector(self):
        raw = f"GET&{INFO_PATH}&{FIXED_TM}&{quark_open.SIGN_KEY}"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(
            quark_open.pan_token("GET", INFO_PATH, FIXED_TM), expected
        )

    def test_shape_and_method_uppercased_by_caller(self):
        token = quark_open.pan_token("POST", "/open/v1/dir", FIXED_TM)
        self.assertRegex(token, r"^[0-9a-f]{64}$")


class SignedRequestTest(unittest.TestCase):
    def test_success_attaches_signing_headers_and_returns_data(self):
        http = RecordingHttp()
        data = quark_open.signed_request(
            "GET", INFO_PATH,
            access_token="AT", device_id="dev123",
            http=http, current_ms=int(FIXED_TM),
            uuid_factory=lambda: "uuid-1",
        )
        self.assertEqual(data, {})
        call = http.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertTrue(call["url"].startswith(
            f"{quark_open.OPEN_BASE}{INFO_PATH}?"
        ))
        self.assertIn("req_id=uuid-1", call["url"])
        self.assertIn("access_token=AT", call["url"])
        self.assertIn("device_id=dev123", call["url"])
        headers = call["headers"]
        self.assertEqual(headers["x-pan-client-id"], quark_open.CLIENT_ID)
        self.assertEqual(headers["x-pan-tm"], FIXED_TM)
        self.assertEqual(
            headers["x-pan-token"],
            quark_open.pan_token("GET", INFO_PATH, FIXED_TM),
        )
        self.assertIsNone(call["data"])

    def test_no_access_token_omits_query_field(self):
        http = RecordingHttp()
        quark_open.signed_request(
            "GET", INFO_PATH, http=http,
            uuid_factory=lambda: "u", current_ms=1,
        )
        self.assertNotIn("access_token", http.calls[0]["url"])

    def test_extra_params_included(self):
        http = RecordingHttp()
        quark_open.signed_request(
            "GET", "/agent/v1/oauth/get_aac_by_pagecode",
            params={"page_code": "PC"}, http=http,
            uuid_factory=lambda: "u", current_ms=1,
        )
        self.assertIn("page_code=PC", http.calls[0]["url"])

    def test_json_body_encoded(self):
        http = RecordingHttp()
        quark_open.signed_request(
            "POST", "/open/v1/dir", body={"dir_path": "/a", "pdir_fid": "0"},
            http=http, uuid_factory=lambda: "u", current_ms=1,
        )
        self.assertEqual(
            json.loads(http.calls[0]["data"].decode()),
            {"dir_path": "/a", "pdir_fid": "0"},
        )

    def test_non_json_raises_upload_error(self):
        http = RecordingHttp(respond=lambda *a: http_ok(b"not-json"))
        with self.assertRaises(UploadError):
            quark_open.signed_request("GET", INFO_PATH, http=http)

    def test_auth_errnos_raise_auth_error(self):
        for errno in quark_open._AUTH_ERRNOS:
            body = json.dumps(
                make_envelope(errno=errno, status=errno, error_info="bad token")
            ).encode()
            http = RecordingHttp(respond=lambda *a, b=body: http_ok(b))
            with self.assertRaises(AuthError):
                quark_open.signed_request("GET", INFO_PATH, http=http)

    def test_other_errno_raises_upload_error(self):
        body = json.dumps(
            make_envelope(errno=32003, status=32003, error_info="full")
        ).encode()
        http = RecordingHttp(respond=lambda *a: http_ok(body))
        with self.assertRaises(UploadError):
            quark_open.signed_request("GET", INFO_PATH, http=http)


class OAuthFlowTest(unittest.TestCase):
    def test_start_authorization_returns_tuple(self):
        captured = {}

        def fake_request(method, path, body=None, **kwargs):
            captured["body"] = body
            return {
                "authorize_page_url": "https://pan.quark.cn/auth?x=1",
                "page_code": "PAGE",
                "device_id": "SRVDEV",
            }

        url, page_code, device_id = quark_open.start_authorization(
            device_name="mypc", work_dir="/", http=fake_request,
        )
        self.assertEqual(url, "https://pan.quark.cn/auth?x=1")
        self.assertEqual(page_code, "PAGE")
        self.assertEqual(device_id, "SRVDEV")
        self.assertEqual(captured["body"]["client_id"], quark_open.CLIENT_ID)

    def test_start_authorization_device_fallback(self):
        def fake_request(method, path, body=None, **kwargs):
            return {
                "authorize_page_url": "u", "page_code": "p",
            }

        _url, _pc, device_id = quark_open.start_authorization(
            client_device_id="wild_claw", http=fake_request,
        )
        self.assertEqual(device_id, "wild_claw")

    def test_poll_auth_code_done_and_pending(self):
        done = {"status": 1, "agent_auth_code": "CODE"}
        pending = {"status": 0, "agent_auth_code": ""}

        self.assertEqual(
            quark_open.poll_auth_code(
                "P", http=lambda *a, d=done: http_ok(
                    json.dumps(make_envelope(data=d)).encode()
                ),
            ),
            "CODE",
        )
        self.assertIsNone(
            quark_open.poll_auth_code(
                "P", http=lambda *a: http_ok(
                    json.dumps(make_envelope(data=pending)).encode()
                ),
            )
        )

    def test_exchange_auth_code_returns_token_data(self):
        token = {"access_token": "AT", "refresh_token": "RT", "device_id": "d"}

        result = quark_open.exchange_auth_code(
            "CODE", http=lambda *a: http_ok(
                json.dumps(make_envelope(data=token)).encode()
            ),
        )
        self.assertEqual(result["access_token"], "AT")

    def test_rotate_token_posts_refresh(self):
        captured = {}

        def fake_request(method, path, body=None, **kwargs):
            captured["body"] = body
            return {"access_token": "NEW", "device_id": "d"}

        result = quark_open.rotate_token("RT", "d", http=fake_request)
        self.assertEqual(result["access_token"], "NEW")
        self.assertEqual(captured["body"],
                         {"refresh_token": "RT", "device_id": "d"})


class TokenValidityTest(unittest.TestCase):
    def test_missing_or_empty(self):
        self.assertFalse(quark_open.token_valid(None))
        self.assertFalse(quark_open.token_valid({}))
        self.assertFalse(quark_open.token_valid({"access_token": ""}))

    def test_no_expiry_assumed_valid(self):
        self.assertTrue(quark_open.token_valid({"access_token": "AT"}))

    def test_expiry_boundary(self):
        future = {"access_token": "AT", "access_token_expires_at": 2000}
        self.assertTrue(quark_open.token_valid(future, current_ms=1000))
        # 剩余不足 skew → 需刷新
        self.assertFalse(
            quark_open.token_valid(future, current_ms=1000, skew=500)
        )
        self.assertFalse(
            quark_open.token_valid(
                {"access_token": "AT", "access_token_expires_at": 100},
                current_ms=1000,
            )
        )


class EnsureFreshTokenTest(unittest.TestCase):
    def test_valid_returned_without_network(self):
        token = {"access_token": "AT", "access_token_expires_at": 9_000_000_000_000}
        http = RecordingHttp()
        result = quark_open.ensure_fresh_token(token, http=http)
        self.assertIs(result, token)
        self.assertEqual(http.calls, [])

    def test_expired_refreshed(self):
        token = {
            "access_token": "OLD", "refresh_token": "RT",
            "device_id": "d", "access_token_expires_at": 1,
        }

        def fake_request(method, path, body=None, **kwargs):
            return {"access_token": "NEW", "device_id": "d"}

        result = quark_open.ensure_fresh_token(token, http=fake_request)
        self.assertEqual(result["access_token"], "NEW")

    def test_expired_without_refresh_credentials_raises(self):
        with self.assertRaises(AuthError):
            quark_open.ensure_fresh_token(
                {"access_token": "X", "access_token_expires_at": 1,
                 "device_id": "d"}
            )
        with self.assertRaises(AuthError):
            quark_open.ensure_fresh_token(
                {"access_token": "X", "access_token_expires_at": 1,
                 "refresh_token": "RT"}
            )


if __name__ == "__main__":
    unittest.main()
