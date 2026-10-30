#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 codegraph 已返回的技能候选打分并排出短调用链。不扫描技能库。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
LOG_FILE = SKILL_DIR / "data" / "decision_log.json"

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_.]{1,}")

FORM_WORDS = {
    "word": ["word", "文档", "报告", "docx", "公文", "合同", "标书"],
    "ppt": ["ppt", "pptx", "幻灯片", "演示", "汇报", "讲标", "路演"],
    "excel": ["excel", "xlsx", "表格", "报表", "清单", "台账"],
    "pdf": ["pdf", "电子书", "画册"],
    "html": ["网页", "html", "落地页", "官网", "专题页"],
    "code": ["代码", "脚本", "接口", "重构", "自动化"],
    "chart": ["图表", "可视化", "仪表盘", "数据图"],
    "map": ["地图", "gis", "地理"],
    "image": ["图片", "海报", "封面", "配图", "插图", "logo"],
    "video": ["视频", "短视频", "成片", "分镜", "剪辑"],
    "audio": ["音频", "配音", "播客", "音效"],
    "3d": ["3d", "三维", "建模"],
    "research": ["调研", "研究", "竞品", "尽调"],
}

STAGE_WORDS = {
    "调研": ["调研", "研究", "检索", "竞品", "资料", "搜索"],
    "生产": ["撰写", "生成", "方案", "实现", "写作", "创作"],
    "加工": ["排版", "格式", "导出", "幻灯片", "表格", "成稿", "pptx", "docx", "xlsx"],
    "质检": ["检查", "校对", "评审", "质检", "验收", "审核"],
}
STAGE_ORDER = ["调研", "生产", "加工", "质检"]


def tokenize(text: str) -> set:
    text = (text or "").lower()
    toks = set(WORD.findall(text))
    for run in CJK.findall(text):
        if len(run) <= 4:
            toks.add(run)
        for n in (2, 3):
            if len(run) >= n:
                for i in range(len(run) - n + 1):
                    toks.add(run[i:i + n])
    return toks


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def stage_of(text: str) -> str:
    low = (text or "").lower()
    best, best_n = "生产", 0
    for stage, words in STAGE_WORDS.items():
        n = sum(1 for w in words if w.lower() in low)
        if n > best_n:
            best, best_n = stage, n
    return best


def score_one(item: dict, card: dict) -> dict:
    keywords = [k for k in (card.get("keywords") or []) if k]
    domain = card.get("domain") or ""
    forms = card.get("deliverable_forms") or []
    blob = " ".join([
        item.get("id") or "",
        item.get("name") or "",
        item.get("description") or "",
    ])
    low = blob.lower()
    toks = tokenize(blob)

    name_hit = 0.0
    for kw in keywords:
        k = kw.lower()
        if not k:
            continue
        if k in (item.get("id") or "").lower() or k in (item.get("name") or "").lower():
            name_hit += 1.0
        elif k in low:
            name_hit += 0.45
    name_hit = min(name_hit, 3.0) / 3.0

    kw_toks = tokenize(" ".join(keywords))
    cover = 0.0
    if kw_toks:
        cover = len(kw_toks & toks) / len(kw_toks)

    domain_hit = 0.0
    if domain:
        d_toks = tokenize(domain)
        if domain.lower() in low:
            domain_hit = 1.0
        elif d_toks:
            domain_hit = len(d_toks & toks) / len(d_toks)

    form_fit = 0.0
    if forms:
        words = []
        for f in forms:
            words += FORM_WORDS.get(f, [f])
        hits = sum(1 for w in words if w.lower() in low)
        form_fit = min(hits, 4) / 4.0

    raw = (0.40 * cover + 0.30 * name_hit + 0.18 * form_fit + 0.12 * domain_hit) * 100
    text = " ".join([item.get("name") or "", item.get("description") or ""])
    stage = stage_of(text)
    # 成稿和质检技能往往不含行业词，形态对上时单独加分，避免被领域关键词淹没。
    if stage in ("加工", "质检") and form_fit >= 0.25:
        raw += 28
    score = round(max(0.0, min(100.0, raw)), 1)
    why = []
    if name_hit >= 0.34:
        why.append("名称命中关键词")
    elif cover >= 0.2:
        why.append("描述覆盖关键词")
    if form_fit >= 0.25 and forms:
        why.append("交付形态吻合")
    if domain_hit >= 0.5:
        why.append("领域对口")
    if not why:
        why.append("弱相关")
    return {
        "id": item.get("id") or item.get("name") or "",
        "name": item.get("name") or item.get("id") or "",
        "path": item.get("path") or "",
        "score": score,
        "stage": stage,
        "why": "；".join(why),
        "description": (item.get("description") or "")[:160],
    }


