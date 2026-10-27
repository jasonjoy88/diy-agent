import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from tests._base import TmpDirTestCase

from music_agent.models import Track
from music_agent.sources.ytdlp_source import (
    YtdlpSource,
    _cookie_header_to_netscape,
    _looks_like_cookie_header,
    _parse_cookies_from_browser,
    resolve_cookiefile,
)


class TestYtdlp(TmpDirTestCase):
    def test_search_query_format(self):
        t = Track(song_id="1", title="晴天", artist="周杰伦")
        self.assertEqual(YtdlpSource().search_query(t), "周杰伦 晴天")

    def test_fetch_failure_when_no_module(self):
        src = YtdlpSource()
        t = Track(song_id="1", title="晴天", artist="周杰伦")
        with patch.dict(sys.modules, {"yt_dlp": None}):
            r = src.fetch(t, self.tmp)
        self.assertEqual(r.status, "failed")
        self.assertIn("not_installed", r.fail_reason)

    def test_parse_cookies_from_browser(self):
        self.assertIsNone(_parse_cookies_from_browser(""))
        self.assertEqual(_parse_cookies_from_browser("chrome"), ("chrome",))
        self.assertEqual(
            _parse_cookies_from_browser("chrome:Default"),
            ("chrome", None, "Default"),
        )

    def test_build_opts_headers_and_cookiefile(self):
        cookie = os.path.join(self.tmp, "cookies.txt")
        with open(cookie, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
        src = YtdlpSource(cookie_file=cookie, sleep_interval=2, sleep_requests=1)
        opts = src.build_opts(os.path.join(self.tmp, "%(ext)s"))
        self.assertEqual(opts["http_headers"]["Referer"], "https://www.bilibili.com")
        self.assertEqual(opts["cookiefile"], cookie)
        self.assertNotIn("cookiesfrombrowser", opts)
        self.assertGreaterEqual(opts["retries"], 3)
        self.assertIn("bilibili", opts["extractor_args"])

    def test_build_opts_cookies_from_browser_when_no_file(self):
        src = YtdlpSource(cookies_from_browser="edge")
        opts = src.build_opts(os.path.join(self.tmp, "%(ext)s"))
        self.assertEqual(opts["cookiesfrombrowser"], ("edge",))

    def test_cookie_header_detected_and_converted(self):
        header = "buvid3=x; SESSDATA=abc; bili_jct=def; DedeUserID=1"
        self.assertTrue(_looks_like_cookie_header(header))
        ns = _cookie_header_to_netscape(header)
        self.assertIn("# Netscape HTTP Cookie File", ns)
        self.assertIn("\tSESSDATA\t", ns)
        path = os.path.join(self.tmp, "header_cookies.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
        resolved = resolve_cookiefile(path)
        self.assertIsNotNone(resolved)
        self.assertNotEqual(resolved, path)
        with open(resolved, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("SESSDATA", text)
        os.remove(resolved)

    def test_fetch_uses_wbi_then_bv_url(self):
        fake_yt = MagicMock()
        t = Track(song_id="1", title="高山低谷", artist="林奕匡")
        src = YtdlpSource(sleep_interval=0, sleep_requests=0)
        hits = [{"bvid": "BV1xx", "title": "高山低谷", "url": "https://www.bilibili.com/video/BV1xx"}]
        with patch("music_agent.sources.ytdlp_source._import_ytdlp", return_value=fake_yt), \
             patch("music_agent.sources.ytdlp_source.bilibili_wbi_search", return_value=hits), \
             patch.object(src, "_download_url") as dl:
            def _write(_yt, _url, opts):
                out = opts["outtmpl"].replace("%(ext)s", "m4a")
                open(out, "wb").write(b"audio")
            dl.side_effect = _write
            r = src.fetch(t, self.tmp)
        self.assertEqual(r.status, "ok")
        dl.assert_called_once()
        self.assertIn("BV1xx", dl.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
