# kw-qq-music-api 接口开发文档

> 版本：1.20 · 更新：2026-11-06 · 源码分支：`api-server`（musicdl 仓库）
> 服务定位：自托管多源音乐 API —— **六源解析**（酷我/QQ/千千/咪咕/网易云/酷狗）+ **两容器全量曲库透传**（网易云/酷狗生态全覆盖）
> 计划与决策：见 `docs/KUWO-QQ-API-SERVER-PLAN.md`；快速上手见 `server/README.md`

---

## 1. 服务拓扑

```
MusicFree 插件 / 自研客户端
   │  Authorization: Basic base64(API_KEY + ":")
   ▼
https://kwqq-api.pegbiotec.com:4433  （Lucky 反代，外网唯一入口；内网 http://10.10.10.2:3003 免 key）
   ▼
musicdl-api 容器 (FastAPI, host 网络, :3003)
 ├─ 六源解析 adapters: kuwo / qq / qianqian / migu / netease / kugou
 │    netease ──► ncm-api 容器(:3000)   [MUSIC_U 登录态 → VIP 无损]
 │    kugou  ──► kugou-api 容器(:3001)  [cookie-server(:3002/kugou) 动态拉取 → 账户权益]
 │              └─ cookie 由 kugou_refresh.sh 定期续期，本服务自动跟随
 ├─ 通用透传 /{kugou|netease}/api/{path}  ← 覆盖两个容器的全部曲库/运维端点
 └─ TTL 缓存 + ParserHealth 健康度冷却 + API Key 守卫
```

## 2. 认证

### 2.1 双层模型

| 层 | 机制 | 覆盖范围 |
|----|------|----------|
| Lucky 反代 | HTTP Basic | 仅根路径 `/`（实测行为，勿依赖） |
| **服务层** | **API Key** | 全部功能路径 + 透传 |

### 2.2 规则

- `API_KEY` 非空时启用；`/healthz` 恒豁免
- **内网免 key**：来源 IP ∈ `TRUSTED_NETWORKS`（默认含 `10.10.10.0/24,10.20.0.0/24`（办公室 WG）,`172.16/12` 等）且不在 `UNTRUSTED_HOSTS`（默认 `10.10.10.1`=Lucky 入口，防外网借道）
- 其余来源必须携带，二选一：

```
Authorization: Basic base64(API_KEY + ":")     # 与 kugou.js 插件模式一致
X-API-Key: <API_KEY>
```

失败返回 `401`。当前生效 key 见 NAS `/volume2/docker/musicdl-api/docker-compose.yml` 的 `API_KEY`。

### 2.3 v2 播放签名（scoped service credential，2026-10-29 K-01）

v2 托管播放端点 `/v2/*` **不走** `API_KEY`、也不享受内网免 key：它有自己的服务凭证模型。

| 项 | 说明 |
|----|------|
| 头 | `X-Service-Token: <token>` |
| 配置 | `SERVICE_TOKENS`（JSON：`{"token": {"scopes": ["playback:issue"], "generation": 1}}`）；格式错误在启动时直接失败 |
| scope | `playback:issue`（签发播放候选）· `cache:invalidate`（主动失效已成功但陈旧的缓存）· `media:prepare`（Songloft 媒体准备：允许 AAC 规范化输入，见 §4.8） |
| 代次 | 每个 token 带 `generation`；轮换 token/代次即让该 token 的 v2 缓存键失效，不影响他人 |
| 边界 | **下载 API_KEY 不自动获得任何 v2 scope**（用 `API_KEY` 当 token 直接 403）；缺 token 401、scope 不足 403 |

---

## 3. 统一响应格式

业务端点（search/song-url/song-info/lyric/vip）统一信封；**透传端点除外**（原样返回上游 JSON）。

| HTTP | code | 含义 |
|------|------|------|
| 200 | 200 | 成功 |
| 200 | 403 | 无损档被禁用 / 透传路径被黑名单拦截 |
| 200 | 404 | 未知 source / 歌曲无资源 / 咪咕缺 copyright 参数 |
| 401 | 401 | API Key 缺失或错误 |
| 502 | 502 | 上游解析全部失败 |
| 504 | 504 | 硬超时（默认 35s，deezer 类慢通道 150s） |

---

## 4. 解析端点（七源）

`{source}` ∈ `kuwo` | `qq` | `qianqian` | `migu` | `netease` | `kugou` | `bilibili`

### 4.1 GET /{source}/search — 搜索（仅元数据）

| 参数 | 必填 | 说明 |
|------|------|------|
| keywords | ✅ | 关键词 |
| page | — | 页码 ≥1 |
| limit | — | 条数 ≤50 |

item 结构：`{id, name, singer, album, ext, size_bytes, duration_s, cover, source, extra}`。
**migu 的 `extra.copyrightId` 必须在后续 song/url、song/info、lyric 时以 `?copyright=` 回传。**
**kugou 的封面在 `songsearch` 里是 `http://imge.kugou.com/stdmusic/{size}/...` 模板串，门面已替换为 `240`；album/多类型搜索返回的 `img` 也走同一归一。** 未归一模板串**不是 404**——上游对 `{size}` 字面量一律回同一张 17853 B 通用占位图（所有歌曲 md5 相同），所以这个 bug 的表象是"有图但不是专辑封面"；`/240/` 才是逐曲真实封面（2026-11-06 实测：同一首歌 17866 B、不同歌曲分别 29970/16193/26112 B，md5 各自不同）。

### 4.2 GET /{source}/song/url — 播放直链

