"""夸克网盘 Uploader —— 开放平台 API（open-api-drive.quark.cn）。

与旧内部网页接口实现的区别：
  登录态：不用 Cookie，而用 OAuth access_token（见 quark_open.py）；
  请求：每个业务请求走 signed_request（x-pan-token SHA256 签名）；
  上传：upload_pre（可能秒传）→ get_upload_urls → 逐片直传 OSS（用服务端
  给的每片签名，无需自算 OSS 签名）→ upload_finish。
"""

import hashlib
import mimetypes
import os
import posixpath
import time

from ..errors import AuthError, UploadError
from ..quark_open import ensure_fresh_token, signed_request
from .base import Uploader

_HASH_CHUNK = 1 << 20


def _hash_file(path, chunk=_HASH_CHUNK):
    """一次读取同时算全文件 sha1 / md5（hex 小写）。"""
    sha1 = hashlib.sha1()
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            sha1.update(block)
            md5.update(block)
    return sha1.hexdigest(), md5.hexdigest()


def _part_size(part_number, total_size, part_size):
    """第 part_number 片（从 1 起）的实际字节数，末片可能更小。"""
    start = (part_number - 1) * part_size
    return max(0, min(part_size, total_size - start))


def _plan_parts(total_size, part_size):
    """生成分片描述 [{part_number, part_size}]（part_number 从 1 起）。"""
    count = (total_size + part_size - 1) // part_size if part_size else 1
    return [
        {"part_number": i + 1, "part_size": _part_size(i + 1, total_size, part_size)}
        for i in range(count)
    ]


class QuarkUploader(Uploader):
    def __init__(self, token, chunk_size, log=print, request=signed_request):
        self.token = token or {}
        self.chunk_size = chunk_size
        self.log = log
        self._request = request
        self._fid_cache = {}

    # ── 内部工具 ──────────────────────────────────────────────
    def _call(self, method, path, body=None, params=None):
        return self._request(
            method, path, body=body, params=params,
            access_token=self.token.get("access_token"),
            device_id=self.token.get("device_id"),
        )

    def _put_part(self, url, signature, data, common_headers=None):
        """分片原始字节直传 OSS，返回去引号后的 ETag。

        必须用 http.client：urllib.request 会在发送前自动补
        Content-Type: application/x-www-form-urlencoded，破坏 OSS4 签名。
        """
        import http.client
        from urllib.parse import urlparse

        headers = {"Authorization": signature}
        if common_headers:
            # OSS4 要求带上服务端下发的 X-Oss-Date / X-Oss-Content-Sha256
            headers.update(common_headers)
        parsed = urlparse(url)
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn = http.client.HTTPSConnection(
            parsed.hostname, parsed.port or 443, timeout=60
        )
        try:
            conn.request("PUT", path, body=data, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            status = resp.status
            etag = resp.getheader("ETag") or resp.getheader("Etag") or ""
        finally:
            conn.close()
        if status >= 400:
            raise UploadError(f"分片上传 HTTP {status}：{body[:200]!r}")
        # upload_finish 要求带双引号的 ETag；缺则补上
        if etag and not etag.startswith('"'):
            etag = f'"{etag}"'
        return etag

    # ── Uploader 接口 ─────────────────────────────────────────
    def check_cookies_valid(self):
        """token 未失效（必要时刷新）且 user/info 可达。

        OSError（网络故障）不捕获，交由 main.login_or_none 跳过本轮。
        """
        try:
            self.token = ensure_fresh_token(self.token)
            self._call("GET", "/open/v1/user/info")
            return True
        except (AuthError, UploadError):
            return False

    def ensure_dir(self, remote_path):
        if not remote_path or remote_path == "/":
            return "0"
        if remote_path in self._fid_cache:
            return self._fid_cache[remote_path]
        data = self._call(
            "POST", "/open/v1/dir",
            body={"dir_path": remote_path, "pdir_fid": "0"},
        )
        fid = data.get("fid")
        self._fid_cache[remote_path] = fid
        return fid

    def exists(self, remote_path):
        parent, name = posixpath.split(remote_path)
        pdir_fid = self.ensure_dir(parent)
        # 开放平台列目录是 /open/v1/file/list（旧内部接口才是 file/sort）
        query_cursor = None
        while True:
            body = {
                "parent_fid": pdir_fid,
                "size": 100,
                "sort": "file_name:asc",
            }
            if query_cursor:
                body["query_cursor"] = query_cursor
            data = self._call("POST", "/open/v1/file/list", body=body)
            for item in data.get("file_list") or []:
                # file_type 可能是 int 或 str：1 = 文件，0 = 文件夹
                if item.get("filename") == name and str(item.get("file_type")) == "1":
                    return True
            if data.get("last_page", True):
                return False
            query_cursor = data.get("next_query_cursor")
            if not query_cursor:
                return False

    def upload(self, local_path, remote_path):
        parent, name = posixpath.split(remote_path)
        pdir_fid = self.ensure_dir(parent)
        size = os.path.getsize(local_path)
        sha1, md5 = _hash_file(local_path)
        now_ms = int(time.time() * 1000)
        format_type = mimetypes.guess_type(name)[0] or "application/octet-stream"

        # ① 预上传（开放平台字段；旧 same_path_file_reuse/part_info_list 会导致 finish ccp error）
        pre = self._call(
            "POST", "/open/v1/file/upload_pre", body={
                "file_name": name,
                "size": size,
                "format_type": format_type,
                "sha1": sha1,
                "md5": md5,
                "l_created_at": now_ms,
                "l_updated_at": now_ms,
                "pdir_fid": pdir_fid,
                "same_path_reuse": True,
            },
        )
        if pre.get("finish") in (1, True):
            return  # 秒传命中，无需再传
        task_id = pre["task_id"]
        part_size = pre.get("part_size") or self.chunk_size

        # ③ 单独取每片签名直传地址（与 OpenList quark_open 一致）
        part_info = _plan_parts(size, part_size)
        urls = self._call(
            "POST", "/open/v1/file/get_upload_urls", body={
                "task_id": task_id, "part_info_list": part_info,
            },
        )
        common_headers = urls.get("common_headers") or {}

        # ④ 逐片 PUT（用服务端给的每片签名 + common_headers），记录 ETag
        finished_parts = []
        with open(local_path, "rb") as f:
            for entry in urls.get("upload_urls") or []:
                pn = entry["part_number"]
                f.seek((pn - 1) * part_size)
                chunk = f.read(_part_size(pn, size, part_size))
                signature = entry["signature_info"]["signature"]
                etag = self._put_part(
                    entry["upload_url"], signature, chunk, common_headers
                )
                finished_parts.append({
                    "part_number": pn,
                    "part_size": _part_size(pn, size, part_size),
                    "etag": etag,
                })

        # ⑤ 完成
        self._call(
            "POST", "/open/v1/file/upload_finish", body={
                "task_id": task_id, "part_info_list": finished_parts,
            },
        )
