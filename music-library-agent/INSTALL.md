# 歌手歌库 Agent — 二次安装手册

> 目标：在一台新机器上从零复现 `music-library-agent`，并配齐 yt-dlp、ffmpeg，跑通真实下载。
> 适用系统：Windows 10/11 + Python 3.12。
> 本手册记录本次搭建的完整流程、踩坑与可复用脚本，照着做即可二次安装。

---

## 0. 最终环境（本次实测）

| 组件 | 版本 | 来源 | 安装方式 |
| --- | --- | --- | --- |
| Python | 3.12.10 | python.org | 官方安装包 |
| langgraph / langchain-openai / requests / pydantic | 已装（版本不限） | pypi | `pip install`（**需代理**，见 §2） |
| yt-dlp | 2026.08.19 | pypi | `pip install yt-dlp`（**需代理**） |
| ffmpeg / ffprobe | 6.1.1-essentials | npmmirror 镜像 | Python urllib 下载裸 exe（**免代理**，见 §4） |
| 源码 | music-library-agent | 本仓库 | 直接拷贝目录 |

---

## 1. 网络环境结论（重要，决定安装策略）

本机网络对**部分 HTTPS 下载做了限制**，规律如下（实测）：

| 访问方式 | 结果 | 用途 |
| --- | --- | --- |
| Python `urllib` / `requests` 访问 iTunes、网易云、npmmirror、Bilibili | ✅ 通 | API、小文件、国内镜像 |
| `pip install`（走 pypi） | ❌ 被重置 | 装 langgraph / yt-dlp |
| PowerShell `Invoke-WebRequest` / .NET `WebClient` | ❌ 被重置 | 下载大文件 |
| GitHub / gyan.dev / YouTube / SoundCloud / Vimeo | ❌ 超时/重置 | ffmpeg 官方包、yt-dlp 默认源 |
| Bilibili | ✅ 通 | yt-dlp 实际可用的下载源 |

**结论**：
- **Python 下载走国内镜像（npmmirror）免代理可行** → ffmpeg 用它。
- **pip 装包需代理** → langgraph / yt-dlp 需你先配好代理，或找离线 wheel。
- **yt-dlp 下载源必须用 Bilibili**（YouTube 不可达），代码已内置优先 Bilibili。

---

## 2. 安装 Python 依赖

`requirements.txt` 内容：
```
langgraph>=1.2.0
langgraph-checkpoint-sqlite>=3.1.0
langchain-openai>=1.6.0
# 可选增强（装好即用，代码已降级处理）：
# yt-dlp>=2024.1.1
# mutagen>=1.46.0
```

**有代理时**（推荐，一次装齐）：
```bash
cd music-library-agent
pip install langgraph langgraph-checkpoint-sqlite langchain-openai yt-dlp
```

**无代理时**：找一台有网的机器 `pip download` 离线 wheel 拷贝安装；或仅装 langgraph/langchain-openai（yt-dlp 缺失时代码自动降级，但见 §5 说明下载会不可用）。

> 本机 `pip install python-dotenv pytest` 被重置装不上，因此：
> - `config.py` 已**手写 .env 解析**，不依赖 python-dotenv；
> - 测试用 **stdlib unittest**，不依赖 pytest。

---

## 3. 部署源码

直接拷贝整个目录即可（无编译、无构建）：
```
music-library-agent/
├── main.py
├── music_agent/            # Agent 包（config/llm/state/graph/prompts/models/catalog/sources/convert/validate/manifest/nodes）
├── tests/                  # 34 个 unittest
├── tools/ffmpeg/bin/       # ffmpeg.exe + ffprobe.exe（见 §4）
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 4. 安装 ffmpeg（免代理，npmmirror 镜像）

官方 GitHub/gyan 包在本机下载被重置。**用 Python urllib 从 npmmirror 拉 ffmpeg-static 的 Windows 裸 exe**，无需解压、免代理。

**一键脚本** `install_ffmpeg.py`（放项目根目录运行）：
```python
"""从 npmmirror 下载 ffmpeg-static Windows 裸 exe 到 tools/ffmpeg/bin/。"""
import os, ssl, urllib.request

ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
BASE = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/"
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "ffmpeg", "bin")
os.makedirs(DEST, exist_ok=True)

def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read()

for remote, local in [("ffmpeg-win32-x64", "ffmpeg.exe"),
                      ("ffprobe-win32-x64", "ffprobe.exe")]:
    print(f"下载 {remote} ...")
    data = get(BASE + remote)
    with open(os.path.join(DEST, local), "wb") as f:
        f.write(data)
    print(f"  -> {local}  ({len(data)} bytes)")
