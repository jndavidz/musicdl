# 音乐源端点与凭证总册

> 用途：kwqq-api 全部已知解析端点、凭证、密钥的登记与存活状态台账（含失效条目，供考古与恢复参考）
> 维护方式：每次探测后更新「状态」列；新增端点追加到对应平台章节
> 实测方法：真实歌曲 id 直调（QQ mid=0039MnYb0qxYhV《晴天》/ 酷我 rid=228908《晴天》/ 网易 id=108914《江南》/ 网易灰曲 id=186016《晴天》）
> 最后全量探测：2026-08-24 · 标注 ✅=可用 ⚠️=不稳定 ❌=失效 🔐=需凭证
> ⬆️ **上游同步基线：musicdl v2.14.2**（merge `74c6ac1`，2026-10-24）。标 ⬆️ 的条目取自上游源码 diff，**本轮未复测**，其存活状态以下一轮探测为准
> 2026-10-27 补登记：§3.4 网易链重排、§5.4 Apple Music 重构、§5.5 五个网页源的端点修正、§5.2 社区鉴权链——同属 **⬆️ 未复测** 范围
> 2026-11-06 补登记：**§12 MV 端点**（netease/qq/kugou ✅ 已接入，kuwo/migu/qianqian ❌ 无匿名通道）——本轮现网只读实测

---

## 图例与集成标记

| 标记 | 含义 |
|------|------|
| 🟢 已集成 | 在 musicdl-api 出链路由中 |
| 🧪 备用未集成 | 代码/清单在案，按需启用 |
| 💀 已死亡 | 端点不可达或永久失效 |

---

## 1. QQ 音乐

### 1.1 第三方解析端点

| 端点 | 音质 | 鉴权 | 状态 | 集成 |
|------|------|------|------|------|
| `api.vkeys.cn/music/tencent/song/link?mid=&quality=` | FLAC→128 多档 | 无 | ✅ 主力（热门曲出真 FLAC ~1.1s） | 🟢 musicdl l1 |
| 元力 `175.27.166.236/kgqq1/qq.php?id=&type=json&level=exhigh\|lossless` | exhigh=320k / lossless=FLAC（**实为酷我 CDN 换源**） | 无 | ✅ 2026-08-23 实测 | 🟢 兜底位 |
| `music.haitangw.cc/music/qq.php` | 会员歌无法解析 | 无 | ⚠️ 免费歌可用 | 未集成 |
| `api.xcvts.cn/api/music/qq` | — | apikey | 💀 无效密钥 | — |
| `api.xingmian.bbroot.com` | — | base64 key | ❌ 探测不稳定 | — |
| `antra.hoshi.cfd`（job 队列 lossless-24） | 24bit | 内置账号池 | 🧪 未验证（慢） | — |
| `flacdownloader.com` | flac | token 动态 | 🧪 未验证 | — |
| `deemixer.com` | 按 bitrate | 无 | 🧪 未验证 | — |
| `musicfab.io/api/deezer` | mp3 | 无 | 🧪 未验证 | — |
| `deezdownloaders.com` | 128 | 无 | 🧪 未验证 | — |
| ⬆️ `https://qqovo.top/api/session/bootstrap`（POST `{"deviceId"}` → `apiSignKey`） | — | 会话内签密钥 | 🧪 v2.14.2 引入，未复测 | 🟢 qq / 酷狗 / 汽水 l2 |
| ⬆️ `https://qqovo.top/api/meting?server=tencent&type=url&id={mid}&quality=lossless` | lossless 声明 | HMAC-SHA256 自签 | 🧪 未复测 | 🟢 qq l2 |
| ⬆️ `https://meting.mikus.ink/api?server=tencent&type=url&id={mid}` | 服务端定档 | 无 | 🧪 未复测 | 🟢 qq l3 |

### 1.2 官方端点

| 端点 | 状态 | 说明 |
|------|------|------|
| `media.deezer.com/v1/get_url`（Deezer 章节，加密流参照） | — | QQ 的 media 加密流同类问题见酷狗章节 |
| `u.y.qq.com/cgi-bin/musicu.fcg`（搜索/歌单/榜单） | ✅ 匿名 | 元力插件同款 |
| GetVkey 匿名 purl | ❌ | 匿名/兜底 token 均拿不到（2026-08-07 与 08-23 两次确认） |

### 1.3 QQ 密钥/Cookie 登记

| 凭证 | 值/来源 | 状态 |
|------|---------|------|
| musicfab/deezdownloaders 等 | 见 ETC 分析 §4.2 | 部分 key 明文有效 |
| QQ 登录 Cookie（uin/qm_keyst） | 用户自有 | 🔐 未配置 |

### 1.4 解析链与签名协议（⬆️ v2.14.2）

**QQovo 签名协议**（qq / 酷狗 / 汽水三端共用一套实现）：bootstrap 取回 `apiSignKey` 后，每个请求带 `X-OM-Ts`、`X-OM-Nonce`、`X-OM-Sign`，其中签名 = `base64url(HMAC-SHA256(signKey, payload))` 去尾 `=`，payload = `"GET\n" + path + "\n" + 排序后的 query + "\n\n" + ts + "\n" + nonce`。Referer 固定 `https://qqovo.top/room/4SVWQK`，Origin `https://qqovo.top`。

**QQ 解析链位次变化**：

| 层级 | v2.13.10 | ⬆️ v2.14.2 | 影响 |
|------|----------|------------|------|
| l1（svip 直取） | vkeys · 317ak · xingmian · chksz · xcvts（5 项全跑） | 重排为 vkeys · xcvts · 317ak · xingmian **且截断 `[:2]`** → 实际只跑 vkeys + xcvts | xcvts 密钥已失效（见 §9），**l1 实际只剩 vkeys 单点**；317ak / xingmian 被挤出主链，chksz 下移 l2 |
| l2（vip） | nki · tang · hk0cc | chksz · **qqovo** · nki · tang · hk0cc | chksz 从 l1 上移入；qqovo 插到第 2 位 |
| l3（vip，仅 mp3/m4a） | cy · lzmhhh · xunhuisi | cy · lzmhhh · xunhuisi · **mikus** | 新增 mikus 兜底 |
| l4（失效池） | xianyuw · yutangxiaowu · lxmusic · lpz | 不变 | — |

⚠️ 风险：l1 重排后截到 `[:2]` = vkeys + xcvts，而 xcvts 密钥已失效（见 §9），**QQ 无损实际单点依赖 vkeys**。若 vkeys 挂掉，冷启动直接落到 l2 的 chksz——比 v2.13.10 的 5 项 l1 池脆弱得多。

---

## 2. 酷我音乐

### 2.1 解析端点

| 端点 | 音质 | 鉴权 | 状态 | 集成 |
|------|------|------|------|------|
| **`nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid=&br=`** | 精确档位（320kmp3→真320；2000kflac→无损；**20900kmflac→192k/24bit母带+ekey**；**20501kmflac→44.1k/16bit/6ch全景声+ekey**） | 无 | ✅ 主力直出 ~120ms 不降档；臻品档 2026-09-07 探明（详见 `KUWO-ZHENPIN-PROBE.md`） | 🟢 |
| `mobi.kuwo.cn/mobi.s?f=kuwo&q=<des加密>`（convert_url2） | 会静默降档 | 无（内置密钥 ylzsxkwm） | ✅ 备胎 | 🟢 |
| `musicpay.kuwo.cn/music.pay?newver=3&op=query&action=play&ids=` | 臻品档位元数据（N_MINFO/audio[]/token） | 无 | ✅ 2026-09-07 探明：匿名报价单，op 必须 `query`、id 参数必须 `ids` | 🟢 |
| `music.nxinxz.com/kw.php?id=&level=` | lossless/exhigh/standard | 无 | ✅ 稳定 | 🟢 第三方链 |
| **`music.haitangw.cc/music/kw.php?id=&level=`**（⚠️ 插件内置 /music1/ 为死路径） | lossless=FLAC / exhigh=320k | 无 | ✅ 2026-08-23 修正路径后可用 | 🟢 兜底 |
| `kw-api.cenguigui.cn/?id=&level=` | lossless | 无 | ⚠️ 连接失败（间歇） | 🟢 musicdl l2 |
| `kwdec.942240.xyz` | 七级音质 | 无 | 💀 DNS 失效 | — |
| `music.90svip.cn` | — | 无 | 💀 404 | — |
| `music-api.gdstudio.xyz (source=kuwo)` | url 空 br=-1 | 无 | ⚠️ 上游空响应 | 未集成 |