| 参数 | 必填 | 说明 |
|------|------|------|
| id | ✅ | 歌曲 id |
| quality | — | auto/320k/128k/flac/hires/**master/surround51**（MusicFree 四档归一：low=128k、standard=192k、high=320k、super 封顶 320k；5.1→surround51；无损档仅对 musicdl 下载有效） |
| copyright | — | 仅 migu |
| cid / page | — | 仅 bilibili（可选）：已验证的分 P 身份；给出后按该 P 解析并计入缓存键，避免分 P 串播 |

成功 data 字段：`{url, ext, bitrate_kbps(如实), size_bytes, duration_s, verified, parser, elapsed_ms, headers, ekey}`。
**bilibili 源的 `headers` 必须传给播放器**（CDN 校验 Referer，缺了 403）：`{"Referer": "www.bilibili.com", "User-Agent": "..."}`。其他源 headers 通常为空。
**音质路由**：MusicFree 四档：low→128k 全源；standard→192k（网易 level=higher 实测 192kbps；其余源无原生 192k 档回落 320k——酷我 192kmp3 为假档实测降 128 故向上就近）；high→320k 全源；super 封顶 320k（QQ 第三方链尽力而为，若上游给 flac 则响应 quality 如实标注）。auto/320k 封顶 320kbps（netease 经 MUSIC_U 可出 exhigh=320k）；flac/hires/master/surround51 受 `ENABLE_LOSSLESS` 门控（默认 false→403）。各源通道：酷我 nmobi 直出（320k/flac/**master=20900kmflac 匿名 192k/24bit**）→mobi.s→第三方链；QQ 第三方链(vkeys…)→元力→3e0；千千 tracklink（rate=3000 实测真 FLAC：48k/24bit 入门 Hi-Res 与 44.1k/16bit CD 逐曲不定，无母带）；咪咕 listen-url(HQ/SQ)（**匿名 SQ/ZQ 实测为假无损**——URL 200 可下但实为降档 MP3）；网易 ncm-api(level)；酷狗 kugou-api(quality)（**酷狗无 hires 参数**，high=24bit/44.1k 即高解析位阶；viper 三档需超级VIP，当前不可达）。各平台规格详见 docs/QUALITY-MATRIX.md。
**酷我 master/surround51 专属**：`ext=mflac` 且携带 `ekey`（QMC 密钥）——`url` 指向**加密**容器，消费方须用 `KuwoQmcDecryptor`（`scripts/kuwo_qmc_decryptor.py`）解密得到明文 flac（192k/24bit 或 44.1k/16bit/6ch）；明文档位无 `ekey` 字段。仅酷我源支持这两档，其他源按各自能力回落。

### 4.3 GET /{source}/song/info · GET /{source}/lyric

单曲元数据 / LRC 歌词。netease lyric 需容器登录态才有完整翻译/罗马音。

**lyric 参数与契约（2026-11-06）**

| 参数 | 必填 | 说明 |
|------|------|------|
| id | ✅ | 歌曲 id |
| copyright | — | 仅 migu：搜索条目 `extra.copyrightId`（歌词按版权下发，缺省直接返回空歌词） |

成功 `data`：`{id, source, lyric, lxlyric, cached}`。

- `lxlyric`：**逐字歌词**，字符串，可为 `null`。格式为洛雪逐字格式——每行 `[mm:ss.mmm]` 行时间戳 + 逐字 `<偏移ms,时长ms>文本`，偏移**相对行首**（与 songloft 播放器/TV 解析器、LX Music 一致）。字段名固定，客户端按此消费。
- **逐字源与实测覆盖率（2026-11-06 现网抽样，仅记条数/长度，不记歌词正文）**：

  | 源 | 上游逐字资源 | 抽样覆盖 | 门面实现 |
  |---|---|---|---|
  | `qq` | QRC（`musicu.fcg` `GetPlayLyricInfo` + `qrc:1`，匿名零 Cookie） | **18/18** | `lyric` 字段是 **HEX 串而非 base64** → hex 解码 → QQ 自研 DES 变体 `D(K1)→E(K2)→D(K3)` → zlib → XML；`[start,dur](绝对ms,dur,0)` 片段偏移减行头 |
  | `kuwo` | LRCX（`newlyric.kuwo.cn/newlyric.lrc` + `lrcx=1`） | **14/18** | `[kuwo:<八进制>]` 标度 → `k1=k//10, k2=k%10`，`start=(a+b)/(2k1)`、`dur=(a-b)/(2k2)`；整行 `<0,0>` 的译文行丢弃 |
  | `netease` | YRC（`/lyric/new?id=` → `yrc.lyric`，ncm-api 匿名即可） | **7/20（35%）** | 跳过首行 JSON 元信息；`[start,dur](绝对ms,dur,0)` 片段偏移减行头（`klyric` 20/20 为空，不用） |
  | `kugou` | KRC（`krcs.kugou.com/download` `fmt=krc`） | — | 4 字节 `krc1` 头 + XOR + zlib |
  | `qianqian` | 无 | **0/15** | 歌词 URL 内容无任何 `<…>`/`(…)` 逐字标记，纯行级 LRC |
  | `migu` | 仅有 `mrcUrl`（`application/marc`，hex 21.8k–34k 字符） | — | **不可解**：无公开 MRC 算法，QRC/KRC/LRCX 均不适用；`trcUrl` 恒空、`lrcUrl` 纯行级 → 一律不出 `lxlyric` |

- 取不到逐字时 `lxlyric` 为 `null`，`lyric` 照常返回（不返回半成品逐字）。QQ 验收判据：「同一首歌能同时取到 QRC 密文与明文 LRC 且行时间对得上」——`我记得`（MID `002dw4gv1ZmiGt`）QRC 密文 10512 hex 字符 → 解密 XML 8724 字符，66 条逐字行与明文 LRC 行头最大偏差 **9ms**。
- **qianqian 的歌词 URL 只挂在搜索结果行上**（行内 `lyric`），无 by-id 通道：门面在 `_search_raw` 里写进程内 `id → url` 缓存（上限 500 条，满则清空），因此 `lyric` 必须紧跟同进程内的一次搜索（kwqq 插件正是「先回搜再取词」）；服务重启或跨进程后未搜索过的 id 返回空歌词。
- 缓存键 `lyric2` **不变**：值形状仍是 `{lyric, lxlyric}`，只是原先恒为 `null` 的三个源开始填充内容；插件侧 `lyric2|` 键同理无需再换前缀（重启容器即清空进程内 24h 缓存）。

### 4.4 GET /{source}/album — 专辑检索（P6，2026-10-28 v1.8）

专辑名 → 候选专辑 + **首选专辑的有序曲目**，一次调用覆盖"整张连播"场景（消费方：bridge `song_request`、songloft kwqq 插件专辑页）。

| 参数 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 专辑名关键词 |
| artist | — | 歌手提示（用于同名异手专辑的候选排序） |
| page | — | 专辑候选页码 ≥1 |

成功 data：`{source, name, artist, albums: [{id, name, artist, size, cover, source, extra}], items: [<search item 结构> + track_no], total, track_count}`。

- **items = 首选专辑的官方曲序**，`track_no` 1 起；item 结构与 `/search` 完全一致 → 曲目解析照走 `/{source}/song/url?id=`（二段式不变）。
- **曲目数 `track_count`**（2026-11-04 v1.17）：仅 `adapter.album_track_count=True` 的源给出（netease/kuwo/kugou/qq，该通道本就取到整册曲目）；migu/qianqian 上游不提供整册计数，字段为 `null`——产品决定不显示、也不为补数字逐专辑调详情接口（选项 A）。`/{source}/album/detail` 同规则。
- **逐源能力**（未实现的源返回 **HTTP 501** envelope——能力缺失类，非业务未命中 403/404）：`netease` ✅（ncm-api `/cloudsearch?type=10` → `/album`）；`kugou` ✅（容器 `/search?type=album` → `/album/songs`，按 `extend.disc+sort` 官方曲序）；`migu` ✅（`search_all.do` album=1 → `resource/album/song/v2.0`）；`qianqian` ✅（`/v1/search type=3` → `/v1/album/info`，曲库较稀疏）；`kuwo` ✅（2026-11-03 v1.13：r.s `ft=album` 候选 → `stype=albuminfo` 曲目，零 Cookie，musicfree kuwo 插件同款）；`qq` ✅（2026-11-03 v1.13：fcg `DoSearchForQQMusicDesktop` search_type=2 候选 → `music.musichallAlbum.AlbumSongList` 曲目，零 Cookie，musicfree qq 插件同款——旧记「匿名模块 500003」仅指旧通道）。
- 候选检索：先用 `name+artist`，无结果自动退 `name`；排序 = 名字精确匹配 + 歌手提示命中。
- 缓存：meta_cache，键含 name/artist/page。

### 4.5 GET /{source}/playlist — 歌单检索（P6，2026-10-28 v1.8）

歌单名 → 候选歌单 + **首选歌单的有序曲目**（消费方：bridge 歌单意图、播放器歌单视图）。

| 参数 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 歌单名关键词 |
| page | — | 候选页码 ≥1 |

成功 data：`{source, name, playlists: [{id, name, creator, track_count, cover, source, extra}], items: [<search item 结构> + track_no], total}`。

- **逐源能力**：`netease` ✅（ncm-api `cloudsearch?type=1000` → `/playlist/track/all`，上限 1000 曲）；其余源 501（kuwo/qq/qianqian 无公开歌单搜索通道；kugou 歌单曲目端点容器返回 20010）。
- items 结构与 `/search` 一致，曲目解析仍走 `/{source}/song/url?id=`。缓存：meta_cache。

### 4.5b GET /{source}/search/multi — 多类型搜索（P7，2026-11-03 v1.13）

关键词 → 类型特定条目列表（**非歌曲条目**，形状随 type 变化）。消费方：songloft kwqq 插件浏览搜索（`/browse/search` 的 album/artist/sheet 类型按源 fan-out 聚合）。

| 参数 | 必填 | 说明 |
|------|------|------|
| keywords | ✅ | 搜索词 |
| type | — | `album`（默认）/ `artist` / `sheet` |
| page | — | ≥1 |
| limit | — | 缺省 search_size_default，上限 search_size_max |

成功 data：`{source, type, keywords, page, total, items}`。条目形状（MusicFree 语义归一，全部带 source）：

- `album`：`{id, name, artist, cover, track_count}`
- `artist`：`{id, name, avatar}`
- `sheet`：`{id, name, creator, cover, track_count, play_count}`

- **逐源能力**（未实现源 501 envelope）：`qq` ✅ 全三类（fcg Desktop search_type 2/1/3）；`kuwo` ✅ 全三类（r.s ft=album/artist/playlist，itemset=web_2013）；`migu` ✅ album/artist（search_all.do searchSwitch，sheet 501）；`qianqian` ✅ album/artist（/v1/search type=3/2 签名通道，sheet 501）；`netease`/`kugou` **不经本端点**——走透传（`/netease/api/cloudsearch type=10/100/1000`、`/kugou/api/search type=album/author/special`，插件直连容器）；`bilibili` 不支持（501；其插件侧 album 类型与 music 同源，无独立通道）。
- total 可为 null（qianqian 无总数）；分页 isEnd 由消费方按「返回条数 < limit」启发。
- 缓存：meta_cache，键含 keywords/type/page/limit。

### 4.6 POST /v2/playback/resolve — v2 托管播放解析（K-01，2026-10-29）

托管播放（Songloft 当前项准备、bridge 点歌）只提交 **稳定曲目身份**，不接受调用方 URL。v1 端点（§4.1–4.5）行为完全不变，旧下载/ekey 契约不受影响。

请求（`X-Service-Token` 必须带 `playback:issue` scope，见 §2.3）：

```json
{
  "track_ref": {"source": "bilibili", "id": "BV1xx411c7mD",
                 "extra": {"cid": "123456", "page": 2}},
  "profile": {"quality": "320k", "target": "device"},
  "freshness": "allow_cache"
}
```

| 字段 | 说明 |
|------|------|
| `track_ref.source` / `.id` | 必填；`id` 为该源原生 id（kuwo rid / qq songmid / kugou hash / qianqian TSID / netease id / migu contentId / bilibili bvid） |
| `track_ref.extra` | **只保留影响身份的字段**：migu `copyrightId`；bilibili `cid` 和/或 `page`。其余键一律丢弃（伪造 ekey/URL 不进入缓存键） |
| `profile.quality` | 原始拼写；v2 先按白名单校验再归一化（§4.8） |
| `profile.target` | `device`（托管播放）或 `media_prepare`（仅 Songloft 媒体准备，需 `media:prepare` scope） |
| `freshness` | `allow_cache`（默认）/ `revalidate`（跳过读缓存，仅重解析**一次**，仍写回） |

**身份硬约束（缺字段明确拒绝，HTTP 400）**：

- migu 必须带 `extra.copyrightId`——同一 contentId 在不同版权下是不同媒体，不得串解析/串缓存。
- bilibili 必须带 `extra.cid` 或 `extra.page`——不再固定 `pages[0]`；`cid` 与 `page` 同时给出且互相矛盾 → 400；`cid` 不属于该视频 → 404。响应 `track_ref.extra` 回填**已验证**的 `cid`/`page`。
- 搜索仍是单次元数据请求；需要补全身份时只对**选中项**调 `/{source}/song/info`（bilibili 返回 `data.extra.cid/page` 与 `data.raw.pages`），不做逐候选 view N+1。

成功 data（`PlaybackResolveData`）：`{track_ref, resolved_source, requested_quality, delivered_quality, codec, url, ext, size_bytes, bitrate_kbps, duration_s, cover, headers, parser, platform_tag, verification: {level, requires_byte_verification, requires_transcode}, verified, fallback_reason, resolved_at, cache_expires_at, upstream_expires_at, cached}`。

- `track_ref` = 原请求身份（经校验并回填已解析 cid/page）；`resolved_source` = 实际出链来源。
- `verified` 在 v2 **恒为 false**：kwqq 只能声明上游说法或部分字节证据，完整文件验证由 Songloft 准备链完成（`verification.level` ∈ `declared`/`partial`，`requires_byte_verification` 恒 true）。
- 缓存键 = 结构化身份 + **归一化**播放策略（per-source tier + target）+ 凭据代次（`v2:` 命名空间，独立于 v1 url_cache）。因此 `high`/`super`/`320k` 这类同一档位的不同拼写共用一个缓存项，失效时也不必复刻调用方的拼写。

### 4.7 七源逐源详述

#### kuwo 酷我

| 项 | 说明 |
|----|------|
| id 格式 | 数字 rid（如 `228908`） |
| 出链通道 | ① `nmobi.kuwo.cn` 明文直出（精确档位不降档 ~150ms）→ ② `mobi.kuwo.cn` 加密版（会静默降档，备胎）→ ③ 第三方链(nxinxz/nobb) → ④ haitangw `/music/kw.php` |
| 音质上限 | master=20900kmflac（**匿名 192kHz/24bit/2ch**，mflac+ekey 需 QMC 解密）/ surround51=20501kmflac（匿名 44.1k/16bit/6ch）；flac 需 `ENABLE_LOSSLESS=true`（br=2000kflac 实测 ~1647kbps CD 抓轨）；320k mp3 可靠 |
| 歌词 | newlyric DES 解密 ✅ / h5 lrclist 兜底 |

#### qq QQ音乐

| 项 | 说明 |
|----|------|
| id 格式 | songmid 字母数字（如 `0039MnYb0qxYhV`） |
| 出链通道 | 第三方解析链 vkeys→xcvts→xingmian→317ak→xianyuw→nki→hk0cc→tang→cyapi→xunhuisi→lxmusic→yutangxiaowu→lpz（健康度冷却排序）→ 元力中转 → 3e0 兜底 |
| 音质上限 | 热门曲 FLAC（vkeys）；冷门 m4a 降级 |
| 已知边界 | 官方匿名 GetVkey 无 purl；xcvts/xingmian/317ak 已失效但仍在链中（冷却跳过）；元力实为酷我 CDN 换源可能匹配翻唱 |

#### qianqian 千千音乐

| 项 | 说明 |
|----|------|
| id 格式 | TSID（如 `T10065400429`） |
| 出链通道 | `tracklink(TSID, rate)` MD5 签名官方 API；rate=3000(FLAC)→320→128 逐级尝试 |
| 音质上限 | 真 FLAC（rate=3000）：**48kHz/24bit（入门级 Hi-Res，非母带——母带门槛 ≥96kHz）或 44.1kHz/16bit（CD）逐曲不定**；rate=999 与 3000 同文件 |
| 已知边界 | 版权库覆盖有限（周杰伦/邓紫棋热门曲实测整缺；部分曲标注大文件实下 MP3）；规格逐曲不定必须以实下文件头为准；歌词需从搜索结果的 lyricUrl 获取，by-id 不支持 |

#### migu 咪咕音乐

| 项 | 说明 |
|----|------|
| id 格式 | contentId 数字（如 `600902000006889366`） |
| **by-id 必需** | search 返回的 `extra.copyrightId` 须以 `?copyright=` 回传到 song/url、song/info |
| 出链通道 | `listen-url/h5/v2.4` 按 toneFlag 逐档尝试（HQ→SQ→ZQ），XOR 异或解密响应；失败回退 listenSong.do 模板 |
| 音质上限 | HQ=320k mp3 可靠；**匿名 SQ/ZQ 为假无损**（URL 可下但实测 3.9MB audio/mpeg=MP3，元数据标注 28.6MB 不透出；URL 段替换 FLAC 路径 404）——真无损需会员 Cookie |
| 歌词 | strategy/pc/listen 接口或 search_result.lyricUrl |

#### netease 网易云音乐

| 项 | 说明 |
|----|------|
| id 格式 | 数字 id（如 `108914`） |
| 出链通道 | ncm-api 容器 `/song/url/v1?level=` + MUSIC_U cookie 注入 |
| 音质上限 | exhigh=320k（黑胶 VIP）；lossless/hires 需 `ENABLE_LOSSLESS=true` |
| 灰色曲目兜底 | 官方无资源时自动走 two-pass unblock mirror（kuwo CDN）+ qijieya 流 + oiapi |
| 已知边界 | 腾讯系版权曲全量灰化（含周杰伦）；MUSIC_U 长期有效但非永久，失效后需重新获取并更新 NAS compose |

#### kugou 酷狗音乐

| 项 | 说明 |
|----|------|
| id 格式 | FileHash 32 位大写十六进制（如 `B3A52A7A958BF0AED0EBFBA2E9A818B7`） |
| 出链通道 | kugou-api 容器 `/song/url?hash=&quality=&cookie=`（cookie 从 :3002/kugou 动态拉取自动续期） |
| 音质上限 | quality=flac → 真 FLAC 16bit/44.1k；quality=high → **24bit/44.1k FLAC（高解析位阶，酷狗无 `hires` 参数）**；quality=320 → 320k mp3；viper_tape/clear/atmos → 需超级VIP（当前 cookie vip_type=0 被拒 status=2）；`hires` 参数无效（status=0） |
| VIP 运维 | POST `/kugou/vip/day`（领畅听）、`POST /kugou/vip/upgrade`（升概念）、GET `/kugou/vip/status`（svip/tvip 到期时间+本月领取明细）——见 §5.2 |
| 已知边界 | search 走匿名 songsearch（稳定）；VIP 曲目依赖账户权益有效期 |

#### bilibili 哔哩哔哩

| 项 | 说明 |
|----|------|
| id 格式 | BV 号（如 `BV15g411X7vj`） |
| 出链通道 | DASH 提取：`playurl?fnval=16` → dash.audio/flac/dolby 按 quality 选轨 → bilivideo CDN 直链 |
| 凭证 | finger/spi 动态 buvid3/4（免登录绕风控，进程缓存 7 天）；可选 `BILI_SESSDATA` 解锁 Hi-Res/Dolby |
| 音质映射 | low→64k、standard→192k AAC（30280，2026-10-27 起归一为 320k 档请求）、auto/320k→192k AAC 档；flac/hires→Hi-Res/Dolby 声道（gated） |
| **headers 必须** | CDN 校验 Referer：客户端须携带 `Referer: www.bilibili.com` + UA，否则 403 |
| 已知边界 | 匿名音质封顶 192k AAC；UGC 内容库（翻唱/改编/现场），与版权曲库互补而非替代 |
| v2 身份 | `track_ref.extra` 必带 `cid` 或 `page`；`/song/info` 回传 `extra.cid/page` + `raw.pages` 供补全（2026-10-29） |

### 4.8 v2 播放准入（严格 profile，K-02）

v2 与 v1 共用 adapter 出链能力，但**准入判断独立且更严**。以下规则只作用于 `/v2/playback/resolve`：

| 请求/候选 | 结果 |
|-----------|------|
| `quality` 不在已知拼写表 | 400 `invalid_quality` |
| `quality` = `flac`/`hires`/`master`/`surround51`（含 `super`→320k 这类合法别名不受影响） | 400——**拒绝而不是回落 auto**，无损仅 v1 下载可用 |
| 候选 ext ∈ FLAC/WAV/APE 等无损容器 | 415——托管播放只收 mp3；无损/无损封装不进入设备链 |
| 候选带 `ekey` 或 ext ∈ mflac/mgg/ncm/qmc*/kgm/vpr/kwm | 415 加密件；仍保留为 v1 下载+解密产物 |
| 候选 ext = aac/m4a（AAC 家族） | 仅 `profile.target=media_prepare` 且 token 有 `media:prepare` scope 时放行，返回 `requires_transcode=true`、`ready=false`；其余一律 415，**AAC 不得直投** |
| 候选 mp3 但 `bitrate_kbps > 320` | 415 超出 320k 上限 |
| 候选 mp3 且无 bitrate、无 size/duration | 200 但 `ready=false`，`fallback_reason` 标注证据不足；必须字节验证 |
| 候选 mp3 有实测码率 | 200，`ready=true`，`delivered_quality` 由**实测码率**推出（≥240→320k，≥160→192k，≥96→128k）；低于请求档位如实标注 `downgraded` |

