# Php Migration Analyst

面向 PHP 任意低版本升级到高版本（如 5.6→7.4、7.2→8.0、7.4→8.4、8.1→8.5 等）的只读排障专家：根据异常接口返回检索日志与代码，输出含证据链与修改建议的问题分析结论。

本包为**平台无关**结构，可在 Cursor、Claude Code、Codex、以及其它支持「Agent 定义 + Skill」的环境中接入使用。

## 类型

Agent 型（单个 AI 专家）

## 目录结构

```
php-migration-analyst/
├── README.md
├── agents/
│   └── php-migration-analyst.md    # Agent 人设与工作流
├── skills/
│   └── php-migration-analysis/     # 排障 skill + 迁移变更速查
│       ├── SKILL.md
│       └── references/
│           └── migration-changes.md
└── avatars/
    └── expert.png                  # 可选头像
```

## 功能

1. **确定版本区间**：确认源版本与目标版本，叠加区间内所有 major/minor 变更条目作为比对基础。
2. **解析异常**：从 HTTP 状态码、业务错误码、PHP 报错中提取错误类型、出错位置与请求标识，对照变更知识速查形成候选假设。
3. **检索日志**：按请求标识 → 错误特征 → 时间窗 → 接口路径逐级检索 PHP 错误日志、应用日志与 access log，记录每条证据来源。
4. **检索代码**：按文件:行号或函数名/类名定位出错点，验证是否命中区间内的迁移不兼容项，并检查调用方影响面。
5. **根因分析**：说明代码在源版本下为何正常、目标版本下为何报错，区分根因与次生现象；证据不足时列出待验证假设。
6. **输出结论**：产出《问题分析结论》（固定 Markdown 结构），含证据链、官方依据（php.net 迁移指南条目）与不代写代码的修改建议。

内置 skill `php-migration-analysis`，其中 `references/migration-changes.md` 收录 PHP 5.x–8.5 高频迁移变更速查表与版本区间叠加原则。

## 使用示例

- 我们准备把 PHP 从 {源版本} 升级到 {目标版本}，这是异常接口返回：{粘贴返回内容}，帮我定位根因并给出修改建议
- 接口报 Call to undefined function each()，帮我检索日志和代码，给出证据链与改法
- 帮我梳理项目从 PHP {源版本} 升级到 {目标版本} 的高频兼容风险点

## 接入方式（按平台）

核心资产是 `agents/*.md` 与 `skills/**`。按目标平台惯例放置即可，无需平台专属注册脚本。

### Cursor

- **项目级 skill**：将 `skills/php-migration-analysis` 复制或软链到项目的 `.cursor/skills/`（或团队约定的 skills 目录）。
- **Agent 人设**：将 `agents/php-migration-analyst.md` 内容作为自定义 Agent / 系统提示，或在对话中 `@` 引用该文件。
- **个人全局**：也可放到 `~/.cursor/skills/php-migration-analysis/`。

### Claude Code / 其它 CLI Agent

- 将 `skills/php-migration-analysis` 放入该工具支持的 skills 目录（如项目 `.claude/skills/` 或工具文档指定路径）。
- 将 `agents/php-migration-analyst.md` 作为 Agent 定义或会话 system prompt 引入。

### 通用（任意支持 Markdown Agent 的环境）

1. 加载 `agents/php-migration-analyst.md` 作为角色与流程约束。
2. 确保运行时可读取 `skills/php-migration-analysis/`（尤其是 `references/migration-changes.md`）。
3. 用「使用示例」中的提示词发起排障。

## 头像（可选）

`avatars/` 下提供默认头像。如需替换：

- 格式：PNG（推荐）或 JPG
- 尺寸：512×512 px
- 大小：单张不超过 500KB

## 打包分享

```bash
zip -r php-migration-analyst.zip php-migration-analyst/
```

## 相关

对 diy-agent 内其它专家包做同样的「去平台绑定 / 多平台 README」处理时，见仓库根目录 `skills/agent-platform-agnostic/`。
