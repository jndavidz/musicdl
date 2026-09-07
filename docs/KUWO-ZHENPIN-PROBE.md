# 酷我臻品（ZhenPin）匿名直出探测报告

> 探测日期：2026-09-07
> 触发物：D:\temp\kuwo 下的 MITM 重写脚本 + 4 个"会员版" APK
> 结论一句话：**酷我臻品音质（mflac/kmgg）可匿名直连 nmobi 获取，无需会员、无需 Cookie、无需 APK。**
> 仓库改动：无（本文档为唯一产出，其余全部为探测性临时文件，已清理）

---

## 1. 核心发现：臻品档位匿名直出

### 1.1 端点

```
http://nmobi.kuwo.cn/mobi.s?f=web
    &source=kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk
    &user=0
    &type=convert_url_with_sign
    &rid={song_id}
    &br={quality}
```

响应为结构化 JSON：`{code:200, data:{bitrate, duration, format, ekey, url, sig, source, user}}`

- `user=0` 即匿名，无 Cookie、无 token、无签名
- 带 `ekey` 的档位需 QMC 解密；不带 `ekey` 的为明文直链
- URL 有时效（数分钟级），必须现取现下，不能长期缓存

### 1.2 完整档位表（全部实测）

| br 参数 | 返回 bitrate | format | ekey | 解密后规格 | 实测大小/首 | 结论 |
|---|---|---|---|---|---|---|
| `320kmp3` | 320 | mp3 | ✗ | mp3 320k | ~11 MB | ✅ 真实 320 |
| `192kmp3` | 128 | mp3 | ✗ | — | — | ❌ 静默降档 |
| `128kmp3` | 128 | mp3 | ✗ | mp3 128k | ~5 MB | ✅ |
| `2000kflac` | 2000 | flac | ✗ | FLAC 44.1k/16bit/2ch | ~9-53 MB | ✅ 明文无损（现行主档） |
| `20000kflac` | 2000 | flac | ✗ | 同 2000kflac | — | 等效 2000kflac |
| **`20201kmflac`** | 20201 | mflac | **✓** | FLAC 44.1k/**16bit**/2ch | 31 MB | ✅ 臻品 2.0.1 |
| **`20501kmflac`** | 20501 | mflac | **✓** | FLAC 44.1k/16bit/**6ch(5.1)** | 80 MB | ✅ 臻品全景声 5.0.1 |
| **`20900kmflac`** | 20900 | mflac | **✓** | FLAC **192k/24bit**/2ch | 187 MB | ✅ 臻品音质（母带级） |
| `22000kmgg` | 128 | mp3 | ✗ | — | — | ❌ 降档 |
| `24000kmgg` | 24000 | mgg | **✓** | **Ogg Vorbis 12ch(7.1.4)** ~1090kbps | 37 MB | ⚠️ 可下但 12ch Ogg |
| `23000kflac` | 128 | mp3 | ✗ | — | — | ❌ 降档 |
| `25000kmmp4` | 128 | mp3 | ✗ | — | — | ❌ 降档 |
| `10000kflac` | 不稳定 | — | — | — | — | ❌ 无效档位 |
| `4000kflac` | 128 | mp3 | ✗ | — | — | ❌ nmobi 上无效（仅 mobi.s f=kuwo 可用） |

### 1.3 命名陷阱：`m` 前缀

臻品档的 br 参数**必须带 `m` 前缀**（`kmflac`/`kmgg`），对应 master/encrypted 格式名。
探测初期用 `20900kflac`（漏 `m`）全部降档到 128k，险些误判为"不可用"。
`m` 前缀只在 APK 的 `classes8.dex` 字符串表里出现，纯猜参数不可能命中。

### 1.4 端到端实证（2026-09-07）

对 rid=228908《晴天》完成三档全流程：

```
nmobi 拿 {url, ekey} → requests 下载 → KuwoQmcDecryptor.decrypt() → 解析文件头
```

| br | 文件体积 | 解码结果 | 采样率 | 声道 | 位深 | 码率 |
|---|---|---|---|---|---|---|
| 20201kmflac | 31,168,013 | FLAC | 44100 | 2 | 16 | ~928 kbps |
| 20501kmflac | 80,437,198 | FLAC | 44100 | 6 | 16 | ~2393 kbps |
| 20900kmflac | 186,980,254 | FLAC | 192000 | 2 | 24 | ~5560 kbps |
| 24000kmgg | 36,638,639 | Ogg Vorbis | 44100 | 12 | — | ~1090 kbps |

