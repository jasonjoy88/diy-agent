"""本机夸克桌面客户端探测（localhost:9128）。

桌面端已登录时，授权页应走客户端打开，而不是孤立的 WebView2：
WebView 没有客户端 Cookie/会话，用户点授权后 page_code 轮询也拿不到 token。
"""

import json
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

LOCAL_APP = "http://127.0.0.1:9128"
_TIMEOUT = 3


def _get(path, timeout=_TIMEOUT):
    req = Request(
        LOCAL_APP + path,
        headers={"User-Agent": "pan-sync-agent", "Accept": "application/json"},
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def desktop_status():
    """返回 (running, logged_in)。客户端未开则 (False, False)。"""
    try:
        envelope = _get("/desktop_info")
    except (OSError, URLError):
        return False, False
    data = envelope.get("data") or {}
    return True, bool(data.get("isLogin"))


def open_in_desktop(url):
    """用桌面端打开 URL；成功返回 True。"""
    if not url:
        return False
    try:
        envelope = _get("/desktop_caller?deeplink=" + quote(url, safe=""), timeout=5)
    except (OSError, URLError):
        return False
    return bool(envelope.get("success")) or envelope.get("code") == "OK"
