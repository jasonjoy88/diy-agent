"""本地音乐库整理脚本。

功能：
  1. 扫描 music/ 下所有顶层目录，识别哪些是「独立歌手目录」（目录名不含合唱分隔符）
  2. 识别合唱歌曲 / 合唱目录（目录名或文件名含 _、&、、、/、  等分隔符）
  3. 合唱歌曲按分隔符拆分出候选歌手，优先归入第一个已存在的独立歌手目录
  4. 消除嵌套子目录（歌手目录下的子目录里的歌曲上移到歌手目录）
  5. 处理重复文件（同名则保留音质更好的，或按优先级 mp3 > flac > ogg > wav）

用法：
  python organize_library.py [--dry-run] [--root PATH]

  --dry-run   只打印计划，不实际移动文件
  --root      指定音乐根目录，默认 music/
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

# 合唱歌曲的歌手分隔符（按出现频率排序）
# 全角/半角下划线、&、顿号、逗号、斜杠、空格分隔等
_CHORUS_SEPARATORS = re.compile(r'[_\&、，,/\s]+')

# 音频格式优先级（同歌同名时，值越小优先级越高）
_EXT_PRIORITY = {".mp3": 0, ".flac": 1, ".ogg": 2, ".wav": 3}
AUDIO_EXTS = set(_EXT_PRIORITY.keys())

# 关联文件后缀（需要一起移动的配套文件）
_SIDE_SUFFIXES = (".lrc", ".cover.jpg", ".cover.png")


def is_chorus_name(name: str) -> bool:
    """判断名称是否像合唱（多歌手）名称。"""
    return bool(_CHORUS_SEPARATORS.search(name))


def split_artists(name: str) -> list[str]:
    """按合唱分隔符拆分出歌手列表，去空、去重、保序。"""
    parts = [p.strip() for p in _CHORUS_SEPARATORS.split(name) if p.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def safe_dir_name(name: str) -> str:
    """目录名安全化（去除非法字符）。"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def collect_audio_files(root: str) -> list[str]:
    """递归收集所有音频文件路径。"""
    result: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in AUDIO_EXTS:
                result.append(os.path.join(dirpath, name))
    return result


def detect_solo_artists(root: str) -> dict[str, str]:
    """检测独立歌手目录。

    返回 {歌手名: 目录绝对路径}。
    判断标准：顶层目录名不含合唱分隔符，且目录下有音频文件。
    """
    artists: dict[str, str] = {}
    if not os.path.isdir(root):
        return artists
    for name in os.listdir(root):
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        if is_chorus_name(name):
            continue
        # 目录下有音频才算有效歌手目录
        has_audio = any(
            os.path.splitext(f)[1].lower() in AUDIO_EXTS
            for f in os.listdir(full)
            if os.path.isfile(os.path.join(full, f))
        )
        if has_audio:
            artists[name] = full
            continue
        # 也可能音频在子目录里（嵌套情况），再探一层
        for sub in os.listdir(full):
            sub_full = os.path.join(full, sub)
            if os.path.isdir(sub_full):
                for f in os.listdir(sub_full):
                    if os.path.splitext(f)[1].lower() in AUDIO_EXTS:
                        has_audio = True
                        break
            if has_audio:
                break
        if has_audio:
            artists[name] = full
    return artists


def resolve_target_artist(file_artist_hint: str, solo_artists: dict[str, str]) -> str | None:
    """根据文件名中的 artist 部分，判断应该归属到哪个独立歌手目录。

    - 如果 file_artist_hint 本身就是独立歌手，返回该歌手名
    - 如果是合唱名，拆分后找第一个存在于 solo_artists 的歌手
    - 都找不到返回 None
    """
    if file_artist_hint in solo_artists:
        return file_artist_hint
    if not is_chorus_name(file_artist_hint):
        return None
    for artist in split_artists(file_artist_hint):
        if artist in solo_artists:
            return artist
    return None


def extract_title_and_artist_hint(filename: str) -> tuple[str, str]:
    """从文件名提取 (title, artist_hint)。

    有 " - " 分隔时：artist_hint = 前半段，title = 后半段（去扩展名）
    无时：artist_hint = "", title = 文件名（去扩展名）
    """
    base = os.path.splitext(filename)[0]
    if " - " in base:
        artist_part, title_part = base.split(" - ", 1)
        return title_part.strip(), artist_part.strip()
    return base, ""


