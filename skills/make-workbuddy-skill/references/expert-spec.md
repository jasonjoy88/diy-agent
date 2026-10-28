# 专家（Expert）完整规范

来源：WorkBuddy 开放平台官方文档（open.workbuddy.cn/docs/expert）。

## 1. 包结构

```
my-expert/
├── .codebuddy-plugin/
│   └── plugin.json         # 核心配置：运行配置 + 市场展示信息
├── avatars/
│   └── expert.png          # 512×512，≤500KB，PNG（推荐）或 JPG
├── agents/
│   └── my-expert.md        # Agent 定义：YAML frontmatter + 系统提示词正文
└── README.md
```

专家团（expertType=team）在 agents/ 下放多个 Agent 定义文件，avatars/ 下放团队头像 + 每个成员头像。

## 2. plugin.json 字段

### 基础字段

| 字段 | 必填 | 说明 |
|---|---|---|
| name | ✅ | 唯一标识：小写字母 + 连字符，如 `design-experts` |
| version | ✅ | 语义化版本，如 `1.0.0` |
| description | ✅ | 英文简短描述 |
| author | ✅ | `{name, email}`；示例包可只有 name |
| agents | ✅ | Agent 定义文件路径数组，如 `["./agents/my-expert.md"]` |
| skills | 否 | 内置技能目录路径数组，如 `["./skills/my-skill"]` |
| homepage / license / keywords | 否 | 项目主页 / 许可证 / 搜索标签 |

### 类型字段

| 字段 | 必填 | 说明 |
|---|---|---|
| expertType | ✅ | `"agent"`（单专家）或 `"team"`（专家团） |
| agentName | ✅ | 主 Agent 名称 = agents/ 下 md 文件名（不含 .md） |
| teamInfo | team 必填 | `{ "leadAgent": "主理人", "memberAgents": ["成员A", ...] }` |

### 展示字段

| 字段 | 必填 | 说明 |
|---|---|---|
| displayName | ✅ | `{en, zh}` 市场展示名称 |
| profession | ✅ | `{en, zh}` 职业头衔 |
| displayDescription | ✅ | `{en, zh}` 市场描述。**中文 40–50 字**，突出核心能力 |
| avatar | ✅ | 头像相对路径，如 `avatars/expert.png` |
| categoryId | ✅ | 行业分类（见第 5 节，15 选 1） |
| defaultInitPrompt | ✅ | 首次对话默认提示语，**必须与 quickPrompts 第一条一致** |
| plugin | ✅ | 与 name 字段值一致 |
| tags | ✅ | 固定 3 个 `{en, zh}`，用于搜索和市场展示 |
| quickPrompts | ✅ | 固定 3 个 `{en, zh}`，展示在专家卡片上引导快速提问 |
| members | 团队建议 | 每个成员的 `{id, name{en,zh}, profession{en,zh}, avatar, role: "lead"/"member"}` |

## 3. Agent 定义文件（agents/*.md）

```markdown
---
name: my-expert                     # 与文件名一致（不含 .md）
description: 英文功能描述            # AI 用来判断何时激活该专家
displayName:
  en: "Diana"
  zh: "黛安娜"
profession:
  en: "Design System Architect"
  zh: "设计系统文档架构师"
maxTurns: 100                       # 可选，默认 50
skills:                             # 可选，预加载技能名称列表
  - some-skill
---

# 角色身份（一句话定人设）

## 核心能力（3–5 条，带编号）
## 工作流程（分步骤：先做什么、后做什么、缺信息时怎么办）
## 输出规范（格式、字段、约束）
```

提示词正文骨架：**角色身份 → 核心能力 → 工作流程 → 输出规范**。

### 关于工具

开发者**不可自行添加 tools**：所有工具权限由系统统一分配。内置工具（Read / Write / Grep / Glob / Bash / WebSearch / WebFetch / AgentTool / SendMessage）由系统自动分配，AgentTool 与 SendMessage 仅主理人可用。

## 4. 依赖声明（可选，仅当必须调用外部服务时）

用户召唤专家（团）前，WorkBuddy 弹出内联引导卡片逐个引导连接；已连接过的依赖不重复引导。

### 方式一：plugin.json 内声明（推荐）

```json
{
  "dependencies": {
    "mcpServers": "./.mcp.json",
    "connectors": ["tencent-docs", "feishu"]
  }
}
```

- `dependencies.mcpServers`：string 或 string[]，指向 `.mcp.json`
- `dependencies.connectors`：已上架连接器 ID 列表；引导卡片信息由连接器自身提供，无需在专家包内重复声明

### 方式二：插件根目录 .mcp.json（兜底）

plugin.json 未声明 `dependencies.mcpServers` 时，系统自动读取插件根目录 `.mcp.json`。格式同标准 MCP 配置，每个 server 可附加 `x-workbuddy` 元信息（详见 connector-spec.md）。

### 注意事项

- `x-workbuddy` 是私有字段，连接后写入用户「自定义连接器」配置时会被剥离，不污染本地 mcp.json
- **专家包内严禁硬编码任何真实 Token / 密钥**；Token 由用户本地填写保存
- icon 相对路径基于「该 MCP 声明文件所在目录」解析

## 5. 行业分类（categoryId）

| categoryId | 分类 |
|---|---|
| 01-ProductDesign | 产品设计 |
| 02-Engineering | 技术工程 |
| 03-GameSpatial | 游戏空间 |
| 04-DataAI | 数据智能 |
| 05-MarketingGrowth | 营销增长 |
| 06-ContentCreative | 内容创作 |
| 07-SalesCommerce | 销售商务 |
| 08-FinanceInvestment | 金融投资 |
| 09-OperationsHR | 运营人力 |
| 10-ProjectQuality | 项目质量 |
| 11-SecurityCompliance | 法务安全 |
| 12-IndustryConsultant | 行业顾问 |
| 13-TencentZone | 腾讯专家 |
| 14-WorldWise | 全球发展 |
| 15-Education | 教育学习 |

## 6. 头像规范

512×512 px 正方形、单张 ≤500KB、PNG（推荐）或 JPG、漫画/插画风格、符合角色定位。全部放 `avatars/`，plugin.json 用相对路径引用。