**验证等级**：`verification.level` ∈ `declared`（仅上游声明）/ `partial`（HEAD/后缀/MIME/8KB sniff 级证据）。kwqq **不再**把后者写成“完整编码验证”：v2 `verified` 恒 false、`requires_byte_verification` 恒 true；完整文件（实际 codec、MP3 帧、时长、每帧码率上限）由 Songloft 准备链验证后才有资格投送。

**缓存**：被拒绝的候选不写缓存（下次仍重新解析）；AAC 的 `media_prepare` 结果与 `device` 请求是不同缓存键，不会互相串用。

---


### 4.9 POST /v2/cache/invalidate — 受限缓存失效（K-04）

当成功缓存但已陈旧（上游直链换签）时，媒体服务用独立 scope 主动失效**当前身份**，随后按 `freshness=revalidate` 重解析。

```json
{"track_ref": {"source": "bilibili", "id": "BV1xx", "extra": {"page": 2}},
 "profile": {"quality": "320k", "target": "device"}}
```

- 需要 `cache:invalidate` scope（`playback:issue` token 调用 → 403）。
- 只删除「该身份 + 该策略 + 该 token 代次」的精确键：无通配符、无跨身份、无跨代次；返回 `{invalidated, identity_digest, generation, profile}`，其中 `profile` 回显 `{quality（原拼写）, target, tier（归一化档位）}`。
- `profile.quality` 走与 resolve 相同的白名单与归一化（无损请求 400），因此用别名拼写也能失效到对应档位的缓存项。
- 重解析预算：一次失效后最多一次受控重解析（并发同键由 singleflight 合并）；端到端重试预算由最外层命令持有，kwqq 不叠加自己的多轮重试。

