# 音乐平台无损音质参数总册

> 覆盖范围：酷我 / QQ / 酷狗 / 网易云四大平台 + 咪咕 / 千千两个补充源，**全部音质档位**的官方命名、私有参数、获取参数、实测规格。
> 维护规则：改任何 adapter 的 QUALITY 映射或新增档位时**同步更新本表**；探明新档位时在「状态」列标注实测日期。
> 参数来源：`musicdl/modules/utils/{neteaseutils,kugouutils,qqutils}.py`、`musicdl/modules/sources/{kuwo,qq,kugou,netease,migu,qianqian}.py`、`server/adapters/*.py`（逐行核对，非记忆）；规格列均为**下载真实文件解析头字节**的实测值（fLaC/OggS/ID3 magic），非官方宣传值。
> 建档：2026-09-07 · 关联文档：`API-REFERENCE.md §4.2`（对外 quality 参数）、`MUSIC-SOURCES-REGISTRY.md`（端点存活台账）、`KUWO-ZHENPIN-PROBE.md`（酷我臻品探测全记录）

---

## 0. 对外统一参数（本服务 /song/url 的 quality）

| quality | 归一化别名 | 说明 |
|---|---|---|
| `128k` | low | 有损低档（MusicFree low=128kbps）|
| `192k` | standard | 有损中档（MusicFree standard=192kbps；仅网易有原生 higher 档，其余源回落 320k）|
| `320k` | high / super / auto | 有损高档（MusicFree high=320kbps；super 封顶于此）|
| `flac` | — | CD 无损 16bit/44.1k（**仅对 musicdl 下载有效**）|
| `hires` | — | 高解析（各源含义见 §2，同名不同义；仅下载有效）|
| `master` | — | 母带（**仅酷我**实现，2026-09-07 新增；仅下载有效）|
| `surround51` | surround5.1 / 5.1 | 5.1 全景声（**仅酷我**实现，2026-09-07 新增；仅下载有效）|

`server/config.py QUALITY_ALIASES` 负责别名归一；各源 adapter 再把归一后的 quality 映射到平台私有参数。

---

## 1. 三档全景速查（母带 / 高解析 / CD 无损）

规格列 = 本项目实测（下载文件解析头字节）；可获得性 = 本项目当前链路（2026-09-07 实测）。

### 1.1 母带档（master，24bit/96kHz 及以上）

> **门槛定义**：母带 = **24bit 且采样率 ≥96kHz**（96k/192k 级）。24bit/48kHz 只是入门级 Hi-Res，**不构成母带**（归入 §1.2）。

| 平台 | 官方命名 | 私有参数/前缀 | 实测规格 | 可获得性 |
|---|---|---|---|---|
| **酷我** | 臻品音质 zply / 至臻母带 | `br=20900kmflac` | **fLaC 192000Hz/24bit/2ch ~5560kbps**（《晴天》解密后实测） | 🟢 匿名直出（user=0，需 QMC 解密） |
| **网易云** | 超清母带 | `level=jymaster` | 官方标 192kHz/24bit | 🔒 需黑胶 VIP Cookie 走官方 eapi |
| **QQ** | 臻品母带 | 前缀 `AI00`/.flac（加密 `AIM0`/.mflac）；vkey 数字档 14 | 官方标 24bit/192kHz（媒体普遍实测为 AI 升频） | 🔒 官方需 VIP；第三方链尽力而为 |
| **酷狗** | 蝰蛇母带 | `quality=viper_tape`（v6/priv_url 特权端点） | 官方标 192kHz，需转码 | 🔒 需超级VIP（vip_token+vip_type=6）；加密无解码器（§2.3） |
| **千千** | （无母带产品） | — | `rate=3000` 实测最高仅 48kHz/24bit | ❌ 不及母带门槛 |

### 1.2 高解析档（hires，位深 24bit 或 96kHz 级）

