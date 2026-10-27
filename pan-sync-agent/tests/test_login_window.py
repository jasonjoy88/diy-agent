import time
import unittest
from http.cookies import SimpleCookie

from pan_sync.errors import PanSyncError
from pan_sync.login_window import (
    LOGIN_URLS,
    _cookies_to_dict,
    cookies_ready,
    interactive_login,
    quark_poll,
)


class FakeWindow:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class LoginWindowBasicTest(unittest.TestCase):
    def test_login_urls(self):
        self.assertEqual(LOGIN_URLS["baidu"], "https://pan.baidu.com")

    def test_baidu_requires_bduss(self):
        self.assertFalse(cookies_ready("baidu", {"STOKEN": "s"}))
        self.assertTrue(cookies_ready("baidu", {"BDUSS": "b", "STOKEN": "s"}))


class CookiesToDictTest(unittest.TestCase):
    """pywebview get_cookies() 可能返回 SimpleCookie 或 name/value 对象。"""

    def test_simple_cookie_items(self):
        sc = SimpleCookie()
        sc["BDUSS"] = "secret-value"
        sc["STOKEN"] = "s"
        self.assertEqual(
            _cookies_to_dict([sc]), {"BDUSS": "secret-value", "STOKEN": "s"}
        )

    def test_name_value_objects(self):
        class Cookie:
            def __init__(self, name, value):
                self.name = name
                self.value = value

        result = _cookies_to_dict([Cookie("a", "1"), Cookie("b", "2")])
        self.assertEqual(result, {"a": "1", "b": "2"})

    def test_empty_and_none(self):
        self.assertEqual(_cookies_to_dict([]), {})
        self.assertEqual(_cookies_to_dict(None), {})

    def test_mixed_items(self):
        sc = SimpleCookie()
        sc["BDUSS"] = "u"

        class Cookie:
            name = "STOKEN"
            value = "p"

        result = _cookies_to_dict([sc, Cookie()])
        self.assertEqual(result, {"BDUSS": "u", "STOKEN": "p"})


class QuarkPollTest(unittest.TestCase):
    def _run(self, poll_code, exchange=lambda c: {"access_token": "AT"},
             deadline=None, sleep=lambda s: None):
        window = FakeWindow()
        holder = {}
        quark_poll(
            window, "PAGE", holder,
            deadline if deadline is not None else time.time() + 100,
            1.0, poll_code, exchange, sleep, print,
        )
        return window, holder

    def test_success_sets_token_and_closes(self):
        window, holder = self._run(lambda pc: "CODE")
        self.assertEqual(holder["token"], {"access_token": "AT"})
        self.assertTrue(window.destroyed)

    def test_pending_then_done(self):
        state = {"n": 0}

        def poll_code(pc):
            state["n"] += 1
            return "CODE" if state["n"] >= 3 else None

        window, holder = self._run(poll_code)
        self.assertEqual(holder["token"], {"access_token": "AT"})
        self.assertTrue(window.destroyed)

    def test_transient_oserror_ignored(self):
        state = {"n": 0}

        def poll_code(pc):
            state["n"] += 1
            if state["n"] == 1:
                raise ConnectionError("net blip")
            return "CODE"

        _window, holder = self._run(poll_code)
        self.assertIn("token", holder)

    def test_deadline_passed_leaves_holder_empty(self):
        window, holder = self._run(
            lambda pc: "CODE", deadline=time.time() - 1
        )
        self.assertEqual(holder, {})
        self.assertFalse(window.destroyed)


class QuarkInteractiveDispatchTest(unittest.TestCase):
    def test_quark_login_uses_authorize_url_and_returns_token(self):
        class FakeWebview:
            def __init__(self):
                self.window = None

            def create_window(self, title, url, **kwargs):
                self.window = FakeWindow()
                self.window.url = url
                return self.window

            def start(self, func):
                func()

        wv = FakeWebview()
        token = interactive_login(
            "quark",
            start_auth=lambda: ("https://pan.quark.cn/AUTH", "PAGE", "dev"),
            poll_code=lambda pc: "CODE",
            exchange=lambda c: {"access_token": "AT"},
            sleep=lambda s: None,
            webview_module=wv,
        )
        self.assertEqual(token, {"access_token": "AT"})
        self.assertEqual(wv.window.url, "https://pan.quark.cn/AUTH")

    def test_unsupported_drive_raises(self):
        with self.assertRaises(PanSyncError):
            interactive_login("onedrive")


if __name__ == "__main__":
    unittest.main()