### 2.2 酷我官方匿名说明

`mobi.s convert_url2` 密钥 `SECRET_KEY_SONG=b"ylzsxkwm"` 为防爬非认证；歌词双通道（newlyric DES / openapi）均匿名可用。

### 2.3 臻品（ZhenPin）匿名直出与鉴权结论

2026-09-07 全量探测（详见 `KUWO-ZHENPIN-PROBE.md`）：

| br 参数 | 规格 | ekey | 可用 |
|---|---|---|---|
| `20900kmflac` | FLAC 192kHz/24bit/2ch（母带） | ✓ | ✅ |
| `20501kmflac` | FLAC 44.1kHz/16bit/6ch（5.1 全景声） | ✓ | ✅ |
| `20201kmflac` | FLAC 44.1kHz/16bit/2ch | ✓ | ✅（与 2000kflac 同级，未单列）|
| `24000kmgg` | Ogg Vorbis 12ch（7.1.4） | ✓ | ⚠️ 可下但 12ch Ogg |
| `192kmp3`/`22000kmgg`/`23000kflac`/`25000kmmp4`/`10000kflac` | — | — | ❌ 降档/无效 |

- **鉴权三层结论**：①客户端 UI 闸门（LSPosed hook 的打击面）②music.pay 报价接口（匿名可查，`policy=vip/st=102` 只是标记）③**nmobi 直链下发不做身份校验** —— musicdl 直打第③层，`user=0` 全档通过，无需会员/Cookie/APK
- **命名陷阱**：臻品档必须带 `m` 前缀（`20900kflac` 漏 m 会静默降 128k）
- **URL 时效**：数分钟级，必须现取现下（二段式天然契合）
- 落地：`server/adapters/kuwo.py` `ZHENPIN_BR` + `parser=nmobi.zhenpin`；响应新增 `ekey` 字段，下载侧 `KuwoQmcDecryptor` 解密为 flac

---

## 3. 网易云音乐

### 3.1 出链通道

| 通道 | 音质 | 鉴权 | 状态 | 集成 |
|------|------|------|------|------|
| **ncm-api 容器 `/song/url/v1?level=`** + `NETEASE_COOKIE`(MUSIC_U) | standard→hires（黑胶 VIP：lossless=944kbps FLAC 实测） | 🔐 MUSIC_U | ✅ VIP 生效 | 🟢 主通道 |
| **ncm-api 容器 `/cloudsearch?type=10` + `/album?id=`** | 元数据（专辑候选 + 官方曲序，P6 `/{source}/album` netease 实现） | 无（cookie 可选） | ✅ 2026-10-28 实测 | 🟢 P6 主通道 |
| kuwo `/search.kuwo.cn/r.s?ft=album&itemset=album`（专辑候选）| 元数据 | 无 | ✅ 候选可搜 | 🧪 半通：**曲目列表端点未通**（wapi `/api/www/album/musicList` 需 kw_token cookie，JS 注入 curl 拿不到；nmobi albuminfo 空响应）|
| QQ `u.y.qq.com musicu.fcg`（匿名）| 元数据 | 无 | ❌ 专辑受限：search_type=3 空结果、`AlbumInfoEx`/`AlbumSongList` code 500003（匿名拒绝） | 💀 未接（除非带登录态） |
| 咪咕 `search_all.do`（`searchSwitch.album=1`）→ `app.c.nf.migu.cn/MIGUM3.0/resource/album/song/v2.0` | 元数据（专辑候选 + 官方曲序） | 无 | ✅ 2026-10-28 实测（叶惠美 11 曲，以父之名→懦夫→晴天…） | 🟢 P6 album |
| 千千 `/v1/search type=3` → `/v1/album/info`（曲目 `assetId` 即 TSID，tracklink 直出） | 元数据（专辑候选 + 曲序） | 无（MD5 签名 appid） | ✅ 2026-10-28 实测（逆流而上 1 曲；千千曲库稀疏，热门专辑常缺） | 🟢 P6 album |
| 酷狗容器 `/search?type=album` → `/album/songs`（`extend.disc+sort` 官方曲序） | 元数据（专辑候选 + 曲序） | 概念版 Cookie（容器；匿名查询亦可） | ✅ 2026-10-28 实测（叶惠美 11 曲） | 🟢 P6 album |
| netease `cloudsearch?type=1000` → `/playlist/track/all`（P6 `/{source}/playlist`） | 元数据（歌单候选 + 曲序） | 无（cookie 可选） | ✅ 2026-10-28 实测（87 曲） | 🟢 P6 playlist 主通道 |
| 酷狗容器 `/playlist/detail` + `/playlist/track/all` | 元数据 | 概念版 Cookie | ❌ 容器 error_code 20010 | 💀 未接 |
| kuwo / QQ / 千千 歌单按名检索 | 元数据 | — | ❌ 无公开按名检索通道（千千仅 `tracklist/info` by id） | 💀 未接 |
| two-pass unblock mirror（灰色曲目 kuwo CDN） | FLAC（灰曲兜底） | 无 | ✅ 《晴天》灰曲出 FLAC 实测 | 🟢 并行会话实现 |
| `api.qijieya.cn/meting/?server=netease&br=999000` | **直接音频流 fLaC**（VIP 曲被禁） | 无 | ✅ 流魔数验证 | 🧪 备用未注册 |
| `oiapi.net/api/Music_163?id=` | 320k | 无 | ✅ code 0 | 🧪 备用未注册 |
| `api.chksz.top/api/163_music?id=`（Referer: cp.chksz.top） | FLAC 61MB | 无 | 💰 2026-08-24 复测 404 | 💀 |
| gdstudio (source=netease) | — | 无 | 🧪 待复测 | — |

**⬆️ v2.14.2 库层变化**：无新端点，仅解析链重排（`bugpk` / `xunjinlu` / `xingmian` 从 l1 下移到 l2；`jfjt` 从 l3 上移到 l1），以及 `REQUEST_KEYS` 轮换并新增第二把 base64 key。对 kwqq-api 无影响——我们走 ncm-api 容器主通道，不经这条链。

### 3.2 网易云凭证登记

| 凭证 | 值摘要 | 有效期 | 存放 |
|------|--------|--------|------|
| **MUSIC_U** | `000AB782...B78CE`（完整值存 NAS compose `NETEASE_COOKIE`） | 黑胶 VIP · vipType=110 · 账号「皮皮熙熙_jn」(3716000035) · 2026-08-23 验证 | NAS compose env；⚠️ 已进会话记录，建议定期轮换 |

### 3.3 网易云注意

- 周杰伦等腾讯系版权曲全量灰化（MUSIC_U 也无解），依赖 unblock/qijieya 兜底
- `/song/url/v1` 对免费曲返回 128k、VIP 曲 level=lossless 返回 944kbps FLAC

### 3.4 解析链位次变化（⬆️ v2.14.2）