| 平台 | 官方命名 | 私有参数/前缀 | 实测规格 | 可获得性 |
|---|---|---|---|---|
| **酷狗** | 高品 | **`quality=high`** | **fLaC 44100Hz/24bit/2ch**（实测 55.4MB，位深高于自家 `flac`） | 🟢 概念版 Cookie 免 VIP 直出 |
| **酷狗** | （无效参数） | `quality=hires` | — | ❌ 酷狗体系无 `hires` 参数，实测 status=0 空 |
| **网易云** | Hi-Res | `level=hires` | 官方标 24bit/96kHz | 🔒 需黑胶 Cookie |
| **QQ** | Hi-Res | vkey 数字档 11 | 官方标 24bit/96kHz | ⚠️ 第三方链按上游账号池权益 |
| **酷我** | （无独立档） | — | — | ⚪ 无 96k 独立 br 参数；采样率随曲源下发（§2.1 坑位 3） |
| **千千** | （rate 上限制） | `tracklink?rate=3000` | **fLaC 48000Hz/24bit/2ch**（《等晴天》57.6MB，~1714kbps） | 🟢 匿名；**入门级 Hi-Res**（48k 为最低档，非母带），有效码率偏低不排除上采样，逐曲不定 |

### 1.3 CD 无损档（flac，16bit/44.1kHz）

| 平台 | 官方命名 | 私有参数/前缀 | 实测规格 | 可获得性 |
|---|---|---|---|---|
| **酷我** | 无损（ff/ALFLAC） | `br=2000kflac` | **fLaC 44100Hz/16bit/2ch ~1647kbps**（名义 2000 非真实码率） | 🟢 匿名直出（当前主力） |
| **千千** | （rate 上限制） | `tracklink?rate=3000` | **fLaC 44100Hz/16bit/2ch**（《漠河舞厅》32.7MB） | 🟢 匿名，版权库窄 |
| **酷狗** | 无损 | `quality=flac` | **fLaC 44100Hz/16bit/2ch**（实测 31.6MB） | 🟢 概念版 Cookie 免 VIP |
| **网易云** | 无损 | `level=lossless` | 官方标 16bit/44.1k | 🔒 需黑胶 Cookie；第三方链 lossless 常匿名可得 |
| **QQ** | SQ 无损 | 前缀 `F000`/.flac（加密 `F0M0`/.mflac）；vkey 档 10 | 官方标 16bit/44.1k | 🔒 官方需 VIP；第三方链尽力而为 |
| **咪咕** | SQ 无损 | `toneFlag=SQ`（listen-url XOR 链） | **实下 3.9MB audio/mpeg = MP3**（标注 28.6MB 不透出） | ❌ 匿名假无损，降档 MP3（§2.5） |

---

## 2. 各平台详册

### 2.1 酷我（Kuwo）

**官方私有音质命名**：`source=kwplayerhd_...` 请求串里的 `br` 参数；格式名 flac/mflac/mgg/zp。

| 官方档位 | br 参数 | 容器/格式 | ekey | 规格（实测）| 状态 |
|---|---|---|---|---|---|
| 臻品音质（zply）| `20900kmflac` | mflac | ✓ | **FLAC 192kHz/24bit/2ch ~5560kbps** | ✅ 2026-09-07 |
| 臻品全景声 7.1.4（zpga714）| `24000kmgg` | mgg | ✓ | Ogg Vorbis 12ch ~1090kbps | ⚠️ 可下但 12ch |
| 臻品全景声 5.0.1（zpga501）| `20501kmflac` | mflac | ✓ | **FLAC 44.1kHz/16bit/6ch** | ✅ 2026-09-07 |
| 臻品全景声 2.0.1（zpga201）| `20201kmflac` | mflac | ✓ | FLAC 44.1kHz/16bit/2ch | ✅ 未单列 |
| 臻品母带（bcms）| `22000kmgg` | mgg | — | — | ❌ 降档 |
| 臻品（zp）| `20000kzp` | zp | — | — | ❌ 服务端当 2000kflac |
| 杜比 DTS-X（dtsx）| `25000kmmp4` | mmp4 | — | — | ❌ 降档 |
| 无损（ff/ALFLAC）| `2000kflac` | flac | ✗ | **FLAC 44.1kHz/16bit/2ch ~1647kbps** | ✅ 主力 |
| 高品 | `320kmp3` | mp3 | ✗ | 真 320kbps（实测 321）| ✅ |
| 中品 | `192kmp3` | mp3 | ✗ | 实降 128 | ❌ |
| 标准 | `128kmp3` | mp3 | ✗ | 128kbps | ✅ |

