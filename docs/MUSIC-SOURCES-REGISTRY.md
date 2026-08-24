# 音乐源端点与凭证总册

> 用途：kwqq-api 全部已知解析端点、凭证、密钥的登记与存活状态台账（含失效条目，供考古与恢复参考）
> 维护方式：每次探测后更新「状态」列；新增端点追加到对应平台章节
> 实测方法：真实歌曲 id 直调（QQ mid=0039MnYb0qxYhV《晴天》/ 酷我 rid=228908《晴天》/ 网易 id=108914《江南》/ 网易灰曲 id=186016《晴天》）
> 最后全量探测：2026-08-24 · 标注 ✅=可用 ⚠️=不稳定 ❌=失效 🔐=需凭证

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

---

## 2. 酷我音乐

### 2.1 解析端点

| 端点 | 音质 | 鉴权 | 状态 | 集成 |
|------|------|------|------|------|
| **`nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid=&br=`** | 精确档位（320kmp3→真320；2000kflac→无损） | 无 | ✅ 主力直出 ~120ms 不降档 | 🟢 |
| `mobi.kuwo.cn/mobi.s?f=kuwo&q=<des加密>`（convert_url2） | 会静默降档 | 无（内置密钥 ylzsxkwm） | ✅ 备胎 | 🟢 |
| `music.nxinxz.com/kw.php?id=&level=` | lossless/exhigh/standard | 无 | ✅ 稳定 | 🟢 第三方链 |
| **`music.haitangw.cc/music/kw.php?id=&level=`**（⚠️ 插件内置 /music1/ 为死路径） | lossless=FLAC / exhigh=320k | 无 | ✅ 2026-08-23 修正路径后可用 | 🟢 兜底 |
| `kw-api.cenguigui.cn/?id=&level=` | lossless | 无 | ⚠️ 连接失败（间歇） | 🟢 musicdl l2 |
| `kwdec.942240.xyz` | 七级音质 | 无 | 💀 DNS 失效 | — |
| `music.90svip.cn` | — | 无 | 💀 404 | — |
| `music-api.gdstudio.xyz (source=kuwo)` | url 空 br=-1 | 无 | ⚠️ 上游空响应 | 未集成 |

### 2.2 酷我官方匿名说明

`mobi.s convert_url2` 密钥 `SECRET_KEY_SONG=b"ylzsxkwm"` 为防爬非认证；歌词双通道（newlyric DES / openapi）均匿名可用。

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
| **kugou-api 容器 `/song/url?hash=&quality=`**（cookie-server 自动注入） | quality=flac → 真 FLAC（URL 含 us1835587518 账户标识 = VIP 权益） | 🔐 cookie-server | ✅ 实测 flac | 🟢 主通道 |
| kugou-api `/search`（需 cookie，error_code 152=无 cookie） | — | cookie-server | ✅ | 🟢 |
| haitangw `/kgqq/kg.php?type=json&id={FileHash}&level=hires\|lossless\|exhigh` | 多档 | 无 | ✅（musicdl l1） | 🟢 musicdl 链 |
| cocodownloader / baka.plus / 317ak / xuanluoge / tom / jbsou / 90svip | — | 各异 | 🧪 musicdl 链内 | 🟢 musicdl 链 |

### 4.1 酷狗凭证登记

| 凭证 | 值摘要 | 续期 | 存放 |
|------|--------|------|------|
| **概念版账户 cookie** | `token=1abab2e2...;userid=1835587518;dfid=3MJbO42lMtze40ZaEp3LNfQW;t1=d202ad20...` | kugou_refresh.sh cron 自动刷新 | cookie-server(:3002/kugou) + `/volume2/dev/data/api-secrets/kugou_token.json` |

---

## 5. 咪咕 / 千千

| 平台 | 通道 | 鉴权 | 音质 | 状态 |
|------|------|------|------|------|
| 咪咕 | `search_all.do` + `listen-url/h5/v2.4`（XOR 解密 MAGIC abcd01）+ listenSong.do 模板 | 匿名 | HQ 320k 可靠；SQ/ZQ URL 匿名可得（freetyst CDN） | ✅ 已集成 |
| 千千 | `91q.com/v1/search` + `/v1/song/tracklink`（MD5 签名 appid） | 匿名 | rate=3000 真 FLAC（版权库有限） | ✅ 已集成 |

---

## 6. 聚合/通用端点