| 层 | v2.13.10 | v2.14.2 | 变化 |
|----|----------|---------|------|
| l1（svip） | tmetu · xuanluoge · bugpk · kangqiovo · chksz · xunjinlu · xingmian · znnu · xiaoqin · vincentzyu233 · bileizhen（11 项） | tmetu · xuanluoge · kangqiovo · chksz · znnu · xiaoqin · vincentzyu233 · bileizhen · **jfjt**（9 项） | `bugpk`/`xingmian`/`xunjinlu` 降出 l1；`jfjt` 从 l3 升入 l1 末位 |
| l2（svip 但不稳） | rrvenn · haitangw · guyuei · cunyu（4 项） | **xunjinlu · bugpk · xingmian** · rrvenn · haitangw · guyuei · cunyu（7 项） | 三个原 l1 成员被置于 l2 队首 |
| l3（vip） | nanorocky · yutangxiaowu · qjqq · cocodownloader · ff · gdstudio · byfuns · xiaot · xcvts · xianyuw · jfjt · lzmhhh（12 项） | nanorocky · yutangxiaowu · cocodownloader · ff · gdstudio · qjqq · byfuns · xiaot · xcvts · xianyuw · lzmhhh（11 项） | 仅 `jfjt` 上移，其余位次微调 |
| l4 | rxtool · ceseet · manshuo | 未变 | — |

- **与 QQ 链的关键差异**：网易 l1 **没有** `[:2]` 截断（QQ 有，见 §1.4），9 项全跑，故网易侧的抗单点能力弱于表面印象但没有被削池。
- `_parsewithxunjinluapi` 的 `REQUEST_KEYS` 由 1 把增至 2 把 base64 key（`charlespikachuc2tf…` 与新追加的 `charlespikachuc2st…`）——已计入 §8 第 7 行。
- 网易出链仍走 `musicdl` 第三方链，带自定义 Cookie 时整链短路（返回 `MUSIC_QUALITIES[-1]` 空结果），与 [AGENTS.md](../AGENTS.md) 「Cookie 与第三方解析链互斥」不变量一致。

---

## 4. 酷狗音乐

| 通道 | 音质 | 鉴权 | 状态 | 集成 |
|------|------|------|------|------|
| **kugou-api 容器 `/song/url?hash=&quality=`**（cookie-server 自动注入） | quality=flac/high → 真 FLAC（URL 含 us1835587518 账户标识）；**viper_tape/viper_clear/viper_atmos 返回 status=2 priv=0 auth_through=[]（vip_type=0 非会员被挡）** | 🔐 cookie-server | ✅ 实测 flac/high；❌ viper 需 VIP | 🟢 主通道（仅 flac/high/320/128） |
| kugou-api `/song/url?quality=viper_*` 实测（2026-09-07，真实概念版 cookie） | 三档蝰蛇均 `status=2` 无 URL；`priv_status=0`；**蝰蛇音质需超级VIP**（酷狗会员中心明示），伪装 vip_type=1/vip_token 无效（服务端校验） | 🔐 超级VIP | ❌ 当前账户非VIP | 不可达 |
| kugou-api `/search`（需 cookie，error_code 152=无 cookie） | — | cookie-server | ✅ | 🟢 |
| haitangw `/kgqq/kg.php?type=json&id={FileHash}&level=hires\|lossless\|exhigh` | 多档 | 无 | ✅ 可用；⚠️ 勘误：实际处于 musicdl **l3**（v2.13.10 与 v2.14.2 均在 l3），旧记「l1」为笔误 | 🟢 musicdl 链 |
| ⬆️ QQovo `/api/meting?server=kugou&type=url&id={hash}&quality=lossless`（bootstrap + HMAC-SHA256 自签） | lossless 声明 | 会话内签密钥 | 🧪 v2.14.2 新增并置于 l2 首位，未复测 | 🟢 musicdl 链 |
| **咸鱼 API 开放平台**（`_parsewithxianyuwapi`，上游 v2.13.10 新增） | **FLAC 真无损**（周杰伦《晴天》52.83MB 实测） | 无 | ✅ 2026-08-24 实测无损；⬆️ v2.14.2 已从 l1 下移至 l2 末位 | 🟢 musicdl 链 |
| tom / jbsou / 90svip | 128/320 mp3 | 无 | ✅ | 🟢 musicdl 链 |
| 317ak / haitangw（UnboundLocalError） | — | — | ⚠️ 上游代码缺陷，特定响应触发 | 🟢 musicdl 链 |
| baka.plus (br=2000) / cocodownloader | 超时/失败 | — | ⚠️ 不稳定 | 🟢 musicdl 链 |
| 官方 /v5/url（蝰蛇 viper_tape/clear/atmos + flac） | 蝰蛇三档 | 🔐 需蝰蛇母带权益 + 完整登录态 | ❌ 当前凭证 status=2 付费墙（musicdl data 空；kugou-api 容器同拒） | — |
| cocodownloader / baka.plus / 317ak / xuanluoge / tom / jbsou / 90svip | — | 各异 | 🧪 musicdl 链内 | 🟢 musicdl 链 |

### 4.1 解析链与歌词端点（⬆️ v2.14.2）

**解析链位次重排**（对 kwqq-api 无影响：我们走 kugou-api 容器主通道，不消费这条链；仅影响 `musicdl` 库直用）：

| 层级 | v2.13.10 | ⬆️ v2.14.2 |
|------|----------|------------|
| l1 | 317ak · xianyuw | **baka** |
| l2 | lzmhhh · 90svip · tom · jbsou | **qqovo** · lzmhhh · 90svip · tom · jbsou · xianyuw |
| l3 | chksz · baka · cocodownloader · haitangw | 317ak · chksz · cocodownloader · haitangw |

**歌词端点迁移**：`http://lyrics.kugou.com/search` → **`https://krcs.kugou.com/search`**，并新增参数 `ver=1`、`man=yes`、`client=mobi`；下载端点 `https://lyrics.kugou.com/download?...` 不变。这是上游修「fix lyric fetch error」的实质改动——旧端点整域换主。

另：`REQUEST_KEYS`（base64 前缀 `charlespikachu` 的会话密钥）已整体轮换。

### 4.2 酷狗凭证登记

| 凭证 | 值摘要 | 续期 | 存放 |
|------|--------|------|------|
| **概念版账户 cookie** | `token=1abab2e2...;userid=1835587518;dfid=3MJbO42lMtze40ZaEp3LNfQW;t1=d202ad20...;vip_token=;vip_type=0`（2026-09-07 实测：cookie-server 返回 `vip_type=0` = 非VIP，故 viper 三档不可达） | kugou_refresh.sh cron 自动刷新 | cookie-server(:3002/kugou) + `/volume2/dev/data/api-secrets/musicAPI/kugou_token.json` |

---

## 5. 汽水 / Deezer / Qobuz 库层链（⬆️ v2.14.2）

这三个平台不在 kwqq-api 六源内，以下仅为上游库层链路留档——若日后要接入需从零建 adapter。

### 5.1 汽水（SoDa / 七雪）

| 端点 | 变化 | 状态 |
|------|------|------|
| 搜索 `https://api.qishui.com/luna/search/track?` | ⬆️ 由 `https://api.qishui.com/luna/pc/search/track?` 迁移；UA 由 `LunaPC/3.5.1(408871041)` 降为 `LunaPC/3.4.0(388267242)`；新增 `X-Luna-Background-Type: foreground`、`X-Luna-Is-Background-Req: 0`、`X-Luna-Is-Local-User: 1` 三个头 | 🧪 未复测 |
| 解析 `https://qiuyu520.fun/qishuiParse/api/track_v2?_={纳秒时间戳}` | ⬆️ 由 `http://qiuyu520.fun/qishuiParse/api/track/v2` 迁移（http→https、`track/v2`→`track_v2`、加随机参数），载荷从明文 `{"track_id": id}` 改为 **AES-256-GCM 加密** `{"d": b64(nonce ‖ ciphertext)}`，32 字节密钥硬编码在源码（nonce 12 字节随机生成） | 🧪 未复测 |
| 新增 `_parsewithqqovoapi`（`server=qishui`，`quality=exhigh`） | ⬆️ 走 §1.4 QQovo 签名协议 | 🧪 未复测 |
| ⛔ 旧链 `api.qishui.com/luna/pc/search/track`、`http://qiuyu520.fun/.../track/v2` | 已弃 | 见 §9 |

### 5.2 Deezer / Qobuz

