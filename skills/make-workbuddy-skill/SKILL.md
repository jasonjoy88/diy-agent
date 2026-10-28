---
name: make-workbuddy-skill
version: 1.0.0
description: 创建 Tencent WorkBuddy 专家（Expert）、技能（Skill）、连接器（Connector）的规范、模板与脚手架。触发词：workbuddy专家、workbuddy技能、workbuddy连接器、创建专家、创建技能、创建连接器、plugin.json、SKILL.md、mcp.json、MCP连接器、专家团、自定义连接器。当用户要开发/封装/上架 WorkBuddy 的专家、技能或连接器，或需要校验这三类包是否合规时使用。不适用：单纯在客户端安装使用已上架的技能/连接器（那是产品操作，不需要本 skill）。
tags: workbuddy, 专家, 技能, 连接器, expert, skill, connector, plugin.json, SKILL.md, mcp
---

# Make WorkBuddy Skill —— 专家 / 技能 / 连接器生成器

## 三层模型（先想明白再动手）

**专家 = 人设和指令 + 知识和数据 + 技能和工具**

| 构件 | 解决什么 | 载体 | 一句话判断 |
|---|---|---|---|
| 专家 Expert | 怎么想、按什么方法论干活 | `.codebuddy-plugin/plugin.json` + `agents/*.md` | 需要一个"数字员工 / 团队" |
| 技能 Skill | 具体怎么做某件事（原子能力） | `SKILL.md`（+ references/scripts/templates） | 只是一段可复用的操作流程 |
| 连接器 Connector | 数据从哪来、写到哪去 | `mcp.json`（MCP 协议） | 只是打通一个外部服务 |

边界原则：**缺了技能，专家只能讲道理；缺了人设，技能只是散装工具。** 一个具体场景（如"周报整理专家"）= 1 个专家 + 2~3 个原子技能 + 1~2 个连接器。

## 决策流程

1. 用户要"一个能干活的角色 / 团队" → **专家**（走 Step 1）
2. 用户要"一段可复用的操作流程 / 自动化" → **技能**（走 Step 2）
3. 用户要"让 AI 读写某个外部系统（飞书 / 腾讯文档 / 数据库 / API）" → **连接器**（走 Step 3）
4. 专家需要调用外部服务时 → 在专家 `plugin.json` 的 `dependencies` 中声明连接器 / MCP 依赖（见 `references/expert-spec.md`「依赖声明」）

## Step 1：生成专家

```bash
python3 scripts/scaffold.py expert weekly-report          # 单专家
python3 scripts/scaffold.py expert research-team --team   # 专家团
```

1. 按 `references/expert-spec.md` 填写 `plugin.json` 全部展示字段：`displayDescription.zh` 必须 40–50 字；`tags`、`quickPrompts` 各 3 个；`defaultInitPrompt` 与 `quickPrompts[0]` 完全一致
2. 编写 `agents/<name>.md`：YAML frontmatter + 正文四段（角色身份 / 核心能力 / 工作流程 / 输出规范）
3. 放头像 `avatars/expert.png`：512×512、≤500KB、PNG
4. 需要外部服务时在 `dependencies` 声明依赖，**严禁硬编码真实 Token**（用 `${VAR}` 占位 + `tokenSchema`）

## Step 2：生成技能

```bash
python3 scripts/scaffold.py skill pdf-cleaner
```

1. 按 `references/skill-spec.md` 填写 `SKILL.md` frontmatter：`description` 必须写清"用途 + 触发词"——AI 靠它判断何时调用；按需加 `allowed-tools` 白名单（最小权限）
2. 正文写**给 AI 看的操作指令**：前置条件 → 分步执行 → 失败回退
3. 一个技能只做一件事；长知识放 `references/` 并用 `@references/xxx.md` 引用；确定性逻辑放 `scripts/`；模板放 `templates/`

## Step 3：生成连接器

```bash
python3 scripts/scaffold.py connector feishu-docs
```

1. 按 `references/connector-spec.md` 配置 `mcp.json`：标准 MCP 字段（url / type / headers）+ `x-workbuddy` 展示与鉴权元信息
2. 选鉴权方式：`oauth`（用户扫码，体验最好）/ `token`（API Key + `tokenSchema` 表单）/ `none`
3. `x-workbuddy.description` 必须写清"连接后能做什么"——用户授权决策全靠这句话

## 提交前校验清单

- [ ] 专家：`name` 小写字母 + 连字符，全局唯一；`expertType` 为 `agent`/`team`；team 时 `teamInfo`（leadAgent + memberAgents）齐全
- [ ] 专家：`displayDescription.zh` 40–50 字；`tags`、`quickPrompts` 各 3 个；`defaultInitPrompt` == `quickPrompts[0]`
- [ ] 专家：`avatar` 512×512 ≤500KB；`categoryId` 选最匹配分类（15 选 1）
- [ ] Agent 定义文件：frontmatter `name` 与文件名一致；`description` 写清激活时机；正文含角色/能力/流程/输出规范
- [ ] 技能：`description` 含触发词；`name` 与目录名一致；正文是给 AI 的指令而非给人看的介绍
- [ ] 连接器：`mcp.json` 是合法 JSON；无硬编码密钥；`${VAR}` 占位均有对应 `tokenSchema` 字段
- [ ] 打包：专家包根目录含 `.codebuddy-plugin/plugin.json`；技能包根目录含 `SKILL.md`；zip 后目录层级正确
- [ ] 开放平台提交 zip 解析失败时，对照本 skill 的 `references/` 与 `templates/` 逐字段排查

## 真实样例（本仓库）

`../workbuddyskills/` 下有 430+ 专家、297+ 技能、443+ 连接器真实上架包，卡壳时对照：

- 专家团范例：`../workbuddyskills/experts/a-share-analysis/`（8 agent 专家团 + members 展示配置）
- 技能范例：`../workbuddyskills/skills/academic-translation/`（modules + refs + glossary 分层组织）
- 连接器范例：`../workbuddyskills/connectors/135ai-editor/`（mcp.json + 配套调用技能）

## 参考文档

- 专家完整规范：`references/expert-spec.md`
- 技能完整规范：`references/skill-spec.md`
- 连接器完整规范：`references/connector-spec.md`
