import os
from dataclasses import dataclass

from .errors import ConfigError

_ENV_KEYS = (
    "WATCH_DIR",
    "DRIVE",
    "SCAN_INTERVAL_MINUTES",
    "START_HOUR",
    "END_HOUR",
    "REMOTE_ROOT",
    "CONFLICT_POLICY",
    "CHUNK_SIZE_MB",
    "STABLE_SECONDS",
    "SKIP_DIR_PREFIXES",
)


def _read_env_file(path):
    values = {}
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _parse_positive_int(name, raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} 必须是正整数，当前为 {raw!r}")
    if value <= 0:
        raise ConfigError(f"{name} 必须大于 0，当前为 {value}")
    return value


def _parse_hour(name, raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} 必须是整数，当前为 {raw!r}")
    if value < 0:
        raise ConfigError(f"{name} 不能为负数，当前为 {value}")
    return value


def _normalize_remote_root(raw):
    root = raw.strip().replace("\\", "/")
    if not root.startswith("/"):
        root = "/" + root
    root = root.rstrip("/")
    return root


@dataclass(frozen=True)
class Config:
    watch_dir: str
    drive: str
    scan_interval_minutes: int
    start_hour: int
    end_hour: int
    remote_root: str
    conflict_policy: str
    chunk_size_mb: int
    stable_seconds: int
    skip_dir_prefixes: tuple

    @property
    def chunk_size_bytes(self):
        return self.chunk_size_mb * 1024 * 1024


def load_config(env_path):
    values = {}
    if env_path and os.path.exists(env_path):
        values.update(_read_env_file(env_path))
    for key in _ENV_KEYS:
        if key in os.environ:
            values[key] = os.environ[key]

    watch_dir = values.get("WATCH_DIR", "").strip()
    if not watch_dir:
        raise ConfigError("WATCH_DIR 必填")
    if not os.path.exists(watch_dir):
        raise ConfigError(f"WATCH_DIR 不存在：{watch_dir}")
    if not os.path.isdir(watch_dir):
        raise ConfigError(f"WATCH_DIR 必须是目录：{watch_dir}")

    drive = values.get("DRIVE", "baidu").strip().lower()
    if drive not in ("baidu", "quark"):
        raise ConfigError(f"DRIVE 仅支持 baidu/quark，当前为 {drive!r}")

    interval = _parse_positive_int("SCAN_INTERVAL_MINUTES", values.get("SCAN_INTERVAL_MINUTES", "30"))
    chunk_mb = _parse_positive_int("CHUNK_SIZE_MB", values.get("CHUNK_SIZE_MB", "4"))
    stable = _parse_positive_int("STABLE_SECONDS", values.get("STABLE_SECONDS", "60"))

    start_hour = _parse_hour("START_HOUR", values.get("START_HOUR", "8"))
    end_hour = _parse_hour("END_HOUR", values.get("END_HOUR", "23"))
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        raise ConfigError("START_HOUR/END_HOUR 必须在 0-23 之间")
    if start_hour >= end_hour:
        raise ConfigError(f"START_HOUR({start_hour}) 必须小于 END_HOUR({end_hour})")

    remote_root = _normalize_remote_root(values.get("REMOTE_ROOT", "/pan-sync"))

    conflict_policy = values.get("CONFLICT_POLICY", "skip").strip().lower()
    if conflict_policy != "skip":
        raise ConfigError(f"CONFLICT_POLICY 当前仅支持 skip，当前为 {conflict_policy!r}")

    if "SKIP_DIR_PREFIXES" in values:
        skip_dir_prefixes = tuple(
            p.strip() for p in values.get("SKIP_DIR_PREFIXES", "").split(",") if p.strip()
        )
    else:
        skip_dir_prefixes = ("_",)

    return Config(
        watch_dir=os.path.abspath(watch_dir),
        drive=drive,
        scan_interval_minutes=interval,
        start_hour=start_hour,
        end_hour=end_hour,
        remote_root=remote_root,
        conflict_policy=conflict_policy,
        chunk_size_mb=chunk_mb,
        stable_seconds=stable,
        skip_dir_prefixes=skip_dir_prefixes,
    )