### 4.10 singleflight、限流冷却与错误分类（K-04）

- **singleflight**：同一结构化键的并发请求只有一个 leader 执行上游解析，其余等待者共享结果；等待者取消不影响 leader 与其他等待者；leader 失败不写负缓存，后续请求可自行重试。
- **上游 429 冷却**：冷却按**逻辑入口**（如 `kuwo:relay.haitangw`、`netease:ncm-api`、`kugou:container`）记账，与 host 别名/内外网入口无关——换 host、换备用入口都不重置同一冷却，冷却期内备用入口**零请求**；保留上游 `Retry-After`；429 结果永不作为成功缓存。
- **限流分类**：本地限流器 429 带 `X-RateLimit-Scope: local`；上游 429 带 `X-RateLimit-Scope: upstream` + `Retry-After`。两者都是 HTTP 429 + 信封 `code=429`。
- `/status` 的 `parsers` 快照新增 `cooldown_remaining_s`、`throttled`。

### 4.11 GET /{source}/mv — 歌曲 MV（2026-11-06 v1.19）

```
GET /{source}/mv?id=<song id>&title=<可选>&artist=<可选>
```

**契约（字段名固定，客户端直接消费顶层字段）**

```json
{"code": 200, "msg": "ok", "data": {
  "id": "<same song id you passed>", "source": "qq",
  "url": "https://...mp4", "cover": null, "duration_s": 235, "quality": "sd",
  "title": "...", "artist": "...", "items": []
}}
```

- `id` 回显**传入的歌曲 id**（不是 MV 自身的 id），`source` 回显源名；`url` 是可直接播放的地址。
- **拿不到 MV 时 `url: null`**（HTTP 200 + `code: 200`，不做 404、不返回空对象）；未知源仍是 404 信封。
- 可选 `items`：同一首歌存在多个 MV 候选时给出（按可播性排序）；**首个可直接播放的必是顶层字段**，客户端不需要读 `items` 也能播放。
- `title`/`artist` 是可选提示：当 `id` 无法直接映射到 MV（如跨源反查）时，源侧按标题+歌手匹配；不传也能按 id 走主通道。

**各源实测结论（2026-11-06，匿名只读实测）**