12ch 对应 `zpga714`（7.1.4 全景声）；6ch 对应 `zpga501`（5.0.1）；`zply`（20900）是 2ch 母带。

---

## 2. music.pay 付费信息端点（配套发现）

脚本里的 `music.pay?newver=3` 改写规则，实际正确调用方式是：

```
http://musicpay.kuwo.cn/music.pay?newver=3&op=query&action=play&ids={rid}
```

- **`op=query`** 是有效命名空间（`op=play/download/url/getinfo` 全部返回 `Invalid op`）
- **`ids=`** 才是 id 参数（`rid=` 返回空 songs）
- `op=bought&ptype=vip&signver=new` 也有效（返回 user 数组）
- `op=check` 报 `require data`，data 格式未破解，不影响主链路

响应关键字段（以 228908 为例）：

```json
{
  "songs": [{
    "MINFO":  "level:ff,bitrate:2000,format:flac,size:52.83Mb;...",      // 明文档位
    "N_MINFO":"level:bcms,bitrate:22000,format:mgg;level:zply,bitrate:20900,format:mflac;
               level:zpga501,bitrate:20501;level:zpga201,bitrate:20201;
               level:zpga714,bitrate:24000,format:mgg;level:dtsx,bitrate:25000,format:mmp4",  // 臻品档位
    "audio": [{"policy":"vip","st":102,"avaliable":1, "token":...}],
    "token": {"AR501":..,"BCMS":..,"DB":..,"DTSX":..,"F":..,"H":..,"HR":..},
    "payInfo":{"cannotDownload":0,"cannotOnlinePlay":0,"feeType":{"song":"1","vip":"1"},
               "local_encrypt":"1","nplay":"111111111111"},
    "pay":16711935, "tpay":1, "fpay":1, "paytype":3
  }],
  "user": []
}
```

**N_MINFO 的价值**：它是"这首歌有哪些臻品档"的权威清单（`zply`/`zpga201`/`zpga501`/`zpga714`/`bcms`/`dtsx`），
可用来在请求前判断某首是否值得发起 20900kmflac 请求，避免无效调用。

**鉴权语义（见 §4）**：`policy=vip, st=102, tpay=1` 全部来自匿名请求 —— 说明 music.pay 也不做身份校验，
它只是"报价单"，不是"通行证"。

---

## 3. 原始材料逆向结论

### 3.1 MITM 脚本（kuwo.readable.js）

**本质**：Surge/QX/Loon/Shadowrocket/Egern 的 `script-response-body` 重写脚本。
运行前提是代理工具已 MITM 酷我 App 的 HTTPS 流量。它改的是**响应**，不是请求。

13 条规则的可移植性分级：

| 规则 | 机制 | 对 musicdl |
|---|---|---|
| `vip/enc/user/vip` | **远端签名服务** api.120399.xyz | ❌ 服务已关闭 |
| `f=kwxs&q=`（mflac 出链） | **远端签名服务** | ❌ 服务已关闭 + kwxs 端点 404 |
| `vip/v2/user/vip` 字段注入 | 本地 JSON 改写 | ❌ 仅 App UI 有意义 |
| `music.pay` st=0 / mp3Download | 本地 JSON 改写 | ❌ 改的是报价单，不改服务端 |
| `a.p` 听书权限放开 | 本地 JSON 改写 | ⚠️ 仅在新增酷我听书源时才有参考价值 |
| vip 主题/挂件/下载券/首页 HTML | 纯 UI/广告 | ❌ 无用 |

**远端签名服务协议**（仅供考古，已失效）：
`POST https://api.120399.xyz/api/v2`，头 `x-nonce/x-timestamp/x-tools-id/x-app-id: kuwo`，
密钥由 `kuwo#{nonce}#{ts}#{tools-id}OyNyZd3sV` 经自定义 MD5（常量按 seed 洗牌）两次派生，
payload 经 xorshift32-FNV 流 XOR + Base64URL；响应 `oV1`+Base64，盐 `ONZ3V::KUWO_ENC::2025-12-22::|{pathname}`
派生 key/iv 后 AES-CTR 解密。

