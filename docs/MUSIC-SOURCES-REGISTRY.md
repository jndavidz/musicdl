# 音乐源端点与凭证总册

> 用途：kwqq-api 全部已知解析端点、凭证、密钥的登记与存活状态台账（含失效条目，供考古与恢复参考）
> 维护方式：每次探测后更新「状态」列；新增端点追加到对应平台章节
> 实测方法：真实歌曲 id 直调（QQ mid=0039MnYb0qxYhV《晴天》/ 酷我 rid=228908《晴天》/ 网易 id=108914《江南》/ 网易灰曲 id=186016《晴天》）
> 最后全量探测：2026-08-24 · 标注 ✅=可用 ⚠️=不稳定 ❌=失效 🔐=需凭证
> ⬆️ **上游同步基线：musicdl v2.14.2**（merge `74c6ac1`，2026-10-24）。标 ⬆️ 的条目取自上游源码 diff，**本轮未复测**，其存活状态以下一轮探测为准

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

> 注：以上三者均只在 **musicdl 库直用**（`MusicClientBuilder`）路径可达，kwqq-api 的六源 adapter 不经过 `thirdpartysites` 模块，故对服务出链无影响。已同步修正 [examples/musicdlwebgui/app.py:129](../examples/musicdlwebgui/app.py#L129) 的源清单（提交 `3c3720b`）。

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
