"""登录/授权窗口。

两条路径：
  baidu：WebView2 打开官网 → 轮询抓 Cookie（BDUSS），与早期实现一致；
  quark：开放平台拿授权页 URL → 优先用本机已登录的夸克客户端打开
         （WebView2 无客户端会话，点授权也换不到 token）→ 用 page_code
         在本进程轮询换 access_token，全程不读 Cookie。
"""

import time
from http.cookies import SimpleCookie

from . import quark_desktop, quark_open
from .errors import PanSyncError

LOGIN_URLS = {
    "baidu": "https://pan.baidu.com",
}
_REQUIRED = {
    "baidu": ("BDUSS",),
}
# 登录成功后 URL 通常会出现的特征片段（仅作辅助判定，主判定仍是 Cookie）
_LOGGED_IN_HINTS = {
    "baidu": ("disk/main", "/disk/home"),
}


def cookies_ready(drive, cookies):
    return all(key in cookies for key in _REQUIRED[drive])


def _cookies_to_dict(raw_cookies):
    """把 pywebview 返回的 Cookie 列表统一转成 {name: value}。

    pywebview 的 window.get_cookies() 返回 SimpleCookie 列表，也可能因版本/
    平台不同返回带 name/value 属性的对象；两种形态都兼容。
    SimpleCookie 没有 .name/.value 属性，必须按 dict 逐项取 Morsel.value。
    """
    result = {}
    for item in raw_cookies or []:
        if isinstance(item, SimpleCookie):
            for key, morsel in item.items():
                result[key] = morsel.value
            continue
        name = getattr(item, "name", None) or getattr(item, "key", None)
        value = getattr(item, "value", None)
        if name is not None and value is not None:
            result[name] = value
    return result


# ── baidu：Cookie 抓取路径 ─────────────────────────────────────

def _baidu_login(timeout_minutes, poll_seconds, log, sleep):
    import webview  # 延迟导入：无 GUI 的命令无需 GUI 依赖

    result = {}
    state = {"errors": 0, "saw_home": False, "home_retries": 0}
    window = webview.create_window(
        "请登录 - baidu", LOGIN_URLS["baidu"], width=1000, height=720
    )

    def poll():
        deadline = time.time() + timeout_minutes * 60
        while time.time() < deadline:
            sleep(poll_seconds)
            try:
                url = str(window.get_current_url() or "")
            except Exception:
                url = ""
            if not state["saw_home"] and any(
                hint in url for hint in _LOGGED_IN_HINTS["baidu"]
            ):
                state["saw_home"] = True
                log("[login] 检测到已跳转到网盘主页，正在读取 Cookie……")

            try:
                cookies = _cookies_to_dict(window.get_cookies())
            except Exception as e:
                state["errors"] += 1
                if state["errors"] == 1 or state["errors"] % 30 == 0:
                    log(
                        f"[login] 读取 Cookie 失败（{type(e).__name__}: {e}），"
                        "将持续重试；若一直失败可在超时后选择手动粘贴。"
                    )
                continue

            if cookies_ready("baidu", cookies):
                result["cookies"] = cookies
                log(f"[login] 已获取登录凭证（共 {len(cookies)} 个 Cookie）。")
                try:
                    window.destroy()
                except Exception:
                    pass
                return

            if state["saw_home"]:
                state["home_retries"] += 1
                if state["home_retries"] in (3, 10, 30):
                    log("[login] 已登录但暂未读到所需 Cookie，继续重试……")

    webview.start(poll)
    if "cookies" not in result:
        raise PanSyncError(
            f"未能在 {timeout_minutes} 分钟内获取 baidu 的登录凭证"
            "（窗口可能已提前关闭，或 Cookie 读取持续失败）"
        )
    return result["cookies"]


# ── quark：OAuth page_code 轮询路径（不读 Cookie）──────────────

def quark_poll(
    window, page_code, holder, deadline, poll_seconds,
    poll_code, exchange, sleep, log,
):
    """轮询后端；成功把 token 放入 holder；若有窗口则关窗。

    poll_code/exchange/sleep 全部可注入，便于无 GUI/无网络测试。
    轮询中的瞬时网络异常（OSError）忽略，继续到 deadline。
    window 可为 None（客户端/系统浏览器打开授权页时）。
    """
    while time.time() < deadline:
        sleep(poll_seconds)
        try:
            auth_code = poll_code(page_code)
        except OSError:
            auth_code = None
        if not auth_code:
            continue
        token = exchange(auth_code)
        holder["token"] = token
        log("[login] 已完成授权并获取 access_token。")
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        return


def _open_quark_authorize(authorize_url, log):
    """优先本机夸克客户端，其次系统浏览器。返回打开方式描述。"""
    running, logged_in = quark_desktop.desktop_status()
    if running and logged_in:
        if quark_desktop.open_in_desktop(authorize_url):
            log("[login] 已在本机夸克客户端打开授权页，请点击「同意/授权」。")
            return "desktop"
        log("[login] 夸克客户端打开授权页失败，改用系统浏览器。")
    elif running and not logged_in:
        log("[login] 检测到夸克客户端但未登录，请先在客户端登录；改用系统浏览器打开授权页。")
    else:
        log("[login] 未检测到运行中的夸克客户端，改用系统浏览器打开授权页。")
    import webbrowser

    webbrowser.open(authorize_url)
    log("[login] 已用系统浏览器打开授权页，请登录后点击「同意/授权」。")
    return "browser"


