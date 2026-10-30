# diy-agent

自定义的 Agent / Skill 与可独立运行的本地工具。两类东西放在同一仓库：

- **专家包**：平台无关结构（`agents/` + `skills/`），可在 Cursor、Claude Code、Codex 等环境接入。
- **可运行 Agent**：带 `main.py` 的 Python CLI，在本机直接执行。

各子目录的安装、命令与行为以该目录下的 README 为准。

## 专家包

| 目录 | 说明 |
| --- | --- |
| [`php-migration-analyst/`](php-migration-analyst/README.md) | PHP 低版本→高版本升级只读排障：对照迁移变更、检索日志与代码，输出含证据链的修改建议 |
| [`wechat-miniprogram-expert/`](wechat-miniprogram-expert/README.md) | 微信小程序全周期开发：原生框架、WXML/WXSS、云开发、审核合规与项目档案续接 |

## 可运行 Agent

| 目录 | 说明 |
| --- | --- |
| [`music-library-agent/`](music-library-agent/README.md) | 按歌手抓取 Top N 或指定单曲到本地，尽量产出 320k `.mp3` 并同步同名 `.lrc`；支持断点续跑。安装见 [`INSTALL.md`](music-library-agent/INSTALL.md)，操作见 [`USAGE.md`](music-library-agent/USAGE.md) |
| [`pan-sync-agent/`](pan-sync-agent/README.md) | 常驻扫描本地目录，把新增文件按相对路径上传到百度网盘或夸克网盘，成功后删除本地文件，并维护 `.uploaded.json` 清单 |

## 仓库级 Skill

| 目录 | 说明 |
| --- | --- |
| `skills/agent-platform-agnostic/` | 抹去 CodeBuddy/WorkBuddy 等平台绑定，并改写 README 以适配多平台；对其它专家包做相同处理时使用此 skill |
| `skills/make-workbuddy-skill/` | 按规范生成 Tencent WorkBuddy 专家、技能、连接器骨架（`plugin.json` / `SKILL.md` / `mcp.json`），并在提交前校验字段是否合规 |
| `skills/software-project-analyzer/` | 平台无关的多角色项目分析：勘察本地代码库，产出可快速理解架构、环境与作用的中文报告（完整/快速模式）；可在 Cursor、Claude Code、Codex 等环境接入 |
| `skills/local-skill-router/` | 平台无关的本地技能检索：在已建 codegraph 的技能库中推荐技能调用链；可在 Cursor、Claude Code、Codex 等环境接入 |
