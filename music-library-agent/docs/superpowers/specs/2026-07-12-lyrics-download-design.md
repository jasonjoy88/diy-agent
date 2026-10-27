# 歌词同步检索下载 — 设计文档

日期：2026-07-12
状态：已批准

## 背景与目标

music-library-agent 已支持自动检索歌曲并生成 320k mp3。现需在同一次下载流程中，为成功下载的歌曲一并检索歌词并保存到 `music/<歌手>/`。

用户确认的关键决策：

1. 歌词格式：与音频同名的带时间轴 `.lrc`（播放器自动关联同名 mp3 滚动显示）。
2. 翻译处理：检索到翻译歌词时，按时间轴合并为双语 LRC（`原词 / 译文`）。
3. 检索范围：仅对最终音频 `status=ok` 的曲目检索歌词。

## 方案

在状态机中新增独立节点 `fetch_lyrics`，位于 `validate` 之后、`write_manifest` 之前：

```
resolve_artist → plan_tracks → fetch_loop → convert → validate
              → fetch_lyrics → write_manifest → upload
```

独立节点而非并入下载任务：与音频换源循环解耦、可独立 mock 测试、resume 语义清晰。

### 歌词来源

- 网易云歌词接口 `https://music.163.com/api/song/lyric?id=<id>&lv=1&kv=1&tv=-1`，
  返回 `lrc.lyric`（原文）与 `tlyric.lyric`（翻译，可能为空）。
- 该接口无需 cookie/VIP，未配置网易云 cookie 时仍可取歌词。
- `NeteaseSource` 新增 `fetch_lyric(song_id) -> dict`；不受 cookie 门槛 `available()` 限制。
- `ext:` 外源曲目无网易云 id：以「歌手 歌名」搜索，复用
  `catalog._artist_matches` / `catalog.title_matches` 严格匹配同一首歌后再取歌词；
  无匹配 → `not_found`，禁止使用别的歌曲的歌词。

### LRC 处理（`music_agent/lyrics.py`）

- 文件名：`Track.safe_filename() + ".lrc"`，与 mp3 同名。
- 双语合并：以时间戳 tag 为键对齐原文与翻译，翻译拼接到同行 `[mm:ss.xx]原词 / 译文`；
  翻译缺失或对齐失败时仅输出原文。
- 文件头：`[ti:歌名]` `[ar:歌手]` `[al:专辑]` `[by:music-library-agent]`；
  过滤接口返回中已有的元信息 tag 行，避免重复。
- 接口返回空歌词 → `no_lyric`。
- 节点内最多 4 线程并发；目标 `.lrc` 已存在则直接视为 ok（幂等，resume 友好）。

### 状态、配置与 CLI

- `DownloadResult` 新增：`lyric_status`（ok|failed|""）、`lyric_path`、`lyric_source`。
- manifest 经 `asdict` 自动包含上述字段；完成报告追加「歌词 ok=N/M」。
- 新增配置 `MUSIC_ENABLE_LYRICS`（默认 `1`）；CLI 新增 `--no-lyrics`；
  `MusicState` 新增 `lyrics_enabled`；dry-run 节点跳过。

### 边界与降级

- 网络/解析异常 → `lyric_status=failed`，`fail_reason` 形如 `resolve_error:...`，不影响音频结果。
- 旧 manifest 加载时新字段为默认空值。
- 歌词不进入网盘上传暂存（`collect_ok_audio` 只收音频扩展名）。
- 顺带修复 `nodes/upload.py` 使用 `os.path.basename` 却未 `import os` 的既有 NameError。

## 测试

- 新增 `tests/test_lyrics.py`：歌词解析、双语合并、ext 搜索匹配、幂等、禁用/dry-run，全程 mock 无网络。
- 更新 `tests/test_graph.py`：patch 歌词获取，端到端用例不发起真实请求。
- 全量 `python -m unittest discover -s tests` 通过。