def sidecar_files(audio_path: str) -> list[str]:
    """找出音频文件的配套文件（.lrc、.cover.jpg 等）。"""
    base = os.path.splitext(audio_path)[0]
    results: list[str] = []
    for suffix in _SIDE_SUFFIXES:
        cand = base + suffix
        if os.path.isfile(cand):
            results.append(cand)
    return results


def plan_moves(
    root: str,
    solo_artists: dict[str, str],
) -> list[tuple[str, str, str, str]]:
    """生成移动计划。

    返回 [(源路径, 目标路径, 原因说明, 归一化歌名), ...]
    归一化歌名用于去重检测（同一首歌的不同 artist 前缀版本视为重复）。
    """
    plans: list[tuple[str, str, str, str]] = []
    audio_files = collect_audio_files(root)

    for src in audio_files:
        src_dir = os.path.dirname(src)
        src_filename = os.path.basename(src)
        rel_dir = os.path.relpath(src_dir, root)

        title, artist_hint = extract_title_and_artist_hint(src_filename)
        norm_title = title.lower()  # 归一化歌名用于去重

        # 判断目标歌手
        target_artist: str | None = None
        reason = ""

        # 先看所在目录（顶层目录名或相对路径第一段）
        top_dir = rel_dir.split(os.sep)[0] if rel_dir != "." else ""

        if top_dir and not is_chorus_name(top_dir) and top_dir in solo_artists:
            # 已经在正确的独立歌手目录下
            if rel_dir == top_dir:
                # 直接在歌手根目录，无需移动
                continue
            # 在子目录里，需要上移到歌手根目录
            target_artist = top_dir
            reason = f"子目录上移: {rel_dir} -> {top_dir}"
        elif top_dir and is_chorus_name(top_dir):
            # 顶层就是合唱目录名
            target_artist = resolve_target_artist(top_dir, solo_artists)
            if target_artist:
                reason = f"合唱目录归属: {top_dir} -> {target_artist}"
            else:
                # 没找到任何已有的独立歌手，用第一个歌手新建
                parts = split_artists(top_dir)
                if parts:
                    target_artist = parts[0]
                    reason = f"新建目录: {top_dir} -> {target_artist}"
        elif artist_hint and is_chorus_name(artist_hint):
            # 目录名不像歌手，但文件名里有合唱 artist 信息
            target_artist = resolve_target_artist(artist_hint, solo_artists)
            if target_artist:
                reason = f"文件名合唱归属: {artist_hint} -> {target_artist}"

        if not target_artist:
            # 无法识别，跳过
            continue

        # 构建目标路径：保留原文件名，只改目录
        target_dir = os.path.join(root, safe_dir_name(target_artist))
        dst = os.path.join(target_dir, src_filename)
        plans.append((src, dst, reason, norm_title))

    return plans


def dedup_plans(
    plans: list[tuple[str, str, str, str]],
) -> list[tuple[str, str, str, str]]:
    """去重：同一目标目录下同一首歌（归一化歌名相同）只保留一个。

    优先级：
      1. 格式优先级（mp3 > flac > ogg > wav）
      2. 独唱版本优先于合唱版本（文件名 artist 部分不含分隔符）
    """
    # 按 (目标目录, 归一化歌名) 分组
    groups: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for src, dst, reason, norm_title in plans:
        dst_dir = os.path.dirname(dst)
        key = (dst_dir, norm_title)
        groups.setdefault(key, []).append((src, dst, reason))

    deduped: list[tuple[str, str, str, str]] = []
    for (dst_dir, norm_title), items in groups.items():
        if len(items) == 1:
            src, dst, reason = items[0]
            deduped.append((src, dst, reason, norm_title))
            continue

        # 排序：独唱优先（artist 不是合唱）> 格式优先级
        def _rank(item: tuple[str, str, str]) -> tuple[int, int]:
            src, _dst, _r = item
            filename = os.path.basename(src)
            title_part, artist_part = extract_title_and_artist_hint(filename)
            solo_bonus = 0 if (artist_part and not is_chorus_name(artist_part)) else 1
            ext = os.path.splitext(src)[1].lower()
            prio = _EXT_PRIORITY.get(ext, 99)
            return (solo_bonus, prio)

        items.sort(key=_rank)
        best_src, best_dst, best_reason = items[0]
        extra = f"（去重：保留 {os.path.basename(best_src)}，跳过 {len(items)-1} 个同歌版本）"
        deduped.append((best_src, best_dst, best_reason + extra, norm_title))

    return deduped