| 端点 | 覆盖 | 音质 | 状态 | 用途 |
|------|------|------|------|------|
| `music.3e0.cn?server={tencent\|netease\|kuwo\|kugou\|migu}&type=url&id=` | 五平台 | 320k 代理流 | ✅ | QQ 链末位兜底（已集成） |
| `music-api.gdstudio.xyz/api.php` | 六平台 | 至 999 | ⚠️ qq source 不支持 / kuwo 空响应 | 备选观察 |
| `api.qijieya.cn/meting/` | netease 为主 | br=999000 真 FLAC（VIP 曲禁） | ✅ | 网易灰曲兜底候选 |
| `oiapi.net/api/Music_163` / `api/Kuwo?msg=歌名` | netease / kuwo | 320k | ✅ | 备选 |
| `zz123.com` / `gequbao.com` / `t.ijanz.cn` | 网页爬取类 | — | 沙箱捕获到搜索请求 | 潜在补充源（需 HTML 解析） |

---

## 7. 凭证与密钥总登记

| # | 凭证 | 类型 | 值摘要 | 有效期 | 存放 | 备注 |
|---|------|------|--------|--------|------|------|
| 1 | **API_KEY** | 服务认证 | `B2oyLl83BvhminZF_8eKEYaOdFm12vDn` | 长期 | NAS compose `API_KEY`；插件侧 Basic base64(key:) | 与 kugou.js/netease.js 插件同一把 |
| 2 | **MUSIC_U**（网易云黑胶） | 账户 cookie | `000AB7821244...A10F9346...B78CE`（完整值存 compose NETEASE_COOKIE） | 长期（账号「皮皮熙熙_jn」vipType=110） | NAS compose；⚠️ 已入会话记录建议轮换 | 网易云 VIP 无损的关键 |
| 3 | **酷狗概念版 cookie** | 账户 cookie 三项+ t1 | `token=1abab2e2...;userid=1835587518;dfid=3MJbO42l...;t1=...` | 自动续期 | cookie-server(:3002/kugou) ← kugou_refresh.sh ← kugou_token.json | musicdl-api 动态拉取 |
| 4 | Lucky WebUI | 管理员 | zxsadmin / Ll_296302 | ⚠️ 已入会话记录建议改密 | 路由器 WebUI | kwqq 反代规则重建时需要 |
| 5 | lx-music 签名对 | SCRIPT_MD5+SECRET_KEY | `1888f986...` / `JaJ?a7...` | ❌ v4 协议已弃（服务端强制 v5） | ETC 文档留档 | 不可用 |
| 6 | musicdl 内置免费账户池 | antrahoshi 等 base64 账号 | 见 deezer.py/qobuz.py 源码 | 未知 | musicdl 源码 | Deezer/Qobuz 启用时相关 |

---

## 8. 死亡考古名单（勿再尝试）

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

---

## 9. 待验证池 —— 2026-08-24 全量实测完毕

| 待验证项 | 实测结论 |
|----------|----------|
| mkr-0920/music-api-server (GitHub) | 标准 EAPI 协议重实现（cloudsearch/detail/lyric/playlist），无新端点；ncm-api 已全覆盖 |
| ywain-zh/Netease_url (GitHub) | 同上（自托管+扫码登录参考实现） |
| hubhike/Music_Plugins「小X系列」(xiaogou/xiaomi/xiaoqiu/xiaowo/xiaoyun) | 各平台**官方接口聚合封装**（酷狗歌词/专辑/榜单、网易、QQ 歌词、咪咕搜索），端点已被 musicdl-api 容器/musicdl 全覆盖 |
| flowsasa / ThomasBy2025 / wkndjs / TZB679 插件集合 | 索引解析后 94 个插件下载沙箱扫描：getMediaSource 层普遍依赖 userVariables 用户凭证或上游失效，**无新增可集成出链端点** |
| 搜索层新捕获域名 | zz123.com（SPA）、gequbao.com（JS 渲染）、t.ijanz.cn（网易推荐接口，价值低）、api.tyhua.top（DNS 失效）、suno studio-api（401） |

**结论**：两轮扫描（本地 23 + 网络 94 + 官方分析 23）合计 **130 个插件、100 个索引源**穷尽后，除已集成的六源与元力/haitangw/nxinxz 兜底外，**无新增有价值的独立音源端点**。当前六源架构已是该生态下的最优覆盖。

后续增量维护建议：
1. 监控 [Huibq/keep-alive](https://github.com/Huibq/keep-alive) 与元力公众号的端点更新
2. 每季度重跑 `.state/probe_endpoints.py` 探测矩阵复核存活状态
3. musicdl 上游更新时同步 hifi 分支解析链