- **获取参数**：`GET nmobi.kuwo.cn/mobi.s?f=web&source=kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk&user=0&type=convert_url_with_sign&rid={rid}&br={br}`（全匿名，详见 KUWO-ZHENPIN-PROBE.md）
- **命名陷阱**：臻品档必须带 `m` 前缀（kmflac/kmgg）；漏 m 静默降 128k
- **adapter 映射**：`server/adapters/kuwo.py ZHENPIN_BR = {'master':'20900kmflac','surround51':'20501kmflac','flac':'2000kflac'}`
- **本服务对应**：master / surround51 / flac / 320k / 128k
- **无此源客户端**：`server/adapters/kuwo.py` 付费曲回退链 `_parsewiththirdpartapis`（多方第三方 API）

**坑位（均实测）**：
1. `2000kflac` ≠ 2000kbps，实测 ~1647kbps（CD 抓轨水平）
2. `10000kflac`/`20000kzp`/`22000kmgg`/`25000kmmp4` 均非有效档（降档或回落）
3. **不存在独立 96kHz br 参数**：官方宣传"至臻音质2.0=96kHz"，但实测 `9600kmflac`/`96000kmflac`/`96kmflac`/`96khmflac`/`19200kmflac`/`192khmflac`/`10000kflac` 等 9 个候选全部被服务端忽略、回退该曲默认臻品档；《晴天》`20900kmflac` 解密实测 192000Hz。**真实采样率由服务端按曲库母带源下发**（有的 192k、有的更低、无源则降 128k/mp3）。详见 KUWO-ZHENPIN-PROBE.md §5.5

### 2.2 QQ 音乐（Tencent）

**官方私有音质命名**：文件前缀 ID（SongFileType）+ 中文名；另有 vkeys 数字档并行体系。

| 官方档位（中文名） | 文件前缀 | 明文扩展名 | 加密前缀 | 加密扩展名 | 规格 |
|---|---|---|---|---|---|
| 臻品母带 | `AI00` | .flac | `AIM0` | .mflac | 24bit 母带 |
| 臻品全景声 2.0 | `Q000` | .flac | `Q0M0` | .mflac | 多声道 |
| 臻品全景声 5.1 | `Q001` | .flac | `Q0M1` | .mflac | 5.1 |
| SQ 无损 | `F000` | .flac | `F0M0` | .mflac | 16bit/44.1k |
| OGG 640 | `O801` | .ogg | `O801` | .mgg | 640kbps |
| OGG 320 | `O800` | .ogg | `O800` | .mgg | 320kbps |
| OGG 192 | `O600` | .ogg | `O6M0` | .mgg | 192kbps |
| OGG 96 | `O400` | .ogg | `O4M0` | .mgg | 96kbps |
| MP3 320 | `M800` | .mp3 | — | — | 320kbps |
| MP3 128 | `M500` | .mp3 | — | — | 128kbps |
| AAC 192 | `C600` | .m4a | — | — | 192kbps |
| AAC 96 | `C400` | .m4a | — | — | 96kbps |
| AAC 48 | `C200` | .m4a | — | — | 48kbps |

**vkeys 数字档位**（第三方链 `api.vkeys.cn` 用 quality 名）：
0 试听 / 1-3 有损 / 4-7 标准 / 8 HQ / 9 HQ增强 / 10 SQ无损 / 11 Hi-Res / 12 杜比全景声 / 13 臻品空间音频 / 14 臻品母带2.0 / 15 AI伴奏4轨 / 16 AI 5.1六轨

**获取参数**：
- 第三方链 `api.vkeys.cn/music/tencent/song/link?mid={mid}&quality={数字档名}`（匿名，主流通道）
- 官方走 `u.y.qq.com/cgi-bin/musicu.fcg` + 文件前缀（需 Cookie/VIP）
- lx 命名对照：`flac24bit/hires/flac/320k` → 分别对应 AI00/F000 等

