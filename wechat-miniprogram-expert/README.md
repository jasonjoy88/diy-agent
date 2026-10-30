# 码小序（WeChat Mini Program Expert）

面向微信小程序全周期开发的专家：从需求确认、项目骨架、页面与组件、微信能力与云开发，到性能、审核合规、联调排障和提审续接。内置八份参考文件，输出可运行代码，并用《小程序项目档案》把多轮进度串起来。

本包为**平台无关**结构，可在 Cursor、Claude Code、Codex、以及其它支持「Agent 定义 + Skill」的环境中接入使用。

## 类型

Agent 型（单个 AI 专家）

## 目录结构

```
wechat-miniprogram-expert/
├── README.md
├── agents/
│   └── wechat-miniprogram-expert.md   # Agent 人设与工作流（码小序 v2.3.0）
├── skills/
│   └── wechat-miniprogram-reference/  # 小程序开发参考库
│       ├── SKILL.md
│       └── references/
│           ├── project-structure-config.md
│           ├── component-page-templates.md
│           ├── wechat-api-integration.md
│           ├── cloud-development.md
│           ├── performance-optimization.md
│           ├── review-compliance.md
│           ├── business-scenario-templates.md
│           └── debugging-troubleshooting.md
└── avatars/
    └── expert.png                     # 可选头像
```

## 功能

1. **先诊断再开方**：项目类型、技术栈、后端方案、当前阶段不足时先澄清（最多 4 问），或先给方案并写明假设。纯 API 查询直接给代码。
2. **任务分流**：项目搭建、页面与组件、微信能力、云开发、性能、审核合规、业务方案、调试排查八类，先读对应参考再输出。
3. **可运行交付**：页面给 WXML / WXSS / JS / JSON 四件套；支付与登录区分前后端，敏感签名留在服务端。
4. **全周期档案**：在工作目录维护 `小程序项目档案.md`（不含 AppID、密钥明文），回复开头标注所处阶段，交付末尾附「下次开发卡」。
5. **审核与防幻觉**：类目资质、隐私协议、虚拟支付、诱导分享主动提示；不编造 wx API、配置项和基础库版本号，规则以微信官方最新文档为准。
6. **会话续接**：用户说「继续 / 进度 / 复盘」时先读档案，复述进度再给下一步选项。

## 使用示例

- 帮我搭建一个微信原生小程序项目，电商向，用云开发，从零开始
- 用 WXML/WXSS 写一个商品列表页，要有加载、空态和分页
- 怎么接入微信支付，前端和云函数都要，并说明审核注意点
- 小程序首屏太慢，帮我按优先级给优化方案和代码
- 审核被拒了，这是驳回意见：{粘贴原文}，逐条给整改方案
- 报了这个错：{粘贴报错}，按现象→原因→排查→修复来查
- /进度

## 接入方式（按平台）

核心资产是 `agents/*.md` 与 `skills/**`。按目标平台惯例放置即可，无需平台专属注册脚本。宿主需要能读取参考文件，并能在用户工作目录创建、更新 `小程序项目档案.md`。

### Cursor

- **项目级 skill**：将 `skills/wechat-miniprogram-reference` 复制或软链到项目的 `.cursor/skills/`（或团队约定的 skills 目录）。
- **Agent 人设**：将 `agents/wechat-miniprogram-expert.md` 内容作为自定义 Agent / 系统提示，或在对话中 `@` 引用该文件。
- **个人全局**：也可放到 `~/.cursor/skills/wechat-miniprogram-reference/`。

### Claude Code / 其它 CLI Agent

- 将 `skills/wechat-miniprogram-reference` 放入该工具支持的 skills 目录（如项目 `.claude/skills/` 或工具文档指定路径）。
- 将 `agents/wechat-miniprogram-expert.md` 作为 Agent 定义或会话 system prompt 引入。

### 通用（任意支持 Markdown Agent 的环境）

1. 加载 `agents/wechat-miniprogram-expert.md` 作为角色与流程约束。
2. 确保运行时可读取 `skills/wechat-miniprogram-reference/`（尤其是 `references/` 下八份参考）。
3. 用「使用示例」中的提示词发起开发；多轮任务依赖工作目录中的 `小程序项目档案.md`。

## 头像（可选）

`avatars/` 下提供默认头像。如需替换：

- 格式：PNG（推荐）或 JPG
- 尺寸：512×512 px
- 大小：单张不超过 500KB

## 打包分享

```bash
zip -r wechat-miniprogram-expert.zip wechat-miniprogram-expert/
```

## 相关

对 diy-agent 内其它专家包做同样的「去平台绑定 / 多平台 README」处理时，见仓库根目录 `skills/agent-platform-agnostic/`。
