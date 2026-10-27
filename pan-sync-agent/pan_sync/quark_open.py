"""夸克网盘开放平台客户端（open-api-drive.quark.cn）。

本模块按参考库 wlor0623/quark-api 文档实现，包含：
  1. x-pan-token SHA256 请求签名；
  2. 带签名的 HTTP 调用（无第三方依赖，用 urllib）；
  3. OAuth 授权引导：get_authorize_page_url → 轮询 page_code → 换 token；
  4. token 有效期判定与刷新；

两套接口的区别：
  旧（内部网页接口 drive-pc.quark.cn）：靠 Cookie 鉴权，登录要抓 Cookie；
  新（开放平台 open-api-drive.quark.cn）：靠 access_token + 每请求签名，
  登录走后端轮询，完全不碰 WebView2 的 Cookie API。

注意：该开放平台仍由逆向整理、非官方正式公开，字段可能需实测微调。
"""

import hashlib
import json
import os
import time
import uuid as _uuid
from urllib.parse import urlencode

from .errors import AuthError, ConfigError, UploadError
from .uploader.base import http_request

# ── 开放平台常量（参考库 1.4 节硬编码默认凭据，wild 模式）────────
OPEN_BASE = "https://open-api-drive.quark.cn"
CLIENT_ID = "third_party_agent"
DEFAULT_DEVICE_ID = "wild_claw"
SCOPE = "clouddrive.base clouddrive.netdisk"


def _load_sign_key() -> str:
    """从环境变量 QUARK_SIGN_KEY 读取签名密钥。

    优先级：os.environ（系统环境变量 / config.txt 注入 / 上游 .env 加载）。
    缺失时抛 ConfigError，避免在无密钥环境下静默产出错误签名。
    """
    key = os.environ.get("QUARK_SIGN_KEY", "").strip()
    if not key:
        raise ConfigError(
            "QUARK_SIGN_KEY 未配置。请在 pan-sync-agent/.env 或 config.txt "
            "中设置 QUARK_SIGN_KEY=<你的夸克开放平台签名密钥>，"
            "或通过环境变量传入。"
        )
    return key


# 注意：SIGN_KEY 改为懒加载——模块导入时不立即读，
# 首次调用 pan_token / signed_request 时才从环境变量取。
# 这样保证 dsh_player_tools._paths 先注入 config.txt 和 .env，再使用签名。
_SIGN_KEY_CACHE: str | None = None


def get_sign_key() -> str:
    """获取签名密钥（懒加载 + 缓存）。"""
    global _SIGN_KEY_CACHE
    if _SIGN_KEY_CACHE is None:
        _SIGN_KEY_CACHE = _load_sign_key()
    return _SIGN_KEY_CACHE

# token 临期阈值：剩余有效期低于该值视为需刷新（毫秒）
EXPIRY_SKEW_MS = 5 * 60 * 1000

# 授权页申请参数（无配置注入时的默认值）
DEFAULT_AGENT_ID = "third_party_agent"
DEFAULT_WORK_DIR = "/"
DEFAULT_DEVICE_NAME = os.environ.get("COMPUTERNAME", "pan-sync-pc")

# 业务错误码（参考库第 10 章）
_AUTH_ERRNOS = (11001, 31001)


def now_ms(clock=time.time):
    return int(clock() * 1000)