- **adapter 映射**：`server/adapters/qq.py`（quality 仅建议值，第三方链尽力而为：flac/hires→lossless，其余→exhigh）
- **本服务对应**：flac / 320k / 128k（hires/master 视上游账号池权益回落）

### 2.3 酷狗（Kugou）

**官方私有音质命名**：`quality` 参数字符串。**注意：酷狗体系没有 `hires` 参数——`high` 就是高解析位阶**（实测 24bit FLAC，位深反而高于自家 `flac` 的 16bit）。

| 官方档位 | quality 参数 | 规格 | 状态（2026-09-07 实测）|
|---|---|---|---|
| 蝰蛇磁带（母带）| `viper_tape` | 官方标 192kHz，需转码 | 🔒 需超级VIP，实测 status=2 |
| 蝰蛇超清 | `viper_clear` | 蝰蛇超清母带 | 🔒 需超级VIP，实测 status=2 |
| 蝰蛇全景声 | `viper_atmos` | 多声道 | 🔒 需超级VIP，实测 status=2 |
| **高解析** | **`high`** | **fLaC 44100Hz/24bit/2ch**（实测 55.4MB）| ✅ 概念版 Cookie 免 VIP 直出 |
| 无损 | `flac` | **fLaC 44100Hz/16bit/2ch**（实测 31.6MB）| ✅ 概念版 Cookie 免 VIP |
| 320k | `320` | 320kbps | ✅ |
| 128k | `128` | 128kbps | ✅ |
| 超品 | `super` | — | ⚠️ 实测降 128k mp3 |
| 多轨 | `multitrack` | mkv 多轨容器 | ⚠️ 实测出 mkv |
| （无效参数）| `hires` | — | ❌ 非酷狗体系，实测 status=0 空 |

另一套数字档位（第三方链用）：`['6','5','4','3','2','1']`（6=母带 → 1=标准），见 `kugou.py:170`。

**获取参数**：
- 官方 `trackercdn.kugou.com/v5/url`（仓库 `kugouutils.getsongurl`，需 Cookie+签名 key）；**匿名 status=0 全空**（实测）
- 自托管 KuGouMusicApi 容器 `/song/url?hash=&quality=`（cookie-server 注入概念版 cookie）：flac/high/320/128 正常出 URL；viper 三档返回 `status=2 priv_status=0 auth_through=[]`（vip_type=0 非会员）
- 第三方链 `musicapi.haitangw.net/kgqq/kg.php?type=json&id={hash}&level={hires|lossless|exhigh}`（匿名）

**adapter 映射**：`server/adapters/kugou.py QUALITY = {'128k':'128','320k':'320','auto':'320','flac':'flac','hires':'high'}`
- `hires→high` 恰好是正确映射：酷狗无 `hires` 参数，`high`（24bit/44.1k）即其高解析位阶

**蝰蛇音质如何才能拿到（2026-09-07 源码 + 实证实锤）**：
1. **端点**：蝰蛇走特权端点 `tracker.kugou.com/v6/priv_url`（POST），非普通 `/v5/url`。MakcRe 源码 `song_url_new.js` 请求体：
   `qualities: ['128','320','flac','high','multitrack','viper_atmos','viper_tape','viper_clear','super']`，
   且带 `tracker_param.priv_vip_type='6'`、`tracker_param.viptoken=<cookie.vip_token>`、顶层 `vip=<cookie.vip_type>`
2. **门槛** = 有效 `vip_token` + 超级VIP 对应 `vip_type`（priv_vip_type=6），**服务端校验**。实测伪装 `vip_type=1`+`vip_token=fake` 无效
3. MakcRe 文档 068-071 的"领取 VIP"系列**不是概念版专属、也不通向蝰蛇**——源码模块 `youth_vip.js`/`youth_day_vip.js` 调 `/youth/v1/ad/play_report`、`/youth/v1/recharge/receive_vip_listen_song`，属**酷狗畅听版（Youth）看广告领"听歌VIP"**福利，与超级VIP 蝰蛇权益无关
4. **官方口径**：蝰蛇母带/超清/全景声列在超级VIP特权，会员中心明示"选择某一价格档位的豪华VIP 时，可额外选择并以一定价格购买蝰蛇系列音质中的任意一款"→ 蝰蛇是需另行付费购买的音质包
5. 即便拿到 URL：新版 `/song/url/new`（`priv_url`）**音频加密，参考文档明言"目前无法解码"**；`viper_tape` 还需转码

