"""夸克 OAuth 完整链路诊断（系统浏览器 + 自动换 token）。

一次性跑完 OAuth 全流程并打印每步原始返回：
  ① get_authorize_page_url        拿授权页 + page_code
  ② 系统浏览器打开，用户点同意
  ③ 轮询 get_aac_by_pagecode      拿 agent_auth_code（AAC-…，注意这是授权码不是 token）
  ④ 立刻调 oauth/agent_auth_code  换真正的 access_token / refresh_token
  ⑤ 调 /open/v1/user/info         验证令牌可用
  ⑥ 加密存入 data/cookies.quark.enc，随后 main.py 直接可用

运行：python diag_quark_oauth.py
"""

import json
import time
import uuid
import webbrowser

from pan_sync import credentials
from pan_sync.quark_open import (
    CLIENT_ID,
    OPEN_BASE,
    now_ms,
    pan_token,
    signed_request,
)
from pan_sync.uploader.base import http_request

DATA_DIR = "data"


def _mask(value, keep=10):
    if not isinstance(value, str):
        return value
    if len(value) <= keep + 6:
        return value
    return f"{value[:keep]}...({len(value)}字符)"


def _masked(obj):
    if isinstance(obj, dict):
        return {k: _masked(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_masked(v) for v in obj]
    return _mask(obj)


def _raw_request(method, path, params=None, body=None):
    """不走业务判定，直接返回 (status, 原始 envelope dict)。"""
    tm = str(now_ms())
    query = {"req_id": str(uuid.uuid4())}
    if params:
        query.update(params)
    from urllib.parse import urlencode
    url = f"{OPEN_BASE}{path}?{urlencode(query)}"
    headers = {
        "x-pan-client-id": CLIENT_ID,
        "x-pan-tm": tm,
        "x-pan-token": pan_token(method, path, tm),
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode()
    else:
        payload = None
    status, _h, raw = http_request(method, url, headers, payload)
    return status, json.loads(raw.decode())


def main():
    # ① 申请授权页（看原始返回）
    status, env1 = _raw_request(
        "POST",
        "/agent/v1/get_authorize_page_url",
        body={
            "client_device_id": "wild_claw",
            "device_name": "pan-sync-pc",
            "agent_id": "third_party_agent",
            "client_id": CLIENT_ID,
            "work_dir": "/",
        },
    )
    print(f"[①授权页] HTTP {status} 原始返回：")
    print("   ", json.dumps(_masked(env1), ensure_ascii=False))
    d1 = env1.get("data") or {}
    authorize_url = d1["authorize_page_url"]
    page_code = d1["page_code"]
    print(f"    page_code = {page_code}")

    # ② 系统浏览器
    print("\n[②] 已用系统默认浏览器打开授权页，请登录后点【同意/授权】。")
    webbrowser.open(authorize_url)

    # ③ 轮询拿 AAC（不预设字段，直接看 data 里有没有 agent_auth_code）
    print("[③] 轮询授权码（每 2 秒，最多 3 分钟）……")
    deadline = time.time() + 180
    aac = None
    n = 0
    while time.time() < deadline:
        time.sleep(2)
        n += 1
        try:
            st, env_poll = _raw_request(
                "GET",
                "/agent/v1/oauth/get_aac_by_pagecode",
                params={"page_code": page_code},
            )
        except Exception as e:
            print(f"   第{n}次 请求异常 {type(e).__name__}: {e}")
            continue
        dp = env_poll.get("data") or {}
        print(
            f"   第{n}次 HTTP{st} top.status={env_poll.get('status')} "
            f"errno={env_poll.get('errno')} data.status={dp.get('status')} "
            f"keys={sorted(dp.keys())} AAC={_mask(dp.get('agent_auth_code'))}"
        )
        if dp.get("agent_auth_code"):
            aac = dp["agent_auth_code"]
            break

    if not aac:
        print("\n[×] 没拿到授权码。请把上面所有轮询行贴回给我。")
        return

    print(f"\n[✓③] 拿到授权码（AAC）：{_mask(aac)}")

    # ④ 立刻用 AAC 换真正的 token（授权码一般单次/短时有效，故马上换）
    print("[④] 用授权码换取 access_token……")
    try:
        st, env_tok = _raw_request(
            "GET",
            "/agent/v1/oauth/agent_auth_code",
            params={"agent_auth_code": aac},
        )
    except Exception as e:
        print(f"   换 token 异常：{type(e).__name__}: {e}")
        return
    print(f"    HTTP {st} 原始返回：")
    print("   ", json.dumps(_masked(env_tok), ensure_ascii=False))
    token = env_tok.get("data") or {}
    if not token.get("access_token"):
        print("[×] 返回里没有 access_token，请把上面原始返回贴回给我。")
        return

    # ⑤ user/info 验证
    print("\n[⑤] 调 /open/v1/user/info 验证令牌……")
    try:
        st, env_user = _raw_request(
            "GET",
            "/open/v1/user/info",
            params={"access_token": token["access_token"],
                    "device_id": token.get("device_id", "wild_claw")},
        )
        print(f"    HTTP {st}：", json.dumps(_masked(env_user),
              ensure_ascii=False))
    except Exception as e:
        print(f"    user/info 异常：{type(e).__name__}: {e}")

    # ⑥ 加密保存（补上 device_id，便于后续刷新）
    if not token.get("device_id"):
        token["device_id"] = d1.get("device_id") or "wild_claw"
    credentials.save_cookies("quark", token, DATA_DIR)
    print("\n[⑥] 真正的令牌已加密存入 data/，现在可直接：python main.py once")
    print("    access_token =", _mask(token.get("access_token")))
    print("    refresh_token =", _mask(token.get("refresh_token")))
    print("    device_id =", token.get("device_id"))


if __name__ == "__main__":
    main()