**实测 403 关闭**，返回作者留言（明确反感解混淆+AI 还原+倒卖）。

### 3.2 APK 四件套

| 文件 | 签名证书 subject | 包名 | dex 数 |
|---|---|---|---|
| 主版 12.2.0.1 | `O=Kuwo, CN=Kuwo`（官方原证书） | `cn.kuwo.*` | 14 |
| 车机版 7.6.2 | `O=kuwo, CN=kuwo`（官方原证书） | `cn.kuwo.kwmusiccar` | 2 |
| 车机共存版 | 同上 | `cn.kuwo.kwmusiccasvipdm` | 2 |
| 手表版 2.2.3 | **`CN=by 东明, O=频道, L=https://t.me/domgmingapk`** | `cn.kuwo.*` | 1 |

- 车机版 vs 共存版：dex 仅差 **8 字节**，唯一差异是包名（`dm`=东明），纯共存打包
- 全部 dex 无 `4077187200000`、无 `luxAutoPayUser` 赋值、无 `y_s_vip` 字面量
- **注入证据**：主版 `classes2.dex` 含 `LSPHooker`+`LSPosed`+`LPCallbackHolder`；
  车机版 `classes.dex` 含 `LSPosed`、`classes2.dex` 含 `de.robv.android.xposed.XposedBridge`
- 主版 `classes8.dex` 含完整音质档位表（§1.2 的 br 参数来源）
- 主版 `classes9.dex` 含"功能拓展"入口文案（作者说明里的 mflac URL 展示位）

**APK 存在的意义**：它是给**手机/车机用户**用的，让 App 客户端自己"以为"有会员，
从而解除 UI 层的播放/下载限制，并在"功能拓展"里暴露内部直链。
对 musicdl 这种服务端直连，**零必要**——且车机版的 `source=` 拿去请求会降档成 1kbps 废流：

```
source=kwplayer_carct_ar_7.6.2.2176221  → bitrate=1 ❌
source=kwplayercar_ar_7.6.2.2176221     → bitrate=1 ❌
source=kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk → 正常 ✅（已在用）
```

---

## 4. 酷我鉴权体系与"绕过"真相

### 4.1 三层结构

```
┌─ 第 1 层：客户端 UI 闸门 ──────────────── App 自己判断
│   依据：本地缓存的 vipExpire / isYearUser / audio[].st / payInfo
│   APK 的 LSPosed hook 打在这里（改方法返回值）
│   MITM 脚本打在 HTTP 响应层（改同一批字段）
│
├─ 第 2 层：报价/策略接口 ────────────────── music.pay
│   返回 policy=vip、st=102、tpay=1、token{}、N_MINFO
│   ★ 实测：匿名可查全部字段，含臻品档位清单和 token
│   ★ 它是"报价单"，不是"通行证" —— 查了不代表能拿
│
└─ 第 3 层：直链下发 ───────────────────── nmobi / mobi.s
    ★ 实测：nmobi 对臻品档完全不做身份校验
      user=0、无 Cookie、无签名，直接返回 url + ekey
    真正的"鉴权"只有一个：br 参数名必须精确（kmflac 带 m）
```

### 4.2 为什么说"不是绕过，是换门"

- 酷我把会员校验做在**第 1 层**（客户端自检）和**第 2 层**（报价接口的 st/policy 标记）
- 但**第 3 层**的直链下发对匿名请求是放开的
- APK/脚本做的是第 1 层的"解锁"（让 App 敢去请求高规格）
- musicdl 直接打第 3 层，跳过前两层，所以既不需要会员也不需要破解

### 4.3 佐证

- `music.pay` 匿名请求返回完整报价（policy=vip/st=102/token/N_MINFO）
- `nmobi` 匿名请求返回 url+ekey，且 `user=0` 与 `user=123456789` 结果一致
- 下载 228908（tpay=1 付费曲）的 192k/24bit 母带成功
- 唯一拦路的参数名 `m` 前缀，是**知识门槛**而非**权限门槛**

---

## 5. 与既有链路的关系（新旧对比）

