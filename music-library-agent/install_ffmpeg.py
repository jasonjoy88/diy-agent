"""从 npmmirror 下载 ffmpeg-static Windows 裸 exe 到 tools/ffmpeg/bin/。"""
import os
import ssl
import urllib.request

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
BASE = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "ffmpeg", "bin")
os.makedirs(DEST, exist_ok=True)


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()


for remote, local in [
    ("ffmpeg-win32-x64", "ffmpeg.exe"),
    ("ffprobe-win32-x64", "ffprobe.exe"),
]:
    print(f"下载 {remote} ...")
    data = get(BASE + remote)
    with open(os.path.join(DEST, local), "wb") as f:
        f.write(data)
    print(f"  -> {local}  ({len(data)} bytes)")
print("完成。ffmpeg 位于:", DEST)
