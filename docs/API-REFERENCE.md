# kw-qq-music-api 接口开发文档

> 版本：1.1 · 更新：2026-08-23 · 源码分支：`api-server`（musicdl 仓库）
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
**migu 的 `extra.copyrightId` 必须在后续 song/url、song/info 时以 `?copyright=` 回传。**

### 4.2 GET /{source}/song/url — 播放直链

| 参数 | 必填 | 说明 |
|------|------|------|
| id | ✅ | 歌曲 id |
| quality | — | auto/320k/128k/flac/hires/**master/surround51**（MusicFree 四档归一：low=128k、standard=192k、high=320k、super 封顶 320k；5.1→surround51；无损档仅对 musicdl 下载有效） |
| copyright | — | 仅 migu |

成功 data 字段：`{url, ext, bitrate_kbps(如实), size_bytes, duration_s, verified, parser, elapsed_ms, headers, ekey}`。
**bilibili 源的 `headers` 必须传给播放器**（CDN 校验 Referer，缺了 403）：`{"Referer": "www.bilibili.com", "User-Agent": "..."}`。其他源 headers 通常为空。
**音质路由**：MusicFree 四档：low→128k 全源；standard→192k（网易 level=higher 实测 192kbps；其余源无原生 192k 档回落 320k——酷我 192kmp3 为假档实测降 128 故向上就近）；high→320k 全源；super 封顶 320k（QQ 第三方链尽力而为，若上游给 flac 则响应 quality 如实标注）。auto/320k 封顶 320kbps（netease 经 MUSIC_U 可出 exhigh=320k）；flac/hires/master/surround51 受 `ENABLE_LOSSLESS` 门控（默认 false→403）。各源通道：酷我 nmobi 直出（320k/flac/**master=20900kmflac 匿名 192k/24bit**）→mobi.s→第三方链；QQ 第三方链(vkeys…)→元力→3e0；千千 tracklink（rate=3000 实测真 FLAC：48k/24bit 入门 Hi-Res 与 44.1k/16bit CD 逐曲不定，无母带）；咪咕 listen-url(HQ/SQ)（**匿名 SQ/ZQ 实测为假无损**——URL 200 可下但实为降档 MP3）；网易 ncm-api(level)；酷狗 kugou-api(quality)（**酷狗无 hires 参数**，high=24bit/44.1k 即高解析位阶；viper 三档需超级VIP，当前不可达）。各平台规格详见 docs/QUALITY-MATRIX.md。
**酷我 master/surround51 专属**：`ext=mflac` 且携带 `ekey`（QMC 密钥）——`url` 指向**加密**容器，消费方须用 `KuwoQmcDecryptor`（`scripts/kuwo_qmc_decryptor.py`）解密得到明文 flac（192k/24bit 或 44.1k/16bit/6ch）；明文档位无 `ekey` 字段。仅酷我源支持这两档，其他源按各自能力回落。

### 4.3 GET /{source}/song/info · GET /{source}/lyric

单曲元数据 / LRC 歌词。migu 两端点同样需要 `copyright=`。netease lyric 需容器登录态才有完整翻译/罗马音。

### 4.4 GET /{source}/album — 专辑检索（P6，2026-10-28 v1.8）

专辑名 → 候选专辑 + **首选专辑的有序曲目**，一次调用覆盖"整张连播"场景（消费方：bridge `song_request`、songloft kwqq 插件专辑页）。

| 参数 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 专辑名关键词 |
| artist | — | 歌手提示（用于同名异手专辑的候选排序） |
| page | — | 专辑候选页码 ≥1 |

成功 data：`{source, name, artist, albums: [{id, name, artist, size, cover, source, extra}], items: [<search item 结构> + track_no], total}`。

- **items = 首选专辑的官方曲序**，`track_no` 1 起；item 结构与 `/search` 完全一致 → 曲目解析照走 `/{source}/song/url?id=`（二段式不变）。
- **逐源能力**（未实现的源返回 **HTTP 501** envelope——能力缺失类，非业务未命中 403/404）：`netease` ✅（ncm-api `/cloudsearch?type=10` → `/album`）；`kugou` ✅（容器 `/search?type=album` → `/album/songs`，按 `extend.disc+sort` 官方曲序）；`migu` ✅（`search_all.do` album=1 → `resource/album/song/v2.0`）；`qianqian` ✅（`/v1/search type=3` → `/v1/album/info`，曲库较稀疏）；`kuwo`/`qq` ◐ 未接入（kuwo 曲目列表需 kw_token；QQ 匿名模块 500003）。
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
- 缓存键 = 结构化身份 + 播放策略 + 凭据代次（`v2:` 命名空间，独立于 v1 url_cache）。

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
- 只删除「该身份 + 该策略 + 该 token 代次」的精确键：无通配符、无跨身份、无跨代次；返回 `{invalidated, identity_digest, generation, profile}`。
- 重解析预算：一次失效后最多一次受控重解析（并发同键由 singleflight 合并）；端到端重试预算由最外层命令持有，kwqq 不叠加自己的多轮重试。

### 4.10 singleflight、限流冷却与错误分类（K-04）

- **singleflight**：同一结构化键的并发请求只有一个 leader 执行上游解析，其余等待者共享结果；等待者取消不影响 leader 与其他等待者；leader 失败不写负缓存，后续请求可自行重试。
- **上游 429 冷却**：冷却按**逻辑入口**（如 `kuwo:relay.haitangw`、`netease:ncm-api`、`kugou:container`）记账，与 host 别名/内外网入口无关——换 host、换备用入口都不重置同一冷却，冷却期内备用入口**零请求**；保留上游 `Retry-After`；429 结果永不作为成功缓存。
- **限流分类**：本地限流器 429 带 `X-RateLimit-Scope: local`；上游 429 带 `X-RateLimit-Scope: upstream` + `Retry-After`。两者都是 HTTP 429 + 信封 `code=429`。
- `/status` 的 `parsers` 快照新增 `cooldown_remaining_s`、`throttled`。

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
server/tests/test_smoke.py <url> [--auth K:] # 冒烟默认档（含 netease 与专辑/歌单）；--all 追加容器源
```

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-10-29 | 1.9 | +`POST /v2/playback/resolve`（K-01：TrackRef 身份契约、`X-Service-Token` scoped 服务凭证、结构化缓存键含身份/策略/凭据代次）；bilibili v2 支持受验证 cid/page（不再固定 pages[0]），`/song/info` 回传 `extra.cid/page` + `raw.pages`；migu 保留 contentId+copyrightId；v1 全部端点与 ekey 下载契约不变 |
| 2026-10-29 | 1.10 | v2 严格播放准入（K-02 §4.8）：原始 quality 白名单先于归一化（无损请求 400 而非回落 auto）；FLAC/加密件/>320k 415；AAC 仅 `media:prepare` scope 的 `target=media_prepare` 可进转码准备且 `requires_transcode=true`；`verified` 语义修正（v2 恒 false + `requires_byte_verification=true`，完整验证归 Songloft）；v1 语义不变 |
| 2026-10-29 | 1.11 | 执行层真实并发（K-03）：每源独立线程池，容量仅在 worker 线程真正退出后释放（调用方超时不释放）；等待队列 `MAX_WAITERS` 有界，满则 503 capacity；所有裸同步请求带 `IO_TIMEOUT_S`；netease 高档 HEAD 移入受测执行边界；迟到结果丢弃不投送；`/status` 新增 `runtime` 逐源计数（active/waiting/timed_out/late_dropped）供跨项目容量验收汇总 |
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