| 源 | 歌曲→MV 映射 | 播放地址 | Cookie/签名 | cover | 结果 |
|---|---|---|---|---|---|
| netease | `/song/detail` 的 `songs[].mv`（0=无）；查不到时 `/search?type=1004` 只接受**同名** MV | `/mv/url?id=<mvid>&r=1080`（`r` 是上限，返回实际 `r`）→ mp4 直链 | 匿名；`wsSecret/wsTime` 由 ncm-api 生成 | `mv/detail.cover` | ✅ 可播 |
| qq | 搜索行自带 `mv{id,vid}`（按 `mid` 对齐） | `vv.video.qq.com/getinfo` → `ul.url + fn + "?vkey="` → mp4 直链 | 匿名零 Cookie；`fvkey` 每次现取 | 无公开通道 → `null` | ✅ 可播（匿名档位偏低，实测 `vh` 多为 270~486） |
| kugou | `/search?type=mv` 行的 `FileHash` 与歌曲 hash **精确对齐** | `/video/detail?id=<MvID>` 取逐档 hash → `/video/url?hash=` → mp4 直链 | 容器自带概念版 Cookie；无需额外签名 | `hdpic`（`{size}` 换 480） | ✅ 可播（`fhd` 实测 1080p） |
| kuwo | `m.kuwo.cn/newh5app/wapi/api/www/music/musicInfo` 的 `mvpayinfo.vid`；但**歌曲关联 MV 已被官方全量下线**（对该 vid 走 `playUrl` 恒 `code:-1001「该MV已下线」`，含 2025-2026 新歌） | **在架 MV 目录**：`wapi/api/www/music/mvList`（9 分类，共约 2400 条）的 id → `wapi/api/v1/www/music/playUrl?mid=<MV id>&type=mv` → mp4 直链 | 匿名、零 Cookie、无需预热；但**必须走 `m.kuwo.cn/newh5app/wapi/**` 前缀**——同路径的 `www.kuwo.cn/api/**` 对本机 IP 恒 `{"success":false,"message":"The request is illegal!"}`（WAF，前端 `Secret` 算法复刻亦无效） | `mvList.pic` / `musicInfo.pic` | ✅ 目录 MV 可播；歌曲关联 MV 已下线 → `url: null` |
| migu | 搜索可带出 MV 条目，但播放路由矩阵全部「路由请求不支持」 | — | — | — | `url: null` |
| qianqian | 签名 API 无 MV 搜索类型（type 4~12/1004 均「不被支持」） | — | — | — | `url: null` |

**质量枚举与直链形态**

- `quality` 统一为 `ld` / `sd` / `hd` / `fhd`（按源实际清晰度归一，不照抄平台档位名）：
  `<=300` → `ld`，`<=480` → `sd`，`<=720` → `hd`，`>720` → `fhd`（netease 按实际 `r`，QQ 按 `vh`，kugou 按 `*_height`）。
- 三源实测返回的均为 **mp4 直链**（`Range` 请求 206 + `video/mp4`），**没有 m3u8 通道**；契约不区分形态，`url` 原样透出，客户端按 URL/`Content-Type` 自行选播放器。
- kugou `MvHash` 直接取 `/video/url` 会返回 **mkv（application/octet-stream）**，因此实现只使用 `/video/detail` 的逐档 mp4 hash（2026-11-06 20:31 上游合并重建容器后复核，行为不变）。
- **客户端播发时须带浏览器类 User-Agent**：netease 的 `vodkgeyttp8.vod.126.net` 对非浏览器 UA（如 `Python-urllib/3.x` 默认值）直接 403，带任意 `Mozilla/5.0` UA 即 206。media_kit / Web `video` / hls.js 均自带 UA，正常场景无需额外处理；仅脚本化探测要注意。

**有效期策略（客户端每次点击现取，不做长期缓存）**

- netease：`wsSecret/wsTime` 签名（实测约 1 小时窗口；ncm-api 自身会短暂复用同一签名）。
- QQ：`fvkey` 随 `getinfo` 现取，短时效。
- kugou：`downurl` 为带时效的 CDN 路径。
- 因此本端点**不接进程内缓存**：每次调用现取，避免把过期链接交给播放器。
- kuwo 例外：MV 目录（约 2400 条元数据，不含直链）在进程内缓存 6 小时；直链仍是每次现取。

---

### 4.12 GET /{source}/search?type=mv — MV / 视频搜索（2026-11-06 v1.20）

```
GET /{source}/search?type=mv&keywords=<关键词>&page=<从 1 起>&limit=<默认 settings.search_size_default>
```

**契约（`type=music` 是默认值，歌曲搜索的字段与形状完全不变；本节只在显式 `type=mv` 时生效）**

```json
{"code": 200, "msg": "ok", "data": {
  "source": "kuwo", "type": "mv", "keywords": "林俊杰", "page": 1, "total": 4,
  "items": [{"id": "3244328", "source": "kuwo", "title": "修炼爱情", "artist": "林俊杰",
             "cover": "https://img1.kuwo.cn/wmvpic/...", "duration_s": 268,
             "quality": null, "url": null}]
}}
```

- `data` 从 `{keywords,page,total,items}` 变为 `{source,type,keywords,page,total,items}`；`items` 的元素与 §4.11 的 `MvItem` **同构**（`id/source/title/artist/cover/duration_s/quality/url`）。
- **`url` 恒为 `null`**：MV 搜索只做"找到"，不做"取直链"；点击后按 `id` 走 `GET /{source}/mv?id=` 现取（避免把大批短效链接塞进搜索响应）。
- **`id` 口径 = 该源 `/mv?id=` 能直接接收的 id**，四源实测可衔接：
  | 源 | MV 搜索 `id` 是 | 说明 |
  |---|---|---|
  | netease | **mvid** | `mv()` 对"不存在的歌曲 id"回退按其作为 mvid 直取 |
  | qq | **歌曲 mid** | `mv()` 原口径（搜索行 `mv{id,vid}` 按 mid 对齐） |
  | kugou | **歌曲 FileHash** | `mv()` 按 `FileHash` 精确对齐 `/search?type=mv` 行 |
  | kuwo | **在架 MV id** | `mv()` 先查 MV 目录命中（避免与歌曲 rid 撞号），未命中再走歌曲路径 |
- **不支持 MV 搜索的源**（migu / qianqian / bilibili）→ HTTP 501 + `{"code":501,"msg":"MV search not supported ..."}`，与 §4.1 的能力缺失口径一致。
- 备案：`type` 只接受 `music` / `mv`（其它值 422），避免静默回落造成"以为是 MV 结果"。

**各源 MV 搜索通道（2026-11-06 实测）**

| 源 | 通道 | 结果特征 | 可播性 |
|---|---|---|---|
| netease | `cloudsearch?type=1004` → `result.mvs[]` | 标准 MV 目录，字段全 | 视 MV 是否下架/付费 |
| qq | 歌曲搜索行自带 `mv{id,vid}`，只保留带 `vid` 的行 | "有 MV 的歌" | 老 MV 大量被 QQ 下架（`getinfo` 回"视频被外星人劫走"），点击时由插件侧闸门过滤 |
| kugou | `/search?type=mv`（容器） | MV 行含 `FileHash/MvID/MvHash` | ✅ 逐档 mp4 |
| kuwo | **在架 MV 目录 `mvList` 本地检索**（9 分类 ≈2400 条，按 name+artist 分词全命中，`mvPlayCnt` 降序） | 只有酷我目前仍在架的 MV（以自家/新歌为主，华语老歌 MV 基本不在架） | ✅ 目录内全可播 |

> kuwo 说明：按歌曲关键词的 MV 库（`wapi/api/www/search/searchMvBykeyWord`）仍能匿名返回"有 MV 的歌"，但**这些歌的 MV 直链已被官方全量下线**；因此 MV 搜索改用"在架目录"通道，从源头保证搜到的都能点开。

---

## 5. 透传端点（酷狗/网易云全量能力）

