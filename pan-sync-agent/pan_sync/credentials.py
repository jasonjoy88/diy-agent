import ctypes
import ctypes.wintypes
import json
import os


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blob_from_bytes(data):
    return _DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))


def _crypt_protect(data):
    in_blob = _blob_from_bytes(data)
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect(blob):
    in_blob = _blob_from_bytes(blob)
    out_blob = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _cookie_path(drive, data_dir):
    return os.path.join(data_dir, f"cookies.{drive}.enc")


def save_cookies(drive, cookies, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    raw = json.dumps(cookies, ensure_ascii=False).encode("utf-8")
    encrypted = _crypt_protect(raw)
    path = _cookie_path(drive, data_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(encrypted)
    os.replace(tmp_path, path)


def load_cookies(drive, data_dir):
    path = _cookie_path(drive, data_dir)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        encrypted = f.read()
    raw = _crypt_unprotect(encrypted)
    return json.loads(raw.decode("utf-8"))
