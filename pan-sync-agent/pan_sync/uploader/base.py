import json
import time
import urllib.error
from urllib.request import Request, urlopen

from ..errors import AuthError, UploadError

DEFAULT_TIMEOUT = 30


def format_cookie(cookies):
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def encode_multipart(fields, boundary=None):
    if boundary is None:
        boundary = f"----PanSyncBoundary{int(time.time() * 1000)}"
    body = b""
    for name, (filename, data) in fields.items():
        body += (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'
        ).encode()
        body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def http_request(method, url, headers=None, data=None, timeout=DEFAULT_TIMEOUT):
    req = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def retry(call, attempts=3, base_delay=1.0, sleep=time.sleep, log=print):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except AuthError:
            raise
        except (OSError, UploadError) as e:
            last_error = e
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log(f"[retry] 第 {attempt} 次失败：{e}；{delay:.0f}s 后重试")
            sleep(delay)
    raise last_error


class Uploader:
    """两个网盘适配器的统一接口。"""

    def __init__(self, cookies, chunk_size, log=print):
        self.cookies = cookies
        self.chunk_size = chunk_size
        self.log = log

    def check_cookies_valid(self):
        raise NotImplementedError

    def ensure_dir(self, remote_path):
        raise NotImplementedError

    def exists(self, remote_path):
        raise NotImplementedError

    def upload(self, local_path, remote_path):
        raise NotImplementedError