```
GET|POST /kugou/api/{上游路径}?原始参数...
GET|POST /netease/api/{上游路径}?原始参数...
```

- 自动注入各自账户 cookie（酷狗动态拉取、网易固定 MUSIC_U），客户端无需关心凭证
- 上游 JSON **原样返回**（不包信封），HTTP 状态码透传
- 黑名单拦截（403）：`logout / captcha / sms / register / setcookie / cellphone / user/update`
- 超时 40s；受全局 API Key 保护

### 5.1 MusicFree 插件函数 ↔ 端点映射速查

| MusicFree 函数 | 酷狗透传路径 | 网易云透传路径 |
|----------------|-------------|---------------|
| search(music/album/artist/sheet) | `/kugou/api/search?keywords=&type=` | `/netease/api/cloudsearch?keywords=&type=` |
| getMediaSource / getLyric | 用 §4.2/§4.4 精装端点（非透传） | 同左 |
| getAlbumInfo（详情+曲目） | `/kugou/api/album/detail?id=` ＋ `/album/songs?id=` | `/netease/api/album?id=` |
| getArtistWorks（歌手作品） | `/kugou/api/artist/detail?id=` ＋ `/artist/audios?id=` | `/netease/api/artists?id=` ＋ `/artists/songs?id=` |
| getMusicSheetInfo / importMusicSheet | `/kugou/api/playlist/detail?id=` | `/netease/api/playlist/detail?id=` |
| getTopLists | `/kugou/api/rank/list` | `/netease/api/toplist` |
| getTopListDetail | `/kugou/api/rank/info?rankid=` 或 `/rank/top?rankid=` | `/netease/api/toplist/detail?idx=` 或 `/playlist/detail?id=` |
| getRecommendSheetTags / ByTag | `/kugou/api/playlist/…classify` 系列 | `/netease/api/playlist/hot` ＋ `/top/playlist?cat=` |
| getMusicInfo | `/kugou/api/privatelike` 或 §4.3 | `/netease/api/song/detail?ids=` |
| 评论（扩展能力） | `/kugou/api/comment/music?hash=` / `comment_album` | `/netease/api/comment/music?id=` |
| 云盘 | — | `/netease/api/user/cloud` 系列 |

> 路径规则：kugou-api 的模块文件名下划线即斜杠（`album_songs.js` → `/album/songs`）。完整模块清单见 KuGouMusicApi 仓库 `module/` 目录与 NeteaseCloudMusicApiEnhanced 文档。

### 5.1b P8 在线浏览端点（2026-11-04，kuwo 首发）

```
GET /{source}/toplists                       → 榜单列表（平铺）
GET /{source}/toplist/songs?id=&page=&limit= → 榜单曲目（by id 分页）
GET /{source}/playlist/tags                  → 推荐歌单标签（pinned+groups）
GET /{source}/playlist/sheets?tag=&page=&limit= → 标签下歌单（tag 空=全部热门；专区 <id>@<digest>）
GET /{source}/playlist/songs?id=&page=&limit= → 歌单曲目（by id 分页；page=1 附 meta）
```

- 统一 Envelope + schema（`ToplistsData/PlaylistTagsData/SheetListData/SheetSongsData`）；曲目 = `SearchItem` 同构，解析仍走 `/{source}/song/url` by-id（二段式不变）。
- 默认 501 envelope；kuwo 已实现（官方 wapi 免登通道在 adapter 内归一，形状 2026-11-04 现网实测；曲目 id=rid）。netease/kugou 榜单/推荐继续走透传族（§5）。
- kwqq 插件消费映射：cover→cover_url、SearchItem→source_data（`itemToResult`）、dedup_key `kwqq_kuwo_<rid>`。

### 5.1c P9 收编二期 + 导入协议（2026-11-04，netease/kugou 全量）

```
GET /{source}/artist                → 歌手详情（alias/描述/作品数）
GET /{source}/artist/works?type=music|album&page=  → 歌手作品（music=SearchItem / album=AlbumEntry）
GET /{source}/comments?id=|title=&artist=          → 歌曲评论（netease 支持回搜；kugou 需数字 mixsongid）
GET /{source}/album/detail?id=      → 专辑 by-id 详情（官方曲序 track_no；netease /album、kugou /album/songs；track_count 同 /album 规则）
GET /{source}/import/item?url=      → 导入单曲（urlLike 提取 id；MusicFree importMusicItem）
GET /{source}/import/sheet?url=&cap= → 导入歌单（自动翻页全量；cap 截断保护默认 1000）
GET /{source}/search/multi          → netease/kugou P9 收编（此前走透传）
GET /{source}/toplists|toplist/songs|playlist/tags|sheets|songs  → netease/kugou P9 收编
```