STAGE_FLOOR = {"调研": 40, "生产": 40, "加工": 20, "质检": 20}


def build_chain(rows: list, limit: int = 6) -> list:
    picked = []
    per_stage = {s: 0 for s in STAGE_ORDER}
    pool = rows
    for stage in STAGE_ORDER:
        for row in pool:
            if row["stage"] != stage or row in picked:
                continue
            if row["score"] < STAGE_FLOOR.get(stage, 40):
                continue
            if per_stage[stage] >= 2:
                break
            picked.append(row)
            per_stage[stage] += 1
            if len(picked) >= limit:
                return picked
    picked.sort(key=lambda r: STAGE_ORDER.index(r["stage"]) if r["stage"] in STAGE_ORDER else 9)
    return picked


def load_log() -> dict:
    if not LOG_FILE.is_file():
        return {"combos": {}}
    try:
        data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"combos": {}}
    if not isinstance(data, dict):
        return {"combos": {}}
    data.setdefault("combos", {})
    return data


def save_log(data: dict) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_combo(task_type: str) -> int:
    rec = load_log()["combos"].get(task_type)
    if not rec:
        print(f"MISS\t{task_type}")
        return 0
    flag = "PROMOTED" if rec.get("promoted") else "TRIAL"
    skills = ",".join(rec.get("skills") or [])
    print(f"{flag}\t{task_type}\t{skills}")
    return 0


def record(task_type: str, skills: list, ok: bool) -> int:
    data = load_log()
    rec = data["combos"].get(task_type) or {"skills": skills, "ok": 0, "bad": 0, "promoted": False}
    if rec.get("skills") != skills:
        rec = {"skills": skills, "ok": 0, "bad": 0, "promoted": False}
    if ok:
        rec["ok"] = int(rec.get("ok") or 0) + 1
    else:
        rec["bad"] = int(rec.get("bad") or 0) + 1
    rec["promoted"] = rec["ok"] >= 2 and rec["bad"] == 0
    data["combos"][task_type] = rec
    save_log(data)
    state = "已晋级" if rec["promoted"] else "试用中"
    print(f"{state}\t{task_type}\t{','.join(skills)}\tok={rec['ok']}")
    return 0


def render(card: dict, rows: list, chain: list) -> None:
    print(f"任务类型：{card.get('task_type') or '未分类'}")
    if card.get("deliverable_forms"):
        print("交付形态：" + "、".join(card["deliverable_forms"]))
    print()
    print("建议调用链")
    if not chain:
        print("  （无够格候选）")
        return
    for i, row in enumerate(chain, 1):
        print(f"  {i}. [{row['stage']}] {row['name']}（{row['id']}）")
        print(f"     {row['score']:.1f}  {row['why']}")
        if row["path"]:
            print(f"     {row['path']}")


def main() -> int:
    ap = argparse.ArgumentParser(description="为 codegraph 召回的技能候选打分")
    ap.add_argument("--card", help="任务解析卡 JSON")
    ap.add_argument("--candidates", help="候选技能 JSON 数组")
    ap.add_argument("--check-combo", metavar="TASK_TYPE", help="查看该任务类型是否已有验证组合")
    ap.add_argument("--record", action="store_true", help="写入本次调用链")
    ap.add_argument("--task-type", default="")
    ap.add_argument("--skills", default="", help="按调用顺序逗号分隔的技能 id")
    ap.add_argument("--ok", action="store_true")
    args = ap.parse_args()

    if args.check_combo:
        return check_combo(args.check_combo)
    if args.record:
        skills = [s for s in args.skills.split(",") if s]
        task_type = args.task_type or "未分类任务"
        if not skills:
            print("[x] --record 需要 --skills")
            return 2
        return record(task_type, skills, args.ok)

    if not args.card or not args.candidates:
        print("[x] 打分需要 --card 与 --candidates")
        return 2
    card = load_json(Path(args.card))
    if not isinstance(card, dict):
        print("[x] 任务卡必须是 JSON 对象")
        return 2
    raw = load_json(Path(args.candidates))
    if not isinstance(raw, list):
        print("[x] 候选必须是 JSON 数组")
        return 2
    rows = [score_one(it, card) for it in raw if isinstance(it, dict)]
    rows = [r for r in rows if r["id"] and r["id"] != "local-skill-router"]
    rows.sort(key=lambda r: (-r["score"], r["id"]))
    render(card, rows, build_chain(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