def _quark_login(
    timeout_minutes, poll_seconds, log, sleep,
    start_auth, poll_code, exchange, webview_module,
):
    log("[login] 正在申请夸克授权页……")
    authorize_url, page_code, _device_id = start_auth()
    _open_quark_authorize(authorize_url, log)
    log("[login] 等待授权完成（后台轮询，无需把 AAC 粘贴回来）……")

    holder = {}
    deadline = time.time() + timeout_minutes * 60
    quark_poll(
        None, page_code, holder, deadline, poll_seconds,
        poll_code, exchange, sleep, log,
    )
    if "token" not in holder:
        raise PanSyncError(
            f"未能在 {timeout_minutes} 分钟内完成夸克授权"
            "（请在客户端/浏览器中点击同意；超时后可改为手动粘贴 AAC 或 token）"
        )
    return holder["token"]


def interactive_login(
    drive, timeout_minutes=10, poll_seconds=1.0, log=print,
    sleep=time.sleep,
    start_auth=quark_open.start_authorization,
    poll_code=quark_open.poll_auth_code,
    exchange=quark_open.exchange_auth_code,
    webview_module=None,
):
    """弹窗登录/授权。baidu 返回 Cookie dict；quark 返回 token dict。"""
    if drive == "baidu":
        return _baidu_login(timeout_minutes, poll_seconds, log, sleep)
    if drive == "quark":
        return _quark_login(
            timeout_minutes, poll_seconds, log, sleep,
            start_auth, poll_code, exchange, webview_module,
        )
    raise PanSyncError(f"不支持的网盘：{drive}")


# ── 手动兜底 ───────────────────────────────────────────────────

def _manual_baidu_cookie(log):
    required = "、".join(_REQUIRED["baidu"])
    log("\n[login] 请按以下步骤手动获取 Cookie：")
    log("  1. 用浏览器打开 https://pan.baidu.com 并完成登录；")
    log(
        "  2. 按 F12 打开开发者工具 → 「应用/Application」→ 左侧「Cookie」"
        "→ 选中 pan.baidu.com 域名；"
    )
    log(f"  3. 找到 {required} 字段，复制其 value；")
    log("  4. 按 name=value; name2=value2 的格式粘贴到下方并回车。\n")
    raw = input("粘贴 Cookie> ").strip()
    cookies = {}
    for part in raw.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip()
            if key:
                cookies[key] = value.strip()
    if not cookies_ready("baidu", cookies):
        raise PanSyncError(
            f"手动粘贴的 Cookie 缺少必需字段：{required}"
            f"（实际解析到 {sorted(cookies)}）"
        )
    log(f"[login] 手动凭证校验通过（共 {len(cookies)} 个 Cookie）。")
    return cookies


def manual_token_input(log=print):
    """quark 兜底：手动粘贴 AAC 授权码或 access_token / refresh_token。"""
    log("\n[login] 请手动提供夸克凭证（二选一）：")
    log("  A. 授权页上的 AAC-… 授权码（推荐，程序会立刻换 token）；")
    log("  B. 直接粘贴 access_token（refresh_token / device_id 可留空）。\n")
    first = input("AAC 或 access_token> ").strip()
    if not first:
        raise PanSyncError("凭证不能为空")
    if first.upper().startswith("AAC-"):
        token = quark_open.exchange_auth_code(first)
        if not token.get("access_token"):
            raise PanSyncError("授权码未能换到 access_token（可能已过期，请重新 login）")
        if not token.get("device_id"):
            token["device_id"] = quark_open.DEFAULT_DEVICE_ID
        log("[login] 已用授权码换取 token。")
        return token
    refresh_token = input("refresh_token（可留空）> ").strip()
    device_id = input("device_id（可留空）> ").strip() or quark_open.DEFAULT_DEVICE_ID
    log("[login] 手动令牌已接收。")
    return {
        "access_token": first,
        "refresh_token": refresh_token,
        "device_id": device_id,
        "access_token_expires_at": 0,
        "refresh_token_expires_at": 0,
    }


def manual_cookie_input(drive, log=print):
    if drive == "baidu":
        return _manual_baidu_cookie(log)
    if drive == "quark":
        return manual_token_input(log)
    raise PanSyncError(f"不支持的网盘：{drive}")


def login_with_fallback(drive, log=print):
    """优先弹窗；失败时询问是否改为手动输入。"""
    try:
        return interactive_login(drive, log=log)
    except PanSyncError as e:
        log(f"[login] {e}")
        try:
            answer = input("是否改为手动输入凭证？[y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer in ("y", "yes"):
            return manual_cookie_input(drive, log=log)
        raise