- 全部走统一 Envelope + schema；501 缺省（base）；kugou 曲目 id=hash（rank/audio hash_320 优先降档）、歌单 id=gid、import item id=mixsongid（media 链实测可解析）。
- kugou specialid→gid 换算（/playlist/detail）现网稳定返回空 data（疑似需登录态）→ import/sheet 对纯数字 specialid 报 404 引导 collection_… 形态。
- netease 评论 IComment 归一（nick_name/content/created_at snake_case → 消费方转 camelCase）。
- **透传族收缩后仅剩**：云盘 user/cloud、登录态端点、VIP（/kugou/vip/*）、排错转发。
- 2026-11-04 扩源：`artist` / `artist/works` 已实现 **qq（fcg `get_singer_detail_info` / `get_singer_album`，id=singerMID）与 kuwo（`search.kuwo.cn/r.s` 的 `artistinfo` / `artist2music` / `albumlist`，id=数字 artistid）**；qq 的 `search/multi?type=artist` 返回 `id=singerMID`（数字 singerID 无对应作品端点）。**qianqian** 补 `artist/works?type=music`（官方签名 `/v1/artist/song`，id=artistCode；与 MusicFree 同口径）——上游无「歌手专辑列表」通道，`type=album` 返回空集合（`total=0/is_end=true`，**不是 501**）。**migu 保持 501**：MusicFree 未实现 `getArtistWorks`，migu 亦无歌手作品聚合端点（能力缺省按 501 如实标注，不造假数据）。QQ `playlist/tags` 的分组标题取 `categoryGroupName`（`categoryName` 在分组层为空），pinned 取各组前 6 个标签。

### 5.2 VIP 运维精装端点（酷狗概念版畅听 VIP，已实测）

业务流程：**每日先领畅听 VIP(tvip) → 再升级为概念版(svip)**；升级会把当天记录的 vip_type 从 tvip 改写为 svip 并追加 24h。

| Method | Path | 成功响应要点 | 幂等错误码 |
|--------|------|--------------|-----------|
| POST | `/kugou/vip/day` | `{success:true, data:{ad_vip_num, server_time}}` | 131001 = 今日已领取 |
| POST | `/kugou/vip/upgrade` | `{success:true, data:{recharge_hours:24}}` | 297002 = 今日已升级 |
| GET | `/kugou/vip/status` | 见下方结构化输出 | — |

`receive_day` 由服务端自动取 **Asia/Shanghai 当天日期**，调用方无需传参。

GET `/kugou/vip/status` 响应 data 结构：

```json
{
  "svip_concept":   { "is_vip": true, "begin": "2026-04-26 15:58:39", "end": "2026-11-10 18:58:39" },
  "tvip_listening": { "is_vip": true, "begin": "2026-04-26 15:58:39", "end": "2027-03-27 18:58:39" },
  "claimed_days_this_month": 90,
  "claim_records": [ { "day": "2026-05-23", "vip_type": "svip" } ],
  "month": "2026-08",
  "raw": { "union": {}, "record": {} }
}
```

可被 cron / Home Assistant 自动化调用（例：每日 08:00 POST /kugou/vip/day → 等待 → POST /kugou/vip/upgrade），替代原 kugou_vip.sh 脚本。

---

## 6. 配置项全表（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `KWQQ_PORT` | 3003 | 监听端口 |
| `API_KEY` | 空 | 服务层 Key；空=关闭校验 |
| `SERVICE_TOKENS` | 空 | v2 播放签名（JSON：`{"<token>": {"scopes": ["playback:issue","cache:invalidate","media:prepare"], "generation": 1}}`）；与 `API_KEY` 独立，格式错误启动即失败 |
| `CREDENTIAL_GENERATION` | 1 | 未显式写 generation 的 token 默认代次；轮换即让 v2 缓存键失效 |
| `TRUSTED_NETWORKS` | `127/8,10.10.10.0/24,10.20.0.0/24,172.16/12,192.168/16` | 内网免 key 来源（含办公室 WG 10.20.0.0/24） |
| `UNTRUSTED_HOSTS` | `10.10.10.1` | 强制要求 key（Lucky 入口） |
| `RATE_LIMIT` | `120/minute` | 仅外网固定窗口限流（可信网段豁免，空=关闭；429 + `X-RateLimit-*`/`Retry-After` 头） |
| `ENABLE_LOSSLESS` | false | flac/hires 档总开关 |
| `NETEASE_COOKIE_FILE` | `/volume2/dev/data/api-secrets/musicAPI/netease_cookie.txt` | 网易云 MUSIC_U 凭证文件（volume 挂载直读，更新文件即生效） |
| `KUGOU_TOKEN_FILE` | `/volume2/dev/data/api-secrets/musicAPI/kugou_token.json` | 酷狗账户 token 文件（volume 挂载直读） |
| `NCM_API_BASE` / `KUGOU_API_BASE` | `:3000` / `:3001` | 两个兄弟容器地址 |
| `COOKIE_REFRESH_S` | 1800 | 酷狗 cookie 本地缓存时长 |
| `HARD_TIMEOUT_S` | 35 | 默认硬超时（deezer 类慢通道单独 150s） |
| `TESTER_TIMEOUT` | `3,8` | 直链验证超时 |
| `MAX_CONCURRENCY` | 4 | 每源工作线程数（= 真实并发容量；调用方超时不释放，须等线程真正退出） |
| `MAX_WAITERS` | `MAX_CONCURRENCY×2` | 每源排队上限，超出返回 503 capacity（静态分区，跨项目验收汇总两侧活跃数） |
| `IO_TIMEOUT_S` | 20 | 适配器同步请求读超时上限（且 ≤ `HARD_TIMEOUT_S`） |
| `PARSER_FAIL_THRESHOLD` / `PARSER_COOLDOWN_S` | 3 / 300 | 第三方源熔断参数 |
| `URL_CACHE_TTL` / `SEARCH_CACHE_TTL` / `META_CACHE_TTL` | 600/300/86400 | 缓存 TTL |

---

## 7. 部署与运维

```bash
# 同步代码（本机）→ NAS 并重建
tar czf - --exclude='.git' --exclude='.venv' --exclude='.uvcache' --exclude='.state' \
    --exclude='scripts' --exclude='examples' --exclude='mcp' --exclude='.github' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='deploy' ./ \
  | ssh zxsadmin@10.10.10.2 "tar xzf - -C /volume2/docker/musicdl-api/src/"
ssh zxsadmin@10.10.10.2 "cd /volume2/docker/musicdl-api && /usr/local/bin/docker compose up -d --build"

# 验收
python server/tests/test_smoke.py http://10.10.10.2:3003                       # 内网免 key
python server/tests/test_smoke.py https://kwqq-api.pegbiotec.com:4433 --auth <KEY>:  # 外网
```

compose：NAS `/volume2/docker/musicdl-api/docker-compose.yml`（host 网络模式）。日志 `docker logs musicdl-api`。监控建议盯 `/status` 的 parsers 冷却状态与缓存命中率。

常见故障：外网 401=key 错；502=第三方链挂（看 status 冷却表）；403=请求了无损档或命中黑名单；内网 401=来源 IP 不在信任网段。

---

## 8. 开发指南

### 8.1 代码结构

```
server/
├── app.py            # FastAPI 路由、API Key 中间件、VIP 精装端点、透传路由
├── proxy.py          # 通用透传引擎（cookie 注入/黑名单/字节直传）
├── config.py         # 配置
├── cache.py          # TTL 缓存
├── parsers_health.py # 第三方源健康度冷却
├── schemas.py        # Pydantic 模型（SearchItem 含 extra 回传字段）
├── adapters/
│   ├── base.py       # SourceAdapter 抽象（run/run_with_timeout/search_items）
│   ├── kuwo.py qq.py qianqian.py migu.py   # 四个自研解析 adapter
│   ├── netease.py kugou.py                 # 容器背书 adapter（账户态出链）
│   └── deezer.py     # 实验性未注册（解析站失效留档）
└── tests/test_smoke.py  # 离线/在线双轨冒烟（--auth 支持外网，--all 追加容器源）
```

### 8.2 核心约定

1. **零 Cookie 进 musicdl 国内解析链**：qq/kuwo 客户端配 Cookie 会禁用第三方链（源码门控），故四源恒匿名；网易/酷狗的账户态走**容器背书**路线而非 musicdl 客户端
2. **by-id 最小字典**：`_parsewiththirdpartapis({'mid'|'musicrid'|'id': id})` 触发元数据自动补全，无需重搜索
3. **search 不做解析**：元数据搜索走单请求接口；全解析链只属于 CLI
4. **新增源三步**：实现 SourceAdapter 子类 → 注册 ADAPTER_CLASSES → 加 SOURCES
5. **新增透传目标**：在 proxy.PROXY_CFG 加条目 + app.py 加两条路由

### 8.3 测试体系

```bash
scripts/regress_stage1.py                    # 核心回归 8 项
.state/instrument_plugin.cjs <插件.js>       # vm 插桩捕获混淆插件真实请求
server/tests/test_offline.py                 # 离线：信封/鉴权/缓存/音质表/限流/指标
server/tests/test_contract.py                # 离线：v2 TrackRef 身份/凭据/严格播放 profile
server/tests/test_concurrency.py             # 离线：真实并发/容量/waiter 有界/迟到结果丢弃
server/tests/test_resilience.py              # 离线：singleflight/429 冷却/受限失效
examples/musicdlwebgui/tests/test_offline.py # 离线：webgui 身份快照/原子发布/outbox/kwqq_only/鉴权
server/tests/test_smoke.py <url> [--auth K:] # 冒烟默认档（含 netease 与专辑/歌单）；--all 追加容器源
```

七插件（MusicFree）侧契约与测试：姊妹仓 `D:\_work\repos\musicfree-plugins\docs\PLUGIN-COMPAT.md`
（`node shared/build.js && node tests/run.js`）。

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-11-06 | 1.20 | +`/{source}/search?type=mv`（MV/视频搜索：`data={source,type,keywords,page,total,items}`，item 与 §4.11 MvItem 同构、`url` 恒 null，点击后按 `id` 走 `/mv` 现取；`type=music` 默认行为与歌曲搜索字段完全不变；migu/qianqian/bilibili 501）。`id` 口径对齐 `/mv?id=`：netease=mvid、qq=mid、kugou=FileHash、kuwo=在架 MV id。**酷我 MV 更正**：上一版判"无匿名通道"不成立——匿名通道在 `m.kuwo.cn/newh5app/wapi/**`（`www.kuwo.cn/api/**` 被 WAF 恒回 `The request is illegal!`，前端 Secret 算法复刻无效）；但酷我已把**歌曲关联 MV 全量下线**（`mvpayinfo.vid` 走 `playUrl` 恒 `code:-1001`），故 `/{source}/mv` 改从**在架 MV 目录**（9 分类 `mvList` ≈2400 条，直链全可播）取址；MV 搜索按目录本地检索，从源头保证"搜到的都能点开" |
| 2026-11-06 | 1.19 | +`/{source}/mv`（歌曲 MV：顶层恒为首个可直接播放项 `{id,source,url,cover,duration_s,quality}`，可选 `items`；无 MV 走 HTTP 200 + `url:null`，不做 404/空对象）。实测可用源：netease（`/mv/detail`+`/mv/url`，r 为上限）、qq（`vv.video.qq.com/getinfo` 的 `<fvkey>` 拼链）、kugou（容器 `/search?type=mv` 按 FileHash 精确对齐 + `/video/detail`+`/video/url` 逐档 mp4）；kuwo/migu/qianqian 无匿名 MV 通道 → `url:null`。全部为 mp4 直链（三源均无 m3u8）；签名短链不缓存、客户端每次现取 |
| 2026-10-29 | 1.9 | +`POST /v2/playback/resolve`（K-01：TrackRef 身份契约、`X-Service-Token` scoped 服务凭证、结构化缓存键含身份/策略/凭据代次）；bilibili v2 支持受验证 cid/page（不再固定 pages[0]），`/song/info` 回传 `extra.cid/page` + `raw.pages`；migu 保留 contentId+copyrightId；v1 全部端点与 ekey 下载契约不变 |
| 2026-10-29 | 1.10 | v2 严格播放准入（K-02 §4.8）：原始 quality 白名单先于归一化（无损请求 400 而非回落 auto）；FLAC/加密件/>320k 415；AAC 仅 `media:prepare` scope 的 `target=media_prepare` 可进转码准备且 `requires_transcode=true`；`verified` 语义修正（v2 恒 false + `requires_byte_verification=true`，完整验证归 Songloft）；v1 语义不变 |
| 2026-10-29 | 1.11 | 执行层真实并发（K-03）：每源独立线程池，容量仅在 worker 线程真正退出后释放（调用方超时不释放）；等待队列 `MAX_WAITERS` 有界，满则 503 capacity；所有裸同步请求带 `IO_TIMEOUT_S`；netease 高档 HEAD 移入受测执行边界；迟到结果丢弃不投送；`/status` 新增 `runtime` 逐源计数（active/waiting/timed_out/late_dropped）供跨项目容量验收汇总 |
| 2026-10-29 | 1.13 | 消费方收口（K-06）：七 MusicFree 插件改为 v2 优先（配置 `serviceToken` 时走 `/v2/playback/resolve`，未配置/旧服务端回落 v1 迁移窗口）；B站 cid/page、咪咕 copyrightId 进 TrackRef；酷狗播放不再回落 FLAC、兼容链拒绝非 mp3；插件 runtime 对 HTTP 429 不换 host（保留 Retry-After、冷却期零请求）；清单与许可开放项见姊妹仓 `docs/PLUGIN-COMPAT.md` |
| 2026-10-29 | 1.16 | 探测哨兵修复：`AudioLinkTester` 推断失败时返回的 `"NULL"` 不再作为 ext 出现在任何响应或 v2 准入（`clean_ext` 单点归一为 null）；bilibili 探测带 CDN 要求的 Referer，并按 DASH 轨 id 兜底编解码（30251=flac / 30250=ec3 / 其余 m4a） |
| 2026-11-04 | 1.17 | `/{source}/album` 与 `/{source}/album/detail` 新增 `track_count`（adapter 能力位 `album_track_count`：netease/kuwo/kugou/qq 有值；migu/qianqian null=不显示，选项 A 不逐专辑查详情）；kwqq 插件专辑曲目数改读该字段，不再用 `total`/页长臆造 |
| 2026-11-04 | 1.18 | qq/kuwo 补齐 `artist` + `artist/works`（qq id=singerMID、kuwo id=artistid）；qianqian 补 `artist/works?type=music`（`/v1/artist/song`，album 空集合非 501）；migu 仍 501（无上游通道）；qq `playlist/tags` 分组标题改 `categoryGroupName`、pinned 取各组前 6 标签；live 冒烟新增 artists works/tags 检查项 |
| 2026-10-29 | 1.15 | 评审修复：v2 缓存键改用归一化策略（别名拼写共享一项、失效不必复刻拼写）；v2 `cache/invalidate` 同样做 quality 白名单校验；非 ASCII `X-Service-Token` 返回 401（不再 500）；bilibili search 遇 429 不再缓存空结果并按逻辑入口冷却；七插件 v2 超时不换 host 重跑 |
| 2026-10-29 | 1.14 | 审查修复：`/{source}/song/url` 新增可选 `cid`/`page`（bilibili 分 P 身份进 v1 缓存键）；透传与 netease search 共用逻辑入口冷却（429 不再被旁路）；`freshness=revalidate` 先失效再经 singleflight 重解析并把新值写回；singleflight 键改用稳定 uid；bilibili buvid 取指纹移入受测执行边界 |
| 2026-10-29 | 1.12 | singleflight + 限流冷却 + 受限失效（K-04）：同结构化键并发只解析一次（等待者取消隔离、失败不写负缓存）；上游 429 按逻辑入口冷却并保留 Retry-After，换 host/备用入口零请求、429 不入成功缓存；+`POST /v2/cache/invalidate`（`cache:invalidate` scope，精确身份失效，一次受控重解析）；`freshness` 仅接受 allow_cache/revalidate；本地/上游 429 以 `X-RateLimit-Scope` 区分 |
| 2026-10-27 | 1.6 | `TRUSTED_NETWORKS` 默认加入办公室 WG 网段 `10.20.0.0/24`（D-x 定案：办公室免 key / 免限流；代价是该网段内设备均可匿名访问） |
| 2026-10-28 | 1.7 | +`/{source}/album`（P6 专辑检索：候选 + 首选专辑有序曲目 track_no；netease 先行，未实现源 HTTP 501）|
| 2026-10-28 | 1.8 | +`/{source}/playlist`（P6 歌单检索，netease 先行）；`/{source}/album` 扩至 kugou/migu/qianqian（候选 name+artist 无结果自动退 name-only）；netease 进 live 冒烟常规档 |
| 2026-10-27 | 1.5 | +`/metrics`（Prometheus 文本格式，非信封）；+`RATE_LIMIT` 仅外网限流（429 + X-RateLimit 头，内网豁免）；kugou `/lyric` 容器 400（20010）时 fallback 官方歌词链路；部署现状注记：NAS compose `ENABLE_LOSSLESS=true`（仓库默认 false，以 NAS 为准） |
| 2026-08-12 | 1.0 | 六源中的四源上线（酷我/QQ/千千/咪咕）+ NAS 部署 + 外网验收 |
| 2026-10-27 | 1.4 | 音质档位知识收敛 `server/quality.py`（ADR-0003）：192k 语义统一（真档优先/就近上取；bilibili 192k 由落 auto 收紧为 320k）、每源白名单/lossless 门单点化、LOSSLESS_EXTS 补齐 8 元素 |
| 2026-08-24 | 1.2 | +bilibili 第七源（DASH 提取，匿名 192k，SESSDATA 可解锁 Hi-Res）；+MUSIC_U VIP 无损；+VIP 运维端点；+全量透传层；+内网免 key |
| 2026-08-23 | 1.1 | 元力/haitangw 兜底通道；nmobi 主通道；服务层 API Key + 内网免 key；host 网络部署；网易云 MUSIC_U VIP 无损；酷狗容器背书出链；**通用透传层（全函数就绪）**；Deezer/Apple/TIDAL 等调研结论留档 |> **GD音乐台（gdstudio）实验性未启用**：官方无签名 API 已验证可用（2026-08-23 全平台普查）：
> - ✅ 存活通道：netease（真直链）、**joox（FLAC）**、bilibili（m4s 音视频流，B站曲库含大量 Hi-Res 翻唱/OST）
> - ❌ 已下线：tencent / tidal / qobuz / apple / spotify / ytmusic（400 not supported，因连续封号收缩战线）
> - ⚠️ kuwo 通道接口通但版权曲空 url
> - ❌ 硬伤：新付费服务器国内连接超时率约 50%；限频 5min≤50 次
> - adapter 代码已备（server/adapters/gdstudio.py），服务器稳定后加回 ADAPTER_CLASSES 即启用


