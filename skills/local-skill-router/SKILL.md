---
name: local-skill-router
description: >-
  从已建立 codegraph 索引的本地技能库中检索并推荐技能调用链。平台无关，适用于
  Cursor、Claude Code、Codex，以及任何能读取本地目录并调用 codegraph 的环境。
  当用户说「该用哪个技能」「从本地技能库推荐」「帮我选技能」「技能编排」
  「这个任务用什么 skill」「自动匹配技能」时使用。
---

# 本地技能检索

给一句任务，在**本地技能库**里找出该用哪几个技能、按什么顺序用。召回只走该库的 codegraph 索引。

核心信念：技能不靠印象挑，靠任务卡 + 图谱召回 + 打分。

## 技能库在哪

按这个顺序确定根目录，命中即停：

1. 用户这句话里给出的路径
2. 环境变量 `SKILL_LIBRARY`
3. 本技能目录下的 `config.json` 字段 `skill_library`（由 `config.example.json` 复制而来）

三项都空着时，问用户要一次技能库根目录，不要猜。不要把某一台机器上的绝对路径写进仓库。

确认 `<库根>/.codegraph/` 存在。不存在就停，请用户在该目录执行 `codegraph init -i`。不要自己建索引，也不要改用全库文件名扫描。

## 步骤

### 0. 组合记忆

任务类型先对照 `references/task-card.md` 的命名表。

```bash
python scripts/rank_skills.py --check-combo "任务类型"
```

- 输出 `PROMOTED`：用 codegraph 按这些技能 id 复核是否仍在库中。都在，就沿用这条链，跳过打分。
- `TRIAL` 或 `MISS`：继续第 1、2 步。

### 1. 任务卡

先读 `references/task-card.md`。填好 `keywords`、`deliverable_forms`、`domain`、`task_type`。交付形态和受众都判断不了时，先问用户，不要硬检索。

把卡存成临时 JSON，供第 3 步使用。

### 2. 用 codegraph 召回

读 `references/ranking.md`。对技能库根目录调用 codegraph（工具名通常是 `codegraph_explore`）：

- `projectPath` = 技能库根目录
- `query` = 关键词 + 领域 + 形态触发词 + `SKILL`
- `maxFiles` = 12

只收返回结果里的 `SKILL.md`。命中偏少时用任务类型词再查一次。两次之后仍没有技能文件，就告诉用户库里没有对口技能，停止。

把候选写成 JSON 数组：`id`、`name`、`description`、`path`。排除 `local-skill-router` 自己。

### 3. 打分并收成短链

```bash
python scripts/rank_skills.py --card card.json --candidates candidates.json
```

脚本只给候选排序，不扫描磁盘上的技能库。链的顺序是 **调研 → 生产 → 加工 → 质检**，默认不超过 6 个。有质检命中就不要省掉。

描述和分数打架时，以读到的 description 为准，收紧关键词后再查一次图谱。

### 4. 告诉用户

只报入选的技能：名称、阶段、一句话理由、`SKILL.md` 路径。然后按这个顺序加载并执行。不要把图谱里的其余命中倒出来。

### 5. 做完后记一条

```bash
python scripts/rank_skills.py --record --task-type "正式方案类文档" --skills "id-a,id-b,id-c" --ok
```

`--skills` 按真实调用顺序写。同一任务类型、同一顺序累计成功 2 次且没有失败记录，会晋级为 `PROMOTED`。记忆写在本技能的 `data/decision_log.json`，不要提交进仓库。

## 红线

1. 先有任务卡，再查图谱。
2. 召回只用技能库上的 codegraph。索引不在就停。
3. 不凭印象从别的目录挑技能。
4. 调用链保持短。少而准。
5. 交付后记下实际用过的链。不记，下次同类任务还是从头再猜。
