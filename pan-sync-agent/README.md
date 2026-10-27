# pan-sync-agent

常驻定时任务：每天 8–23 点按可配置间隔递归遍历指定目录，将新增文件按相对路径结构上传到**配置选定的百度网盘或夸克网盘**，成功后删除本地文件，并在每个子目录维护 `.uploaded.json` 上传清单。

## 全局契约

本 agent 遵循 dsh-agent 根目录的全局配置 [`../dsh-agent.config.json`](../dsh-agent.config.json)
（见根目录 [`../AGENT.md`](../AGENT.md)）。执行入口 `main.py` 已接入根目录共享包
[`../dsh_guard/`](../dsh_guard/__init__.py)：**单轮执行（一次扫描上传）超过全局时限
（当前 15 分钟）将中断本轮**，在根目录生成 `timeout-interrupt-*.json` 记录，
`once` 子命令此时退出码为 `3`，`start` 模式则记录后进入下一间隔。本地文件不会因此丢失。

## 安装

标准方式：

```bash
cd pan-sync-agent
pip install -r requirements.txt
```

弹窗依赖系统 WebView2 运行时（Windows 10/11 通常自带）；缺失时安装 Edge WebView2 Runtime。

> **离线/受限环境免安装兜底**：本目录下若存在 `.vendor/`（已内置 pywebview 及其依赖
> pythonnet、bottle、proxy_tools），程序会自动优先加载，无需 pip 安装；全局安装后
> 该目录可删除，不影响使用。

## 配置

```bash
cp .env.example .env
```

至少修改 `WATCH_DIR`；`DRIVE` 选择 `baidu` 或 `quark`（只对配置的网盘弹窗登录）。
其余可选项：扫描间隔 `SCAN_INTERVAL_MINUTES`、时间窗 `START_HOUR/END_HOUR`、
网盘目标根目录 `REMOTE_ROOT`、分片大小 `CHUNK_SIZE_MB`、稳定判定 `STABLE_SECONDS`、
跳过目录前缀 `SKIP_DIR_PREFIXES`（默认 `_`，不上传 `_pool_smoke` / `_probe_dj` 等非歌手目录）。

## 使用

```bash
python main.py login    # 夸克走官方 Skill 授权；百度弹窗扫码
python main.py login --token CAC-…   # 非交互：粘贴夸克授权码
python main.py once     # 立即跑一轮，验证效果
python main.py start    # 常驻运行（手动启动，不开机自启）
python main.py status   # 凭证与清单状态
```

登录窗口按网盘走不同流程：

- **百度**：窗口打开百度网盘登录页（百度 App 扫码/账密），后台读取 `BDUSS` Cookie 判定成功。
- **夸克（官方 Skill）**：项目内 `quarkclouddrive/`（Quark Drive Skill 1.0.22）。
  `login` / 上传走 `node scripts/quark-drive.cjs`。可用 `python main.py login --token CAC-…` 非交互授权。
  Skill CLI 不可用时，才回退到开放平台弹窗授权。

弹窗在检测到凭证后自动关闭。若超时未完成，会提示是否改为**手动输入**：百度按指引
从浏览器开发者工具（F12 → 应用 → Cookie）复制所需字段；夸克粘贴授权页上的
`AAC-…` 或 `access_token` / `refresh_token`。

## 行为说明

- 递归所有子目录，网盘内保持相同相对路径：`<REMOTE_ROOT>/<相对路径>`。
- 文件 size/mtime 持续 `STABLE_SECONDS` 秒不变才上传，避免传到写入中的文件。
- 网盘已存在同名文件：跳过、保留本地，清单记 `conflict`，等人工处理。
- 上传失败：保留本地、清单记 `failed`，下一轮自动重试（网络错误重试 3 次，指数退避）。
- 上传成功：先原子写入清单，再删除本地文件。
- 清单有旧 `uploaded` 记录而本地仍有同名文件时，会比对 size/mtime/md5：
  一致才在确认网盘存在后补删；不一致则视为同名新文件，重新上传。
- 凭证经 Windows DPAPI 加密存于 `data/`（百度存 Cookie、夸克存 OAuth token），
  任何日志都不打印凭证明文。

## 测试

```bash
python -m unittest discover -s tests -v
```

共 104 个无网络 mock 测试（配置/凭证/清单/扫描/调度/两个上传器/夸克开放平台客户端/
引擎/登录窗口/CLI）。
> 若在受限沙箱下运行遇到临时目录 `PermissionError`，可用仓库根目录的垫片：
> `python ../_tmp_test_shim.py discover`。

## 风险

百度网页版接口与夸克内部接口均非官方开放承诺，可能变动；失败一律不删除本地文件，
可据日志修复单个适配器（`uploader/baidu.py` / `uploader/quark.py`）。仅供个人合规使用。