print("完成。ffmpeg 位于:", DEST)
```

运行：
```bash
python install_ffmpeg.py
```

**验证**：
```bash
python -c "from music_agent.convert import find_ffmpeg; ff=find_ffmpeg('tools/ffmpeg/bin'); print(ff)"
tools\ffmpeg\bin\ffmpeg.exe -version          # 应打印 6.1.1-essentials_build
```
`convert.find_ffmpeg()` 会自动探测 `tools/ffmpeg/bin/`，**无需配系统 PATH**。

> 想换版本：把脚本里 `b6.1.1` 改成其他目录（可用版本见 `https://registry.npmmirror.com/-/binary/ffmpeg-static/`）。

---

## 5. 安装 yt-dlp（需代理）

```bash
pip install yt-dlp
```

**验证**：
```bash
python -c "from music_agent.sources.ytdlp_source import YtdlpSource; print(YtdlpSource().available())"
# 应输出 True
```

> ⚠️ **yt-dlp 装不上时**：Agent 流程仍完整，但下载会走网易云兜底；网易云无 cookie 时标记 `vip_required`，即**实际下不到歌**。所以 yt-dlp 是真正能下到歌的关键，务必装好。

---

## 6. 配置 .env（可选，按需启用增强）

```bash
cp .env.example .env
```

| 配置项 | 作用 | 不填时 |
| --- | --- | --- |
| `ARK_API_KEY` + `ARK_MODEL` | LLM 智能决策（歌手别名/选源/失败换源） | 降级为确定性规则，Agent 照常跑 |
| `NETEASE_COOKIE_FILE` | 网易云 cookie 文件或目录 | 直链返回 null（VIP），网易云兜底不可用 |
| `MUSIC_OUTPUT_ROOT` | 输出目录 | 默认 `music/` |
| `MUSIC_CONCURRENCY` | 下载并发 | 默认 3 |
| `MUSIC_TOP_N` | Top N | 默认 30 |
| `MUSIC_BITRATE` | mp3 码率 | 默认 320k |
| `MUSIC_FFMPEG_BIN` | ffmpeg 路径 | 默认 `tools/ffmpeg/bin` |

---

## 7. 验证安装（三步）

```bash
cd music-library-agent

# ① 单测（34 个，无网络，应全 OK）
python -m unittest discover -s tests

# ② dry-run（真实调网易云/iTunes，只列曲目不下载）
python main.py run --singer "周杰伦" --top 5 --dry-run

# ③ 真实下载一首（Bilibili 源 + ffmpeg 转 320k mp3）
python main.py run --singer "周杰伦" --song "晴天"
```

③ 成功标志：
```
[fetch_loop] 下载完成 1/1
[convert] 转码完成
[完成] ... ok=1 failed=0 ...
可正常访问：1/1
```
产出 `music/周杰伦/周杰伦 - 晴天.mp3`，ffprobe 验证为 320k mp3。

---

## 8. 日常使用

```bash
python main.py run --singer "周杰伦" --top 30            # Top N
python main.py run --singer "周杰伦" --song "晴天"        # 指定单曲（--song 可多次）
python main.py run --singer "周杰伦" --resume            # 断点续跑（跳过已完成）
python main.py run --singer "周杰伦" --dry-run           # 只列曲目
python main.py verify --singer "周杰伦"                  # 校验可访问性
python main.py state --thread-id music-周杰伦            # 查看 checkpoint
```

---

## 9. 本次踩坑记录（二次安装可避开）

1. **pip / .NET 下载被重置** → Python urllib 走 npmmirror 免代理；pip 需代理。
2. **iTunes 中文搜索返回 0**（"周杰伦"查不到，"Jay Chou"才返回"周杰倫"）→ 曲目发现主用网易云，iTunes 仅作别名参考。
3. **网易云直链无 cookie 返回 `url=null`**（code=-110，需 VIP）→ 网易云兜底需配 `NETEASE_COOKIE_FILE`。
4. **YouTube/SoundCloud/Vimeo 不可达** → yt-dlp 源改为优先 Bilibili（代码已内置）。
5. **沙箱临时区 `E:\dsn\.tmp` 写入被拒** → 测试用工作区内目录（`tests/_base.py` 的 `TmpDirTestCase`）。
6. **新版 SqliteSaver API 变更** → 用 `SqliteSaver(sqlite3.connect(path, check_same_thread=False))`，不能再用 `from_conn_string()` 直接传 compile。
7. **LangGraph checkpoint 串状态** → `run` 默认用带时间戳的 thread_id，`--resume` 才复用固定 thread。

---

## 10. 合规提醒

仅供个人学习与本地收藏，请尊重音乐版权，勿用于商业用途或公开传播。
