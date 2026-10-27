"""夸克网盘官方 Skill CLI（quarkclouddrive）封装。

Skill 位于项目内 quarkclouddrive/，通过 node scripts/quark-drive.cjs 调用。
登录态由 CLI 写入用户主目录 ~/.quarkclouddrive/config.json，不走本工具 DPAPI。
"""

import json
import os
import secrets
import shutil
import subprocess
import time

from .errors import AuthError, PanSyncError, UploadError

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(_PROJECT_ROOT, "quarkclouddrive")
CLI_SCRIPT = os.path.join(SKILL_DIR, "scripts", "quark-drive.cjs")
WORK_DIR = os.path.join(_PROJECT_ROOT, "data", "quark-cli")

_SESSION_ID = None
_SESSION_INPUT = "pan-sync-agent"


def session_id():
    global _SESSION_ID
    if not _SESSION_ID:
        rand = secrets.token_hex(3)
        _SESSION_ID = f"{int(time.time())}-{rand}"
    return _SESSION_ID


def set_session_input(text):
    global _SESSION_INPUT
    if text:
        _SESSION_INPUT = text


def cli_available():
    return bool(os.path.isfile(CLI_SCRIPT) and shutil.which("node"))


def _node():
    node = shutil.which("node")
    if not node:
        raise PanSyncError("未找到 node，无法调用夸克网盘官方 Skill（需要 Node.js >= 16）")
    if not os.path.isfile(CLI_SCRIPT):
        raise PanSyncError(f"未找到夸克 Skill CLI：{CLI_SCRIPT}")
    return node


def _parse_ndjson(stdout):
    rows = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _result_row(rows):
    for row in reversed(rows):
        if row.get("type") == "result":
            return row
    return rows[-1] if rows else {}


def run(args, timeout=600, input_text=None):
    """调用 CLI，返回 (result_row, all_rows)。"""
    os.makedirs(WORK_DIR, exist_ok=True)
    cmd = [
        _node(), CLI_SCRIPT, *args,
        "--session-input", _SESSION_INPUT,
        "--session-id", session_id(),
    ]
    env = os.environ.copy()
    # 官方 CLI 只认一组宿主 Agent；Cursor 不在名单内，用 OpenClaw 标记才能启动。
    env.setdefault("OPENCLAW_CLI", "1")
    proc = subprocess.run(
        cmd,
        cwd=WORK_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input_text,
        env=env,
    )
    rows = _parse_ndjson(proc.stdout)
    result = _result_row(rows)
    if not result:
        err = (proc.stderr or proc.stdout or "").strip()[:400]
        raise UploadError(f"夸克 Skill CLI 无 JSON 结果：{err or proc.returncode}")
    return result, rows


def _raise_if_auth_failed(result):
    code = result.get("code")
    msg = result.get("msg") or ""
    if code == 0:
        return
    text = msg.lower()
    if code in (-1408, -118) or any(
        k in msg for k in ("未授权", "未完成授权", "认证")
    ) or "token" in text:
        if code == -118:
            return
        raise AuthError(msg or "夸克 Skill 未授权")
    raise UploadError(msg or f"夸克 Skill 失败 code={code}")


def login(token=None):
    args = ["login"]
    if token:
        args.extend(["--token", token])
    result, _ = run(args, timeout=700)
    code = result.get("code")
    if code == -118:
        return result
    if code != 0:
        raise AuthError(result.get("msg") or "夸克 Skill 登录失败")
    return result


def user_info():
    result, _ = run(["get-user-info"], timeout=60)
    _raise_if_auth_failed(result)
    return result


def authorized():
    try:
        result = user_info()
        return result.get("code") == 0
    except AuthError:
        return False
    except (OSError, UploadError, PanSyncError):
        return False


def create_folder(dir_path, parent_fid="0"):
    args = ["create-folder", "--dir-path", dir_path]
    if parent_fid is not None:
        args.extend(["--parent-fid", str(parent_fid)])
    result, _ = run(args, timeout=60)
    _raise_if_auth_failed(result)
    return (result.get("data") or {}).get("fid")


def browse_all(parent_fid="0"):
    task_dir = os.path.join(WORK_DIR, "browse-tasks")
    os.makedirs(task_dir, exist_ok=True)
    result, _ = run(
        [
            "browse",
            "--parent-fid", str(parent_fid),
            "--all",
            "--task-dir", task_dir,
        ],
        timeout=120,
    )
    _raise_if_auth_failed(result)
    data = result.get("data") or {}
    path = data.get("file_path")
    items = []
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("type") == "list" or "filename" in row or "file_name" in row:
                    payload = row.get("data") or row
                    items.append(payload)
    preview = data.get("file_list") or []
    return items or preview


def upload_file(local_path, parent_fid):
    args = ["upload", os.path.abspath(local_path)]
    if parent_fid is not None:
        args.extend(["--parent-fid", str(parent_fid)])
    result, rows = run(args, timeout=3600)
    _raise_if_auth_failed(result)
    if result.get("code") not in (0, None):
        raise UploadError(result.get("msg") or "夸克 Skill 上传失败")
    return result
