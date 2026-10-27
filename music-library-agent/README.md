# 歌手歌库获取 Agent（music-library-agent）

基于 **LangGraph + LangChain** 的 CLI Agent：输入歌手名（可选 `--song` 指定单曲），抓取该歌手 Top N（默认 30）音频到本地 `music/<歌手>/`，**尽可能产出 320k `.mp3`**（m4a/aac 兜底），并**同步检索歌词、产出同名 `.lrc`**（有翻译时合并为双语），支持断点续跑与 manifest 报告。用途：个人学习 / 本地收藏。

## 架构（LangGraph 状态机）

```
START → resolve_artist → plan_tracks → fetch_loop → convert → validate → fetch_lyrics → write_manifest → END
          🤖别名/同名消歧  曲目规划      并发下载      转320k     校验      歌词LRC       落盘+报告
          (LLM/规则)    TopN/单曲    选源+换源      mp3               (无需cookie)    manifest.json
```

- **编排**：`StateGraph` + `SqliteSaver` checkpoint（`music_agent/graph.py`），7 个节点（`music_agent/nodes/`）。
- **歌词**：`fetch_lyrics` 为最终校验通过的曲目取歌词，写同名 `.lrc`（与 mp3 同名，播放器自动关联滚动）；检索到翻译歌词时按时间轴合并为双语（`原词 / 译文`）。歌词接口无需 cookie/VIP；可用 `--no-lyrics` 或 `MUSIC_ENABLE_LYRICS=0` 关闭。
- **同名消歧**：`resolve_artist` 在网易云检出多个**同名**歌手时，为每位生成 ≤50 字简介（国籍、成立时间、代表作）供交互选择；也可用 `--artist-id` 跳过交互。若候选都不符合，可输入 **`0`** 重新输入歌手名并再次检索。选中后目录为 `music/<歌手>_<id>/`，并按 id 精确拉歌。
- **LLM 决策**（🤖）：歌手别名、同名简介、选源、失败换源，走火山方舟 Ark（`ChatOpenAI`）；**无 `ARK_API_KEY` 时自动降级为确定性规则**，Agent 仍可完整运行。
- **音源**：`yt-dlp`（Bilibili 优先，可选 YouTube）+ 酷我 / 咪咕 / 酷狗 / QQ 音乐 / 网易云 / 汽水 / Apple Music（检索元数据）。检索可多平台聚合；下载按免费可得性排序并换源，瞬时失败自动重试。
- **转码**：`ffmpeg` 转 320k mp3（可选）；缺失/失败保留原格式（m4a/aac）兜底。

## 快速开始

```bash
cd music-library-agent
pip install -r requirements.txt   # langgraph / langchain-openai / yt-dlp
python install_ffmpeg.py          # 下载 ffmpeg 到 tools/ffmpeg/bin/（转 320k mp3）
cp .env.example .env              # 可选：填 ARK_API_KEY / NETEASE_COOKIE_FILE
```

> ⚠️ **务必安装 yt-dlp**：无 cookie 时网易云直链通常拿不到；两者都缺会出现 `无可用音源（yt-dlp 未装且网易云无 cookie）`。
> 验证 yt-dlp：`python -c "from music_agent.sources.ytdlp_source import YtdlpSource; print(YtdlpSource().available())"` → `True`
>
> **建议安装 ffmpeg**：否则下载后保留 m4a/aac，无法统一转 320k mp3。`install_ffmpeg.py` 从 npmmirror 拉 Windows 裸 exe，**无需配系统 PATH**（代码自动探测 `tools/ffmpeg/bin/`）。
> 验证 ffmpeg：`python -c "from music_agent.convert import find_ffmpeg; print(find_ffmpeg('tools/ffmpeg/bin'))"`
>
> 完整二次安装（代理、踩坑）见 [`INSTALL.md`](INSTALL.md)。

### 三种模式

```bash
# A. 歌手 Top N（默认 30）
python main.py run --singer "周杰伦" --top 30

# B. 指定单曲（--song 可多次）
python main.py run --singer "周杰伦" --song "晴天"
python main.py run --singer "周杰伦" --song "晴天" --song "稻香"

# C. 断点续跑（跳过已完成，补失败/未完成）
python main.py run --singer "周杰伦" --resume

# D. 同名歌手：交互选序号 / artist-id；输入 0 可重新输入歌手名；或 --artist-id 跳过交互
python main.py run --singer "Dear Jane" --top 5 --dry-run
python main.py run --singer "Dear Jane" --artist-id 11378 --top 5 --dry-run

# E. 下载并发（多线程 / 多进程）
python main.py run --singer "周杰伦" --top 30 --concurrency 4 --pool thread
python main.py run --singer "周杰伦" --top 30 --concurrency 4 --pool process
```

也可在 `.env` 设置 `MUSIC_CONCURRENCY=4`、`MUSIC_POOL=thread|process`（CLI 优先）。

# F. 本次不下载歌词（默认歌词随音频同步检索）
python main.py run --singer "周杰伦" --top 30 --no-lyrics

### 辅助命令

