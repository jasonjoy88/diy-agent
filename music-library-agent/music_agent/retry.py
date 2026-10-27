"""下载瞬时失败重试：识别可重试错误并指数退避。"""
from __future__ import annotations

import random
import time
from typing import Callable

from .models import DownloadResult

# 可重试的失败特征（VIP/资源不存在等不应重试）
_RETRY_MARKERS = (
    "412",
    "429",
    "timeout",
    "timed out",
    "connection",
    "reset",
    "temporarily",
    "503",
    "502",
    "500",
    "empty_or_html",
    "failed to parse json",
    "bilibili_blocked",
    "rate",
    "限流",
    "ssl",
    "eof",
    "broken pipe",
)

_NO_RETRY_MARKERS = (
    "vip_required",
    "resource_not_found",
    "not_installed",
    "no_netease_id",
    "cookie_file_missing",
    "no_source",
    "registered users",
    "premium",
)


def is_retryable(fail_reason: str) -> bool:
    reason = (fail_reason or "").lower()
    if not reason:
        return False
    if any(m in reason for m in _NO_RETRY_MARKERS):
        return False
    return any(m in reason for m in _RETRY_MARKERS)


def fetch_with_retries(
    fetch_fn: Callable[[], DownloadResult],
    *,
    retries: int = 2,
    backoff: float = 1.5,
) -> DownloadResult:
    """对同一音源做瞬时失败重试。retries=额外次数（不含首次）。"""
    last: DownloadResult | None = None
    attempts = max(0, int(retries)) + 1
    for i in range(attempts):
        last = fetch_fn()
        if last.status == "ok":
            return last
        if i + 1 >= attempts or not is_retryable(last.fail_reason):
            return last
        delay = float(backoff) * (2 ** i) + random.uniform(0, 0.5)
        time.sleep(max(0.2, delay))
    assert last is not None
    return last