def execute_plans(
    plans: list[tuple[str, str, str, str]],
    dry_run: bool = True,
) -> tuple[int, int]:
    """执行移动计划。返回 (成功数, 跳过/失败数)。"""
    ok = 0
    skipped = 0
    for src, dst, reason, _norm_title in plans:
        if os.path.abspath(src) == os.path.abspath(dst):
            continue
        if dry_run:
            print(f"  [计划] {os.path.basename(src)}")
            print(f"         从: {src}")
            print(f"         到: {dst}")
            print(f"         原因: {reason}")
            ok += 1
            continue

        dst_dir = os.path.dirname(dst)
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError as e:
            print(f"  [失败] 无法创建目录 {dst_dir}: {e}")
            skipped += 1
            continue

        # 目标已存在则跳过（去重逻辑已保证保留最佳版本，目标已有就不动）
        if os.path.exists(dst):
            print(f"  [跳过] 目标已存在: {dst}")
            skipped += 1
            continue

        try:
            shutil.move(src, dst)
            # 移动配套文件（.lrc / .cover.jpg 等）
            src_base = os.path.splitext(src)[0]
            dst_base = os.path.splitext(dst)[0]
            src_dir = os.path.dirname(src)
            for sc in sidecar_files(src):
                sc_name = os.path.basename(sc)
                # 如果 base 名变了，配套文件也对应改名
                if src_base != dst_base:
                    # 计算相对于 src_base 的后缀
                    sc_rel = sc[len(src_base):]
                    new_sc_name = os.path.basename(dst_base) + sc_rel
                    sc_dst = os.path.join(dst_dir, new_sc_name)
                else:
                    sc_dst = os.path.join(dst_dir, sc_name)
                if not os.path.exists(sc_dst):
                    shutil.move(sc, sc_dst)
            ok += 1
        except OSError as e:
            print(f"  [失败] {src} -> {dst}: {e}")
            skipped += 1

    return ok, skipped


def cleanup_empty_dirs(root: str, dry_run: bool = True) -> int:
    """清理空目录（从深层往表层删）。返回删除的空目录数。"""
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if dirpath == root:
            continue
        try:
            contents = os.listdir(dirpath)
        except OSError:
            continue
        if not contents:
            if dry_run:
                print(f"  [删除空目录] {dirpath}")
            else:
                try:
                    os.rmdir(dirpath)
                except OSError:
                    continue
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="整理本地音乐库：合唱歌曲归属到独立歌手目录")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parent / "music"),
        help="音乐根目录（默认: music/）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印计划，不实际移动",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"目录不存在: {root}")
        return 1

    print(f"音乐根目录: {root}")
    print()

    # 1. 识别独立歌手
    solo_artists = detect_solo_artists(root)
    print(f"检测到 {len(solo_artists)} 个独立歌手目录:")
    for name in sorted(solo_artists.keys()):
        print(f"  - {name}")
    print()

    # 2. 生成移动计划
    plans = plan_moves(root, solo_artists)
    plans = dedup_plans(plans)

    if not plans:
        print("没有需要整理的文件。")
        return 0

    print(f"共 {len(plans)} 个文件待移动:")
    print()

    # 3. 执行
    ok, skipped = execute_plans(plans, dry_run=args.dry_run)
    print()

    # 4. 清理空目录
    empty_removed = cleanup_empty_dirs(root, dry_run=args.dry_run)
    print()

    if args.dry_run:
        print(f"--- 预演完成 ---")
        print(f"  计划移动: {ok} 个文件")
        print(f"  计划删除空目录: {empty_removed} 个")
    else:
        print(f"--- 整理完成 ---")
        print(f"  成功移动: {ok} 个文件")
        print(f"  跳过/失败: {skipped} 个文件")
        print(f"  删除空目录: {empty_removed} 个")

    return 0


if __name__ == "__main__":
    sys.exit(main())
