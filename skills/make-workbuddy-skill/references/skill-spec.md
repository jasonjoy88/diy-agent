# 技能（Skill）完整规范

来源：WorkBuddy 开放平台官方文档（open.workbuddy.cn/docs/skill）。

## 1. 包结构

```
{skill-name}/
├── SKILL.md              # ★ 技能定义（必须）
├── references/           # 参考资料（可选）：API 规范、字段类型、领域知识、示例数据
│   ├── api-spec.md
│   └── examples.md
├── scripts/              # 可执行脚本（可选）：AI 通过 Bash 工具执行
│   ├── fetch-data.js
│   └── transform.py
└── templates/            # 模板文件（可选）：报告/工作流模板
    ├── report.sh
    └── workflow.sh
```

`SKILL.md` 使用 YAML frontmatter + Markdown 正文。

## 2. frontmatter 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| name | ✅ | 技能标识，与目录名一致（小写连字符） |
| display_name | ✅ | 市场中文展示名称 |
| display_name_en | ✅ | 市场英文展示名称 |
| description | ✅ | **写清用途和触发词**——AI 靠它判断何时调用 |
| description_zh | ✅ | 简短中文介绍，展示在技能详情页 |
| description_en | ✅ | 简短英文介绍，展示在技能详情页 |
| allowed-tools | 否 | 工具白名单，逗号分隔（最小权限原则） |
| version | ✅ | 版本号 |
| examples_zh | 否 | 使用案例（中文版），展示在详情页「试试这样用」 |
| examples_en | 否 | 使用案例（英文版） |
| author | ✅ | 合作方名称 |

## 3. 正文写法

正文是**给 AI 看的操作指令**，不是给人看的功能介绍：

```markdown
# 技能名称

## 前置条件
使用 XX 连接器 / 需要用户提供 ...

## 执行步骤
当用户需要做 XX 时，按以下步骤执行：
1. 先检查 ...（前置条件）
2. 调用 scripts/xxx.js 获取数据
3. 按 templates/report.sh 模板生成

## 失败处理
- 返回 401 → 提示重新授权
- 缺参数 → 向用户索取
```

## 4. 定义技巧

- **一个技能只做一件事**。"大而全"的技能触发率低、误调用高
- `description` 同时写「能干什么」+「什么时候触发」，例：
  `将文章正文自动导入 135 编辑器生成 AI 排版。当用户要求自动导入文章、处理正文或生成排版内容时使用。`
- 长知识放 `references/`，正文用 `@references/xxx.md` 引用，避免 SKILL.md 膨胀
- 确定性逻辑（API 调用、数据清洗、批量操作）放 `scripts/` 封装，别让模型即兴写代码
- 有费用/限额的工具，执行前说明并征得同意；已同意不重复询问
- 客户端运营建议：只启用当前任务所需的技能，减少无关干扰与误调用

## 5. 提交

打包为 zip（根目录含 SKILL.md）。开放平台提交 zip 包解析失败时，对照第 1 节结构逐字段排查；仍无法定位可联系 openworkbuddy@tencent.com。
