from __future__ import annotations

import os
import subprocess

MIN_BYTES = 100 * 1024  # 100KB
DURATION_TOLERANCE_MS = 15000

# 平台拦截后只返回试听/片段（网易云 freeTrialInfo、各平台试听版通常 ≤30~60s）。
# 全链路检索口径已要求曲目 ≥2:30，故落盘文件不足 60s 一律视为残缺资源。
PREVIEW_HARD_FLOOR_MS = 60_000
# 有期望时长（检索元数据）时，实际不足期望的 80% 且超出容差，视为残缺/串歌资源
SHORT_RATIO = 0.8


def _hidden_kwargs() -> dict:
    """子进程隐藏控制台窗口参数（仅 Windows），避免 GUI 下弹黑窗。"""
    if os.name != "nt":
        return {}
    kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo
    return kwargs


def _resolve_ffprobe(ffprobe_bin: str = "") -> str | None:
    """ffprobe 路径：可传可执行文件或其所在目录；空则查 PATH。"""
    names = ("ffprobe.exe", "ffprobe")
    if ffprobe_bin:
        if os.path.isfile(ffprobe_bin):
            return ffprobe_bin
        if os.path.isdir(ffprobe_bin):
            for n in names:
                cand = os.path.join(ffprobe_bin, n)
                if os.path.isfile(cand):
                    return cand
    from shutil import which

    for n in names:
        found = which(n)
        if found:
            return found
    return None


def _ffprobe_duration_ms(path: str, ffprobe_bin: str = "") -> int | None:
    ff = _resolve_ffprobe(ffprobe_bin)
    if not ff:
        return None
    try:
        res = subprocess.run(
            [
                ff, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, timeout=20, **_hidden_kwargs(),
        )
    except Exception:  # noqa: BLE001
        return None
    if res.returncode != 0:
        return None
    text = res.stdout.decode("utf-8", errors="replace").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return int(float(text) * 1000)
    except ValueError:
        return None


def _mutagen_duration_ms(path: str) -> int | None:
    """mutagen 兜底读时长（可选依赖；不支持的封装/未安装均返回 None）。"""
    try:
        from mutagen import File as MutagenFile  # type: ignore
        audio = MutagenFile(path)
        if audio is not None and getattr(audio, "info", None):
            return int(audio.info.length * 1000)
    except Exception:  # noqa: BLE001
        return None
    return None


def probe_duration_ms(path: str, ffprobe_bin: str = "") -> int | None:
    """探测媒体真实时长（毫秒）。ffprobe 优先（覆盖 m4a/mp4/webm/opus），失败回退 mutagen；
    都不可用或读不出时返回 None（调用方应放行，避免误伤）。"""
    dur = _ffprobe_duration_ms(path, ffprobe_bin)
    if dur is not None:
        return dur
    return _mutagen_duration_ms(path)


def reject_short_resource(
    path: str,
    expected_ms: int = 0,
    ffprobe_bin: str = "",
) -> str:
    """下载后护栏：平台拦截只给试听/残缺片段时返回拦截原因（非空），供 fetch_loop 换源。

    - 实际时长不足 PREVIEW_HARD_FLOOR_MS：preview_clip（无论元数据声称多长）；
    - 有期望时长且实际明显更短（<80% 且超出容差）：duration_mismatch；
    - 探测不到时长时返回 ""（放行，不阻断下载）。
    """
    dur = probe_duration_ms(path, ffprobe_bin)
    if dur is None:
        return ""
    if dur < PREVIEW_HARD_FLOOR_MS:
        return f"preview_clip:{dur // 1000}s"
    if (
        expected_ms > 0
        and dur + DURATION_TOLERANCE_MS < expected_ms
        and dur < expected_ms * SHORT_RATIO
    ):
        return f"duration_mismatch:{dur // 1000}s/{expected_ms // 1000}s"
    return ""


def check_file(
    path: str,
    expected_ms: int = 0,
    ffprobe_bin: str = "",
) -> tuple[bool, str]:
    """校验文件存在且非空；能读到时长时校验试听片段与时长偏差。返回 (ok, fail_reason)。"""
    if not os.path.isfile(path):
        return False, "missing"
    if os.path.getsize(path) < MIN_BYTES:
        return False, "too_small"
    dur = probe_duration_ms(path, ffprobe_bin)
    if dur is not None:
        if dur < PREVIEW_HARD_FLOOR_MS:
            return False, f"preview_clip:{dur // 1000}s"
        if expected_ms > 0 and abs(dur - expected_ms) > DURATION_TOLERANCE_MS:
            return False, "duration_mismatch"
    return True, ""


def _duration_ms(path: str) -> int | None:
    """兼容旧调用：mutagen 读时长（新代码请用 probe_duration_ms）。"""
    return _mutagen_duration_ms(path)