### 5.1 以前怎么拿会员/付费歌

| 途径 | 状态 | 说明 |
|---|---|---|
| 第三方镜像 API（nxinxz/haitangw/xcloudv/lxmusic/yyy001/gdstudio） | 部分存活 | 靠别人的账号池，随时死 |
| `kwdec.liuyunidc.cn`（RC4+master 档） | **000 连接失败** | 已死（2026-08-07 集成时可用） |
| webgui `kuwo_vip_cookie` + 4000kflac + QMC | 可用 | 需要你自己的 VIP Cookie |
| `mobi.s f=kuwo convert_url2` | 可用 | **静默降档**，最高只到真 2000kflac |

### 5.2 现在的变化

| 维度 | 以前 | 现在 |
|---|---|---|
| 最高音质 | 2000kflac（44.1k/16bit）| **20900kmflac（192k/24bit 母带）** |
| 付费曲 | 依赖第三方账号池 | **匿名直连，无中介** |
| 稳定性 | 上游随时跑路（liuyunidc 已死） | 官方端点，只依赖酷我自己 |
| Cookie | 部分路径需要 | **零 Cookie**（nmobi 匿名端点的客观行为：带 Cookie 反而使第三方链失效） |
| 额外能力 | — | 5.1 全景声（20501kmflac）、多声道 Ogg（24000kmgg） |

### 5.3 与 webgui 音质档的对应关系

webgui 按 MB/min 分级（`examples/musicdlwebgui/app.py`）：
`master ≥42`、`hires ≥17`、`lossless ≥4`（`LOSSLESS_MBPM_FLOOR=4`）

| 酷我档 | 实测 MB/min | webgui 判级 | 备注 |
|---|---|---|---|
| 20900kmflac | 41.7 | hires | **卡在 master 阈值 42 之下**，实为 192k/24bit 母带 |
| 20501kmflac | 17.8 | hires | 16bit/6ch，恰好过 17 |
| 20201kmflac | 6.9 | lossless | 16bit/2ch |
| 2000kflac | ~2-5 | lossless | 现行主档 |

⚠️ **两处判级偏差需要留意**：
1. 20900kmflac 规格上是母带（192k/24bit），但 MB/min=41.7 落在 hires 区
2. webgui 的"hires=24bit/96kHz"理想规格（20-35 MB/min）在酷我**没有对应档位**——
   酷我从 44.1k/16bit 直接跳到 192k/24bit，无 96k 中间档（已穷举 dex 档位表 + 实测确认）

### 5.5 关于"至臻音质2.0 = 96kHz"的澄清（2026-09-07 联网核实 + 实测）

官方宣传确有"至臻音质2.0，采样率从 44.1kHz 提升至 96kHz"（凤凰网/今日头条等多源），且 `kmflac` 是其中的音质档位名。
但**服务端不存在独立可请求的 96kHz `br` 参数**，实测证据：

- 对 `rid=228908/3209103/93157` 等试 `9600kmflac` `9600kflac` `96000kmflac` `96kmflac` `96khmflac` `19200kmflac` `192khmflac` `10000kflac` 等共 9 个候选 —— **全部被服务端忽略，回退到该曲"默认臻品最高档"**：
  - 228908（晴天，无臻品源）→ 回退 `br=128` mp3
  - 3209103（江南）→ 回退 `br=20201`（即 `20201kmflac` 2ch/44.1k）
  - 93157（江南另一版）→ 回退 `br=20900`（即 `20900kmflac`）
- 下载《晴天》`20900kmflac` 完整文件 → QMC 解密 → 真实 `fLaC 192000Hz/24bit/2ch`（**192kHz，非 96kHz**）
- 部分歌曲（七里香/稻香/告白气球/夜曲）走 `20900kmflac` 时服务端**直接降回低码率**（48 aac / 99 mp3 / 192 mp3）—— 这些曲库无臻品母带源

**结论**："至臻音质2.0"是官方产品概念，技术实现上复用 `20900kmflac` 通道，**实际采样率由服务端按曲库母带源下发**（有的 192k、有的更低、有的根本无源降档）。
不存在 `br=96kxxx` 这一独立请求档；文档"无 96k 中间档"的结论成立，修正其原因为"非独立参数，按曲源下发"。

