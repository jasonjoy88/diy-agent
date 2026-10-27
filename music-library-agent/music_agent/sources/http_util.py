"""各音源共用的 HTTP / SSL 工具。"""
from __future__ import annotations

import contextvars
import json
import ssl
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Iterator

# 检索阶段可压低单次 HTTP 超时（见 multi_search 并行检索）
_http_timeout_override: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "http_timeout_override", default=None
)


@contextmanager
def http_timeout_override(seconds: float) -> Iterator[None]:
    """在 with 块内把 HTTP 超时改为不超过 seconds（线程独立）。"""
    token = _http_timeout_override.set(max(0.5, float(seconds)))
    try:
        yield
    finally:
        _http_timeout_override.reset(token)


def effective_timeout(timeout: float) -> float:
    """应用检索超时覆盖：取 override 与调用方 timeout 的较小值。"""
    override = _http_timeout_override.get()
    if override is None:
        return float(timeout)
    return min(float(timeout), float(override))


def has_http_timeout_override() -> bool:
    return _http_timeout_override.get() is not None


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # 部分公司代理会做 TLS 拦截
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(
        req, timeout=effective_timeout(timeout), context=ssl_context()
    ) as resp:
        return resp.read()


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> Any:
    raw = http_get(url, headers=headers, timeout=timeout).decode("utf-8", "replace")
    text = raw.strip()
    if text.startswith("try{") or (text and not text.startswith("{") and not text.startswith("[")):
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
    return json.loads(text)


def http_post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: float = 20,
) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(
        req, timeout=effective_timeout(timeout), context=ssl_context()
    ) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def http_download(
    url: str,
    path: str,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> int:
    """下载到 path，返回写入字节数。"""
    req = urllib.request.Request(url, headers=headers or {})
    written = 0
    with urllib.request.urlopen(
        req, timeout=effective_timeout(timeout), context=ssl_context()
    ) as resp, open(
        path, "wb"
    ) as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
    return written


def is_http_error(exc: BaseException, *codes: int) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return not codes or exc.code in codes
    text = str(exc)
    return any(str(c) in text for c in codes)