### 2.4 网易云（Netease）

**官方私有音质命名**：`level` 参数字符串（v3 song/url 协议）。

| 官方档位（中文） | level 参数 | 规格 | 无损 |
|---|---|---|---|
| 超清母带 | `jymaster` | 24bit/192kHz | ✓ |
| 杜比全景声 | `dolby` | 杜比 AC-4 | ✓（环绕声，非母带）|
| 沉浸环绕声 | `sky` | 沉浸环绕 | ✓（环绕声，非母带）|
| 高清环绕声 | `jyeffect` | 高清环绕 | ✓ |
| Hi-Res | `hires` | 24bit/96kHz | ✓ |
| 无损 | `lossless` | 16bit/44.1k | ✓ |
| 高音质 | `exhigh` | 320kbps | ✗ |
| 低音质 | `standard` | 128kbps | ✗ |

**获取参数**：官方 `interface.music.163.com/eapi/song/enhance/player/url` POST `{ids, level, ...}`（EAPI 加密，需 MUSIC_U Cookie；`neteaseutils.EapiCryptoUtils`）。
匿名通道均用 `level`：haitangw `wy.php`、bugpk `163_music`、bileizhen、chksz 等（第三方链，存活见 REGISTRY）。

- **adapter 映射**：`server/adapters/netease.py levels = ['jymaster','dolby','sky','jyeffect','hires']`（hires 档按序尝试）+ `['lossless','exhigh','standard']`（低档）
- **本服务对应**：flac（→lossless）/ hires（→jymaster..hires 逐级）/ 320k（→exhigh）/ 128k（→standard）

### 2.5 咪咕（Migu）

**官方私有音质命名**：`toneFlag`（PQ/HQ/SQ/ZQ）+ `resourceType`；响应 XOR 加密（MAGIC `\xab\xcd\x01`，key `Jk8qzuePiJ1qE3mDYhLQ3T73DtDoAhLP`）。

| 档位 | toneFlag | 匿名实测（2026-09-07）| 真实性 |
|---|---|---|---|
| SQ（无损）| `SQ`（resourceType `E` 或 `2` 均试） | URL 200 可下，但 **3.9MB audio/mpeg = MP3**；rateFormats 标注 28.6MB 不透出 | ❌ **假无损（降档 MP3）** |
| ZQ（臻品）| `ZQ` | 同样 3.9MB MP3 | ❌ 假无损 |
| HQ | `HQ` | 320k MP3 | ✅ 真实（非无损）|
| PQ/LQ | `PQ`/`LQ` | 128k 及以下 | ✅ |

- **获取参数**：`c.musicapp.migu.cn/strategy/listen-url/h5/v2.4?contentId=&copyrightId=&toneFlag=&resourceType=2`（XOR 解密）；兜底模板 `app.pd.nf.migu.cn/.../listenSong.do?channel=mx&...`（实测 code=200002 拒绝匿名）
- **URL 段实验**：`MP3_128_16_Stero→MP3_320_16_Stero` 替换有效（320k 生效）；替换 `FLAC_44k_16b` → 404，**freetyst CDN 上匿名拿不到 FLAC 路径**
- **结论**：CD 无损匿名拿不到，需会员 Cookie 透出真 SQ；本项目 migu adapter 的 `flac/hires→['SQ','ZQ']` 实际只能拿到降档 MP3，`ext` 按实测返回 mp3
- **adapter 映射**：`server/adapters/migu.py flags = {'flac': ['SQ','ZQ'], 'hires': ['SQ','ZQ']}`

### 2.6 千千（Qianqian / 91q.com）