def pan_token(method, path, tm, sign_key=None):
    """x-pan-token = SHA256_hex("{METHOD}&{PATH}&{TM}&{SIGN_KEY}")。"""
    if sign_key is None:
        sign_key = get_sign_key()
    raw = f"{method}&{path}&{tm}&{sign_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def signed_request(
    method,
    path,
    body=None,
    params=None,
    access_token=None,
    device_id=None,
    timeout=30,
    http=http_request,
    uuid_factory=_uuid.uuid4,
    current_ms=None,
):
    """发起一次带 x-pan-token 签名的开放平台请求，返回 data 对象。

    - method/path：HTTP 方法与仅路径（path 参与签名，不含查询串）；
    - body：dict，将以 JSON 发送；
    - params：除 req_id/access_token/device_id 之外的额外查询参数；
    - 成功返回 envelope["data"]；业务失败按 errno 抛 AuthError/UploadError。
    """
    method = method.upper()
    tm = str(current_ms if current_ms is not None else now_ms())

    query = {"req_id": str(uuid_factory())}
    if access_token:
        query["access_token"] = access_token
    if device_id:
        query["device_id"] = device_id
    if params:
        query.update(params)
    url = f"{OPEN_BASE}{path}?{urlencode(query)}"

    headers = {
        "x-pan-client-id": CLIENT_ID,
        "x-pan-tm": tm,
        "x-pan-token": pan_token(method, path, tm),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None

    status, _, raw = http(method, url, headers, data, timeout=timeout)
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise UploadError(f"夸克返回非 JSON（HTTP {status}）：{raw[:200]!r}")

    errno = envelope.get("errno", envelope.get("status"))
    if envelope.get("status") != 0 and errno not in (0, None):
        message = envelope.get("error_info") or envelope.get("message") or "未知错误"
        if errno in _AUTH_ERRNOS:
            raise AuthError(f"夸克登录失效 errno={errno} msg={message}")
        raise UploadError(f"夸克 {path} errno={errno} msg={message}")
    return envelope.get("data") or {}


# ── OAuth 授权引导（参考库第 3 章）──────────────────────────────

def start_authorization(
    device_name=DEFAULT_DEVICE_NAME,
    work_dir=DEFAULT_WORK_DIR,
    agent_id=DEFAULT_AGENT_ID,
    client_device_id=DEFAULT_DEVICE_ID,
    **kwargs,
):
    """① 申请授权页地址。返回 (authorize_page_url, page_code, device_id)。

    此时尚无 access_token，仅靠默认 sign_key 签名。
    """
    data = signed_request(
        "POST",
        "/agent/v1/get_authorize_page_url",
        body={
            "client_device_id": client_device_id,
            "device_name": device_name,
            "agent_id": agent_id,
            "client_id": CLIENT_ID,
            "work_dir": work_dir,
        },
        **kwargs,
    )
    return (
        data["authorize_page_url"],
        data["page_code"],
        data.get("device_id") or client_device_id,
    )


def poll_auth_code(page_code, **kwargs):
    """② 轮询授权结果；完成返回 agent_auth_code，未完成返回 None。

    兼容新旧两种响应：
      - 旧版：data.status == 1 且有 agent_auth_code
      - 新版：data.status == "authorized"（或非 "pending"/"expired"）且有 agent_auth_code
    实际判断以 agent_auth_code 字段是否存在且非空为准。
    """
    data = signed_request(
        "GET",
        "/agent/v1/oauth/get_aac_by_pagecode",
        params={"page_code": page_code},
        **kwargs,
    )
    auth_code = data.get("agent_auth_code")
    if auth_code:
        return auth_code
    return None


def exchange_auth_code(agent_auth_code, **kwargs):
    """③ 用 agent_auth_code 换取令牌，返回 token 记录。"""
    return signed_request(
        "GET",
        "/agent/v1/oauth/agent_auth_code",
        params={"agent_auth_code": agent_auth_code},
        **kwargs,
    )


def rotate_token(refresh_token, device_id, **kwargs):
    """用 refresh_token 刷新，返回新的 token 记录。"""
    return signed_request(
        "POST",
        "/agent/v1/oauth/access_token/rotate",
        body={"refresh_token": refresh_token, "device_id": device_id},
        **kwargs,
    )


# ── token 有效期 ────────────────────────────────────────────────

def token_valid(token, current_ms=None, skew=EXPIRY_SKEW_MS):
    """access_token 是否存在且未临期。无过期字段时视为有效。"""
    if not token or not token.get("access_token"):
        return False
    exp = token.get("access_token_expires_at")
    if not exp:
        return True
    cur = current_ms if current_ms is not None else now_ms()
    return cur < exp - skew


def ensure_fresh_token(token, current_ms=None, skew=EXPIRY_SKEW_MS, **request_kwargs):
    """token 仍有效直接返回；临期则用 refresh_token 刷新。

    无法刷新（缺 refresh_token/device_id）时抛 AuthError，交由上层重新登录。
    """
    if token_valid(token, current_ms=current_ms, skew=skew):
        return token
    refresh_token = (token or {}).get("refresh_token")
    device_id = (token or {}).get("device_id")
    if not refresh_token or not device_id:
        raise AuthError("夸克 token 已过期且缺少刷新凭证，需重新登录")
    return rotate_token(refresh_token, device_id, **request_kwargs)
