---
name: agent-platform-agnostic
description: >-
  Strip platform-specific bindings (CodeBuddy, WorkBuddy, marketplace paths,
  register scripts) from diy-agent expert packages and rewrite README for
  multi-platform use (Cursor, Claude Code, Codex, etc.). Use when sanitizing
  an agent package, removing .codebuddy-plugin / workbuddy paths, or adapting
  diy-agent experts for more platforms.
---

# Agent 去平台绑定（多平台适配）

将 `diy-agent` 下的专家包从单一平台（CodeBuddy / WorkBuddy 等）解绑，保留核心能力，使 README 与目录结构适用于 Cursor、Claude Code、Codex 等任意支持 Agent + Skill 的环境。

## 何时使用

- 用户要求抹去 / 去掉 codebuddy、workbuddy、marketplace 安装路径等平台痕迹
- 新迁入的专家包带有 `.codebuddy-plugin/`、平台作者字段、`register_expert.py` 说明
- 需要把「同一套操作」套用到 diy-agent 内其它 agent 目录

## 保留 vs 删除

| 保留（平台无关核心） | 删除或改写（平台绑定） |
| --- | --- |
| `agents/*.md` 人设与工作流 | `.codebuddy-plugin/`、`.workbuddy*`、同类平台 manifest |
| `skills/**`（`SKILL.md` + references） | README 中的绝对安装路径（如 `~/.workbuddy/plugins/...`） |
| `avatars/`（可选） | 「运行 `register_expert.py` / 注册到 marketplace」等专属步骤 |
| 业务能力描述、使用示例提示词 | author 显示名中的 WorkBuddy/CodeBuddy 用户字样（若仍保留 manifest） |
| 打包 zip 的通用说明 | 仅某一 IDE 插件市场可用的字段（expertType、categoryId 等） |

## 操作步骤（对单个专家包）

对目标目录（如 `php-migration-analyst/`）按序执行：

### 1. 扫描平台痕迹

在专家包根目录检索（大小写不敏感）：

```text
codebuddy | workbuddy | .codebuddy-plugin | register_expert
marketplace/my-experts | plugins/marketplaces
```

记录命中文件，再决定删文件还是改文案。

### 2. 删除平台专属目录与清单

- 删除整个 `.codebuddy-plugin/`（含 `plugin.json`）
- 删除其它仅服务单一平台的配置目录（若存在且无跨平台等价物）
- **不要**删除 `agents/`、`skills/`、业务 references

### 3. 重写 README.md（多平台模板）

README 应包含：

1. **一句话能力** + 明确「平台无关 / 可多平台接入」
2. **类型**（Agent 型 / Skill 型等）
3. **目录结构**（树状列出 agents / skills / avatars）
4. **功能要点**（保留原业务能力，勿删排障流程）
5. **使用示例**（提示词，平台无关）
6. **接入方式（按平台）**——至少覆盖：
   - **Cursor**：skills → `.cursor/skills/` 或 `~/.cursor/skills/`；agent md 作自定义 Agent / `@` 引用
   - **Claude Code / 其它 CLI**：按该工具 skills 目录约定放置
   - **通用**：加载 agent md + 保证可读取 skills/references
7. **头像**（可选约束）
8. **打包分享**（`zip -r ...`）
9. **相关**：指向本 skill（`skills/agent-platform-agnostic/`），便于后续批处理

禁止再写：

- 某一用户机器上的绝对路径
- 仅 WorkBuddy/CodeBuddy 的注册命令
- 「必须放到某某 marketplace 目录」作为唯一安装方式

### 4. 自检

- [ ] 全文检索无 `codebuddy` / `workbuddy` / `register_expert`（除非在「历史说明」中明确标注已废弃，默认应清零）
- [ ] 无 `.codebuddy-plugin/` 目录
- [ ] `agents/` 与 `skills/` 仍完整可读
- [ ] README 含至少两种平台的接入说明 + 通用说明
- [ ] 未改坏 skill 内业务 references（如迁移速查表）

### 5. 可选：更新仓库根 README

在 `diy-agent/README.md` 中维护专家包列表，并注明 `skills/agent-platform-agnostic` 用于批量化去平台绑定。

## 批处理其它 agent

对 `diy-agent/` 下每个子目录（排除 `skills/` 自身）：

1. 若存在 `.codebuddy-plugin/` 或 README 含 workbuddy 路径 → 对本 skill 跑完整流程
2. 已是平台无关结构 → 跳过，仅确认 README 有「接入方式」小节
3. 多个包处理时保持 README「接入方式」章节口径一致（复制 Cursor / Claude / 通用三段即可）

## 输出约定

完成后向用户简要说明：

- 删除了哪些平台专属文件/目录
- README 主要改动点
- 核心 agents/skills 是否未动
- 若还有其它子包未处理，列出建议下一批目标