**官方私有音质命名**：`rate` 数字上限（服务端按库存下发，rate=999 与 3000 可返回同一文件）。

| 档位 | rate | 匿名实测（2026-09-07）| 真实性 |
|---|---|---|---|
| 高解析（入门）/CD 无损 | `3000` | **fLaC 48000Hz/24bit/2ch**（周深《等晴天》57.6MB，~1714kbps，**入门级 Hi-Res，非母带**）；**fLaC 44100Hz/16bit/2ch**（柳爽《漠河舞厅》32.7MB，CD 规格）| ✅ 真 FLAC，档位逐曲不定 |
| — | `999` | 与 3000 同文件 | ✅ |
| 高品 | `320` | 320k MP3 | ✅ |

- **获取参数**：`music.91q.com/v1/song/tracklink?TSID=&appid=16073360&rate=3000`（MD5 签名 `_addsignandtstoparams`，secret `0b50b02fd0d73a9c4c8c3a781c30845f`，匿名可用）
- **⚠️ 版权库窄（实测）**：周杰伦《晴天》《七里香》、邓紫棋《泡沫》《光年之外》**搜索直接无结果**（整缺）；赵雷《成都》标注 30.6MB 实下 MP3（版权个案）。**每曲规格不定，必须以解密/解析头后的实际文件为准**
- **adapter 映射**：`server/adapters/qianqian.py rates = {'flac': ['3000'], 'hires': ['3000']}`

---

## 3. 多声道专区（环绕 / 全景声，独立于三档）

