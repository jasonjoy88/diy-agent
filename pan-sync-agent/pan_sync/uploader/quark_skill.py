"""夸克上传器：走官方 Skill CLI（quarkclouddrive），不再手写开放平台分片。"""

import os
import posixpath

from .. import quark_cli
from ..errors import UploadError
from .base import Uploader


def _is_file_entry(item):
    name = item.get("filename") or item.get("file_name") or item.get("fileName")
    ftype = item.get("file_type")
    if ftype is None:
        ftype = item.get("fileType")
    is_dir = item.get("dir")
    if is_dir is True:
        return False, name
    if str(ftype) == "0":
        return False, name
    return True, name


class QuarkSkillUploader(Uploader):
    def __init__(self, cookies=None, chunk_size=0, log=print):
        self.cookies = cookies or {}
        self.chunk_size = chunk_size
        self.log = log
        self._fid_cache = {"/": "0", "": "0"}

    def check_cookies_valid(self):
        return quark_cli.authorized()

    def ensure_dir(self, remote_path):
        if not remote_path or remote_path == "/":
            return "0"
        if remote_path in self._fid_cache:
            return self._fid_cache[remote_path]
        parts = [p for p in remote_path.replace("\\", "/").split("/") if p]
        parent_fid = "0"
        built = ""
        for name in parts:
            built = f"{built}/{name}"
            if built in self._fid_cache:
                parent_fid = self._fid_cache[built]
                continue
            fid = quark_cli.create_folder(name, parent_fid=parent_fid)
            if not fid:
                raise UploadError(f"创建网盘目录失败：{built}")
            self._fid_cache[built] = fid
            parent_fid = fid
        return parent_fid

    def exists(self, remote_path):
        parent, name = posixpath.split(remote_path)
        pdir_fid = self.ensure_dir(parent)
        for item in quark_cli.browse_all(pdir_fid):
            is_file, item_name = _is_file_entry(item)
            if is_file and item_name == name:
                return True
        return False

    def upload(self, local_path, remote_path):
        parent, _name = posixpath.split(remote_path)
        pdir_fid = self.ensure_dir(parent)
        self.log(f"[quark-skill] 上传 {os.path.basename(local_path)}")
        quark_cli.upload_file(local_path, pdir_fid)
