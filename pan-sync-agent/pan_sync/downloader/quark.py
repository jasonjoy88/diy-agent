"""夸克网盘只读下载能力。

新增：取文件临时下载地址、流式落盘、目录解析与遍历（游标分页）。
复用 quark_open 的签名请求与 token 体系；不动任何上传代码。

端点说明（2026-10 BUG-001 诊断后修正，与 OpenList quark_open 驱动对齐）：
  - 目录列表 POST /open/v1/file/list，body {parent_fid,size,sort,query_cursor?}，
    响应 data.file_list[] + last_page + next_query_cursor；
    原 /open/v1/file/sort 在开放网关不存在（报 errno=10001 签名验证失败）。
  - 下载直链 POST /open/v1/file/get_download_url，body {fid}，响应 data.download_url；
    原 /open/v1/file/download 同样不在网关上。
  - 开放平台 file_type 为字符串（"0"=目录），解析时同时兼容数字。
  - 直链下载必须带 Cookie: x_pan_client_id / x_pan_access_token。
响应解析集中在 _extract_download_url。
"""
from __future__ import annotations

import os
import urllib.request

from ..errors import UploadError
from ..quark_open import CLIENT_ID, signed_request

DOWNLOAD_PATH = "/open/v1/file/get_download_url"
LIST_PATH = "/open/v1/file/list"

_PAGE_SIZE = 100  # 开放平台 file/list 每页上限（OpenList 同款）
_STREAM_CHUNK = 1 << 20
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_DEFAULT_SORT = "file_name:asc"


def _is_dir(item: dict) -> bool:
    """开放平台 file_type 为字符串 "0"（目录）；兼容数字 0。"""
    return str(item.get("file_type")) == "0"


def _call(token, method, path, body=None, request=signed_request) -> dict:
    return request(
        method, path, body=body,
        access_token=(token or {}).get("access_token"),
        device_id=(token or {}).get("device_id"),
    )


def _extract_download_url(data) -> str:
    """下载接口响应 → 第一个可用下载地址。结构以实测为准，集中在此解析。"""
    if isinstance(data, dict):
        for key in ("download_url", "url"):
            if data.get(key):
                return data[key]
        for container in ("list", "data", "files"):
            items = data.get(container)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        for key in ("download_url", "url"):
                            if item.get(key):
                                return item[key]
    raise UploadError(f"下载接口响应中找不到下载地址：{str(data)[:200]!r}")


def get_download_url(token, fid: str, request=signed_request) -> str:
    """取单个文件的临时下载地址（token 需已刷新）。"""
    data = _call(token, "POST", DOWNLOAD_PATH, body={"fid": str(fid)}, request=request)
    return _extract_download_url(data)


def _http_download(url: str, dest_path: str, cookie: str = "",
                   chunk_size: int = _STREAM_CHUNK, timeout: int = 120) -> int:
    """朴素流式下载，返回字节数。直链必须带开放平台鉴权 Cookie。"""
    headers = {"User-Agent": _UA}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as f:
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    return total


def download_file(token, fid: str, dest_path: str, request=signed_request) -> str:
    """拉取网盘文件到本地路径，返回落盘路径；已存在则原子覆盖。"""
    url = get_download_url(token, fid, request=request)
    access_token = (token or {}).get("access_token") or ""
    cookie = f"x_pan_client_id={CLIENT_ID}; x_pan_access_token={access_token}"
    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    part_path = dest_path + ".part"
    try:
        total = _http_download(url, part_path, cookie=cookie)
        if total <= 0:
            raise UploadError(f"下载内容为空：fid={fid}")
        os.replace(part_path, dest_path)
    except BaseException:
        if os.path.exists(part_path):
            os.remove(part_path)
        raise
    return dest_path


def _list_page(token, fid: str, cursor, request=signed_request):
    """file/list 单页：返回 (条目列表, 是否最后一页, 下一页游标)。"""
    body = {"parent_fid": str(fid), "size": _PAGE_SIZE, "sort": _DEFAULT_SORT}
    if cursor:
        body["query_cursor"] = cursor
    data = _call(token, "POST", LIST_PATH, body=body, request=request)
    items = data.get("file_list") or data.get("list") or []
    return items, bool(data.get("last_page")), data.get("next_query_cursor") or {}


def resolve_dir_fid(token, remote_path: str, request=signed_request) -> str:
    """逐级解析网盘目录路径 → fid（只读，不创建；找不到抛 UploadError）。"""
    path = (remote_path or "/").replace("\\", "/").strip()
    if not path or path == "/":
        return "0"
    fid = "0"
    for seg in [s for s in path.split("/") if s]:
        fid = _resolve_one_level(token, fid, seg, remote_path, request=request)
    return fid


def _resolve_one_level(token, parent_fid: str, seg: str, remote_path: str,
                       request=signed_request) -> str:
    """在 parent_fid 目录下按名查找子目录 seg（跨页遍历）。"""
    cursor = None
    while True:
        items, last_page, next_cursor = _list_page(
            token, parent_fid, cursor, request=request)
        match = next(
            (it for it in items
             if it.get("filename") == seg and _is_dir(it)),
            None,
        )
        if match is not None:
            return match.get("fid")
        if last_page or not next_cursor:
            raise UploadError(f"网盘目录不存在：{remote_path}")
        cursor = next_cursor


def list_dir(token, remote_path: str = "/", recursive: bool = False, request=signed_request) -> list[dict]:
    """列网盘目录 → [{path, filename, fid, size, file_type}]；recursive 深度优先遍历。"""
    root_fid = resolve_dir_fid(token, remote_path, request=request)
    prefix = (remote_path or "/").replace("\\", "/").rstrip("/")
    out: list[dict] = []

    def walk(fid: str, dir_prefix: str) -> None:
        cursor = None
        while True:
            items, last_page, next_cursor = _list_page(
                token, fid, cursor, request=request)
            for it in items:
                entry = {
                    "path": f"{dir_prefix}/{it.get('filename', '')}",
                    "filename": it.get("filename", ""),
                    "fid": it.get("fid"),
                    "size": it.get("size", 0),
                    "file_type": it.get("file_type"),
                }
                out.append(entry)
                if recursive and _is_dir(it):
                    walk(it.get("fid"), entry["path"])
            if last_page or not next_cursor:
                break
            cursor = next_cursor

    walk(root_fid, prefix or "")
    return out
