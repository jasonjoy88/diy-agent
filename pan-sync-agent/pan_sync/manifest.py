import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime

MANIFEST_FILENAME = ".uploaded.json"
_VERSION = 1
_VALID_STATUS = ("uploaded", "conflict", "failed")


@dataclass(frozen=True)
class ManifestEntry:
    rel_path: str
    size: int
    mtime: float
    md5: str
    remote_path: str
    status: str
    recorded_at: str
    fail_reason: str | None = None


def make_entry(rel_path, size, mtime, md5, remote_path, status, fail_reason=None):
    if status not in _VALID_STATUS:
        raise ValueError(f"非法清单状态：{status}")
    return ManifestEntry(
        rel_path=rel_path,
        size=size,
        mtime=mtime,
        md5=md5,
        remote_path=remote_path,
        status=status,
        recorded_at=datetime.now().isoformat(timespec="seconds"),
        fail_reason=fail_reason,
    )


def manifest_path(directory):
    return os.path.join(directory, MANIFEST_FILENAME)


def load_entries(directory):
    path = manifest_path(directory)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [ManifestEntry(**item) for item in data.get("entries", [])]


def latest_by_relpath(entries):
    latest = {}
    for entry in entries:
        latest[entry.rel_path] = entry
    return latest


def append_entry(directory, entry):
    entries = load_entries(directory)
    entries.append(entry)
    payload = {"version": _VERSION, "entries": [asdict(item) for item in entries]}
    path = manifest_path(directory)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