| 端点 | 变化 | 状态 |
|------|------|------|
| `https://antra.hoshi.cfd/api/jobs` + `/api/resolve` | ⬆️ 无损格式 `lossless-24` → **`lossless-16`**（降规格换可用性） | 🧪 未复测 |
| `https://api.dezalty.com/auth/telegram/guest` → `/download/qobuz/stream?quality_str=Normal` | ⬆️ 全新通道：先拿 Telegram guest token，再解析流；同时被 `deezer.py` 与 `qobuz.py` 复用 | 🧪 未复测 |
| `https://clashflac.kanjijewels.com/api/qobuz/resolve` + `/api/qobuz/download`（`quality: UHD`） | ⬆️ 全新通道；请求 Origin 头为 `https://clashflac.pages.dev`（前端页与 API 不同域） | 🧪 未复测 |
| `https://open.qobuz.com/track/{id}` | 保留（元数据） | — |
| ⬆️ `https://verify.spotbye.qzz.io`（`CommunityClientBase`，`app_version 7.2.0 → 7.2.2`） | ⬆️ Qobuz 与 TIDAL **共用**的社区鉴权/会话兑换链；`401/428` 触发重建会话、`429/502/504` 按瞬态重试（`max_retries=6`，浏览器 opener 走人工验证，超时 300s） | 🧪 未复测 |
| ⛔ `https://qobuz-tidal-eclipse.cyrusna29.workers.dev/generate` + `/u/{token}/stream/{id}` | 整段移除 | 见 §9 |
| ⛔ `https://flacdownloader.com/prepare` + `/asset` | 整段移除（原为 X-Dl-Token 动态取链） | 见 §9 |

### 5.3 库层网页源（thirdpartysites）变动

| 模块 | 站点 | 状态 | 凭证门槛 |
|------|------|------|----------|
| 💀 `LivePOOMusicClient` | `www.livepoo.cn` | 整模块删除 | — |
| 💀 `LiziYYMusicClient` | `liziyy.top` | 整模块删除（上游称搜索已废） | — |
| 💀 `ITingWaMusicClient` | 听蛙 `itingwa` | 整模块删除 | — |
| 🧪 `LeedodoMusicClient` | `music.leedodo.com`（轻音乐/纯音乐，承接听蛙） | 新增；端点 `https://music.leedodo.com/wp-admin/admin-ajax.php`（WordPress 主题后端） | 匿名 |
| 🧪 `HeishanMusicClient` | `www.163cn.cc`（承接 livepoo） | 新增；`/search.html?` + `/download/{id}.html?t=0|1`，站内链接指向 `https://pan.quark.cn/s/` 夸克网盘 | 🔐 **硬门槛**：无 `quark_parser_config.cookies` 直接 `assert` 抛错，模块无法实例化 |
| 🧪 `GequkeMusicClient` | `www.gequke.com`（承接 liziyy） | 新增；`/search?s=` + POST `/api/music`，返回 MP3 + 歌词 | 🔐 无 quark cookie 仅能下 MP3，仅 **warning** 不阻断（比 heishan 软） |