```bash
python main.py run --singer "周杰伦" --top 5 --dry-run   # 只列曲目不下载（预览）
python main.py verify --singer "周杰伦"                  # 校验已下文件可访问性（ok N/M）
python main.py state --thread-id music-周杰伦            # 查看 checkpoint 状态
python main.py resume --thread-id music-周杰伦           # 从 checkpoint 续跑

# 唤起平台登录窗口，用户自行登录后自动抓 Cookie → .cookies/
python main.py login --platform list
python main.py login --platform bilibili
python main.py login --platform netease
python main.py login --platform qq
```

## 环境依赖与优雅降级

| 依赖 | 必需? | 作用 | 缺失时 |
| --- | --- | --- | --- |
| Python 3.12 | ✅ | 运行环境 | — |
| langgraph / langchain-openai | ✅ | Agent 编排 / LLM 客户端 | — |
| `yt-dlp` | **强烈建议** | Bilibili/YouTube/QQ 下载；`pip install yt-dlp` | 仍可用酷我等直链源 |
| `ffmpeg`（放 `tools/ffmpeg/bin/`） | **建议** | 转 320k mp3；`python install_ffmpeg.py` | 保留 m4a/aac 兜底 |
| `ARK_API_KEY`+`ARK_MODEL` | 可选 | LLM 智能决策（别名/选源/换源/选检索平台） | 降级为确定性规则 |
| `NETEASE_COOKIE_FILE` | 可选 | 网易云 cookie 文件或目录（如 `F:\secret` → `wangyiyun.txt`） | 无 cookie 直链多为 null（VIP） |
| `MUSIC_QQ_COOKIE_FILE` | 可选 | QQ 音乐 cookie（yt-dlp 下载） | 无 cookie 时 QQ 下载多失败，会换酷我/B站 |
| `MUSIC_ENABLE_QQ/KUGOU/KUWO/QISHUI/MIGU/APPLE` | 可选 | 各平台开关（默认 `1`） | 设 `0` 关闭该平台 |
| `MUSIC_APPLE_STOREFRONT` | 可选 | iTunes 店面优先码（如 `TW`） | 空则 TW→HK→JP→US→CN 回退 |
| `MUSIC_FETCH_RETRIES` | 可选 | 单源瞬时失败额外重试次数（默认 `2`） | — |
| `MUSIC_CONCURRENCY` | 可选 | 下载并发数（默认 **1**，防 B 站 412）；CLI `--concurrency` | — |
| `MUSIC_POOL` | 可选 | `thread` 多线程（默认）/ `process` 多进程；CLI `--pool` | — |
| `MUSIC_YTDLP_COOKIE_FILE` | 可选 | B 站 Netscape cookies.txt | 无 cookie 更易 412 |
| `MUSIC_YTDLP_COOKIES_FROM_BROWSER` | 可选 | 如 `chrome` / `edge`（无 cookie 文件时） | — |
| `MUSIC_YTDLP_ENABLE_YOUTUBE` | 可选 | 默认 `0`；国内建议保持关闭 | — |
| `MUSIC_ENABLE_LYRICS` | 可选 | 同步检索歌词并写同名 `.lrc`（默认 `1`）；CLI `--no-lyrics` | 不产出歌词文件 |

> ⚠️ **国内网络实测**：YouTube/SoundCloud/Vimeo 均不可达（连接超时），**Bilibili 可达**。
> 因此 yt-dlp 源已配置为**优先 Bilibili 搜索**（B 站有大量华语音乐），失败自动回退 YouTube。
> 网易云直链需有效 cookie（`NETEASE_COOKIE_FILE` 指向文件/目录）；两者都缺时下载标记 `no_source`/`vip_required`（见 manifest）。

## 产出

```
music/<歌手>/
├── <歌手> - <歌名>.mp3        # 或 .m4a/.aac（ffmpeg 缺失时）
├── <歌手> - <歌名>.lrc        # 同名歌词（双语时为「原词 / 译文」）
└── manifest.json              # 每首 format/source/status/fail_reason + lyric_* + 汇总
```

## 测试

```bash
cd music-library-agent
python -m unittest discover -s tests -v   # 64 个无网络 mock 测试
```

## 目录结构

```
music-library-agent/
├── main.py                     # CLI：run / resume / verify / state
├── install_ffmpeg.py           # 一键下载 ffmpeg 到 tools/ffmpeg/bin/
├── music_agent/
│   ├── config.py               # .env 配置（手写解析，无 dotenv 依赖）
│   ├── llm.py                  # ChatOpenAI→Ark；无 key 返回 None → 节点降级
│   ├── state.py / graph.py     # LangGraph State + StateGraph 编排
│   ├── prompts.py              # LLM prompt
│   ├── models.py               # Track / DownloadResult
│   ├── catalog.py              # 网易云曲目发现 + iTunes 别名参考
│   ├── sources/{base,ytdlp,netease,qq,kugou,kuwo,qishui,multi_search}.py
│   ├── lyrics.py               # 歌词检索 + LRC 解析/双语合并
│   ├── convert.py / validate.py / manifest.py
│   └── nodes/                  # resolve_artist/plan_tracks/fetch_loop/convert/validate/fetch_lyrics/write_manifest
├── tests/                      # 无网络 mock 测试（stdlib unittest）
├── tools/ffmpeg/               # 绿色版 ffmpeg（手动放置，自动探测）
└── music/                      # 默认输出
```

## 合规说明

仅供个人学习与本地收藏。请尊重音乐版权，勿用于商业用途或公开传播。
