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
- **内网免 key**：来源 IP ∈ `TRUSTED_NETWORKS`（默认含 `10.10.10.0/24,172.16/12` 等）且不在 `UNTRUSTED_HOSTS`（默认 `10.10.10.1`=Lucky 入口，防外网借道）
- 其余来源必须携带，二选一：

```
Authorization: Basic base64(API_KEY + ":")     # 与 kugou.js 插件模式一致
X-API-Key: <API_KEY>
```

失败返回 `401`。当前生效 key 见 NAS `/volume2/docker/musicdl-api/docker-compose.yml` 的 `API_KEY`。

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

### 4.4 七源逐源详述

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
| 音质映射 | low→64k、standard→132k、auto/high/320k→192k AAC；super/flac/hires→Hi-Res/Dolby 声道（gated） |
| **headers 必须** | CDN 校验 Referer：客户端须携带 `Referer: www.bilibili.com` + UA，否则 403 |
| 已知边界 | 匿名音质封顶 192k AAC；UGC 内容库（翻唱/改编/现场），与版权曲库互补而非替代 |

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
| `TRUSTED_NETWORKS` | `127/8,10.10.10.0/24,172.16/12,192.168/16` | 内网免 key 来源 |
| `UNTRUSTED_HOSTS` | `10.10.10.1` | 强制要求 key（Lucky 入口） |
| `ENABLE_LOSSLESS` | false | flac/hires 档总开关 |
| `NETEASE_COOKIE_FILE` | `/volume2/dev/data/api-secrets/musicAPI/netease_cookie.txt` | 网易云 MUSIC_U 凭证文件（volume 挂载直读，更新文件即生效） |
| `KUGOU_TOKEN_FILE` | `/volume2/dev/data/api-secrets/musicAPI/kugou_token.json` | 酷狗账户 token 文件（volume 挂载直读） |
| `NCM_API_BASE` / `KUGOU_API_BASE` | `:3000` / `:3001` | 两个兄弟容器地址 |
| `COOKIE_REFRESH_S` | 1800 | 酷狗 cookie 本地缓存时长 |
| `HARD_TIMEOUT_S` | 35 | 默认硬超时（deezer 类慢通道单独 150s） |
| `TESTER_TIMEOUT` | `3,8` | 直链验证超时 |
| `MAX_CONCURRENCY` | 4 | 每源并发信号量 |
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
└── tests/test_smoke.py  # 15 项冒烟（--auth 支持外网）
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
server/tests/test_smoke.py <url> [--auth K:] # 冒烟 15 项
```

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-08-12 | 1.0 | 六源中的四源上线（酷我/QQ/千千/咪咕）+ NAS 部署 + 外网验收 |
| 2026-08-24 | 1.2 | +bilibili 第七源（DASH 提取，匿名 192k，SESSDATA 可解锁 Hi-Res）；+MUSIC_U VIP 无损；+VIP 运维端点；+全量透传层；+内网免 key |
| 2026-08-23 | 1.1 | 元力/haitangw 兜底通道；nmobi 主通道；服务层 API Key + 内网免 key；host 网络部署；网易云 MUSIC_U VIP 无损；酷狗容器背书出链；**通用透传层（全函数就绪）**；Deezer/Apple/TIDAL 等调研结论留档 |> **GD音乐台（gdstudio）实验性未启用**：官方无签名 API 已验证可用（2026-08-23 全平台普查）：
> - ✅ 存活通道：netease（真直链）、**joox（FLAC）**、bilibili（m4s 音视频流，B站曲库含大量 Hi-Res 翻唱/OST）
> - ❌ 已下线：tencent / tidal / qobuz / apple / spotify / ytmusic（400 not supported，因连续封号收缩战线）
> - ⚠️ kuwo 通道接口通但版权曲空 url
> - ❌ 硬伤：新付费服务器国内连接超时率约 50%；限频 5min≤50 次
> - adapter 代码已备（server/adapters/gdstudio.py），服务器稳定后加回 ADAPTER_CLASSES 即启用