### 5.4 用户已定的命名方案（已落地）

> 音质档位只给二声道，5.1 声道单独命名。
> **20900kmflac 定为 master**（192k/24bit 是母带规格；webgui 旧 MB/min 阈值 42 会把它误判成 hires，已由 `channels`/显式档位修正）。

| 命名 | br 参数 | 规格 | 大小/首 |
|---|---|---|---|
| `master`（2ch 最高） | `20900kmflac` | 192kHz/24bit/2ch | 187 MB |
| `flac`（2ch 常规） | `2000kflac` | 44.1kHz/16bit/2ch | ~9 MB |
| `surround51`（5.1 独立档） | `20501kmflac` | 44.1kHz/16bit/6ch | 80 MB |
| `320k` / `128k` | `320kmp3` / `128kmp3` | mp3 | 现状不变 |

`20201kmflac`（2ch/44.1k/16bit）不单列——与 2000kflac 规格接近仅码率略高。
`24000kmgg`（12ch Ogg）不进下载链路——用户音箱 5.1，12ch 用不上且容器特殊。

**关于 `flac` vs `lossless` 的定性**：2000kflac 实测 1647 kbps（≈CD 抓轨），MB/min 11.8 落在
webgui 的 lossless 区（5-10 上下，<17）——**它就是 CD 无损，不叫 hires**。臻品四档中只有
20900kmflac 是真正的位深/采样率跃升。

**API 质量参数归一化**（`server/config.py QUALITY_ALIASES`）：`master`、`surround51`、
`surround5.1`、`5.1` 均已注册。

---

## 6. 落地状态（2026-09-07 已实现）

| 项 | 文件 | 说明 |
|---|---|---|
| 档位路由 | `server/adapters/kuwo.py` `ZHENPIN_BR` | master→20900kmflac、surround51→20501kmflac、flac→2000kflac |
| ekey 透传 | `server/adapters/kuwo.py _finalize_direct` | 加密档 `ext=mflac` + `ekey` 字段；明文档位无 ekey |
| 参数归一化 | `server/config.py QUALITY_ALIASES` | `master`/`surround51`/`surround5.1`/`5.1` |
| 响应契约 | `server/schemas.py SongUrlData` | 新增 `ekey: Optional[str]` |
| API 解析 | `examples/musicdlwebgui/app.py api_resolve_into` | ekey → `info.api_extra`，webgui 偏好 `master_only`/`surround51_only` |
| 下载解密 | `examples/musicdlwebgui/app.py` 下载 hook | `KuwoQmcDecryptor.decrypt()` → 明文 flac，platform_tag `臻品·已解密` |
| 显示层 | `examples/musicdlwebgui/static/index.html` | `master`/`surround51` 徽标与排序、下拉选项 |
| 冒烟 | `server/tests/test_smoke.py` | 15/15 PASS（默认 ENABLE_LOSSLESS=false，含 403 门控项） |

端到端实证：`/kuwo/song/url?quality=master` → 下载 187MB → QMC 解密 → `fLaC 192000Hz/24bit/2ch` ✅

## 6.1 前置条件与不变量

1. **解密**：`scripts/kuwo_qmc_decryptor.py`（2026-09-01 入库），webgui 已有 `qmc_decrypt_file()` 范式
2. **零 Cookie 匿名直连**：nmobi `user=0` 全程匿名，无账户依赖
3. **URL 时效**：数分钟级，必须维持二段式（`/song/url` 时现取现下），不可缓存直链
4. **门控**：master/surround51 与 flac/hires 同受 `ENABLE_LOSSLESS` 管控（默认 403）

## 7. 涉及文件

- `musicdl/modules/utils/kuwoutils.py` — DES 加密（ylzsxkwm）、歌词加解密（与脚本同源，无新算法可抄）
- `scripts/kuwo_qmc_decryptor.py` — QMC/mflac/mgg 解密器（本方案核心依赖）
- `server/adapters/kuwo.py` — 落地点（`_nmobi_direct` 加 br 参数即可复用）
- `examples/musicdlwebgui/app.py` — 解密调用范式与音质判级
- `docs/MUSIC-SOURCES-REGISTRY.md` — 台账，需补录臻品档位（本文档 §1.2）
