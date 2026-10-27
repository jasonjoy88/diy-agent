import hashlib
import json
import os
import posixpath
from urllib.parse import quote, urlencode

from ..errors import AuthError, UploadError
from .base import Uploader, encode_multipart, format_cookie, http_request

APP_ID = "250528"
USER_AGENT = "netdisk;P2SP;3.0.2.30"


class BaiduUploader(Uploader):
    def _headers(self):
        return {
            "User-Agent": USER_AGENT,
            "Cookie": format_cookie(self.cookies),
            "Referer": "https://pan.baidu.com",
        }

    def _json(self, raw):
        try:
            return json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            raise UploadError(f"百度返回非 JSON：{raw[:200]!r}")

    def _api(self, path, params=None, form=None):
        url = "https://pan.baidu.com" + path
        if params:
            url += "?" + urlencode(params)
        headers = self._headers()
        data = None
        if form is not None:
            data = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        status, _, raw = http_request("POST" if form is not None else "GET", url, headers, data)
        js = self._json(raw)
        errno = js.get("errno")
        if errno != 0:
            if errno in (-6, -4):
                raise AuthError(f"百度登录失效 errno={errno}")
            raise UploadError(f"百度 {path} errno={errno}")
        return js

    def _list_dir(self, remote_dir):
        js = self._api(
            "/api/list",
            params={
                "dir": remote_dir,
                "order": "time",
                "desc": "1",
                "clienttype": "0",
                "app_id": APP_ID,
            },
        )
        return js.get("list") or []

    def check_cookies_valid(self):
        try:
            self._list_dir("/")
            return True
        except (AuthError, UploadError):
            return False

    def exists(self, remote_path):
        parent, name = posixpath.split(remote_path)
        for item in self._list_dir(parent or "/"):
            if item.get("server_filename") == name and item.get("isdir") == 0:
                return True
        return False

    def ensure_dir(self, remote_path):
        if remote_path in ("", "/", "."):
            return
        parent, name = posixpath.split(remote_path)
        if parent and parent != "/":
            self.ensure_dir(parent)
        for item in self._list_dir(parent or "/"):
            if item.get("server_filename") == name and item.get("isdir") == 1:
                return
        self._api("/api/create", params={"app_id": APP_ID}, form={"path": remote_path, "isdir": "1"})

    def _block_ranges(self, path):
        size = os.path.getsize(path)
        start = 0
        while start < size:
            length = min(self.chunk_size, size - start)
            yield start, length
            start += length

    def _block_md5_list(self, path):
        md5_list = []
        with open(path, "rb") as f:
            while True:
                chunk = f.read(self.chunk_size)
                if not chunk:
                    break
                md5_list.append(hashlib.md5(chunk).hexdigest())
        return md5_list

    def _superfile(self, uploadid, remote_path, seq, chunk):
        url = (
            "https://d.pcs.baidu.com/rest/2.0/pcs/superfile2?method=upload&type=tmpfile"
            f"&app_id={APP_ID}&uploadid={quote(uploadid)}&path={quote(remote_path)}&partseq={seq}"
        )
        body, content_type = encode_multipart(
            {"file": (posixpath.basename(remote_path), chunk)}
        )
        headers = self._headers()
        headers["Content-Type"] = content_type
        status, _, raw = http_request("POST", url, headers, body)
        if status != 200:
            raise UploadError(f"superfile2 分片{seq} HTTP {status}")
        js = self._json(raw)
        if js.get("error_code", 0) not in (0, None):
            raise UploadError(f"superfile2 分片{seq} 失败：{js}")

    def upload(self, local_path, remote_path):
        if self.exists(remote_path):
            return
        size = os.path.getsize(local_path)
        block_md5 = self._block_md5_list(local_path)
        js = self._api(
            "/api/precreate",
            params={"app_id": APP_ID},
            form={
                "path": remote_path,
                "isdir": "0",
                "autoinit": "1",
                "target_path": remote_path,
                "size": str(size),
                "block_list": json.dumps(block_md5),
            },
        )
        uploadid = js["uploadid"]
        for seq, (start, length) in enumerate(self._block_ranges(local_path)):
            with open(local_path, "rb") as f:
                f.seek(start)
                chunk = f.read(length)
            self._superfile(uploadid, remote_path, seq, chunk)
        self._api(
            "/api/create",
            params={"app_id": APP_ID},
            form={
                "path": remote_path,
                "isdir": "0",
                "block_list": json.dumps(block_md5),
                "uploadid": uploadid,
            },
        )