> 注：以上三者均只在 **musicdl 库直用**（`MusicClientBuilder`）路径可达，kwqq-api 的六源 adapter 不经过 `thirdpartysites` 模块，故对服务出链无影响。已同步修正 [examples/musicdlwebgui/config.py:108](../examples/musicdlwebgui/config.py#L108) 的源清单（提交 `3c3720b`；D1 模块化后该表已从 `app.py` 迁入 `config.py`）。

### 5.4 Apple Music（⬆️ v2.14.2 重构，上游修 #99/#87/#86）

| 项 | v2.13.10 | v2.14.2 | 状态 |
|----|----------|---------|------|
| 搜索/取曲基址 | `https://amp-api-edge.music.apple.com/v1/catalog/{geo}/search` | **`https://amp-api.music.apple.com`**（与 `appleutils.AMP_API_URL` 统一，`-edge` 域弃用） | 🧪 未复测 |
| 语言参数 | 全线查询串带 `l={language}`（`/v1/me/account`、catalog songs/playlists/search、next-uri、webPlayback、license 六处） | **`l=` 全部移除**；`language` 仅保留在 `POST MZPlay.woa/wa/webPlayback` 的 body（`salableAdamId` + `language`） | 🧪 未复测 |
| 歌单 | 只走 `getplaylist` | 新增 library 分支 `getlibraryplaylist`（`/v1/me/library/playlists/{id}`）+ `extendapidata` 对 `tracks` 关系逐页扩展 | 🧪 未复测 |
| wrapper 入口 | `wrapper_account_url` 原样拼接（尾斜杠产生 `//`） | 构造时 `rstrip('/')` | 🧪 未复测 |
| 加密流链 | `play.itunes.apple.com/.../webPlayback` + `acquireWebPlaybackLicense` | 端点不变，仅去掉 `l=` | — |

> 影响面：Apple Music 只在库直用与 webgui 的「国外流媒体」组可达，kwqq-api 六源不含它；`use_wrapper` 仍默认关（本地 `127.0.0.1:30020` 账户代理），未配 wrapper 时该源出链为空。

### 5.5 保留网页源的端点修正（⬆️ v2.14.2）

| 模块 | 站点变化 | 状态 |
|------|----------|------|
| `FangpiMusicClient` | **整站换域** `www.fangpi.net → www.fangpiw.com`（搜索 `/s/{kw}`、Origin/Referer 同步）；出链 `POST /member/common-play-url` 由 JSON 改 **form**，并新增 `purpose=play` | 🧪 未复测 |
| `GequbaoMusicClient` | 域不变；`POST /member/common-play-url` 同样 JSON → form + `purpose=play` | 🧪 未复测 |
| `GequhaiMusicClient` | `POST /api/music` 的 `type` 不再固定 `'0'`，改取详情页 `mp3_type`；新增解码字段 `mp3_extra_url2` 且**优先于** `mp3_extra_url` | 🧪 未复测 |
| `XiagebaMusicClient` | 数据端点 `xiageba.liumingye.cn/music/{id}/_payload.json` → **`https://so.liumingye.cn/api/music/{id}`**；响应改读 `downloads[].url`，歌词直接来自 `lyrics` 字段 | 🧪 未复测 |
| `FiveSongMusicClient` | 夸克链接不再从 HTML `li[data-url]` 直取，改 `POST https://www.5song.xyz/play/songdown.php`（`{id, terminal:'pc', t: data-t, visitor:''}`，`code==200` 且 URL 前缀 `https://pan.quark.cn/` 才认）；歌词新增 `GET /play/lrc.php?id=` | 🧪 未复测 |
| `MP3JuiceMusicClient` | 见 §7：`apiKey` 变必填，须先从首页 JS 取 | 🧪 未复测 |
| `JBSouMusicClient` | 见 §7：搜索前须先取首页并注入 `mk_visit` cookie | 🧪 未复测 |

---

## 6. 咪咕 / 千千

| 平台 | 通道 | 鉴权 | 音质 | 状态 |
|------|------|------|------|------|
| 咪咕 | `search_all.do` + `listen-url/h5/v2.4`（XOR 解密 MAGIC abcd01）+ listenSong.do 模板 | 匿名 | HQ 320k 可靠；**匿名 SQ/ZQ 为假无损（实下 3.9MB MP3，真无损需会员 Cookie）**——规格详见 QUALITY-MATRIX.md §2.5 | ✅ 已集成（无损档仅名义） |
| 千千 | `91q.com/v1/search` + `/v1/song/tracklink`（MD5 签名 appid） | 匿名 | rate=3000 真 FLAC（48k/24bit 入门 Hi-Res 与 44.1k/16bit CD 逐曲不定；**无母带能力**；周杰伦/邓紫棋等热门曲整缺）——规格详见 QUALITY-MATRIX.md §2.6 | ✅ 已集成 |

---

## 7. 聚合/通用端点

| 端点 | 覆盖 | 音质 | 状态 | 用途 |
|------|------|------|------|------|
| `music.3e0.cn?server={tencent\|netease\|kuwo\|kugou\|migu}&type=url&id=` | 五平台 | 320k 代理流 | ✅ | QQ 链末位兜底（已集成） |
| `music-api.gdstudio.xyz/api.php` | 六平台 | 至 999 | ⚠️ qq source 不支持 / kuwo 空响应 | 备选观察 |
| `api.qijieya.cn/meting/` | netease 为主 | br=999000 真 FLAC（VIP 曲禁） | ✅ | 网易灰曲兜底候选 |
| `oiapi.net/api/Music_163` / `api/Kuwo?msg=歌名` | netease / kuwo | 320k | ✅ | 备选 |
| `zz123.com` / `gequbao.com` / `t.ijanz.cn` | 网页爬取类 | — | 沙箱捕获到搜索请求 | 潜在补充源（需 HTML 解析） |
| ⬆️ `https://music.gdstudio.org/api.php` + `/time`（与 `.xyz` 双域可选） | 十平台（embeat 新增；spotify 已移除） | 至 999 | 🧪 v2.14.2：VERSION `2026.08.01 → 2026.09.25`、**POST → GET**、加解密白名单末两项常量微调（`0xFCEFA3F8→0xFCFEA3F8`、`0x8D2A4D8A→0x8D2A4C8A`）；可传 `host=` 选域 | 备选观察（大陆用户可用 `.org`） |
| ⬆️ `https://qqovo.top/api/meting?server={tencent\|kugou\|qishui}` | 三平台 | 声明档 | 🧪 跨源复用同一签名协议（见 §1.4） | 跨源出链候选 |
| ⬆️ `https://meting.mikus.ink/api?server=tencent` | QQ | 服务端定档 | 🧪 未复测 | QQ l3 兜底 |
| ⬆️ `https://mp3juice.sc/`（页面内 `var apiKey='...'` 动态取） + `https://theta.thetacloud.org/api/v1/auth?api_key=` | 通用转换 | mp3 | ⬆️ 上游修复：**apiKey 已变为必填**，须先从首页 JS 抓取；下载 URL 追加 `&v={id}&f=mp3&r=mp3juice.sc` | 库层（非 kwqq-api） |
| ⬆️ `https://www.jbsou.cn/` | 酷狗 | 128/320 | ⬆️ 上游修复：搜索前须先 GET 首页并从 JS 提取 `mk_visit` cookie 写入会话（旧直调已失效） | 库层 |

---

## 8. 凭证与密钥总登记

| # | 凭证 | 类型 | 值摘要 | 有效期 | 存放 | 备注 |
|---|------|------|--------|--------|------|------|
| 1 | **API_KEY** | 服务认证 | `B2oyLl83BvhminZF_8eKEYaOdFm12vDn` | 长期 | NAS compose `API_KEY`；插件侧 Basic base64(key:) | 与 kugou.js/netease.js 插件同一把 |
| 2 | **MUSIC_U**（网易云黑胶） | 账户 cookie | `000AB7821244...A10F9346...B78CE`（完整值存 compose NETEASE_COOKIE） | 长期（账号「皮皮熙熙_jn」vipType=110） | NAS compose 已弃用 → 现为 `musicAPI/netease_cookie.txt`（volume 挂载直读）；⚠️ 已入会话记录建议轮换 | 网易云 VIP 无损的关键 |
| 3 | **酷狗概念版 cookie** | 账户 cookie 三项+ t1（实测 `vip_type=0` 非VIP） | `token=1abab2e2...;userid=1835587518;dfid=3MJbO42l...;t1=...` | 自动续期 | cookie-server(:3002/kugou) ← kugou_refresh.sh ← kugou_token.json | musicdl-api 动态拉取；**viper 蝰蛇档需超级VIP，当前不可达** |
| 4 | Lucky WebUI | 管理员 | zxsadmin / Ll_296302 | ⚠️ 已入会话记录建议改密 | 路由器 WebUI | kwqq 反代规则重建时需要 |
| 5 | lx-music 签名对 | SCRIPT_MD5+SECRET_KEY | `1888f986...` / `JaJ?a7...` | ❌ v4 协议已弃（服务端强制 v5） | ETC 文档留档 | 不可用 |
| 6 | musicdl 内置免费账户池 | antrahoshi 等 base64 账号 | 见 deezer.py/qobuz.py 源码 | 未知 | musicdl 源码 | Deezer/Qobuz 启用时相关 |
| 7 | 网易 `xunjinlu` REQUEST_KEYS | base64 请求密钥 | `charlespikachuc2tfZDFh…`（旧）+ `charlespikachuc2stZGRj…`（⬆️ v2.14.2 追加，共 2 把轮用） | 未知 | musicdl/modules/sources/netease.py | 两把同属上游内置，非我方凭证；链失效时先查此处 |

---

## 9. 死亡考古名单（勿再尝试）

| 端点 | 死亡方式 | 确认日期 |
|------|----------|----------|
| `kwdec.942240.xyz`（七级音质） | DNS 失效 | 2026-08-07 / 08-23 |
| `api.ikunshare.com` | DNS 失效 | 2026-08-07 |
| `lxmusicapi.onrender.com`（share-v2/v3） | 403 key 失效 | 2026-08-07 |
| `musicapi.haitangw.net` | 整域下线 | 2026-08-07 |
| liuyunidc RC4（master-tier） | 上游卡密失效 | 2026-08-12 |
| `88.lxmusic.xn--fiqs8s` v4 签名协议 | 服务端强制升级 v5（code 6） | 2026-08-23 |
| 元力 `175.27.166.236/kgqq1`（旧探测失败） | **2026-08-23 vm 插桩翻案：实际可用** ✅ | 见 §1 |
| haitangw.cc `/music1/kw.php` | 插件内置路径错误，正确为 `/music/kw.php` | 2026-08-23 修正 ✅ |
| `api.chksz.top`（网易 FLAC） | 404 | 2026-08-24 |
| xcvts / xingmian / 317ak（QQ l1 池） | 密钥失效/接口异常 | 2026-08-12 Spike |
| `music.90svip.cn` | 404 | 2026-08-24 |
| ⬆️ `www.livepoo.cn`（LivePOOMusicClient） | 整模块被上游删除，替换为 `www.163cn.cc`（HeishanMusicClient） | 2026-10（v2.14.1 `a6d1a2b`） |
| ⬆️ `liziyy.top`（LiziYYMusicClient） | 整模块被上游删除（上游称「搜索功能已废」），替换为 `www.gequke.com` | 2026-10（v2.14.1 `be2023c`） |
| ⬆️ 听蛙 itingwa（ITingWaMusicClient） | 整模块被上游删除，替换为 `music.leedodo.com` | 2026-10（v2.14.1 `9cc907d`） |
| ⬆️ `https://qobuz-tidal-eclipse.cyrusna29.workers.dev/generate` + `/u/{token}/stream/{id}` | 上游整段移除，替换为 clashflac / dezalty | 2026-10（v2.14.0 `c5a44b1`） |
| ⬆️ `https://flacdownloader.com/prepare` + `/asset`（X-Dl-Token 取链） | 上游整段移除，替换为 antra `lossless-16` | 2026-10（v2.14.0 `a81b123`） |
| ⬆️ `https://api.qishui.com/luna/pc/search/track?` | 端点整体迁移到 `/luna/search/track?`，PC UA 弃用 | 2026-10（v2.14.0 `d0bc7e1`） |
| ⬆️ `http://qiuyu520.fun/qishuiParse/api/track/v2` | 改 https + 路径 `track_v2` + AES-256-GCM 加密载荷 | 2026-10（v2.14.0 `d0bc7e1`） |
| ⬆️ `http://lyrics.kugou.com/search` | 迁移到 `https://krcs.kugou.com/search`（新增 `ver`/`man`/`client` 参数） | 2026-10（`ac3a4f3`） |
| ⬆️ `antra.hoshi.cfd` `lossless-24` 格式 | 降规格为 `lossless-16` | 2026-10（v2.14.0 `a81b123`） |

---

## 10. 待验证池 —— 2026-08-24 全量实测完毕

| 待验证项 | 实测结论 |
|----------|----------|
| mkr-0920/music-api-server (GitHub) | 标准 EAPI 协议重实现（cloudsearch/detail/lyric/playlist），无新端点；ncm-api 已全覆盖 |
| ywain-zh/Netease_url (GitHub) | 同上（自托管+扫码登录参考实现） |
| hubhike/Music_Plugins「小X系列」(xiaogou/xiaomi/xiaoqiu/xiaowo/xiaoyun) | 各平台**官方接口聚合封装**（酷狗歌词/专辑/榜单、网易、QQ 歌词、咪咕搜索），端点已被 musicdl-api 容器/musicdl 全覆盖 |
| flowsasa / ThomasBy2025 / wkndjs / TZB679 插件集合 | 索引解析后 94 个插件下载沙箱扫描：getMediaSource 层普遍依赖 userVariables 用户凭证或上游失效，**无新增可集成出链端点** |
| 搜索层新捕获域名 | zz123.com（SPA）、gequbao.com（JS 渲染）、t.ijanz.cn（网易推荐接口，价值低）、api.tyhua.top（DNS 失效）、suno studio-api（401） |

**结论**：两轮扫描（本地 23 + 网络 94 + 官方分析 23）合计 **130 个插件、100 个索引源**穷尽后，除已集成的六源与元力/haitangw/nxinxz 兜底外，**无新增有价值的独立音源端点**。当前六源架构已是该生态下的最优覆盖。

**⬆️ 2026-10-24 上游同步新增待验证项**（均为 v2.14.2 引入，本轮未复测）：

| 待验证项 | 建议验证方式 |
|----------|--------------|
| `qqovo.top` bootstrap + HMAC-SHA256 签名（qq/酷狗/汽水三端） | 直调 bootstrap 验签名头可通；再用真实 mid/hash 验 lossless 是否真无损 |
| `meting.mikus.ink` | 直接 audio_link_tester 测档 |
| `api.dezalty.com`（Telegram guest auth） | 验 guest token 能否取到 stream |
| `clashflac.kanjijewels.com`（qobuz UHD） | 验 resolve + download 两段 |
| `qiuyu520.fun/.../track_v2` AES-GCM 新协议 | 用汽水真实 track_id 验解包 |
| `krcs.kugou.com/search`（歌词新端点） | 带 hash 验 candidates 返回 |
| `music.gdstudio.org`（大陆域） | 对比 `.org` / `.xyz` 双域与 v2026.09.25 GET 协议 |
| `mp3juice.sc` 动态 apiKey / `jbsou.cn` `mk_visit` cookie | 库层自校验 |
| QQ l1 截断后无损命中率 | 专挑 QQ 无损批量冒烟，观察是否大面积落 l2 |

### 10.1 歌词端点（2026-11-06 登记）

| 端点 | 现状 | 凭证/参数 | 实测 | 角色 |
|---|---|---|---|---|
| `https://app.c.nf.migu.cn/MIGUM3.0/strategy/pc/listen/v1.0` | 取 `data.lrcUrl` 再 GET；须 headers `birth:h5page`、`signature:1`、`Content-Type: application/json;charset=UTF-8`，并走客户端 `get()` + `_decryptresp`（裸请求返回 `code 299999`）。域名是 `app.c.nf.migu.cn`，`app.c.migu.cn` 本地 DNS 不解析 | 匿名；参数 `scene=&netType=01&resourceType=2&copyrightId=<版权ID>&contentId=<歌曲ID>&toneFlag=PQ`，`copyrightId` 来自搜索项 `extra` | ✅ 2026-11-06 NAS 实测（865 字符/45 行） | 🟢 migu 歌词主通道 |
| `91q.com /v1/search` 结果行 `lyric` 字段 | 千千静听（qianqian）**没有 by-id 歌词频道**，歌词 URL 只随搜索结果下发 → 门面用进程内 id→url 缓存（上限 500，`workers=1` 才一致）；缓存未命中（如直接按 id 取）返回空串 | 匿名，需 `_addsignandtstoparams` 签名 | ✅ 2026-11-06 NAS 实测（450 字符） | 🟡 qianqian 歌词（受限） |
| `https://krcs.kugou.com/download?...&fmt=krc` | 逐字歌词：`lyrics.kugou.com/search`（`ver=1&man=yes&client=pc&hash=<hash>`）取 candidates 的 `id`/`accesskey`，再 `fmt=krc&charset=utf8` 取 base64；KRC = 4 字节 `krc1` 头 + XOR(16 字节固定 key，从索引 4 起) + zlib 压缩，解出后转洛雪逐字格式（`[mm:ss.mmm]` + `<偏移ms,时长ms>文本`） | 匿名 | ✅ 2026-11-06 NAS 实测（4624 字符/47 逐字行） | 🟢 kugou 逐字主通道 |
| `http://10.10.10.2:3000/lyric/new?id=<id>`（ncm-api） | 网易云逐字：一次响应同时含 `lrc.lyric`（行级）与 `yrc.lyric`（逐字，首行是 JSON 元信息需跳过）；yrc 行 `[start,dur](绝对ms,dur,0)文本` | 匿名（ncm-api 容器） | ✅ 2026-11-06 实测：20 首抽样 **7 首有 yrc**（35%），`klyric` 20/20 为空；有 yrc 的样本 59/57 逐字行 | 🟢 netease 逐字主通道（逐曲可用性） |
| `https://u.y.qq.com/cgi-bin/musicu.fcg`（`PlayLyricInfo/GetPlayLyricInfo`, `qrc:1`） | QQ 逐字：`req.data.lyric` 是 **HEX 串**（10512 hex 字符 → 5256 字节，不是 base64）→ hex 解码 → QQ 自研 DES 变体 `D(K1)`/`E(K2)`/`D(K3)`（`!@#)(NHL` / `123ZXC!@` / `!@#)(*$%`）→ zlib → XML；`Lyric_1 LyricType="1"` 的 `LyricContent` 为 `[start,dur](绝对ms,dur,0)文本`。与标准 DES 不等价（pycryptodome 失败），须用位级移植实现（`musicdl/modules/utils/lyricfmt.py`） | 匿名；GET `params={format:json,data:<payload>}`，`Referer: https://y.qq.com/` | ✅ 2026-11-06 实测：18/18 有 QRC；样本 XML 8724 字符/66 逐字行，与同曲明文 LRC 行头最大偏差 9ms | 🟢 qq 逐字主通道 |
| `http://newlyric.kuwo.cn/newlyric.lrc?...&lrcx=1` | 酷我逐字：解码后首行 `[kuwo:<八进制>]` 为标度 → `k=int(tag,8), k1=k//10, k2=k%10`；片段 `<a,b>txt` 解算 `start=(a+b)/(2k1)`、`dur=(a-b)/(2k2)`（毫秒，相对行头）；整行 `<0,0>` 是译文行须丢弃 | 匿名 | ✅ 2026-11-06 实测：18 首抽样 **14 首有 lrcx**（4 首只回普通 LRC，门面退 `lxlyric=null`） | 🟢 kuwo 逐字主通道（逐曲可用性） |
| 咪咕 `mrcUrl`（listen 响应） | 名义逐字资源，`application/marc` hex 21.8k–34k 字符；**无公开解密算法**（QRC/KRC/LRCX 均不适用），`trcUrl` 恒空、`lrcUrl` 纯行级 → **不接入** | 匿名 | ❌ 2026-11-06 实测解不出 | 🔴 不可用 |


后续增量维护建议：
1. 监控 [Huibq/keep-alive](https://github.com/Huibq/keep-alive) 与元力公众号的端点更新
2. 每季度重跑 `.state/probe_endpoints.py` 探测矩阵复核存活状态
3. ⚠️ **勘误（2026-10-24）**：原第 3 条「musicdl 上游更新时同步 hifi 分支解析链」已失效——`archive/hifi` tag 已于 2026-09-06 归档并入本分支，单分支治理后**上游同步只发生在 `api-server`**（fetch `upstream` 后直接 merge `upstream/master`）。每次合并后须按本台账口径复核库层解析链变动（即本文所有 ⬆️ 条目的来源）。

## 11. bilibili（第 7 源，2026-08-24 并入；此前漏登记，2026-10-27 补）

| 端点 | 现状 | 凭证 | 实测 | 角色 |
|---|---|---|---|---|
| `api.bilibili.com/x/web-interface/search/type?search_type=video` | **2026-10-27 起匿名裸请求 412 Precondition Failed（风控收紧）**——须带 buvid3 cookie；adapter 经 `finger/spi` 动态换指纹（7 天 TTL 缓存）后恢复 | 免 cookie（动态指纹）；`BILI_SESSDATA` 可选解锁 Hi-Res/Dolby | ✅ 2026-10-27 NAS 修复后实测 | 🟢 搜索主通道 |
| `api.bilibili.com/x/frontend/finger/spi` | 匿名换 buvid3/buvid4，正常 | 无 | ✅ | 🟢 指纹源 |
| DASH 音频流提取（`bili.dash.*` parser） | m4a 192k 上下，URL 需 `Referer: www.bilibili.com` | 同上 | ✅ 2026-10-27 | 🟢 取链主通道 |

修复记录：`server/adapters/bilibili.py` `_search_raw` 原先裸请求未走 `_api_get`（注释声称带 buvid 实则未带），2026-10-27 统一走 `_api_get` 修复 412。

---

## 12. MV 端点登记（2026-11-06 全量只读实测）

门面：`GET /{source}/mv?id=<歌曲 id>&title=&artist=` → `data{id,source,url,cover,duration_s,quality[,items]}`；无 MV 一律 HTTP 200 + `url:null`（不做 404/空对象）。质量归一枚举 `ld|sd|hd|fhd`（按实测高度：≤300 ld / ≤480 sd / ≤720 hd / >720 fhd）。**四源实测全为 mp4 直链，无 m3u8 通道**（kuwo 无分档，`quality:null`）。

**MV 搜索通道（`GET /{source}/search?type=mv`，契约见 `docs/API-REFERENCE.md` §4.12）**

| 源 | 通道 | `id` 口径（接 `/mv?id=`） | 状态 |
|---|---|---|---|
| netease | `cloudsearch?type=1004` → `result.mvs[]` | mvid（`mv()` 对不存在歌曲 id 回退当 mvid 直取） | 🟢 |
| qq | 歌曲搜索行 `mv{id,vid}`，只保留带 `vid` 的行 | 歌曲 mid | 🟢（老 MV 多被下架，靠插件侧可播性闸门过滤） |
| kugou | 容器 `/search?type=mv` | 歌曲 `FileHash` | 🟢 |
| kuwo | **`wapi/api/www/music/mvList` 9 分类目录本地检索**（≈2400 条，name+artist 分词全命中、`mvPlayCnt` 降序；目录 6h 缓存） | 在架 MV id | 🟢（目录内全可播） |
| migu / qianqian / bilibili | 无 | — | 501 envelope |

> kuwo 为什么不用 `wapi/api/www/search/searchMvBykeyWord`：它匿名可用，但返回的是"有 MV 的**歌曲**"（`id`=歌曲 rid），而这些歌的 MV 直链已被官方全量下线 → 搜到点不开。改用在架目录，从源头消除该问题。

| 源 | 通道 | 鉴权 | 返回形态 | 清晰度 | 状态 | 集成 |
|------|------|------|------|------|------|------|
| netease | `/song/detail?ids=` 取 `songs[].mv`（0=无）→ `/mv/detail?mvid=` → `/mv/url?id=&r=` | 匿名（ncm-api 容器 :3000） | mp4 直链（`wsSecret`/`wsTime` 签名），URL 内为 CDN 域名 | `r` 为**上限**：请求 1080 实际回落 480/240；付费 MV `code:-125`+url null | ✅ 实测（江南 108914 → sd；孤勇者 1901371647 → ld） | 🟢 `/{source}/mv` |
| qq | 搜索结果行自带 `mv{id,vid,vt}` → `vv.video.qq.com/getinfo?vids=<vid>&platform=101001&charge=0&newplatform=1&defn=<fhd/hd/sd>&fmt=json` | 匿名零 Cookie、无签名 | XML：`<td>`(秒) `<vh>`(高) `<fn>`(mp4 名) `<fvkey>` `<ui><url>`；URL=`host+fn+"?vkey="+fvkey`；HEAD 403 属正常，**Range GET 206 video/mp4** | `defn` 三档请求，实际按 `<vh>` 回落（匿名 270/486 → sd） | ✅ 实测（光年之外 002E3MtF0IAMMY、告白气球） | 🟢 `/{source}/mv` |
| kugou | 容器 `/search?type=mv`（行含 `MvID`/`MvHash`/`FileHash`；**FileHash 即歌曲 hash，与门面 id 精确对齐**）→ `/video/detail?id=<MvID>` → `/video/url?hash=<档位 hash>` | 🔐 容器内 cookie（cookie-server 注入；裸搜 error_code 152） | `downurl` = mp4 直链（`fsmvpc.tx.kugou.com`）；封面 `hdpic`（`{size}`→480）/`Pic` | ld/sd/hd/qhd/fhd 逐档 `*_hash` + `*_height`（实测 fhd 1080） | ✅ 实测（江南 B83DBB8E…、七里香 9218D816…） | 🟢 `/{source}/mv` |
| kuwo | **匿名通道在 `m.kuwo.cn/newh5app/wapi/**`**（非 `www.kuwo.cn/api/**`）：歌曲 rid → `wapi/api/www/music/musicInfo` 的 `mvpayinfo.vid` → `wapi/api/v1/www/music/playUrl?mid=<vid>&type=mv&httpsStatus=1`；**在架 MV 目录** `wapi/api/www/music/mvList?pid=&pn=&rn=`（9 分类 ≈2400 条）的 `id` 直接走同一 `playUrl` | 匿名、零 Cookie、无需预热（`Secret` 不需要）；⚠️ `www.kuwo.cn/api/**` 对本机 IP 恒 `{"success":false,"message":"The request is illegal!"}`（WAF，前端 `dcc6cd7.js` 的 `Secret=f(cookie值, 'Hm_Iuvt_...')` LCG 算法已 Python 复刻，仍被拒 → 不是算法问题） | `{"code":200,"data":{"url":"https://kw-bj.kuwo.cn/...mp4"}}`，`Range` 206 `video/mp4`，**faststart（moov 在前）** | 无分档，单一 mp4（目录条目无高度字段 → `quality:null`） | ⚠️ 目录 MV ✅ 全可播；**歌曲关联 MV 已被官方全量下线**（`mvpayinfo.vid` 走 `playUrl` 恒 `code:-1001「该MV已下线」`，含 2025-2026 新歌） | 🟢 目录 id 可播；歌曲 id → `url:null` |
| migu | `search_all.do` 带 `searchSwitch={"mvSong":1}` 有 MV 条目，但播放路由矩阵全部「路由请求不支持」 | 匿名搜索可，取链不可 | — | — | ❌ | `url:null` |
| qianqian | 签名 API `/v1/search` 各 `type`（4~12/1004）均「不被支持的搜索类型」 | 匿名 | — | — | ❌ 无 MV 搜索类型 | `url:null` |

**酷我 MV 探测全链路取证（2026-11-06，只读，脚本在 `.state/mv_kuwo_probe*.py`）**：

1. `search.kuwo.cn/r.s?ft=video`（**`ft=mv` 恒 `HIT=0`**）→ 行含 `MUSICRID=MUSIC_<歌曲 rid>`、`DC_TARGETID`（MV vid）、`hts_MVPIC`、`DURATION`；可精确对齐歌曲 id，但这些 vid 已被下线。
2. `antiserver.kuwo.cn/anti.s?type=convert_url3&format=mp4&rid=MVID_<vid>` → 回 `m1/15/2/3489980661.mp4`，**不同 vid 同一文件（31KB 公共桩）**；`format=hls/flv` → `res not found`。**不可用**。
3. `mobi.kuwo.cn/mobi.s?f=kuwo&q=<des 加密>` 各 `type`：`get_mv_info`/`mv_url`/`search_mv` → 404；`convert_url` → 403；`convert_url2` 对 `MVID_` 前缀回落成 aac 音频。
4. `www.kuwo.cn/mv/<vid>` → 302 `/mvplay/<vid>` → **430**（反爬）；`www.kuwo.cn/yy/st/mvurl`（yt-dlp 老通道）→ 已下线（返回 SPA HTML）。
5. `www.kuwo.cn/api/**`（`searchMvBykeyWord`、`music/musicInfo`、`v1/www/music/playUrl?type=mv`）→ 恒 `{"success":false,"message":"The request is illegal!"}`；带 `Secret`（算法已复刻）+ `httpsStatus/reqId/plat/from` + `Referer` + `csrf`/`kw_token` 全部无效 → **WAF 层拒绝，非签名问题**。
6. **突破点**：同样路径换成 **`m.kuwo.cn/newh5app/wapi/<原 api 路径>`** → 匿名通过。`wapi/api/www/music/musicInfo?mid=93157` 回 `mvpayinfo{play:1,vid:17603493}`；`wapi/api/v1/www/music/playUrl?mid=<vid>&type=mv` 对在架 vid 回真 mp4。
7. **下线证据**：`mvpayinfo.vid`（江南/七里香/光年之外/周深/单依纯/张杰 等逐一）→ 恒 `code:-1001「该MV已下线」`；而 `mv.kuwo.cn` 首页 `mvList` 的在架 vid → 真 mp4（9.7MB/10MB/38MB 实测）。
8. 结论：酷我 **没有"歌曲→MV"可用映射**，但**有在架 MV 目录**（9 分类 ≈2400 条，全可播）→ 门面按目录接入。

**上游更迭复核（2026-11-06 20:31 NAS `kugou-api` 容器随 KuGouMusicApi 上游合并重建）**：`/search?type=mv` 行字段未变（`FileHash`/`MvID`/`MvHash`/`MvName`/`SingerName`/`Duration`/`Pic`）；`video_url.js` 参数仍为 `hash`（内部 `/v2/interface/index` + `x-router: trackermv.kugou.com`），`video_detail.js` 仍 `/v1/video`；门面 `/kugou/mv` 复测江南 269s/fhd、七里香 303s/fhd，NAS `curl -r 0-1023` 均 **206 video/mp4**；`MvHash` 直取仍返回 **.mkv**（复核后结论不变）。

**弃用条目（避免复活）**：
- kugou `/video/url?hash=<MvHash>` 返回 **mkv**（`application/octet-stream`），非 mp4 → 只用 `/video/detail` 的逐档 `ld/sd/hd/qhd/fhd_hash`。
- kugou `/kmr/audio/mv?album_audio_id=`（文档有载，2026-11-06 实测返回**推荐 MV**：七里香 → 薛之谦「天份」，`is_recommend:1`）→ 不采用。
- netease `/search?type=1004` 只接受**同名**命中（否则命中访谈/翻唱），仅作 `/song/detail` 无 mvid 时的退路，且须 title 归一相等 + artist 包含。

**有效期策略**：三源链接均为短时效签名（netease `wsTime` ≈ 请求时刻、QQ `fvkey` 现取、kugou CDN 路径）→ **服务端不做缓存，客户端每次点击现取**（门面路由不写 TTL 缓存）。

## 13. 元数据通道 —— 评论发布时间 / 词曲编曲（2026-11-07 全量只读实测）

门面契约见 `docs/API-REFERENCE.md` §4.3（`credits`）与 §5.1c（`create_time`）。探测脚本在 `.state/probe_times.py` / `probe_kugou.py` / `probe_credits*.py`。

**评论时段（2026-11-07 v1.22 四源全量实测，王菲《季候风》同一首歌）**

| 源 | 通道 | 时间字段 | 量级/形态 | 结论 |
|---|---|---|---|---|
| netease | ncm 容器 `/comment/music?id=&limit=&offset=` | `comments[].time` | **毫秒**整数 | ✅ → `time//1000` |
| kugou | 容器 `/comment/music?mixsongid=&page=&pagesize=&folder=0`（mixsongid 由 FileHash 经匿名搜索行回查） | `list[].addtime` | **东八区文本** `YYYY-MM-DD HH:MM:SS` | ✅ → +08:00 解析成 Unix 秒；解析失败才落 `create_time_text` |
| qq | `https://u.y.qq.com/cgi-bin/musicu.fcg`，module `music.globalComment.CommentRead` / method `GetHotCommentList`；`param={BizType:1, BizId:"<数字songid>", HotType:1, PageNum: page-1, PageSize, PicEnable:1, WithAirborne:0}`（**BizId 必须字符串**，int → code 10006）；返回 `req_1.data.CommentList{Comments[],Total,HasMore}` | `Comments[].PubTime` | **Unix 秒** | ✅ → 原样透出；`SubComments[]` 作 replies（`PubTime` 可能 0，如实留空） |
| kuwo | `http://ncomment.kuwo.cn/com.s?f=web&type=get_comment&aapiver=1&prod=kwplayer_ar_10.5.2.0&digest=15&sid=<rid>&start=(page-1)*count&msgflag=1&count=&newver=3&uid=0`（匿名免 cookie） | `comments[].time` | **Unix 秒** | ✅ → 原样透出；总数 `comments_counts`，无回复列表 |
| migu / qianqian / bilibili | 门面 `/comments` 未实现（base 501） | — | — | 不接，不伪造 |

**词曲编曲（credits）**：六源全部**没有独立 credits 接口**（netease `music.163.com/api/song/credit` 与容器 `/song/credit` 均 404；QQ `pf_song_detail_svr` track_info 无作词/作曲字段；kugou `/audio/related` 只有 `authors`(歌手) 与 `works`；酷我 `songinfoandlrc` 的 `songinfo` 无署名；migu/qianqian 也无结构化署名接口）。**但各源歌词头部都内嵌署名行**，故统一从歌词解析（`base.parse_credits`）：

| 源 | 实测样例文本（头部） | 字段 | 覆盖 |
|---|---|---|---|
| netease | `作词 : 方文山` / `作曲 : 周杰伦` / `编曲 : 洪敬尧`（ASCII 空格+半角冒号） | 作词/作曲/编曲 | ✅ |
| qq | `词：唐恬` / `曲：…` / `编曲：…`（全角冒号） | 词/曲/编曲 | ✅ |
| kugou | 同上（容器 `/lyric` 或官方 fallback 的 LRC 头） | 词/曲/编曲 | ✅ |
| kuwo | `作词：…` / `作曲：…` / `编曲：…`（h5 `songinfoandlrc` 的 `lrclist`，第 8 行起） | 作词/作曲/编曲 | ✅ |
| migu | `作词 : …`（歌词通道同款署名行，`?copyright=` 照常回传） | 作词/作曲（编曲常缺） | ✅ |
| qianqian | **单行双位** `作词：李瑞洵 作曲：林俊杰`（江南 T10063528778 实抓）；晴天 `T10065400429` 等结果行不带歌词 URL → 无署名 | 作词/作曲 | ✅ 有条件 |

> 探测证据：netease/kuwo 的歌词头署名行已实抓到（`作词 : ` / `作词：`）；qq/kugou 的 `词：`/`曲：`/`编曲：` 行同样实抓；migu 走容器解密后的歌词内容同样命中；qianqian 是单行内「作词… 作曲…」两段，解析器按位切段。**只在歌词前 25 个非空行内识别**，避免正文误命中；支持全角/半角/英文冒号、一行多位、`/、，,;；|｜` 多值与「佚名/未知」占位剔除。
