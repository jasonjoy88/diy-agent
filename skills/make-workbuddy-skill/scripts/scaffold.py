#!/usr/bin/env python3
"""make-workbuddy-skill 脚手架：生成 WorkBuddy 专家 / 技能 / 连接器包骨架。

用法:
    python3 scaffold.py expert <name> [--team] [--out DIR]
    python3 scaffold.py skill <name> [--out DIR]
    python3 scaffold.py connector <name> [--out DIR]

示例:
    python3 scaffold.py expert weekly-report
    python3 scaffold.py expert research-team --team
    python3 scaffold.py skill pdf-cleaner
    python3 scaffold.py connector feishu-docs --out ./output

生成后所有 {{TODO_*}} 占位符需人工填写，详见 ../SKILL.md 与 ../references/。
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def to_kebab(name: str) -> str:
    """转小写连字符命名；已合规则原样返回。"""
    kebab = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    if not kebab:
        sys.exit(f"错误: 名称 {name!r} 无法转换为合法标识（需含字母或数字）")
    return kebab


def render(src: Path, dst: Path, tokens: dict) -> None:
    text = src.read_text(encoding="utf-8")
    for k, v in tokens.items():
        text = text.replace("{{" + k + "}}", v)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")


def scaffold_expert(name: str, team: bool, out: Path) -> Path:
    kebab = to_kebab(name)
    root = out / kebab
    if root.exists():
        sys.exit(f"错误: 目录已存在 {root}")
    tokens = {"NAME_KEBAB": kebab}

    tpl = TEMPLATES / "expert"
    plugin_src = tpl / ("plugin-team.json" if team else "plugin.json")
    render(plugin_src, root / ".codebuddy-plugin" / "plugin.json", tokens)
    render(tpl / "agent.md", root / "agents" / f"{kebab}.md", tokens)
    (root / "avatars").mkdir(parents=True)
    (root / "README.md").write_text(f"# {kebab}\n", encoding="utf-8")
    return root


def scaffold_skill(name: str, out: Path) -> Path:
    kebab = to_kebab(name)
    root = out / kebab
    if root.exists():
        sys.exit(f"错误: 目录已存在 {root}")
    render(TEMPLATES / "skill" / "SKILL.md", root / "SKILL.md", {"NAME_KEBAB": kebab})
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "templates").mkdir()
    return root


def scaffold_connector(name: str, out: Path) -> Path:
    kebab = to_kebab(name)
    root = out / kebab
    if root.exists():
        sys.exit(f"错误: 目录已存在 {root}")
    tpl = TEMPLATES / "connector"
    render(tpl / "mcp.json", root / "mcp.json", {"NAME_KEBAB": kebab})
    render(tpl / "mcp-full.example.json", root / "mcp-full.example.json", {"NAME_KEBAB": kebab})
    return root


NEXT_STEPS = {
    "expert": [
        "填写 .codebuddy-plugin/plugin.json 中所有 {{TODO_*}} 占位符",
        "   - displayDescription.zh 必须 40-50 字；tags / quickPrompts 各 3 个",
        "   - defaultInitPrompt 必须与 quickPrompts[0] 一致",
        "编写 agents/*.md 正文：角色身份 / 核心能力 / 工作流程 / 输出规范",
        "放入头像 avatars/expert.png（512x512, <=500KB, PNG）",
        "需要外部服务时在 plugin.json 声明 dependencies（严禁硬编码 Token）",
        "对照 references/expert-spec.md 校验后打包 zip",
    ],
    "skill": [
        "填写 SKILL.md frontmatter：description 必须含用途 + 触发词",
        "编写正文：前置条件 / 执行步骤 / 失败处理（给 AI 看的指令）",
        "按需创建 references/、scripts/、templates/ 子资源",
        "对照 references/skill-spec.md 校验后打包 zip",
    ],
    "connector": [
        "填写 mcp.json：url / type / timeout（Token 用 ${VAR} 占位，禁止硬编码）",
        "参考 mcp-full.example.json 添加 x-workbuddy 展示与鉴权元信息",
        "   - description 必须写清'连接后能做什么'",
        "   - 选择 auth.type: oauth / token / none",
        "对照 references/connector-spec.md 校验",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 WorkBuddy 专家/技能/连接器包骨架")
    parser.add_argument("type", choices=["expert", "skill", "connector"], help="生成类型")
    parser.add_argument("name", help="包名（将自动转为小写连字符）")
    parser.add_argument("--team", action="store_true", help="专家团模式（仅 expert 有效）")
    parser.add_argument("--out", type=Path, default=Path.cwd(), help="输出目录（默认当前目录）")
    args = parser.parse_args()

    builders = {
        "expert": lambda: scaffold_expert(args.name, args.team, args.out),
        "skill": lambda: scaffold_skill(args.name, args.out),
        "connector": lambda: scaffold_connector(args.name, args.out),
    }
    root = builders[args.type]()

    print(f"已生成 {args.type} 包: {root}")
    print("\n下一步:")
    for step in NEXT_STEPS[args.type]:
        print(f"  {step}")


if __name__ == "__main__":
    main()
