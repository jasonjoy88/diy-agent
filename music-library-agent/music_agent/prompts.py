RESOLVE_ARTIST = """你是音乐资料助手。用户想下载歌手「{singer}」的作品。
如果该名称为中文且你确知其官方英文/别名（或反之），仅返回这个最可能的官方名；若已是最优名称则原样返回。
只返回名称本身，不要任何解释、标点或多余文字。名称："""

ARTIST_BLURB = """你是音乐资料助手。请根据下列资料，为歌手写一句中文简介供用户在同名候选中辨别。
硬性要求：
1. 总字数不超过 {max_len} 个汉字（含标点）；超长必须自行压缩。
2. 必须同时包含：国籍/地区、成立（或出道）时间、代表作。
3. 资料不足时写「国籍不详」「成立时间不详」「代表作不详」，不可编造具体事实。
4. 只返回简介本身，不要序号、引号或解释。

歌手名：{name}
网易云 briefDesc：{brief_desc}
官方简介摘录：{intro_text}
热门歌曲：{hot_songs}
简介："""

PICK_SOURCE = """你是下载策略助手。要为歌曲「{artist} - {title}」选择音源。
可用源：{sources}。
平台特点（供决策）：
- ytdlp：Bilibili（国内优先）/ 可选 YouTube，适合华语翻唱与上传资源
- kuwo：酷我，多数曲目可无登录直链
- migu：咪咕，免费曲可直链，热门常需 VIP
- kugou：酷狗，热门正版常需 VIP
- qq：QQ音乐，下载通常需登录 cookie
- netease：网易云，直链常需 VIP cookie
- qishui：汽水音乐，流媒体多加密，成功率偏低
- apple：Apple Music，仅元数据，完整曲受 DRM 无法直下
优先选更可能免费拿到音频的源。只返回一个源名（{sources} 之一），不要解释。"""

PICK_PLATFORMS = """你是音乐检索助手。用户查询：「{query}」。
可选检索平台：{platforms}（netease=网易云 qq=QQ音乐 kugou=酷狗 kuwo=酷我 qishui=汽水 migu=咪咕 apple=Apple Music）。
请选出最值得检索的 1~3 个平台（华语流行优先 kuwo/migu/netease/qq；欧美可加 apple；小众或现场可加 qishui）。
只返回平台英文名，用空格或逗号分隔，不要解释。"""

ON_FAIL = """下载「{artist} - {title}」失败，原因：{reason}。已尝试源：{tried}，剩余可试源：{remaining}。
若原因含 vip_required / registered / premium，优先换 kuwo、migu 或 ytdlp（避开 apple）；
若含 bilibili_blocked / 412 / rate / 限流，优先换 kuwo/migu/kugou/qq 并避免再打 B 站；
若含 timeout / connection，可换其它源重试。
决定下一步：若还有可试源返回该源名；若无返回 "giveup"。只返回这一个词。"""