| 平台 | 官方命名 | 私有参数/前缀 | 实测规格 | 可获得性 |
|---|---|---|---|---|
| **酷我** | 臻品全景声 5.0.1（zpga501）| `br=20501kmflac` | **fLaC 44100Hz/16bit/6ch（精确 5.1）**，~2392kbps，80MB/首 | 🟢 **四平台唯一匿名多声道**（需 QMC 解密）|
| **酷我** | 臻品全景声 2.0.1（zpga201）| `br=20201kmflac` | fLaC 44100Hz/16bit/**2ch**（名义全景声档实测立体声，~927kbps）| 🟢 匿名（不建议单列：规格≈2000kflac）|
| **酷我** | 臻品全景声 7.1.4（zpga714）| `br=24000kmgg` | Ogg Vorbis **12ch** ~1090kbps | 🟢 匿名可下，但 12ch 容器特殊（5.1 音箱用不上）|
| **QQ** | 臻品全景声 2.0 / 5.1 | `Q000` / `Q001`（加密 `Q0M0`/`Q0M1`）；vkey 档 12 / 16 | 官方标多声道 | 🔒 官方需 VIP |
| **酷狗** | 蝰蛇全景声 | `viper_atmos` | 官方标多声道 | 🔒 超级VIP（实测 status=2）|
| **网易云** | 杜比全景声 / 沉浸环绕 / 高清环绕 | `level=dolby` / `sky` / `jyeffect` | 官方标环绕声（非母带，体积可能小于 hires）| 🔒 eapi+黑胶 Cookie |

**本项目落地**：`surround51`（仅酷我）= `20501kmflac`，为 5.1 音箱精确匹配；`master_only`/`surround51_only` 偏好在 webgui 可配，回落顺序见 `examples/musicdlwebgui/app.py QUALITY_PREF_RANKS`。

---

## 4. 横向对照与坑位

### 4.1 同名不同义对照表

| 本服务 quality | 网易云 | 酷狗 | 酷我 | QQ | 千千 | 咪咕 |
|---|---|---|---|---|---|---|
| master | `jymaster` | `viper_tape` 🔒 | `20900kmflac` 🟢 | `AI00` 🔒 | —（48k/24bit 不及母带）| —（ZQ 假无损）|
| hires | `hires` | **`high`**（无 hires 参数）🟢 | —（无独立96k档）| vkey 11 ⚠️ | rate=3000 ⚠️（48k/24bit 入门）| —（SQ 假无损）|
| flac | `lossless` | `flac` 🟢 | `2000kflac` 🟢 | `F000` 🔒 | rate=3000 🟢 | —（假无损）|
| 320k | `exhigh` | `320` | `320kmp3` | `M800` | rate=320 | `HQ` |
| 128k | `standard` | `128` | `128kmp3` | `M500` | — | `PQ` |
| surround51 | `dolby`/`sky` | `viper_atmos` 🔒 | `20501kmflac` 🟢 | `Q001` 🔒 | — | — |

### 4.2 坑位提示（全部实测依据）

1. **酷我 `2000kflac` ≠ 2000kbps**——实测 ~1647kbps，CD 抓轨水平；"2000"是名义值
2. **酷我无独立 96k 参数**——"至臻音质2.0=96kHz"是产品概念，技术实现复用 `20900kmflac` 通道按曲源下发采样率（192k 或更低）
3. **酷我臻品档必须带 `m` 前缀**——`20900kflac`（漏 m）静默降 128k
4. **酷狗没有 `hires` 参数**——`high`（24bit/44.1k FLAC）才是其高解析位阶，位深反超自家 `flac`（16bit）；`super` 实测降 128k
5. **酷狗蝰蛇 = 超级VIP + 另行付费音质包**——`v6/priv_url` 特权端点 + `priv_vip_type=6` + 有效 `vip_token`，服务端校验；且音频加密"目前无法解码"
6. **QQ 双体系并行**——文件前缀（`AI00/F000/Q001/M800…`，明文与加密各一套如 `F0M0`）+ vkeys 数字档（0-16），同名 `hires` 在两套里指代不同
7. **网易 `dolby/sky` 是环绕声不是母带**——体积可能反而小于 hires
8. **咪咕匿名 SQ/ZQ 是假无损**——URL 200 可下但实为 3.9MB MP3；元数据标注的 size 不透出，只能以实下文件为准
9. **千千规格逐曲不定且无母带**——rate 是上限不是保证：48k/24bit（入门 Hi-Res）、44.1k/16bit（CD）、假 MP3、曲库整缺四种情况均实测；48k/24bit **不构成母带**（门槛 ≥96kHz）
10. **一切规格以实下文件头字节为准**（fLaC/OggS/ID3 magic + STREAMINFO），各平台元数据标注均不可信

---

## 5. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-07 | 建册；酷我新增 master/surround51（匿名臻品通道）|
| 2026-09-07 | 酷我 96kHz 澄清：无独立 96k br 参数，采样率按曲源下发（§2.1 坑位 2）|
| 2026-09-07 | 酷狗实测：概念版 cookie（vip_type=0）下 flac/high 可出、viper 三档被挡（status=2）；蝰蛇机制源码实锤（v6/priv_url + priv_vip_type=6 + vip_token，超级VIP 付费音质包，加密无解码器）；youth"领取VIP"系畅听版福利，与蝰蛇无关 |
| 2026-09-07 | 酷狗补测：`flac`=16bit/44.1k、`high`=**24bit/44.1k FLAC**、`hires` 参数无效（酷狗体系无此参数）、`super` 降 128k、`multitrack` 出 mkv |
| 2026-09-07 | 咪咕/千千实测新增（§2.5/§2.6）：咪咕匿名 SQ/ZQ 为假无损（降档 MP3）；千千匿名出真 FLAC（48k/24bit 及 44.1k/16bit）但版权库窄 |
| 2026-09-07 | 全册重构：按母带/高解析/CD 三档 + 多声道专区重排（§1/§3），新增咪咕千千横向对照列 |
| 2026-09-07 | 修正千千档位定性：rate=3000 实测 48kHz/24bit 为**入门级 Hi-Res，不构成母带**（母带门槛 = 24bit/≥96kHz），从母带档移至高解析档 |
| 2026-09-07 | MusicFree 四档校准：`standard` 归一化由 128k 改为 **192k**（网易走原生 `higher` 档实测 192kbps；酷我/QQ/酷狗/咪咕/千千无原生 192k 档回落 320k，酷我 192kmp3 为假档）；无损档（flac/hires/master/surround51）标注仅对 musicdl 下载有效 |
