from __future__ import annotations

import os
import re
import sys

from .. import catalog, llm, prompts
from ..config import CONFIG
from ..models import ArtistCandidate

# 交互：都不符合候选时的重输指令（序号 0 / 关键字）
_REENTER_TOKENS = frozenset({"0", "r", "R", "re", "RE", "重新", "重新输入", "换一个", "都不符合"})

# 合唱歌曲的歌手分隔符
_CHORUS_SEP_RE = re.compile(r'[_\&、，,/\s]+')


def _is_chorus_name(name: str) -> bool:
    """判断名称是否像合唱（多歌手）名称。"""
    return bool(_CHORUS_SEP_RE.search(name))


def _split_chorus_artists(name: str) -> list[str]:
    """按合唱分隔符拆分出歌手列表，去空去重保序。"""
    parts = [p.strip() for p in _CHORUS_SEP_RE.split(name) if p.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _detect_local_solo_artists(output_root: str) -> set[str]:
    """扫描本地输出目录下已有的独立歌手目录。"""
    if not output_root or not os.path.isdir(output_root):
        return set()
    solo: set[str] = set()
    for name in os.listdir(output_root):
        full = os.path.join(output_root, name)
        if not os.path.isdir(full):
            continue
        if _is_chorus_name(name):
            continue
        solo.add(name)
    return solo


class ArtistAmbiguousError(RuntimeError):
    """存在多个同名歌手且无法交互选择时抛出。"""

    def __init__(self, singer: str, candidates: list[ArtistCandidate]):
        self.singer = singer
        self.candidates = candidates
        lines = [f"检测到多个同名歌手「{singer}」，请用 --artist-id 指定其一："]
        for i, c in enumerate(candidates, 1):
            lines.append(f"  {i}. id={c.artist_id}  {c.blurb}")
        if candidates:
            lines.append("  （交互终端也可选 0 重新输入歌手名）")
        super().__init__("\n".join(lines))


def _safe_dir_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def _format_choice_lines(candidates: list[ArtistCandidate]) -> list[str]:
    lines = ["[resolve_artist] 检测到多个同名歌手，请根据简介选择："]
    for i, c in enumerate(candidates, 1):
        lines.append(f"  {i}. [id={c.artist_id}] {c.blurb}")
    lines.append("  0. 都不符合，重新输入歌手名")
    return lines


def _pick_by_id(candidates: list[ArtistCandidate], artist_id: str) -> ArtistCandidate | None:
    aid = str(artist_id).strip()
    if not aid:
        return None
    return next((c for c in candidates if c.artist_id == aid), None)


def _prompt_new_singer(prev: str) -> str:
    """提示用户重新输入歌手名；空输入则保留原名并再问一次。"""
    print(f"请重新输入歌手名（当前：{prev}）：", end="", flush=True)
    while True:
        raw = sys.stdin.readline()
        if not raw:
            raise ArtistAmbiguousError(prev, [])
        name = raw.strip()
        if name:
            return name
        print("歌手名不能为空，请重新输入：", end="", flush=True)


def _prompt_user_choose(candidates: list[ArtistCandidate]) -> ArtistCandidate | None:
    """交互选择。返回候选；返回 None 表示用户要重新输入歌手名。

    非 TTY 时抛 ArtistAmbiguousError。
    """
    if not sys.stdin.isatty():
        raise ArtistAmbiguousError(candidates[0].name, candidates)
    print(
        f"请输入序号 1-{len(candidates)} / 网易云 artist-id（输入 0 重新输入歌手名）：",
        end="",
        flush=True,
    )
    while True:
        raw = sys.stdin.readline()
        if not raw:
            raise ArtistAmbiguousError(candidates[0].name, candidates)
        raw = raw.strip()
        if not raw:
            print("输入不能为空，请重试：", end="", flush=True)
            continue
        if raw in _REENTER_TOKENS:
            return None
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(candidates):
                return candidates[idx - 1]
            # 也可能直接输入了纯数字 artist-id（非 0）
            hit = _pick_by_id(candidates, raw)
            if hit:
                return hit
            print(
                f"序号无效，请输入 1-{len(candidates)}、artist-id，或 0 重新输入歌手名：",
                end="",
                flush=True,
            )
            continue
        hit = _pick_by_id(candidates, raw)
        if hit:
            return hit
        print("未匹配到候选，请输入序号、artist-id，或 0 重新输入歌手名：", end="", flush=True)


def run(state: dict) -> dict:
    singer = (state.get("singer") or "").strip()
    preferred_id = str(state.get("artist_id") or "").strip()
    msgs: list[str] = []

    # === 合唱归属：如果输入是合唱名，优先归入本地已有的独立歌手目录 ===
    if _is_chorus_name(singer):
        local_solo = _detect_local_solo_artists(CONFIG.output_root)
        parts = _split_chorus_artists(singer)
        primary_artist = ""
        for p in parts:
            if p in local_solo:
                primary_artist = p
                msgs.append(
                    f"[resolve_artist] 合唱名「{singer}」→ 归属到已有独立歌手目录「{p}」"
                )
                break
        if not primary_artist and parts:
            # 本地没有任何一个歌手的独立目录，用第一个歌手名作为目录
            primary_artist = parts[0]
            msgs.append(
                f"[resolve_artist] 合唱名「{singer}」→ 新建独立歌手目录「{primary_artist}」"
                "（本地无匹配的已有目录）"
            )
        if primary_artist:
            # 用第一个匹配的独立歌手作为 singer，继续后续的同名消歧流程
            singer = primary_artist
            # 指定了 artist_id 时保留，否则清空避免错位
            if not preferred_id:
                preferred_id = ""

    # 同名消歧：可循环——选中候选，或「0」换歌手名后重新检索
    chosen: ArtistCandidate | None = None
    while True:
        candidates = catalog.find_same_name_artists(singer)
        if len(candidates) < 2:
            break

        choice_lines = _format_choice_lines(candidates)
        msgs.extend(choice_lines)
        chosen = _pick_by_id(candidates, preferred_id)
        if chosen is not None:
            break

        if preferred_id:
            msgs.append(f"[resolve_artist] --artist-id={preferred_id} 不在同名候选中，改为交互选择")
            preferred_id = ""  # 仅提示一次

        for line in choice_lines:
            print(line, flush=True)
        picked = _prompt_user_choose(candidates)
        if picked is None:
            new_singer = _prompt_new_singer(singer)
            msgs.append(f"[resolve_artist] 候选均不符合，重新输入歌手名：{singer} -> {new_singer}")
            singer = new_singer
            preferred_id = ""
            chosen = None
            continue
        chosen = picked
        break

    if chosen is not None:
        msgs.append(f"[resolve_artist] 已选择 id={chosen.artist_id}：{chosen.blurb}")
        artist = chosen.name
        artist_id = chosen.artist_id
        # 同名分目录，避免不同艺人歌库混在同一文件夹
        out_dir = os.path.join(CONFIG.output_root, f"{_safe_dir_name(artist)}_{artist_id}")
    else:
        # 唯一命中或无线索：走原名 / LLM 别名
        artist = singer
        artist_id = ""
        if len(candidates) == 1:
            artist_id = candidates[0].artist_id
            msgs.append(f"[resolve_artist] 唯一命中 id={artist_id}")
        elif preferred_id:
            artist_id = preferred_id
        # LLM 别名解析（无 key 时降级：直接用原名）
        suggestion = llm.ask(prompts.RESOLVE_ARTIST.format(singer=singer))
        if suggestion:
            suggestion = suggestion.strip().strip("。.,，")
            if suggestion and suggestion != singer:
                artist = suggestion
        out_dir = state.get("out_dir") or os.path.join(CONFIG.output_root, _safe_dir_name(artist))

    # iTunes 别名参考（展示用，不强制）
    alias = catalog.itunes_alias(artist) or catalog.itunes_alias(singer)
    msg = f"[resolve_artist] {singer} -> {artist}"
    if artist_id:
        msg += f"（netease_id={artist_id}）"
    if alias:
        msg += f"（iTunes 权威名：{alias}）"
    msgs.append(msg)
    return {
        "singer": singer,  # 可能因「重新输入」而更新
        "artist": artist,
        "artist_id": artist_id,
        "out_dir": out_dir,
        "messages": msgs,
    }
