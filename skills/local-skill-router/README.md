# 本地技能检索

给一句任务，在已经建好 codegraph 索引的本地技能库里选出技能，并排成一条短调用链。

本包为**平台无关**的 Skill，可在 Cursor、Claude Code、Codex，以及其它能读取本地目录并调用 codegraph 的环境中接入。它不注册到任何插件市场。

## 类型

Skill 型

## 目录结构

```
local-skill-router/
├── README.md
├── SKILL.md
├── config.example.json          # 复制为 config.json 后填写技能库路径
├── references/
│   ├── task-card.md             # 任务卡、形态键、任务类型命名
│   └── ranking.md               # codegraph 查询与调用链规则
└── scripts/
    └── rank_skills.py           # 只对图谱候选打分，不扫描技能库
```

## 功能

1. **定位技能库**：从用户给出的路径、环境变量 `SKILL_LIBRARY`，或 `config.json` 的 `skill_library` 得到库根目录。
2. **确认索引**：库根下要有 `.codegraph/`。没有则请用户在该目录执行 `codegraph init -i`，本技能不代建索引。
3. **解析任务**：抽出关键词、交付形态、领域和任务类型。
4. **图谱召回**：用 codegraph 在该库中查找 `SKILL.md`。
5. **排出短链**：按调研、生产、加工、质检排序，默认不超过 6 个技能。
6. **记住用过的链**：同一任务类型成功重复两次后，下次先走已验证组合。

## 使用示例

- 本地技能库在这个目录，帮我看看写一份客户建议书该用哪些技能
- 这个任务该用哪个 skill？库的 codegraph 已经建好了
- 从本地技能库给「竞品调研 + 汇报材料」排一条技能调用链

## 接入方式（按平台）

核心资产是 `SKILL.md`、`references/` 和 `scripts/rank_skills.py`。技能库是另一份已经建好 codegraph 的目录，不要把本技能目录本身当成技能库。

### Cursor

- **项目级**：将本目录复制或软链到项目的 `.cursor/skills/local-skill-router/`。
- **个人全局**：放到 `~/.cursor/skills/local-skill-router/`。
- 对话中 `@` 本目录的 `SKILL.md`，或让 Cursor 按技能描述自动选用。

### Claude Code / 其它 CLI Agent

- 将本目录放入该工具的 skills 目录（如项目 `.claude/skills/local-skill-router/`，或工具文档指定的用户级 skills 路径）。
- Codex 一类环境可放到该工具约定的用户 skills 目录，并保证运行时能读取 `references/` 与 `scripts/`。

### 通用

1. 让 Agent 读到 `SKILL.md`。
2. 保证能执行 `python scripts/rank_skills.py`，并能调用 codegraph（工具名通常是 `codegraph_explore`）。
3. 复制 `config.example.json` 为 `config.json`，把 `skill_library` 设为技能库根目录；也可以用环境变量 `SKILL_LIBRARY`。
4. 用「使用示例」里的说法发起一次检索。

## 打包分享

```bash
zip -r local-skill-router.zip local-skill-router/
```

不要把 `config.json` 和 `data/` 打进去。前者是本机路径，后者是使用记忆。

## 相关

本包按 `skills/agent-platform-agnostic/` 的口径编写：无单一平台清单、无市场注册步骤。对其它包做同样处理时，使用该 skill。
