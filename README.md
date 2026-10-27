# diy-agent

自定义的一些 Agent / Skill 专家包。包内默认采用**平台无关**结构（`agents/` + `skills/`），可在 Cursor、Claude Code、Codex 等环境接入。

## 专家包

| 目录 | 说明 |
| --- | --- |
| `php-migration-analyst/` | PHP 低版本→高版本升级只读排障专家 |

## 仓库级 Skill

| 目录 | 说明 |
| --- | --- |
| `skills/agent-platform-agnostic/` | 抹去 CodeBuddy/WorkBuddy 等平台绑定，并改写 README 以适配多平台；对其它专家包做相同处理时使用此 skill |
