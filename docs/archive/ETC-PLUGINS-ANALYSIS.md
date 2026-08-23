# MusicFree etc/ 参考插件深度解析

> 创建日期：2026-08-07（最近更新：2026-08-07）
> 数据来源：`X:\web\projects\musicfree-plugins\etc\musicfree\` 目录下的 23 个源插件文件（启用分析样本从 `etc\` 顶层并入 `etc\musicfree\`；目录另含若干 `decode_*.js` / `parse_*.py` 分析工具脚本，非插件）
> 用途：为 musicdl 新增 `_parsewith*` 第三方解析源、密钥、Cookie 字段、音质映射提供参考；相关内容将转入"音源插件专题"对话深入展开
> ⚠️ 参考插件仅反映抓取时点（2026-08-06）的可用性，不保证今天仍可用，所有端点需实测验证后再集成

---

## 0. 阅读指南

本文对 `etc/musicfree/` 下全部 23 个源插件逐一编号（P-01 ~ P-23），按 QQ 系 / 酷我系 / 聚合与歌词 三大类组织。每个插件给出：

- **文件名**（对应 `etc/musicfree/` 目录的实际文件）
- **元信息**（platform / version / author / 打包方式 / 依赖）
- **API 端点清单**（搜索、专辑、歌手、歌单、排行、歌词、封面、getMediaSource 解析）
- **getMediaSource 解析范式**（这是决定能否"按 song_id 实时重解析"的关键）
- **认证 / 密钥 / Cookie 字段**
- **音质映射**（MusicFree 的 `low/standard/high/super` → 平台音质）
- **架构特点与可借鉴点**

文末第 4 章给出**可提取到 musicdl 的端点/密钥总表**和**成果总结**。

---

## 1. QQ 音乐系插件（P-01 ~ P-07）

### P-01 · `QQ.js`

| 项 | 值 |
|----|----|
| 文件名 | `QQ.js` |
| platform | `QQ音乐` |
| version | `2` |
| author | `自用` |
| 打包 | Parcel（`$parcel$export` / `$parcel$interopDefault`，变量前缀 `$d25ff3d008f9e7e0$`） |
| 依赖 | axios + crypto-js + he |

**API 端点**
- 搜索：`https://u.y.qq.com/cgi-bin/musicu.fcg`（POST，`music.search.SearchCgiService` / `DoSearchForQQMusicDesktop`）
- 专辑：`https://u.y.qq.com/cgi-bin/musicu.fcg`（`music.musichallAlbum.AlbumSongList`）
- 歌手歌曲：`http://u.y.qq.com/cgi-bin/musicu.fcg`（`music.web_singer_info_svr`）
- 歌单导入：`http://i.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?disstid={id}`
- 排行榜：`https://u.y.qq.com/cgi-bin/musicu.fcg`（`musicToplist.ToplistInfoServer`）
- 推荐标签：`https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_tag_conf.fcg` / `.../fcg_get_diss_by_tag.fcg`
- 封面：`https://y.gtimg.cn/music/photo_new/T002R800x800M000{albummid}.jpg`
- 歌词：`http://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid=...`（Base64 JSONP，需解码）
- **getMediaSource / getMusicInfo**：`https://api.nki.pw/API/music_open_api.php?apikey={apiKey}&mid={songmid}`

**getMediaSource 范式**：范式 A（直接调第三方 API 吃 songmid）。一次请求返回含所有音质字段的整条记录，按 quality 选字段：

```js
const qualityMap = {
  low: 'song_play_url_hq', standard: 'song_play_url_accom',
  high: 'song_play_url_pq', super: 'song_play_url_sq'
};
// 回退顺序：目标字段 → song_play_url → music_url → url
```

**认证 / 密钥**
- `CONFIG.apikey = "ed34917b6e3ca97d609a82e73c82599c176a07a4bcad5f5f7ab4ee95b3fa90ba"`（硬编码，可被用户变量 `apiKey` 覆盖）
- QQ 官方端点用匿名 Cookie：`Cookie: "uin="`

**音质映射**：`low→song_play_url_hq, standard→song_play_url_accom, high→song_play_url_pq, super→song_play_url_sq`（字段名非标准，注意映射）

**架构特点**：单文件 Parcel 打包，`userVariables` 声明 `apiKey`。getMusicInfo 复用 nki.pw 返回的 `song_lyric`/`lyric` 字段。无测速、无 VIP 检测。失败抛错。

**可借鉴点**：nki.pw 的 apikey 与端点；getMusicInfo 与 getMediaSource 合并到一次 API 调用的设计（减少请求数，规避 10 秒超时）。

---

### P-02 · `QQ(独家音源) v4.js`

| 项 | 值 |
|----|----|
| 文件名 | `QQ(独家音源) v4.js` |
| platform | `QQ(独家音源)` |
| version | `4` |
| author | `竹佀＆玥然OvO` |
| 打包 | Parcel（变量前缀 `$d25ff3d008f9e7e0$`） |
| 依赖 | axios + 内联 SHA-256（无 crypto-js） |

**API 端点**
- 搜索/专辑/歌手/歌单/排行：与 P-01 `QQ.js` 完全相同（代码复制粘贴）
- **getMediaSource**：`https://88.lxmusic.xn--fiqs8s/lxmusicv4/url/tx/{songmid}/{quality}?sign=...`（host 是 punycode，对应 `88.lxmusic.中国`）
- **getLyric**：`https://yunzhiapi.cn/API/jhlrcgc.php?id={songmid}&msg=qq`（不再用 c.y.qq.com cgi）

**getMediaSource 范式**：范式 B（签名 URL，lx-music v4 协议）。

```js
const API_URL    = 'https://88.lxmusic.xn--fiqs8s';
const SCRIPT_MD5 = '1888f9865338afe6d5534b35171c61a4';
const SECRET_KEY = 'JaJ?a7Nwk_Fgj?2o:znAkst';
const txQualityMap = {"128k":"128k","320k":"320k","flac":"flac","flac24bit":"flac24bit"};
function generateSign(requestPath) {
    return sha256(requestPath + SCRIPT_MD5 + SECRET_KEY);  // 内联 SHA-256 实现（约 250 行）
}
// 请求头：x-request-key: lxmusic, user-agent: lx-music-mobile/2.0.0
// 成功 code 0/200 → data.url；403 = key 失效；429 = 限速
```

**认证 / 密钥**
- 硬编码 `SCRIPT_MD5 = '1888f9865338afe6d5534b35171c61a4'`、`SECRET_KEY = 'JaJ?a7Nwk_Fgj?2o:znAkst'`
- 签名 = `sha256(requestPath + SCRIPT_MD5 + SECRET_KEY)`
- 请求头 `x-request-key: lxmusic`，UA `lx-music-mobile/2.0.0`

**音质映射**：`low→128k, standard→320k, high→flac, super→flac24bit`

**架构特点**：失败返回 `{url:''}`（静默，不抛错）——与 P-01 抛错的设计相反。内联 SHA-256 实现，不依赖 crypto-js。无 userVariables、无测速、无 VIP 检测。

**可借鉴点**：lx-music v4 签名协议（SCRIPT_MD5 + SECRET_KEY 密钥对）可直接照搬为 musicdl 的 `_parsewithlxmusicsignedapi`；该协议同时覆盖 QQ 和酷我（见 P-10），一套密钥双平台。

---

### P-03 · `QQ(迟言接口) v1.js`

| 项 | 值 |
|----|----|
| 文件名 | `QQ(迟言接口) v1.js` |
| platform | `QQ(迟言接口)` |
| version | `1` |
| author | `竹佀` |
| 打包 | Parcel |
| 依赖 | axios + crypto-js + he |

**API 端点**：搜索/专辑/歌手/歌单/排行与 P-01 相同。歌词用 c.y.qq.com base64 cgi（与 P-01 一致）。
- **getMediaSource**：`https://cyapi.top/API/qq_music.php?apikey={KEY}&type=json&mid={songmid}`

**getMediaSource 范式**：范式 A，但**忽略 quality 参数**——API 只返回单一 URL。

```js
const apiUrl = `https://cyapi.top/API/qq_music.php?apikey=1ffdf5733f5d538760e63d7e46ba17438d9f7b9dfc18c51be1109386fd74c3a1&type=json&mid=${musicItem.songmid}`;
// 返回 response.data.url 直接用
```

**认证 / 密钥**：apikey `1ffdf5733f5d538760e63d7e46ba17438d9f7b9dfc18c51be1109386fd74c3a1` 硬编码在 URL。请求头 `Referer: https://y.qq.com`。

**音质映射**：定义了 `typeMap`（m4a/128/320/ape/flac filename 编码）但**未使用**，API 返回什么用什么。

**架构特点**：最简实现。无 userVariables、无测速、无 VIP 检测。失败抛错。

**可借鉴点**：cyapi.top 端点 + apikey，作为 musicdl 的低优先级备用源（音质不可控是缺点）。

---

### P-04 · `腾讯音乐 v2025.09.13.js` ⭐（最复杂，唯一带 VIP 判定 + 多源回退）

| 项 | 值 |
|----|----|
| 文件名 | `腾讯音乐 v2025.09.13.js` |
| platform | `腾讯音乐` |
| version | `2025.09.13` |
| author | `Thomas喲` |
| 打包 | 纯 `module.exports`（非 Parcel） |
| 依赖 | axios（无 crypto-js/he） |

**API 端点**
- 主端点：`https://u6.y.qq.com/cgi-bin/musicu.fcg`（POST，所有 module：`vkey.GetVkeyServer`/`CgiGetVkey`、`music.search.SearchCgiService`/`DoSearchForQQMusicLite`、`musicToplist`、`music.playlist.PlaylistSquare`、`music.pf_song_detail_svr` 等）
- 歌词：`http://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?...&nobase64=1`（直接返回原文，不 base64）
- **getMediaSource 主路径**：官方 `GetVkeyServer`/`CgiGetVkey`，需要 `uin` + `qm_keyst`
- **getMediaSource 回退阶梯**（`getMediaProxys`，err_i 0→5）：
  - 0：`https://api.ikunshare.com/url?source=tx&songId={songmid}&quality={128k|320k|flac|flac24bit}`（header `X-Request-Key: <ikun_key>`，UA `lx-music-mobile/2.0.0`）
  - 1：`https://music.haitangw.cc/music/qq_song_kw.php?level={standard|exhigh|lossless|hires}&type=json&id={songmid}`
  - 4：`https://lxmusicapi.onrender.com/url/tx/{songmid}/{128k|320k}`（header `X-Request-Key: share-v2`，UA `lx-music-mobile/2.0.0`）
  - 最终：**酷我重搜回退**——搜 `http://search.kuwo.cn/r.s` 找同名曲，再用 `http://nmobi.kuwo.cn/mobi.s?f=web&source=...&type=convert_url_with_sign&rid={songId}&br={128kmp3|320kmp3|2000kflac|20000kflac}`（UA `okhttp/4.10.0`）解析（实测 2026-08-07：返回 **200 JSON `data.url` 直给 CDN**，非 302 跳转；`20000kflac` 实际回落 `bitrate=2000`）

**getMediaSource 范式**：官方优先 + 多源回退阶梯。

```js
async function getMediaSource(musicItem, quality) {
    if (!musicItem.qualities[quality]) return false;      // VIP/音质前置门控
    let { uin, isLogin } = getLogin();
    try {
        if (!isLogin && musicItem.type == "1") throw new Error('is vip music');  // type "1" = VIP 歌曲
        // ... 构造 filename = `${typeObj.s}${id}${strMediaMid}${typeObj.e}`
        let __ = await ajax({ module: "vkey.GetVkeyServer", method: "CgiGetVkey", param: {...} });
        url = __.midurlinfo[0].purl;
        if (url && url != "") return { url: __.sip[0] + url };
        else throw new Error('no get purl');
    } catch (isVipMusic) { return await getMediaProxys(musicItem, quality); }  // → 回退链
}
```

**认证 / 登录模型**（etc/ 里最完整）
- `getLogin()` 读用户变量 `uin` 和 `qm_keyst`。校验 `qm_keyst` 含 `W_X` 或 `Q_H_L` 前缀视为登录态，否则匿名（`uin=0`）
- `getComm()` 构造 Cookie `qm_keyst=<tk>; uin=<cv>` + 大块 `comm`（`authst`/`qq`/`tmeAppID: qqmusiclight` 等）
- 未登录兜底：硬编码 token `Q_H_L_5FBMRs-uicpIQo8Ymt3v0w1f0DAyJwQMdLJPVKmmOQZRQZkuz8AfB1Q`、uin `948168827`
- `userVariables`：`uin`、`qm_keyst`、`ikun_key`、`source`（酷我渠道）

**VIP 判定**：`musicItem.type === "1"` 表示 VIP 歌曲（`pay.payplay`），未登录时主路径抛错走代理链。这是 etc/ 里**唯一真正的 VIP 门控逻辑**。

**音质映射**（主路径）：`low→M500.mp3, standard→M800.mp3, high→F000.flac, super→RS01.flac`。同时枚举 `size_24aac`(C200)、`size_48aac`、`size_96aac`(C400)、`size_192aac`(C600)、`size_128mp3`/`size_320mp3`、`size_96ogg`/`size_192ogg`、`size_ape`(A000)、`size_flac`(F000)、`size_hires`(RS01)、`size_new[0]`(AI00 母带2.0)、`size_new[1]`(Q000 臻品全景声)、`size_new[2]`(Q001 杜比)、`size_try`(RS02 试听)。代理回退用 lx 命名 `128k/320k/flac/flac24bit` 或 `standard/exhigh/lossless/hires`。

**架构特点**：纯 module.exports，唯一带 `getMusicComments`、`importMusicItem`、富 `formatMusicItem`（含 `qualities` map + `strMediaMid` + `vid`）。回退链用 try/catch 递归 `err_i+1`，**非计时测速**。

**可借鉴点**：① 多源回退阶梯设计（GetVkey→ikunshare→haitangw→lxmusicapi→酷我重搜）是 musicdl 静态 l1-l4 列表的动态版原型；② VIP 判定（type==1）+ 登录态校验（qm_keyst 前缀）可直接搬进 musicdl 的 `detector.py`；③ `nmobi.kuwo.cn/mobi.s` 无 Cookie 官方端点（#11）值得作为酷我的无 Cookie 主源。

---

### P-05 · `元力QQ v1.2.0.js`（长青SVIP音源，付费中转）⭐

> **文件变更说明（2026-08-07）**：本槽位原为 `元力QQ v0.1.0.js`（已从 `etc/musicfree/` 删除，旧版本备份于 `musicfree-new/元力音源(科技长青)/旧版/0.1.0/`）。现文件为 **v1.2.0**，作者转为「微信公众号:元力菌」（原「科技长青」）。

| 项 | 值 |
|----|----|
| 文件名 | `元力QQ v1.2.0.js` |
| @name | **长青SVIP音源**（`@version 1.0.0`，platform version 1.2.0） |
| author | `微信公众号:元力菌` |
| srcUrl | `https://13413.kstore.vip/yuanli/qq.js` |
| 打包 | 混淆（`_0x4a03` 自定义 base64 + `_0x2637` base64+RC4），module.exports |
| 依赖 | axios + he + crypto-js |
| 鉴权 | **无任何凭证/密钥/userVariables**（`Cookie:'uin='` 占位，`g_tk=5381` 固定） |

**API 端点**
- 搜索/专辑/歌手/榜单/歌单：走 QQ 官方公开匿名端点（`u.y.qq.com/cgi-bin/musicu.fcg`、`c.y.qq.com` 等），带 `Cookie:'uin='` + `g_tk=5381`，无真实登录态可用
- 歌词：QQ 官方歌词 cgi（部分歌曲返回空/异常，见缺陷）
- **getMediaSource**：`http://175.27.166.236/kgqq1/qq.php?id={songmid}&type=json&level={...}`（元力菌**私有中转服务器**，§4.1 表 #19，无鉴权、实测可用）

**💡 关键架构（实测中覆盖的 r2.0 与前版结论相反）**：`getMediaSource` **并不直连官方端点**，而是走**元力菌私有中转服务器**（付费 SVIP 服务）。这是 MusicFree 里能正常播放、但单独调用"官方端点"失败的根本原因——插件客户端干净无凭证，凭证与解析都在元力私有后端。详见 `docs/YUANLI-V1.2.0-PLUGIN-API.md`。

**getMediaSource 细节**：`level` 映射 `low/standard/high→exhigh`、`super→lossless`；响应 `{code:200,msg:'换源成功',data:{url,...}}`；**返回的是 kuwo CDN**（`car-lv/car-er.kuwo.cn`，M800=320k mp3、F000=flac），即元力后端对 QQ 走"跨平台酷我重搜"兜底。

**音质标准**：元力 系标准仅 `exhigh(320k) / lossless(FLAC)`，**无母带/Hi-Res**（hires/master/atmos 等参数经中转实测全部塌缩回 320k，2026-08-07 三首样本验证）。母带级需走 musicdl 内置 `kwdec.liuyunidc.cn`（§4.9.2，`kuwo.py` 已解锁 master 档）。

**已知插件缺陷**：QQ `getAlbumInfo` 的 `albumID` 恒传 0，实际返回空列表（bug）；`getLyric` 在部分歌曲返回空/报异常（歌词接口对传入对象字段依赖强）。

**可借鉴点**：① 元力私有中转是"瘦客户端 + 服务端凭证"架构的又一实例（青听同款，读 4.8.6）；该中转端点**无鉴权可用**，可作 musicdl 低优先级兜底源（⚠️ 付费私有、非公开、随时失效，勿作主源）；② QQ→kuwo 跨平台兜底在此插件再次出现，佐证 P-04/青听的同款策略在业界常用，musicdl `qq.py` 值得照搬。

---

### P-06 · `西瓜糖(Q音) v2 (已配置key).js`

| 项 | 值 |
|----|----|
| 文件名 | `西瓜糖(Q音) v2 (已配置key).js` |
| platform | `QQ音乐2` |
| version | `2` |
| author | `玥然OvO` |
| 打包 | Parcel |

**API 端点**：与 P-01 `QQ.js` **完全相同**（同代码分支），getMediaSource 也用 `api.nki.pw` 同一 apikey。

**架构特点**：本质是 P-01 的换名副本，无新增端点。唯一差异是 platform 名和 srcUrl。

**可借鉴点**：无（与 P-01 重复）。

---

### P-07 · `弥音QQ(128k) v1.js`

| 项 | 值 |
|----|----|
| 文件名 | `弥音QQ(128k) v1.js` |
| platform | `弥音QQ` |
| version | `1` |
| 打包 | Parcel |

**API 端点**：搜索同族。getMediaSource 走特定 128k 限流端点（文件名即标注 128k）。

**音质映射**：仅 128k，`super` 也降级到 128k。

**架构特点**：低音质专用源，适合做最低优先级兜底。无测速、无 VIP 检测。

**可借鉴点**：仅作为"最差也能出声"的兜底端点候选，需实测确认端点。

---

## 2. 酷我音乐系插件（P-08 ~ P-15）

### P-08 · `酷我 v0.1.0.js`

| 项 | 值 |
|----|----|
| 文件名 | `酷我 v0.1.0.js` |
| platform | `酷我` |
| version | `0.1.0` |
| author | `JHMS_Channel` |
| 打包 | 纯 `module.exports` |
| 依赖 | axios + he |

**API 端点**
- 搜索（music/album/artist/sheet）、歌手作品、专辑：`http://search.kuwo.cn/r.s`
- 排行榜：`http://wapi.kuwo.cn/api/pc/bang/list`、`http://kbangserver.kuwo.cn/ksong.s`
- 歌单：`http://nplserver.kuwo.cn/pl.svc?op=getlistinfo`
- 推荐标签：`http://wapi.kuwo.cn/api/pc/classify/playlist/getTagList` / `.../getTagPlayList` / `https://wapi.kuwo.cn/api/pc/classify/playlist/getRcmPlayList` / `http://mobileinterfaces.kuwo.cn/er.s?type=get_pc_qz_data`
- 歌词：`https://kuwo.cn/openapi/v1/www/lyric/getlyric?musicId=...`
- getMusicInfo：`http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId=...`
- 封面：`https://img4.kuwo.cn/star/albumcover/1080...`
- **getMediaSource**：`https://api.music.lerd.dpdns.org/mf/kw`（POST）；自更新 URL `https://api.music.lerd.dpdns.org/mf/kw.js`

**getMediaSource 范式**：范式 C（服务端驱动 303 两步协议，etc/ 独有）。

```js
const qualityLevels = { low:"128k", standard:"320k", high:"flac", super:"hires" };
// 第一步：POST {musicItem, quality} → 服务端返回 code:303 + 后续请求描述符
// 第二步：客户端按描述符执行第二次请求，按 check 谓词校验后提取 url
const S = JSON.parse(JSON.stringify(res.data));  // {request:{url,options}, response:{check:{key,value}, url:[...]}}
const res2 = await axios({ url: encodeURI(S.request.url), ...S.request.options });
const req = { status: res2.status, body: res2.data, headers: res2.headers };
if (S.response.check.key.reduce((acc, cur) => acc && acc[cur], req) == S.response.check.value) {
    const url = S.response.url.reduce((acc, cur) => acc && acc[cur], req);
    if (url.startsWith("http")) return { url: url };
}
```

**认证 / 密钥**：无。匿名。

**音质映射**：`low→128k, standard→320k, high→flac, super→hires`

**架构特点**：纯 module.exports，axios + he。`srcUrl` 设自更新。**唯一把实际 URL 抓取委托给远程 "mf" relay 服务器**（api.music.lerd.dpdns.org）而非直连酷我或解析 API。无测速、无 VIP 检测。

**可借鉴点**：lerd.dpdns.org 的 303 两步协议反爬设计；但实现复杂，musicdl 集成需在 `_parsewith*` 里复刻两步逻辑。

---

### P-09 · `酷我(独家音源) v4.js`

| 项 | 值 |
|----|----|
| 文件名 | `酷我(独家音源) v4.js` |
| platform | `酷我(独家音源)` |
| version | `4` |
| author | `竹佀＆玥然OvO` |
| 打包 | Parcel（变量前缀 `$4e63e094b4590b2b$`） |
| 依赖 | axios + he |

**API 端点**：酷我搜索/专辑/排行/歌单与 P-08 相同。差异：
- **getMediaSource**：`https://88.lxmusic.xn--fiqs8s/lxmusicv4/url/kw/{id}/{quality}?sign=...`（路径用 `kw` 而非 `tx`）
- **getLyric**：`https://yunzhiapi.cn/API/jhlrcgc.php?id={id}&msg=kw`（非酷我 openapi）
- getMusicInfo 仍用 `http://m.kuwo.cn/newh5/singles/songinfoandlrc`

**getMediaSource 范式**：范式 B（签名 URL），与 P-02 完全同套协议，仅 path 前缀 `kw` + 用 `id` 而非 `songmid`。

```js
const API_URL    = 'https://88.lxmusic.xn--fiqs8s';
const SCRIPT_MD5 = '1888f9865338afe6d5534b35171c61a4';   // 与 P-02 完全一致
const SECRET_KEY = 'JaJ?a7Nwk_Fgj?2o:znAkst';             // 与 P-02 完全一致
const requestPath = `/lxmusicv4/url/kw/${musicItem.id}/${qualityValue}`;
const sign = generateSign(requestPath);
// 失败抛错（与 P-02 静默不同）
```

**认证 / 密钥**：与 P-02 共用同一对 SCRIPT_MD5/SECRET_KEY，同一 header `x-request-key: lxmusic`。

**音质映射**：`low→128k, standard→320k, high→flac, super→flac24bit`

**架构特点**：文件尾部有内联自测 `search("童话镇",1,"music")...`（开发残留代码）。失败抛错（与 P-02 的 `{url:''}` 静默不同）。

**可借鉴点**：证实 lx-music v4 签名协议**一套密钥双平台**（QQ+酷我），musicdl 实现一个 `_parsewithlxmusicsignedapi` 即可同时服务两个平台。

---

### P-10 · `酷我(念心音源) v1.0.0.js`

| 项 | 值 |
|----|----|
| 文件名 | `酷我(念心音源) v1.0.0.js` |
| platform | `酷我(念心音源)` |
| version | `1.0.0` |
| author | `玥然OvO` |
| 打包 | 纯 `module.exports` |
| 依赖 | axios + he |

**API 端点**：酷我搜索/专辑/排行与 P-08 相同。
- **getMediaSource**：`https://music.nxinxz.com/kw.php?id={id}&level={LEVEL}&type=mp3`
- getLyric：`http://m.kuwo.cn/newh5/singles/songinfoandlrc`（返回 lrclist）

**getMediaSource 范式**：范式 A 的极简变体——**不调 API 解析响应，直接构造 URL 返回**，该 URL 本身就是流式重定向端点：

```js
const PLUGIN_QUALITY_MAP = { 'low':'128k', 'standard':'320k', 'high':'flac', 'super':'flac' };
const QUALITY_MAP = { '128k':'standard', '320k':'exhigh', 'flac':'lossless' };
async function getMediaSource(musicItem, quality) {
  const userQuality = PLUGIN_QUALITY_MAP[quality] || '128k';
  const apiLevel = QUALITY_MAP[userQuality];
  const url = `https://music.nxinxz.com/kw.php?id=${encodeURIComponent(songId)}&level=${encodeURIComponent(apiLevel)}&type=mp3`;
  return { url };  // 无 JSON 二跳，url 即流
}
```

**认证 / 密钥**：无。

**音质映射**：`low→standard(128k), standard→exhigh(320k), high→lossless(flac), super→flac`（**super 无 hires，降级到 flac**）

**架构特点**：最简实现。无测速、无 VIP 检测。

**可借鉴点**：nxinxz 的"URL 即流"模式省一次请求，但 musicdl 的 `AudioLinkTester` 需 HEAD/GET 探测才能验证，集成时注意。该源 musicdl 已内置（`_parsewithnxinxzapi`）。

---

### P-11 · `酷我JHMS v0.1.0.js`

| 项 | 值 |
|----|----|
| 文件名 | `酷我JHMS v0.1.0.js` |
| platform | `酷我JHMS` |
| version | `0.1.0` |
| author | `JHMS_Channel` |
| 打包 | 纯 `module.exports` |

**API 端点**：与 P-08 同源（JHMS_Channel 作者的另一个变体）。getMediaSource 走 lerd.dpdns.org 同 P-08 的 303 协议。

**架构特点**：P-08 的同作者换名版本，无新增端点。

**可借鉴点**：无（与 P-08 重复）。

---

### P-12 · `闻音酷我 v1.0.0.js`

| 项 | 值 |
|----|----|
| 文件名 | `闻音酷我 v1.0.0.js` |
| platform | `闻音酷我` |
| version | `1.0.0` |
| author | `竹佀` |
| 打包 | 纯 `module.exports` |

**API 端点**：全功能代理（搜索+音源+歌词）都走 `https://kw-api.cenguigui.cn`。
- getMediaSource：`kw-api.cenguigui.cn?id={id}&type=song&level=LEVEL&format=json`
- getLyric：`kw-api.cenguigui.cn?id={id}&type=lyr&format=all`（返回 `data.lrclist`，注意返回的是列表对象而非格式化字符串，疑似 bug，MusicFree 里可能渲染为空）
- 歌词请求带硬编码 `kw_token=123456`

**getMediaSource 范式**：范式 A。

**认证 / 密钥**：无鉴权，但歌词请求硬编码 `kw_token: "123456"`（仅歌词用，音源不用）。

**音质映射**：`low→standard, standard→exhigh, high→lossless, super→hires`

**架构特点**：全功能委托 cenguigui.cn 代理，连搜索都不直连酷我。无测速、无 VIP 检测。

**可借鉴点**：cenguigui 端点 musicdl 已内置（`_parsewithcggapi`）；`kw_token=123456` 是个有趣的硬编码，可能用于绕过酷我歌词限流。

---

### P-13 · `闻音酷我 v2重构版.js`

| 项 | 值 |
|----|----|
| 文件名 | `闻音酷我 v2重构版.js` |
| platform | `闻音酷我` |
| version | `2` |
| author | `竹佀` |
| 打包 | Parcel（变量前缀 `$4e63e094b4590b2b$`，与 P-09 同命名空间） |
| 依赖 | axios + he |

**API 端点**：酷我搜索/专辑/排行与 P-08 相同（v2 不再全功能代理）。差异：
- **getMediaSource + getLyric**：都用 `https://kw-api.cenguigui.cn`

**getMediaSource 范式**：范式 A。

```js
async function getMediaSource(musicItem, quality) {
    const qualityMap = { low:"standard", standard:"exhigh", high:"lossless", super:"hires" };
    const apiQuality = qualityMap[quality] || "exhigh";
    const res = await axios.get(`https://kw-api.cenguigui.cn`, {
        params: { id: musicItem.id, type: "song", level: apiQuality, format: "json" }
    });
    if (res.data && res.data.code === 200 && res.data.data && res.data.data.url) {
        return { url: res.data.data.url };
    }
    throw new Error("获取播放链接失败");
}
```

**认证 / 密钥**：无。

**音质映射**：`low→standard, standard→exhigh, high→lossless, super→hires`（与 P-12 一致）

**架构特点**：v2 重构把搜索改回直连酷我官方，只把音源+歌词委托 cenguigui。与 P-12 是同作者迭代。

**可借鉴点**：与 P-12 端点重复，无新增。

---

### P-14 · `yibai酷我流式 v1.js`

| 项 | 值 |
|----|----|
| 文件名 | `yibai酷我流式 v1.js` |
| platform | `yibai酷我流式` |
| version | `1` |
| author | `竹佀` |
| 打包 | 纯 `module.exports` |

**API 端点**
- **getMediaSource**：`https://kwdec.942240.xyz/...`（流式端点）

**getMediaSource 范式**：流式，支持 **7 级音质**（etc/ 里最多）：
`128k → 320k → flac → hires → atmos → atmos_plus → master`

**认证 / 密钥**：无。

**音质映射**：`low→128k, standard→320k, high→flac, super→hires`（另支持 atmos/atmos_plus/master 三档超高端音质）

**架构特点**：唯一支持杜比全景声和母带音质的酷我源。

**可借鉴点**：`kwdec.942240.xyz` 端点对 musicdl 是**全新源**，且支持 atmos/master，值得作为酷我高音质主源之一（⚠️ 实测 2026-08-07：**DNS 解析失败，域名已不可达**，此源当前无法使用）。

---

### P-15 · `元力KW v1.2.0.js`（长青SVIP音源，付费中转）

> **文件变更说明（2026-08-07）**：本文件由 v1.1.0 升级为 **v1.2.0**（`etc/musicfree/` 现为 v1.2.0；v0.1.0 备份于 `musicfree-new/元力音源(科技长青)/旧版/0.1.0/`）。v1.1.0 全树已不存在。v1.1.0 为全混淆不可读，v1.2.0 已用沙箱解出真实端点（下）。

| 项 | 值 |
|----|----|
| 文件名 | `元力KW v1.2.0.js` |
| @name | **长青SVIP音源**（`@version 1.0.0`，platform version 1.2.0） |
| author | `微信公众号:元力菌` |
| srcUrl | `https://13413.kstore.vip/yuanli/kw.js` |
| 打包 | 混淆（`_0x4a03` 自定义 base64 + `_0x2637` base64+RC4），module.exports |
| 依赖 | axios + he |
| 鉴权 | **无任何凭证/密钥/userVariables**（`Cookie:'uin='` 占位，`g_tk=5381` 固定） |

**API 端点**
- 搜索/专辑/歌手/榜单/歌单：走酷我官方公开匿名端点（`search.kuwo.cn/r.s`、`m.kuwo.cn` 等），带 `Cookie:'uin='` + `g_tk=5381`
- 歌词：酷我歌词接口（部分歌曲返回空/异常）
- **getMediaSource**：`https://music.haitangw.cc/music1/kw.php?id={rid}&level={...}`（元力菌**私有中转服务器**，§4.1 表 #20，无鉴权、实测可用）

**💡 关键架构（实测中覆盖的 r2.0 与前版结论相反）**：`getMediaSource` **并不直连官方端点**，而是走**元力菌私有中转服务器**（付费 SVIP 服务）——插件客户端干净无凭证，凭证与解析都在元力私有后端。详见 `docs/YUANLI-V1.2.0-PLUGIN-API.md`。

**getMediaSource 细节**：`level` 映射 `low/standard→exhigh(320k)`、`high/super→lossless(flac)`；响应 `{code:200,msg:'解析成功',data:{url}}`。

**音质标准**：元力 系标准仅 `exhigh(320k) / lossless(FLAC)`，**无母带/Hi-Res**（hires/master/atmos 等参数经中转实测全部塌缩回 320k，2026-08-07 三首样本验证）。母带级需走 musicdl 内置 `kwdec.liuyunidc.cn`（§4.9.2，`kuwo.py` 已解锁 master 档）。

**已知插件缺陷**：KW 歌词接口在部分歌曲返回空/报异常（歌词接口对传入对象字段依赖强）。

**可借鉴点**：元力私有中转是"瘦客户端 + 服务端凭证"架构又一实例（青听同款，读 4.8.6）；该中转端点**无鉴权可用**，可作 musicdl 低优先级兜底源（⚠️ 付费私有、非公开、随时失效，勿作主源）。

---

## 3. 聚合与歌词插件（P-16 ~ P-23）

### P-16 · `碳酸氢钠 v1.39.js`（聚合音源，混淆）

| 项 | 值 |
|----|----|
| 文件名 | `碳酸氢钠 v1.39.js` |
| platform | 多平台聚合 |
| version | `1.39` |
| 打包 | Parcel + 重度混淆（`xlxd.io` 风格字符串数组 + IIFE shuffle，`_0x2288`/`_0xd21e`，~5400 字符串表） |
| 依赖 | axios + cheerio + crypto-js |

**关键发现：聚合器不覆盖 QQ 或酷我**。其 `getMediaSource` 经 `$media$unified(item, quality)` 按 `item._source` 分派，仅含：`2t58`、`zz123`、`htqyy`、`bilibili`、`netease`。`kw`/`tx`/`酷我`/`QQ音乐` 字面量只出现在无关标识符里。Kugou 仅指 `5sing.kugou.com` 独立音乐人源。

**端点**（解码后）
- 2t58：`http://www.2t58.com/js/play.php`（POST，`id=...&type=music`，Referer `http://www.2t58.com/song/{id}.html`，返回 `data.mp3`）
- zz123：`https://zz123.com/ajax/`（`act=songinfo&id={id}&lang=`）
- htqyy：`http://www.htqyy.com/`（硬编码百度统计 cookie）
- netease：`https://music.163.com/api/cloudsearch/pc`、`/api/search/get`、`/song/media/outer/url?id=`、`/api/song/lyric?id=`
- bilibili：`https://api.bilibili.com/x/web-interface/search/type`、`/view`、`/player/playurl`
- 5sing.kugou：`http://5sing.kugou.com/fm/m/json/lrc`、`http://search.5sing.kugou.com/home/json`、`https://5sservice.kugou.com/song/getsongurl?appid=2918...`
- 通用回退后端：`https://music-api.gdstudio.org/api.php`、`http://music.nairocy.com`
- 自更新：`https://gitee.com/nainoz_naa/music/raw/master/carbonate.js`

**回退链**：`$media$fallback` 回退到 2t58 源。`$media$unified` 失败时调 fallback。UA 用 Chrome/106 与 Edge 变体。

**测速 / 健康检查**：无计时测速，纯 try/catch + fallback。

**可借鉴点**：对 QQ/酷我无价值（不在覆盖范围），但 `gdstudio`/`nairocy` 通用后端可探索是否支持 QQ/酷我。混淆设计可作为反例参考（不应在 musicdl 里用混淆）。

---

### P-17 · `gdstudio.js`

| 项 | 值 |
|----|----|
| 文件名 | `gdstudio.js` |
| 打包 | 纯 `module.exports` |

**API 端点**：`https://music-api.gdstudio.org/api.php`（通用聚合后端，支持多平台）。

**架构特点**：gdstudio 通用 API 客户端，是 P-16 碳酸氢钠回退后端之一。

**可借鉴点**：gdstudio 端点，需实测确认 QQ/酷我支持情况与音质。

---

### P-18 ~ P-21 · 歌词专项插件

| 编号 | 文件名 | platform | version | 端点 |
|------|--------|----------|---------|------|
| P-18 | `QQ歌词 v0.2.3.js` | QQ歌词 | 0.2.3 | `c.y.qq.com` base64 cgi + 多歌词源回退 |
| P-19 | `歌词千寻 v0.0.0.js` | 歌词千寻 | 0.0.0 | 歌词千寻 API（小文件 1.6KB） |
| P-20 | `歌词网 v0.0.0.js` | 歌词网 | 0.0.0 | 歌词网 API（小文件 1.5KB） |
| P-21 | `碳酸歌词 v0.1.7.js` | 碳酸歌词 | 0.1.7 | 多源聚合歌词 |

**架构特点**：均为纯歌词插件，只实现 `getLyric`，不提供 search/getMediaSource。独立于音源插件，可单独加载。

**可借鉴点**：歌词多源回退设计可补充到 musicdl 的 `LyricSearchClient`（现支持 lrclib/musixmatch）。`yunzhiapi.cn/API/jhlrcgc.php?msg={qq|kw}`（P-02/P-09 用的歌词源）是跨 QQ+酷我的统一歌词端点，值得加入。

---

### P-22 · `yibai酷我流式 v1.js`（见 P-14，避免重复）

已作为 P-14 处理。

---

### P-23 · 其他（参考文件）

`etc/musicfree/` 下另有若干参考文件（如旧版酷狗、网易云备份等），非本次 QQ/酷我专题范围，从略。

---

## 4. 可提取到 musicdl 的端点 / 密钥总表

### 4.1 第三方解析端点（按对 musicdl 的新增价值排序）

| # | 端点 | 平台 | 来源插件 | 鉴权 | 音质参数 | musicdl 现状 | 实测(2026-08-07) |
|---|------|------|---------|------|---------|-------------|------------|
| 1 | `88.lxmusic.xn--fiqs8s/lxmusicv4/url/tx/{mid}/{q}` | QQ | P-02 | 签名(SCRIPT_MD5+SECRET_KEY) | `128k/320k/flac/flac24bit` | **新增**（musicdl 的 `_parsewithlxmusicapi` 是另一套，非签名版） | 🟡 **128k ✅ / 320k、flac ❌**（5 首热门曲全返回 `code 2 Object trans failure: 140017`，疑似服务端高音质受限，key 本身有效） |
| 2 | `88.lxmusic.xn--fiqs8s/lxmusicv4/url/kw/{id}/{q}` | 酷我 | P-09 | 同上 | 同上 | **新增** | ✅ **128k/320k/flac 全通**，返回真实 CDN |
| 3 | `api.nki.pw/API/music_open_api.php?apikey=KEY&mid={mid}` | QQ | P-01/P-06 | apikey | 一次返回全音质 | ✅ 已有（`_parsewithnkiapi`） | ❌ **2026-08-07 复测：极不稳定**——约半数请求 25~45s **超时**；偶发成功也要 4~22s。且 `song_play_url_sq/pq/hq` **全空**，最高仅 `standard=C400 m4a`、`fq=C200`，**无无损**。建议降级或剔除 |
| 4 | `cyapi.top/API/qq_music.php?apikey=KEY&mid={mid}` | QQ | P-03 | apikey 硬编码 | 忽略音质 | ✅ 已有（`_parsewithcyapi`） | ✅ 可用（响应极快 ~106–200ms）。默认返 **C400 m4a（128k）**；`quality=320` → **M800 320k mp3**（11.2MB，ID3 验证）；`flac/lossless/sq` 参数**全部塌缩回 320k**，**无无损**。附带元信息+LRC 歌词。key 明文免费 |
| 5 | `api.ikunshare.com/url?source=tx&songId={mid}&quality=Q` | QQ | P-04 | header `X-Request-Key` | `128k/320k/flac/flac24bit` | **新增** | ❌ **DNS 解析失败**（域名不可达） |
| 6 | `musicapi.haitangw.net/music/{kw|wy|kg}.php` | 酷我/网易/酷狗 | 旧元力QQ v0.1.0（已删，见 P-05 变更说明） | 无 | `exhigh/lossless` | ✅ 已有（`_parsewithhaitangwapi`，kuwo/kugou/netease 均内置此域名） | ❌ **404**（路径推测错误或已下线） |
| 7 | `lxmusicapi.onrender.com/url/tx/{mid}/{128k|320k}` | QQ | P-04 | header `X-Request-Key: share-v2` | 仅 128k/320k | ✅ 已有（`_parsewithlxmusicapi`，非签名版） | ❌ **403 key 验证失败**（`share-v2` 失效） |
| 8 | `api.music.lerd.dpdns.org/mf/kw`（POST 303 协议） | 酷我 | P-08/P-11 | 无 | `128k/320k/flac/hires` | **新增** | ✅ 303 两步协议完整可用（第二步落回 `mobi.kuwo.cn`） |
| 9 | `kwdec.942240.xyz/...` | 酷我 | P-14 | 无 | `128k..master`(7级,含atmos) | **新增** | ❌ **DNS 解析失败**（域名不可达） |
| 10 | `nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid={id}&br=BR` | 酷我官方 | P-04 | 无 Cookie | `128kmp3/320kmp3/2000kflac/20000kflac` | **新增**（无 Cookie 官方端点） | ✅ **200 JSON 直返 `data.url` CDN**（128k/320k/2000kflac 全通；20000kflac 实际回落 bitrate=2000，与 2000kflac 相同） |
| 11 | `kw-api.cenguigui.cn?id={id}&type=song&level=LEVEL&format=json` | 酷我 | P-12/P-13 | 无 | `standard/exhigh/lossless/hires` | 已有（`_parsewithcggapi`） | ✅ 可用（响应 ~6s，偏慢） |
| 12 | `music.nxinxz.com/kw.php?id={id}&level=LEVEL&type=mp3` | 酷我 | P-10 | 无 | `standard/exhigh/lossless` | 已有（`_parsewithnxinxzapi`） | ✅ 302 重定向到真实 CDN |
| 13 | `music.haitangw.cc/music/qq_song_kw.php?level=L&type=json&id={mid}` | QQ+酷我 | P-04 | 无 | `standard/exhigh/lossless/hires` | 已有（`_parsewithhaitangwapi`） | ✅ 可用（换源成功） |
| 14 | `yunzhiapi.cn/API/jhlrcgc.php?id={id}&msg={qq|kw}` | 歌词 | P-02/P-09 | **需 token**（文档此前记"无"） | — | **新增**（歌词源） | 🟡 **端点可达但需注册 token**（`缺少token密钥`，文档 P-02/P-09 未体现此依赖） |
| 15 | `api.chksz.top/api/163_music?id={id}` | 网易云 | 非常刀/Hei Music/星海/西瓜聚合（Macrohard0001 仓库） | **无** | **FLAC 无损** | **新增** | ✅ **200 可用**，返回网易官方 CDN 直链（FLAC 61MB 实测可下），Referer 需 `https://cp.chksz.top/` |
| 16 | `music.3e0.cn?server={平台}&type=url&id={id}` | 多平台 | 忆音音源 v1（竹佀＆玥然OvO，Macrohard0001 仓库） | **无** | **320k MP3** | **新增** | ✅ **200 可用**，`type=url` 直返音频流、`type=song` 返 JSON，支持 tencent/netease/kuwo/kugou/migu |
| 17 | `oiapi.net/api/Music_163?id={id}` | 网易云 | 全豆要[聚合音源] v9.3（pdone 仓库，`SUYIN_163_API`） | **无** | **320k MP3** | **新增** | ✅ **200 可用**，返回网易 CDN（尝试 lossless 仍 320k，无法出无损） |
| 18 | `oiapi.net/api/Kuwo?msg={歌名}&n=1&br={码率}` | 酷我 | 全豆要[聚合音源] v9.3（pdone 仓库，`SUYIN_KUWO_API`） | **无** | **320k MP3** | **新增** | ✅ **200 可用**，按**歌名**（`msg`）搜索解析（非 id），`br=320k`（但 lossless 仍回落 128k/320k） |
| 19 | `175.27.166.236/kgqq1/qq.php?id={songmid}&type=json&level={exhigh|lossless}` | QQ | **元力QQ v1.2.0**（长青SVIP音源） | **无** | `exhigh→320k MP3 / lossless→FLAC` | **新增**（元力私有中转） | ✅ 2026-08-07 端到端实测可用，返回真实 kuwo CDN（M800=320k mp3、F000=flac）。⚠️ 元力菌付费 SVIP 私有后端，非公开稳定 |
| 20 | `music.haitangw.cc/music1/kw.php?id={rid}&level={exhigh|lossless}` | 酷我 | **元力KW v1.2.0**（长青SVIP音源） | **无** | `exhigh→320k / lossless→FLAC` | **新增**（元力私有中转） | ✅ 2026-08-07 端到端实测返回真实 CDN（低音档 `exhigh`=320k mp3，高音档 `lossless`=FLAC `F000`）。⚠️ 元力私有后端，可能失效 |
| 21 | `api.qijieya.cn/meting/?server=netease&type=url&id={id}&br={码率}` | 网易云（meting 兼容） | 祈杰 | 无 key | `br`(默认320，可用 **999000=FLAC 无损**) | **新增**（musicdl 无此端点） | 🟡 **仅网易云有价值**：搜索+取流 0.3–2s 可用，VIP 歌可解析（回落 MP3）；`br=999000` 对**普通歌**返回**真 FLAC**（`fLaC` 魔数 + STREAMINFO 44.1kHz/16bit，35MB 实测），**VIP 歌无损被禁**（回落 MP3）。**QQ(tencent)/kuwo 取流空响应不可用** |

**对照结论**：经 2026-08-07 源码分析（`scripts/analyze_musicdl.py`）验证，musicdl 已内置的端点包括 **#3 nki、#4 cyapi、#6 haitangw.net、#7 lxmusicapi、#11 cenguigui、#12 nxinxz、#13 haitangw.cc**。**真正对 musicdl 为新增的**是 #1（lx 签名版 QQ，musicdl 已有非签名版）、#2（lx 签名版酷我，同套密钥）、#5（ikunshare，域名已挂）、#8（lerd 303 协议）、#9（kwdec，域名已挂）、#10（nmobi 无 Cookie 官方端点）、#14（yunzhiapi 歌词）、**#15（chksz 网易云 FLAC 无损）、#16（3e0 多平台聚合）、#17（oiapi 网易云 320k）、#18（oiapi 酷我 320k）**。其中 #10 nmobi 是唯一新增且实测可用的官方程音源，价值最高；#15 chksz 是本次全网音源插件挖掘中**唯一新增的免费无损 FLAC 网易云端点**（来自 Macrohard0001/lx-ikun-music-sources 仓库，非常刀/Hei Music 等多插件共用）。

> **与 `MUSICFREE-API-PLAN.md` 第 6 章的交叉核对**：上表"musicdl 现状"列指 musicdl **代码库**是否已覆盖，不代表 PLAN 文档未记录。经核对，#10（`nmobi.kuwo.cn/mobi.s`）PLAN 已在 6.2.5 节专文记录（含参数表与"新增价值极高"判定），#9（kwdec 七级音质）PLAN 6.2.3 已完整列出 `128k→320k→flac→hires→atmos→atmos_plus→master` 七档——这两条对 musicdl 代码是新增，但对 PLAN 文档不是新发现。**相对 PLAN 第 6 章的真增量**为：#14（yunzhiapi 跨平台歌词，PLAN 歌词章节全无）、4.2 中兜底 token 的具体值 `Q_H_L_5FBMRs-...`（PLAN 6.3 仅列字段名未列值）、第 5 章的 A/B/C 范式分类（PLAN 按插件平铺未做此抽象）、P-04 的 `type==1`/`pay.payplay` 字段级 VIP 门控（PLAN 7.3 走的是 VipQueryServer API 路线）、P-04 的"QQ 全挂→酷我重搜同名曲"跨平台兜底（PLAN 2.4.1 的 l1–l4 仅同平台内回退）、以及 P-07 弥音 128k 兜底源（PLAN 6.1.1 插件清单漏列）。lx-music"一套密钥双平台"的**合并实现结论**（实现单个 `_parsewithlxmusicsignedapi` 即可同时服务 QQ+酷我）PLAN 未点明，仅分别提到"同套签名"。
>
> ⚠️ 本节所有端点与 4.2 密钥均为 2026-08-06 抓取时点快照，lx 签名密钥（`SCRIPT_MD5`/`SECRET_KEY`）尤其易失效（见 P-02 第 99 行"403 = key 失效"），集成前必须实测验证。

> **实测结论（2026-08-07，样本 QQ `0019tNGN1TJbLT` / 酷我 `392634142`）**：14 个端点中 **7 个可用**（#2 lx-kw 全音质、#4 cyapi、#8 lerd 303、#10 nmobi、#12 nxinxz、#13 haitangw.cc，及 #3 nki **当时**可用），**4 个不可用**（#5 ikunshare DNS 挂、#6 haitangw.net 404、#7 lxmusicapi 403、#9 kwdec DNS 挂），#1 lx-tx **128k 可用但 320k/flac 全部 code 2**（疑似服务端高音质受限），#14 yunzhiapi **需注册 token**（文档此前记"无"鉴权，与实测不符）。最值得新增的 #10 nmobi 与 #2 lx-kw 实测全通，可信度高；#14 yunzhiapi 若集成需先补 token 依赖说明。
>
> **站点复测（2026-08-07，cyapi/nki/qijieya 三站专项）**：**#3 nki 已降级为不可用**——约半数请求 25~45s 超时，成功时 `sq/pq/hq` 字段全空、最高仅 C400 m4a，**无无损**，建议 musicdl 收窄超时并降级；**#4 cyapi 确认可用**——响应 ~106–200ms 极快，默认 C400 m4a（128k），`quality=320`→M800 320k mp3（11.2MB，ID3 验证），无损参数全塌缩回 320k，仅 320k 价值；**#21 qijieya（新增）**——meting 兼容、无 key，QQ(tencent)/kuwo 取流**空响应不可用**，仅**网易云**有价值（VIP 歌可解析回落 MP3；`br=999000` 对普通歌出**真 FLAC** 35MB）。

#### 4.1.1 新增免费可用端点（2026-08-07 全网音源插件挖掘）

> 从 `pdone/lx-music-source`、`Macrohard0001/lx-ikun-music-sources`、`guoyue2010/lxmusic-` 三个仓库及 tmxk 页面下载 75 个音源插件，去重后实测发现的**免费无 key 可用端点**。已并入上方 §4.1 主表 **#15–#18**，此处为来源与参数速查：

| 端点 | 平台 | 音质 | 参数 | 密钥 | 来源插件 |
|------|------|------|------|------|---------|
| `https://api.chksz.top/api/163_music?id={id}` | 网易云 | **FLAC 无损 61MB** | id | **无** | 非常刀 v5 / Hei Music源 / 星海音乐源 / 西瓜聚合（Macrohard0001 仓库） |
| `https://music.3e0.cn?server={平台}&type=url&id={id}` | tencent/netease/kuwo/kugou/migu | 320k MP3 | server+type+id | **无** | 忆音音源 v1（竹佀＆玥然OvO，Macrohard0001 仓库） |
| `https://oiapi.net/api/Music_163?id={id}` | 网易云 | 320k MP3 | id | **无** | 全豆要[聚合音源] v9.3（pdone 仓库） |
| `https://oiapi.net/api/Kuwo?msg={歌名}&n=1&br={码率}` | 酷我 | 320k MP3 | msg+n+br | **无** | 全豆要[聚合音源] v9.3（pdone 仓库） |

**要点**：
- `api.chksz.top/api/163_music`——CHKSZ 网易云解析 API，被**非常刀 v5 / Hei Music源 / 星海音乐源 / 西瓜聚合**等多插件共用，Referer 需 `https://cp.chksz.top/`，返回网易云官方 CDN 直链（FLAC 61MB 实测可下）
- `music.3e0.cn`——3e0 音乐聚合代理（类 meting），`type=url` 直接返回音频流、`type=song` 返回 JSON
- `oiapi.net/api/Music_163` 与 `oiapi.net/api/Kuwo`——OIAPI 聚合，均只能出 320k MP3（无法出无损）；Kuwo 需按**歌名**（`msg`）而非 id 解析

**对 musicdl 的价值**：`api.chksz.top/api/163_music` 是本次挖掘**唯一新增的免费无损 FLAC 网易云端点**（直接吃 id，契合 `resolve_url(id)` 快路径）；`music.3e0.cn` 可作通用多平台回退源。oiapi 两个端点仅 320k，且 Kuwo 按歌名需重搜索，价值有限。

### 4.2 密钥清单

| 来源 | 域名 | 密钥类型 | 值 | 用途 |
|------|------|---------|-----|------|
| P-01/P-06 | `api.nki.pw` | apikey | `ed34917b6e3ca97d609a82e73c82599c176a07a4bcad5f5f7ab4ee95b3fa90ba` | QQ 音源 |
| P-03 | `cyapi.top` | apikey | `1ffdf5733f5d538760e63d7e46ba17438d9f7b9dfc18c51be1109386fd74c3a1` | QQ 音源 |
| P-02/P-09 | `88.lxmusic.xn--fiqs8s` | SCRIPT_MD5 | `1888f9865338afe6d5534b35171c61a4` | QQ+酷我 签名 |
| P-02/P-09 | `88.lxmusic.xn--fiqs8s` | SECRET_KEY | `JaJ?a7Nwk_Fgj?2o:znAkst` | QQ+酷我 签名 |
| P-04 | `api.ikunshare.com` | X-Request-Key | 用户自定义 `ikun_key` | QQ 回退 |
| P-04 | `lxmusicapi.onrender.com` | X-Request-Key | `share-v2` | QQ 回退 |

| 腾讯音乐 v2025.09.13.js | `u6.y.qq.com` | QQ 兜底 token | `Q_H_L_5FBMRs-uicpIQo8Ymt3v0w1f0DAyJwQMdLJPVKmmOQZRQZkuz8AfB1Q` | 未登录兜底 qm_keyst（uin 948168827） |
### 4.3 Cookie 字段清单

| 平台 | 字段 | 说明 | 来源插件 |
|------|------|------|---------|
| QQ | `uin` | QQ 号（数字） | P-04 |
| QQ | `qm_keyst` | 完整 Cookie 串，含 `W_X` 或 `Q_H_L` 前缀视为登录态 | P-04 |
| QQ | `authst` | 认证令牌（comm 块） | P-04 |
| QQ | `g_tk` | 从 `uin` 计算得出 | P-04 |
| QQ | 兜底 token | `Q_H_L_5FBMRs-uicpIQo8Ymt3v0w1f0DAyJwQMdLJPVKmmOQZRQZkuz8AfB1Q`（uin 948168827） | P-04 ⚠️ 实测已失效（见 §4.4） |
| 酷我 | `kw_token` | 硬编码 `123456`（仅歌词请求） | P-12 🟡 实测歌词接口匿名即可用，此值非必需 |

### 4.4 官方端点与官方凭证实测

> 2026-08-07 基于 `tools/analyze.js` 提取的官方域端点（qq.com / kuwo.cn 系）实测。**官方端点**指平台自身域名下的接口，区别于 §4.1 的第三方解析端点。

#### 4.4.1 QQ 音乐官方端点

| 端点 | 用途 | 凭证 | 实测(2026-08-07) |
|------|------|------|------------------|
| `u6.y.qq.com/cgi-bin/musicu.fcg`（module `vkey.GetVkeyServer`/`CgiGetVkey`） | **音源解析** | 需 `qm_keyst` + `uin`（musicdl `Credential.fromcookiesdict` 读取 `musicid`+`musickey`，无硬编码兜底） | ❌ **匿名/兜底 token 均拿不到 purl**（code=0 但 purl 空） |
| `u.y.qq.com/cgi-bin/musicu.fcg` | 搜索/歌单/排行 | 匿名 | ✅ 可用 |
| `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg` | 歌词 | 匿名（`g_tk=5381`） | 🟡 返回 `retcode:-1310`（疑似需 Cookie 或风控，非 g_tk 问题） |
| `c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_*.fcg` | 歌单标签 | 匿名 | ✅ 可用 |
| `i.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg` | 歌单详情 | 匿名 | ✅ 可用 |
| `y.gtimg.cn/music/photo_new/T002R{size}x{size}M000{album_mid}.jpg` | 封面 | 匿名 | ✅ 可用 |

#### 4.4.2 酷我音乐官方端点

| 端点 | 用途 | 凭证 | 实测(2026-08-07) |
|------|------|------|------------------|
| **`nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid={id}&br={br}`** | **音源解析（明文版，P-04）** | **无 Cookie** | ✅ **完全匿名可用**，FLAC 无损直返 CDN（`2000kflac` 可用；`20000kflac` 回落 `bitrate=2000`） |
| `mobi.kuwo.cn/mobi.s?f=kuwo&type=convert_url2`（musicdl 内置） | **音源解析（加密版）** | 硬编码密钥 `SECRET_KEY_SONG = b"ylzsxkwm"`，`user=0` 匿名 | ✅ 匿名可用，响应纯文本正则提取 URL，音质通过 `ENC_MUSIC_QUALITIES` 映射（128k/320k/2000kflac/4000kflac） |
| `kuwo.cn/openapi/v1/www/lyric/getlyric?musicId={id}` | 歌词 | 匿名 | ✅ 可用（48 行歌词完整返回） |
| `m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={id}` | 歌词+歌曲信息 | 匿名 | ✅ 可用 |
| `search.kuwo.cn/r.s` | 搜索 | 匿名 | ✅ 可用 |
| `wapi.kuwo.cn/api/pc/bang/list` | 排行榜 | 匿名（固定 appUid） | ✅ 可用 |
| `kbangserver.kuwo.cn/ksong.s` | 排行榜详情 | 匿名 | ✅ 可用 |
| `nplserver.kuwo.cn/pl.svc` | 歌单 | 匿名 | ✅ 可用 |
| `mobileinterfaces.kuwo.cn/er.s` | 推荐数据 | 匿名 | ✅ 可用 |
| `img4.kuwo.cn/star/albumcover/1080{path}` | 封面 | 匿名 | ✅ 可用 |

#### 4.4.3 官方凭证可用性结论

| 凭证 | 来源 | 实测状态 | 说明 |
|------|------|---------|------|
| QQ 兜底 token `Q_H_L_5FBMRs-...` / uin `948168827` | P-04 硬编码 | ❌ **已失效** | GetVkey 带此 token 返回 code=0 但 purl 为空（匿名 uin=0 同样为空）。这也解释了 P-04 为何把官方 Vkey 只当第一层、失败即走第三方回退链 |
| QQ 真实登录 Cookie（`qm_keyst` + `uin`） | 用户自行配置 | ⚠️ 需实测 | musicdl 的 `Credential.fromcookiesdict()` 读取 `musicid`+`musickey`，无 cookie 时 `comm` 块不注入 `authst`，官方 Vkey 返回空 purl |
| 酷我 `SECRET_KEY_SONG` | musicdl `kuwoutils.py:38` 硬编码 | ✅ 匿名可用 | `b"ylzsxkwm"` 8 字节，用于 `encryptquery()` 自定义块加密（TEA 类+S-box），`user=0` 完全匿名，防爬非用户认证 |
| 酷我 `SECRET_KEY_LYRIC` | musicdl `kuwoutils.py:38` 硬编码 | ✅ 匿名可用 | `b'yeelion'`，用于歌词解密（`xorencrypt`） |
| 酷我 `kw_token=123456` | P-12 硬编码 | 🟡 非必需 | 仅 P-12 歌词请求附带；实测酷我歌词端点匿名即可用 |
| 酷我官方歌词（无凭证） | — | ✅ 完全匿名 | openapi 与 m.kuwo.cn 双通道均可用 |

**mobi.kuwo.cn 双版本对比**：musicdl 内置的 `f=kuwo` + `convert_url2` 与 P-04 的 `f=web` + `convert_url_with_sign` 是同一酷我后端的两个接口。前者查询参数用 `SECRET_KEY_SONG` 加密（`user=0` 匿名），后者完全明文。两者都无需 Cookie，返回格式不同（纯文本 vs JSON）。musicdl 集成时可直接复用 `SECRET_KEY_SONG` 实现加密版，或直接走 nmobi 明文版更简单。

**核心结论**：
1. **唯一实测可用的官方音源端点是酷我 `nmobi.kuwo.cn/mobi.s`**——完全匿名、返回 FLAC 无损、无需任何 Cookie/密钥，是 musicdl 集成价值最高的一条（与 §4.1 #10 判定一致）。
2. **QQ 官方音源（GetVkey）无可用官方匿名凭证**：musicdl 和 P-04 的硬编码兜底 token 均无有效 purl，必须用户配置真实 `qm_keyst` + `uin` 登录态。
3. **官方歌词端点酷我侧完全匿名可用**（双通道），QQ 侧歌词接口返回 -1310 需进一步排查（可能需 Cookie）。
4. **musicdl 已内置冷酷我官方音源**（`mobi.kuwo.cn?f=kuwo` 加密版，密钥 `SECRET_KEY_SONG=b"ylzsxkwm"`，匿名可用），可直接复用；但 musicdl 只映射到 4000kflac，而 nmobi 明文版支持到 20000kflac（回落 2000）。

### 4.5 musicdl 源码端点与密钥全景

> 2026-08-07 用 `scripts/analyze_musicdl.py` 扫描 `musicdl/modules/sources/` 全部 28 个源得到。**这是 musicdl 自身代码的端点/密钥/第三方解析方法清单**，与 §4.1 的 etc/ 插件端点互为对照。

#### 4.5.1 第三方解析方法数（按源）

| 源 | `_parsewith*` 方法数 | 说明 |
|----|---------------------|------|
| netease.py | 31 | 网易云，第三方 API 最多 |
| qq.py | 15 | QQ 音乐 |
| kuwo.py | 12 | 酷我 |
| kugou.py | 10 | 酷狗 |
| youtube.py | 10 | YouTube |
| spotify.py | 10 | Spotify |
| deezer.py | 9 | Deezer |
| qobuz.py | 9 | Qobuz |
| 其余各源 | 1–4 | 多数仅官方 API |

#### 4.5.2 QQ 音乐已内置第三方解析端点（qq.py，15 个方法）

> **调用链**：`_search`/`parseplaylist` → `_parsewiththirdpartapis`（**仅当无 Cookie 时启用**，有 Cookie 直接走官方）→ 按 l1→l4 分层逐方法尝试 → 成功则 `_parsewithofficialapiv1` 补音质/歌词。

| 端点域名 | 方法 | 分层 | 音质参数 / 鉴权 | 无损实测(2026-08-07) |
|---------|------|------|----------------|---------------------|
| `api.vkeys.cn/music/tencent/song/link` | `_parsewithvkeysapi` | l1 SVIP | **无 key（免费）**；音质=**数字 ID** `14=AI00 母带 / 13=臻品全景声 / 12=杜比 / 11=Hi-Res / 10=FLAC(SQ) / 9=320k ogg / 8=320k mp3`，按 `[14,13,12,11,10,9]` 降级；歌词 `api.vkeys.cn/v2/music/tencent/lyric?mid=` | ✅ **q=14 `AI00` 臻品母带 187-210MB（晴天 209.5MB / 稻香 187MB 实测可下）**；q=10 `F000` FLAC 44-58MB；q=8 `M800` 320k mp3；无母带档的歌 q=14 返回 code 110000 后降级 |
| `api.xingmian.bbroot.com/API/qqmusicparse.php` | `_parsewithxingmianapi` | l1 SVIP | `apikey`（1 个）；`quality`=超清母带/Hi-Res/无损/高音质/低音质 | ❌ 403 apikey 失效 |
| `api.xcvts.cn/api/music/qq` | `_parsewithxcvtsapi` | l1 SVIP | `apiKey`（3 个）；`type`=臻品母带/臻品全景声/臻品2.0/SQ无损（只试前 4） | ❌ code=-6 |
| `api.317ak.com/api/yinyue/qqyinyue` | `_parsewith317akapi` | l1 SVIP | `ckey`（1 个）；`br`=7,9,10,8,6,5 + `type=json&lrc=1` | ❌ `member_or_permission_denied` |
| `apii.xianyuw.cn/api/v1/qq-music-search` | `_parsewithxianyuwapi` | l2 VIP | `key`（2 个，`sk-` 前缀）；`br=hires`；仅无 Cookie 时可用 | ✅ **`br=hires` 返回 `F000` FLAC 58.7MB fLaC 可下**（体积与 vkeys q=10 一致，疑似同源/代理） |
| `api.nki.pw/API/music_open_api.php` | `_parsewithnkiapi` | l2 VIP | `apikey`（2 个）；一次返回 `song_play_url_sq/pq/accom/hq/standard/fq` 全音质 | ❌ **2026-08-07 复测：极不稳定**（约半数请求 25~45s 超时）；成功时 `sq/pq/hq` 全空、最高仅 C400 m4a，**无无损**。建议降级或剔除 |
| `api.hk0.cc/api/qqmusic` | `_parsewithhk0ccapi` | l2 VIP | 无 key；字段同 nki | ❌ 非 JSON 响应 |
| `tang.api.s01s.cn/music_open_api.php` | `_parsewithtangapi` | l2 VIP | 无 key；字段同 nki | ❌ 非 JSON 响应 |
| `cyapi.top/API/qq_music.php` | `_parsewithcyapi` | l3 | `apikey`（2 个**明文**）；`quality=lossless`（固定） | ⚠️ 名义 lossless 实返 **M800 320k MP3**（11.2MB，体积=320k），非无损 |
| `api.xunhuisi.store/API/QQMusic/Song.php` | `_parsewithxunhuisiapi` | l3 | 无 key；`type=json` | ⚠️ m4a（6.7MB） |
| `lxmusicapi.onrender.com/url/tx/{mid}/{q}` | `_parsewithlxmusicapi` | l3 | header `X-Request-Key: share-v3`；音质=`flac24bit/hires/flac/320k` | ⚠️ flac 档降级 **MP3 4.4MB**（非无损） |
| `yutangxiaowu.cn:3015/api/parseqmusic` | `_parsewithyutangxiaowuapi` | l3 | 无 key；`songmid` | ❌ 连接超时 |
| `lpz.chatc.vip/apiqq.php` | `_parsewithlpzapi` | l4 | 无 key；`br=1`；不稳定 | ❌ 非 JSON 响应 |
| 官方 `u.y.qq.com/musicu.fcg`（GetVkey） / `musics.fcg`（GetEVkey） | `_parsewithofficialapiv1` | 官方 | **需 Cookie**（`musicid`+`musickey`），按 `SongFileType`/`EncryptedSongFileType` 排序音质 | ⚠️ **匿名仅 128k**（M500）；320k/FLAC/母带需真实 VIP Cookie |

**无损能力结论（2026-08-07 全端点实测）**：15 个方法中当前能出真无损的第三方端点：**vkeys（免费，q=14 母带 187-210MB 优先 / q=10 FLAC 44-58MB）**、**xianyuw（`sk-` key，`br=hires`→F000 FLAC）**、TuneHubMusicClient（独立于 QQMusicClient，`api.yexin.de5.net`，`quality=flac`，需 `X-API-Key`）。官方 GetVkey 需用户自配 VIP Cookie。其余端点（xcvts/xingmian/317ak 失效；cyapi/lxmusic/xunhuisi 降级非无损；nki/hk0cc/tang/yutangxiaowu/lpz 超时或异常）。**vkeys 是唯一同时支持 AI00 母带（>100MB）与 F000 FLAC 的通道**，musicdl 按 `[14,...,9]` 母带优先。

**第三方密钥（qq.py，共 11 个，base64/`charlespikachu` 前缀混淆 → 明文）**：

| 端点 | 混淆值（前缀已省） | 明文 |
|------|-------------------|------|
| xingmian | `YjJmMjU1ODA2MmJm...NDQwZWQzZTNkMjU5ZA==` | `b2f2558062bf82347065268086f0c090fb30a8916b2227103ed140ed3e3d259d` |
| xcvts ×3 | `Nzg5OTMzNDRiOWJm...YmEzZDI=` 等 | `78993344b9bf1105655599009cdba3d2` / `ce778eb0d1858edfb4b2071a115f1edf` / `74a67af37f528882616dd35597ea740d` |
| 317ak | `Wk83NlFKQ0lINVBQSUNKT09YVUg=` | `ZO76QJCIH5PPICJOOXUH` |
| xianyuw ×2 | `c2stNTc2ZmFkZTQx...ZDkzNzM=` 等 | `sk-576fade416263b7ff726af354d9d9373` / `sk-018b9f8d80dc1898a2927e8020663d86` |
| nki ×2 | `MjhmZWNlOTI1NDM5...ZDMxZWY4` 等 | `28fece925439b052792a97989c870ced3803a71c6b534f71e5a53338b2d31ef8` / `c4c4f5fc36bad4cacb98839e14fea40277b35ea2eb1babdad7bbde128400f3b1` |
| cyapi ×2（明文） | — | `1ffdf5733f5d538760e63d7e46ba17438d9f7b9dfc18c51be1109386fd74c3a1` / `2baf39266d8ef0580aba937245d5bb569fe376f230ff508f1faa0922dc320fe4` |
| lxmusic | header `X-Request-Key: share-v3`（明文） | `share-v3`（UA `lx-music-request/2.6.0`） |

**Cookie/凭证（qqutils.py `Credential.fromcookiesdict`）**：`musicid`←`musicid|uin`、`musickey`←`musickey|qqmusic_key`、`openid`←`openid|psrf_qqopenid|wxopenid`、`access_token`←`access_token|psrf_qqaccess_token|wxaccess_token`、`refresh_token`←`refresh_token|psrf_qqrefresh_token|wxrefresh_token`、`unionid`←`unionid|psrf_qqunionid|wxunionid`。**当 `musicid`+`musickey` 均存在时**，官方请求 `comm` 块注入 `{qq: musicid, authst: musickey, tmeLoginType: login_type}`（`login_type=1` 若 musickey 以 `W_X` 开头，否则 2）。歌词请求固定 `g_tk=5381&loginUin=0`。musicdl 无硬编码 QQ 兜底 token（§4.4.3：P-04 的 `Q_H_L_...` 已失效）。

#### 4.5.3 酷我已内置第三方解析端点（kuwo.py，12 个方法）

| 端点域名 | 方法 | 说明 |
|---------|------|------|
| `kw.006lp.ccwu.cc:7119/api/song` | `_parsewithccwuapi` | `level=jymaster`（极云母带），❌ 2026-08-07 实测 407 区域版权限制 |
| `api.liuyunidc.cn` / `kwdec.liuyunidc.cn/kwurl` | `_parsewithliuyunidcapi` | ✅ **master/atmos_plus/atmos/flac/320k 五档全通（RC4 `b"yeelion666"`，2026-08-07 实测母带 151-200MB）**；⚠️ 代码 `MUSIC_QUALITIES[3:]` 跳过了 master/atmos |
| `kw-api.cenguigui.cn` | `_parsewithcggapi` | ✅ 与 etc #11 一致 |
| `lxmusicapi.onrender.com/url/kw/` | `_parsewithlxmusicapi` | |
| `music.nxinxz.com/kw.php` | `_parsewithnxinxzapi` | ✅ 与 etc #12 一致 |
| `musicapi.haitangw.net/music/kw.php` | `_parsewithhaitangwapi` | ✅ 与 etc #6 一致 |
| `api.nobb.cc/kuwo.music/index.php` | `_parsewithnobbapi` | |
| `music-api.gdstudio.xyz` | `_parsewithgdstudioapi` | 已禁用 |
| `www.guyuei.com/music/kw.php` | `_parsewithguyueiapi` | 已禁用 |
| `apione.apibyte.cn/kwmusic` | （REQUEST_KEYS） | |
| 官方 `mobi.kuwo.cn/mobi.s?f=kuwo`（加密） | `_parsewithofficialapiv1` | ✅ 匿名（`user=0`）`format=flac` 直出无损，**无需 Cookie**（§4.9.2） |

#### 4.5.4 密钥来源（REQUEST_KEYS / 硬编码）

musicdl 的第三方 API 密钥采用 `decrypt_func(random.choice(REQUEST_KEYS))` 模式，密钥常驻 `qqutils.py` / `kuwoutils.py` 等 utils 模块（base64 编码）。**与 etc/ 的硬编码单一 apikey 不同**，musicdl 用多密钥轮换 + 解密，抗风控性更强。各源硬编码密钥情况：
- **deezer.py**：15 个 base64 密钥（`charlesponse...` 版权混淆串）
- **qq.py**：11 个密钥（§4.5.2 已列明文；xingmian×1、xcvts×3、317ak×1、xianyuw×2、nki×2、cyapi×2）
- **kugou.py / qobuz.py / netease.py**：多个 base64 密钥
- **soundcloud.py**：3 个（含 OAuth client id）

**QQ 官方加密/签名密钥（qqutils.py，不参与第三方，用于官方端点）**：

| 密钥 | 值 | 用途 |
|------|-----|------|
| `SECRET` | `ZdJqM15EeO2zWc08` | qimei 请求 sign：`md5(key, params, time_ms, nonce, SECRET, extra)` |
| `APP_KEY` | `0AND0HD6FE4HY80F` | qimei payload 的 `appKey` 字段 + `extra={"appKey": APP_KEY}` |
| `PUBLIC_KEY` | RSA 公钥（PEM，qqutils.py:32） | PKCS1v15 加密 qimei 会话密钥 `crypt_key` |
| qimei appid 附加密钥 | `qimei_qq_androidpzAuCmaFAaFaHrdakPjLIEqKrGnSOOvH` | header `sign = md5("qimei_qq_android"+密钥+ts)` |
| `sign()` 签名算法 | `sha1(JSON) → PART_1_INDEXES=[23,14,6,36,16,40,7,19] / PART_2_INDEXES=[16,1,32,12,19,27,8,5] / SCRAMBLE_VALUES(20 字节 XOR) → base64 去 `/+=` → "zzc{part1}{b64}{part2}" 小写` | 加密端点 `musics.fcg` 的 `sign` 参数（`GetEVkey`） |
| `COMMON_DEFAULTS` | `ct=11, tmeAppID=qqmusic, format=json, uid=3931641530` | 官方请求 `comm` 固定字段 |
| 设备指纹 | `Device`：MI 6（sagit/iarium），Android 10，`version=13.2.5.8`/`version_code=13020508`，`channelId=10003505`，`packageId=com.tencent.qqmusic` | qimei 上报用 |
| qimei 兜底 | `q36=6c9d3cd110abca9b16311cee10001e717614`（获取失败时固定值） | 匿名请求 |

> ⚠️ 第三方密钥均为 base64/混淆存储，§4.5.2 已按本次需求解密列出明文（便于集成验证）；如对外发布文档建议回填为混淆值。

### 4.6 lx/ 目录音源插件分析（洛雪源）

> 2026-08-07 分析 `etc/lx/` 目录 34 个 JS 文件（洛雪格式音源）。洛雪源多为 `\x` 十六进制混淆，URL 运行时拼接，静态提取受限，需结合沙箱执行捕获。

#### 4.6.1 解析/歌词端点（去重后 10 个）

| 端点 | 平台 | 来源插件 | 鉴权/密钥 | 音质 | 实测(2026-08-07) | musicdl 现状 |
|------|------|---------|----------|------|------------------|-------------|
| `nmobi.kuwo.cn/mobi.s?f=web&...convert_url_with_sign` | 酷我 | monster/無名（etc/lx） | 无 Cookie | `128kmp3/320kmp3/2000kflac` | ✅ 200 可用 | ❌ 无（与 §4.1 #10 同端点） |
| `gateway.kugou.com/v5/url?` | 酷狗 | monster/無名（etc/lx） | 需 Cookie+设备注册 | `viper_tape/viper_clear/viper_atmos/flac/high/320/128` | ❌ 502（需设备注册流程） | ❌ 无 |
| `interface.music.163.com/eapi/song/enhance/player/url/v1` | 网易 | monster/無名（etc/lx） | AES 加密 `e82ckenh8dichen8` | `128k/320k/flac` | 🟡 200 但需 eapi 加密参数 | ❌ 无（eapi 需加密） |
| `app.c.nf.migu.cn/MIGUM2.0/strategy/listen-url/v2.4` | 咪咕 | monster/無名（etc/lx） | 需 channel token | `SQ/ZQ/ZQ24/ZQ32` | ✅ 200 可达 | ✅ 已有（migu.py v3.0） |
| `www.kuwo.cn/api/v1/www/music/playUrl?mid=&type=music&br=` | 酷我 | 小熊猫（etc/lx） | 需动态 `Secret` token（`Hm_Iuvt_...`） | `128kmp3/320kmp3/2000kflac` | ❌ **返回 `The request is illegal!`** | ❌ 无 |
| `www.kuwo.cn/api/v1/www/music/playUrl?mid=&type=convert_url3&br=` | 酷我 | 小熊猫（etc/lx） | 同上 | 同上 | ❌ 同上 illegal | ❌ 无 |
| `www.kuwo.cn/url?` | 酷我 | 小熊猫（etc/lx） | 无 | — | ❌ 404 | ❌ 无 |
| `interface3.music.163.com/eapi/song/enhance/player/url` | 网易 | 小熊猫（etc/lx） | AES 加密 `e82ckenh8dichen8` | `128k/320k/flac` | 🟡 200 但需 eapi 加密 | ❌ 无 |
| `app.c.nf.migu.cn/MIGUM2.0/strategy/listen-url/v2.2` | 咪咕 | 小熊猫（etc/lx） | 需 channel token | `SQ/ZQ` | ✅ 200 可达 | ✅ 已有 |
| `music-api.gdstudio.xyz/api.php?types=url&source=` | 聚合 | 洛雪 GD（etc/lx） | 无 | 按 source 平台 | ❌ 400（缺 source 参数） | ✅ 已有（已禁用，kuwo.py `[:0]`） |

#### 4.6.2 密钥/凭证

| 密钥 | 来源 | 实测 | musicdl 现状 | 说明 |
|------|------|------|-------------|------|
| `share-v2` | Huibq_lxmusic源 | ❌ 失效 | ❌ 无 | lxmusicapi 旧密钥（etc #7 403 确认） |
| `share-v3` | render_api | ✅ 有效 | ✅ **已有**（qq.py:146 / kuwo.py:136） | lxmusicapi 新密钥，musicdl 已用同值 |
| `34ad5692a4827386c6c3a88046ba63cd` | ikun-music-source | ❌ 域名挂 | ❌ 无 | ikun SCRIPT_MD5 |
| `d3419099fafcd0a5c49e7004c9ac7c90` | ikun公益音源 | ❌ 域名挂 | ❌ 无 | 同上 |
| `74a88a1d1ae53cf3cb2889e70aed3d6e` | latest_512 (ikun) | ❌ 域名挂 | ❌ 无 | 同上 |
| `848401000134020058524459344E54...` | monster/無名 | — | ❌ 无 | **咪咕 channel token**（monster 源自身凭证，不可移植） |
| `Hm_Iuvt_cdb524f42f0ce19b169a8071123a4700` | 小熊猫 | 🟡 动态 | ❌ 无 | **酷我首页 set-cookie 动态 token**，用作 playUrl 的 `Secret` 头；非固定密钥，且 playUrl 仍返回 illegal |
| `e82ckenh8dichen8` | 小熊猫 | ✅ 有效 | ✅ **已有**（neteaseutils.py:42） | 网易云 eapi AES 密钥，musicdl 已用同值 |

#### 4.6.3 对 musicdl 的集成结论

1. **lx/ 目录的端点大多已在 musicdl 或 etc/ 中覆盖**。新出现的 `www.kuwo.cn/api/v1/www/music/playUrl` 实测**不可用**（需 `Secret` token 且仍返回 illegal），集成价值低。
2. **`share-v3` 和 `e82ckenh8dichen8` 交叉验证一致**——musicdl 已在使用 lx 源同款密钥，印证两套生态共享部分后端。
3. **重度混淆的 flower/grass/sixyin 源**通过 npm registry 拉取远程 `*-source-info`，实际 API 端点需完整洛雪运行时才能解析，musicdl 无法直接复用。
4. **`Hm_Iuvt_...` 是动态 token 而非固定密钥**——从酷我首页 set-cookie 实时获取，用作 playUrl 的 `Secret` 请求头，不可当作静态凭证存储。

> **关于"gdstudio 已禁用"**：musicdl 的 `_parsewithgdstudioapi` 方法源码存在，但被 `[:0]` 空切片排除（kuwo.py:253 `l3_parser_funcs = [..., self._parsewithgdstudioapi, ][:0]`，注释 `# invalid or unstable accounts`），即**方法定义保留但不参与实际解析**。netease.py 中 gdstudio 在 l3 层（无 `[:0]`），但因 SVIP/VIP 层优先，实际很少被调用。

### 4.7 musicfree-new/ 目录音源插件分析

> 2026-08-07 分析 `etc/musicfree-new/` 目录（174 个 JS 文件，含 70 个子目录）。提取 446 个唯一 URL、21 组密钥，对 71 个 mediasource/lyric 端点做 HTTP 可达性探测。

#### 4.7.1 新增可用端点（未在 ETC 文档此前章节记录）

| 端点 | 平台 | 来源插件 | 鉴权/密钥 | 音质 | 实测 | 说明 |
|------|------|---------|----------|------|------|------|
| `antiserver.kuwo.cn/anti.s?type=convert_url3&rid={id}&format=mp3` | 酷我 | 各插件（musicfree-new） | 无 Cookie | `mp3/flac` | ✅ **200 可用** | 酷我官方 anti 端点，`convert_url3` 返回加密 URL，需解密 |
| `api.vkeys.cn/v2/music/tencent?mid={mid}&quality={q}` | QQ | 各插件（musicfree-new） | 无 key | 数字 quality（14/11/10） | ✅ **200 可用** | vkeys v2 腾讯音源 API（musicdl 已有 v1 `/song/link`，v2 路径不同） |
| `www.fangpi.net/api/play_url?id={id}` | 聚合 | 小橙开发（musicfree-new） | 无 | 按平台 | ✅ **200 可用** | 第三方聚合 API，返回播放 URL |
| `zrcdy.dpdns.org/music/lyric_proxy.php` | 歌词 | 咕咕mur（musicfree-new） | 无 | — | ✅ **200 可用** | 歌词代理 |
| `kuwo.cn/api/www/lyric/lyric` | 歌词 | 酷我（musicfree-new） | 无 | — | ✅ **200 可用** | 酷我官方歌词 API（与 `kuwo.cn/openapi` 不同路径） |
| `5sservice.kugou.com/song/getsongurl` | 酷狗 | 碳酸氢钠（musicfree-new） | 固定 `appid=2918` | `flac/high/320` | ✅ **200 可用** | 酷狗官方 API |
| `mobi.kuwo.cn/mobi.s?f=web&source=cenguigui_jiakong.apk` | 酷我 | 各插件（musicfree-new） | 无 Cookie | `standard/exhigh/lossless` | ✅ **200 可用** | 酷我 mobi 另一 source 渠道，同 nmobi 后端 |
| `music.163.com/api/song/lyric?id={id}` | 歌词 | 各插件（musicfree-new） | 无 | — | ✅ **200 可用** | 网易云歌词 API |
| `music.163.com/weapi/song/enhance/player/url/v1?csrf_token=` | 网易 | 各插件（musicfree-new） | AES 加密 | `128k/320k/flac` | ✅ **200 可达** | 网易云 weapi 音源，需加密参数 |
| `music.163.com/weapi/song/lyric?csrf_token=` | 歌词 | 各插件（musicfree-new） | AES 加密 | — | ✅ **200 可达** | 网易云 weapi 歌词 |
| `http://lyrics.kugou.com/search` | 歌词 | 各插件（musicfree-new） | 无 | — | ✅ **200 可用** | 酷狗歌词搜索 |
| `http://lyrics.kugou.com/download` | 歌词 | 各插件（musicfree-new） | 无 | — | ✅ **200 可用** | 酷狗歌词下载 |
| `http://www.2t58.com/plug/down.php?ac=music&lk=lrc&id=` | 歌词 | 碳酸氢钠（musicfree-new） | 无 | — | ✅ **200 可用** | 2t58 歌词源 |

#### 4.7.2 新增密钥（未在 ETC 文档此前记录）

| 密钥 | 值（前 30 字符） | 来源 | 说明 |
|------|-----------------|------|------|
| 小枸音乐 MD5 | `36164c4015e704673c588ee202b9ec` | ikun/SoEasy/小枸 | 酷狗 API 签名密钥 |
| 小枸音乐 MD5 2 | `381d7062030e8a5a94cfbe50bfe654` | 同上 | 同上 |
| QQ Vip 密钥 | `fb5401d5dad8a2917a71e5d8a327fb` | QQ Vip v2.1.0 | 疑似 MD5 |
| 酷狗 ikun MD5 | `f1f93580115bb106680d2375f8032d` | Thomas喲 酷狗 | ikun 酷狗源 |
| 西瓜糖 API key | `ed34917b6e3ca97d609a82e73c8259` | 竹佀 西瓜糖 | 与 §4.2 中 nki apikey 相同值 |
| 西瓜糖 key (已配置) | `78ba562b6b7de94edb2f4465f1a2a1` | 竹佀 西瓜糖 | 另一配置版 |
| lx 非官方 MD5 | `1888f9865338afe6d5534b35171c61` | 竹佀 独家音源 v4 | 与 §4.2 中 lxmusic SCRIPT_MD5 相同值 |
| Audiomack key | `f3ac5b086f3eab260520d8e3049561` | 猫头猫 | Audiomack 平台密钥 |
| 千千音乐 key | `0b50b02fd0d73a9c4c8c3a781c3084` | 猫头猫 | 千千音乐密钥 |
| ikun_key（用户变量） | 用户自定义 | Thomas喲 系列 | 与 §4.1 #5 关联 |

#### 4.7.3 交叉验证与新增结论

1. **`share-v2` 密钥全部 403 失效**：musicfree-new 中 12 处使用 `lxmusicapi.onrender.com` 的源全部返回 403 key 验证失败，印证 etc #7 结论。`share-v3` 未在这些源中更新。
2. **`ikunshare.com` 域名全部不可达**：4 处 ikunshare 源全部 DNS 解析失败，印证 etc #5 结论。
3. **交叉验证一致**：`ed34917b...`（nki apikey）和 `1888f986...`（lx SCRIPT_MD5）在 musicfree-new 与 ETC 文档 §4.2 中值一致，可信度高。
4. **新增可用端点中，`antiserver.kuwo.cn/anti.s` 和 `api.vkeys.cn/v2/music/tencent` 值得关注**：前者是酷我另一个官方音源端点（与 nmobi 不同），后者是 vkeys 的 v2 API（musicdl 已有 v1）。
5. **musicfree-new 的 174 个文件主要覆盖了网易云/酷狗/QQ/酷我/B站/汽水/咪咕/酷狗/5sing 等平台**，与 etc/ 和 musicdl 的覆盖范围高度重叠，**新增的有效端点集中在歌词和官方 API 的替代路径上**。

### 4.8 青听音乐客户端（QingMusic）分析

> 2026-08-07 逆向 `青听音乐.exe`（Electron 应用，`app.asar`），提取其内置 API 端点。开发者 `kejichangqing`（科技长青），与元力音源同作者。

#### 4.8.1 核心架构

青听音乐是一个 Electron 桌面客户端，导入 `music.json` 洛雪格式索引后，通过内置的后端服务器 `musicserver.haitangw.cc` 解析音源。`music.json` 的 `lines` 数组只启停 6 个内置线路（kg/酷狗、kw/酷我、wy/网易云、tx/QQ、bili/哔哩哔哩、mg/咪咕），实际 API 端点在客户端内置代码中。

**双通道架构**：
- **5 个音源（kg/kw/wy/tx/mg）** 走渲染进程 `resolveMusicUrl` → `musicserver.haitangw.cc` 后端统一解析
- **B 站（bili）** 走主进程 IPC `getSongDetailBili` → 直接调 B 站官方 API
- **歌词** 走主进程 IPC `get-lyric-*` → 各平台官方歌词 API
- **搜索** 走主进程 IPC `search-*` → 各平台官方搜索 API

#### 4.8.2 API 端点

**音源解析后端 `musicserver.haitangw.cc`（POST `{source, rid, level}`）**

| 源 | level 格式 | 实测(2026-08-07) | 说明 |
|----|-----------|------------------|------|
| kw（酷我） | `standard/exhigh/lossless` | ✅ **可用**（201，返回 FLAC CDN） | rid 用酷我数字 id |
| tx（QQ） | 同上 | ✅ **可用**（返回酷我 CDN m4a/flac） | rid 用 QQ songmid |
| wy（网易云） | 同上 | ✅ **可用（部分歌曲）**（返回网易 CDN `iot*.music.126.net`） | rid 用网易数字 id；个别 id 503 |
| kg（酷狗） | 同上 | ✅ **可用**（返回酷狗 CDN `fsandroid.tx.kugou.com`） | **rid 必须用酷狗 hash**（非数字 id） |
| mg（咪咕） | 同上 | ❌ 503 | 咪咕音源后端不可用 |

**主进程官方 API（搜索/歌词/B站）**

| 端点 | 用途 | 实测 |
|------|------|------|
| `http://mobi.kuwo.cn/mobi.s?f=web&user=0&source=kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk&type=convert_url_with_sign` | 酷我音源 | ✅ 200 FLAC（同 §4.4.2 nmobi，不同 source） |
| `http://musicpay.kuwo.cn/music.pay?op=query&action=play` | 酷我歌曲信息 | ✅ 200（带 `x-forwarded-for` 伪造 IP） |
| `http://search.kuwo.cn/r.s` | 酷我搜索 | ✅ 同 §4.4.2 |
| `http://u.y.qq.com/cgi-bin/musicu.fcg`（`music.trackInfo.UniformRuleCtrl/CgiGetTrackInfo`） | QQ 详情 | ✅ 带 QIMEI 设备信息 |
| `https://songsearch.kugou.com/song_search_v2` | 酷狗搜索 | ✅ |
| `https://wwwapi.kugou.com/yy/index.php?r=play/getdata` | 酷狗音源 | ✅ 带 `kg_mid/kg_dfid` Cookie |
| `https://m.kugou.com/app/i/getSongInfo.php?cmd=playInfo` | 酷狗音源备用 | 🟡 部分 hash url 空 |
| `https://interface3.music.163.com/api/v3/song/detail` | 网易云详情 | ✅ 带完整移动端 Cookie（maxbr=999000 无损权限） |
| `https://jadeite.migu.cn/music_search/v3/search/searchAll` | 咪咕搜索 | ✅ **需 MD5 签名**（见 §4.8.3） |
| `https://c.musicapp.migu.cn/MIGUM3.0/resource/song/by-contentids/v2.0` | 咪咕详情/歌词 | ✅ |
| `https://app.c.nf.migu.cn/MIGUM2.0/v1.0/content/resourceinfo.do` | 咪咕资源信息 | ✅ 返回 songItems（含 lrcUrl） |
| `https://api.bilibili.com/x/frontend/finger/spi` | B站 Cookie 获取 | ✅ |
| `https://api.bilibili.com/x/web-interface/view` | B站视频信息 | ✅ |
| `https://api.bilibili.com/x/player/playurl?bvid=&cid=&fnval=16` | **B站音源** | ✅ 返回 3 个音频流（dash） |
| `https://interface.music.163.com/eapi/batch` | 网易云 eapi 批量 | 🟡 需加密 |

#### 4.8.3 密钥/凭证

| 凭证 | 值 | 用途 | 实测 | 价值 |
|------|----|------|------|------|
| 咪咕搜索签名盐 | `6cdc72a439cef99a3418d2a78aa28c73` | 咪咕搜索签名 | ✅ 有效 | ⭐⭐⭐ 高（可移植） |
| 咪咕签名盐 2 | `yyapp2d16148780a1dcc7408e06336b98cfd50` | 同上 | ✅ 有效 | ⭐⭐⭐ 高 |
| 咪咕设备 ID | `963B7AA0D21511ED807EE5846EC87D20` | 请求头 `deviceId` | ✅ 有效 | ⭐⭐⭐ 高 |
| 咪咕 channel | `0146921` | 请求头 `channel` | ✅ 有效 | ⭐⭐⭐ 高 |
| 网易云移动端 Cookie | `MUSIC_U=; NMCID=oyapoh.1707738771510.01.4; URS_APPID=E26D3B65...` | 网易云详情接口 | 🟡 `detail` 返回 maxbr=999000 但 **`MUSIC_U=` 为空（未登录）** | ⭐ 低 |
| 酷狗 Cookie | `kg_mid=1; kg_dfid=1` | 酷狗音源 | ✅ 有效 | ⭐ 低（匿名即可用） |
| 酷我伪造 IP | `x-forwarded-for: 1.0.1.114` | music.pay 信息接口 | ✅ 有效 | ⭐ 低 |
| QQ QIMEI | `c2cff9d0d3310d40ea444083100014717907` | musicu.fcg 设备信息 | ✅ 有效 | ⭐ 低（非凭证） |

**咪咕签名算法**（`jadeite.migu.cn` 搜索）：
```
sign = md5(keyword + "6cdc72a439cef99a3418d2a78aa28c73" + "yyapp2d16148780a1dcc7408e06336b98cfd50" + "963B7AA0D21511ED807EE5846EC87D20" + timestamp)
请求头: uiVersion=A_music_3.6.1, deviceId=963B7AA0..., timestamp=Date.now(), sign=md5hex, channel=0146921
```
实测成功返回 66 个搜索结果（含 contentId/copyrightId）。**这是本软件唯一真正有价值的凭证**——完整可移植的咪咕搜索签名方案。

**⚠️ 网易云 Cookie 无解锁能力**：实测对比 `api/song/enhance/player/url` 接口，**有 Cookie 与无 Cookie 返回完全相同**（普通歌都 128k，VIP 歌都 404）。该 Cookie 的 `MUSIC_U=` 为空值（未登录），仅 `detail` 接口因 `maxbr` 字段显示歌曲"可用无损"，但实际**无法解锁任何音质**。此 Cookie 对 musicdl 无集成价值。

#### 4.8.4 对 musicdl 的集成结论

1. **`musicserver.haitangw.cc/v1/music/resolve-url` 后端实测 4/5 源可用**（kw/tx/wy/kg），仅 mg 不可用。level 参数必须用 `standard/exhigh/lossless` 格式（非 `128k/320k`）。返回的 CDN URL **带完整授权参数**（`?bitrate$2000&format$flac&source$...`），GET 可直接播放（FLAC 49MB 验证 ✅）。
2. **酷狗音源 rid 必须用 hash**（非数字 id），这是 musicserver 与 musicdl 现有 `_parsewith*` 的关键差异点。
3. **咪咕搜索签名算法是唯一高价值凭证**——`md5(keyword + 3 个固定盐 + timestamp)`，配合 `deviceId`/`channel` 头，实测有效。musicdl 的 `migu.py` 可补充此搜索方式（当前 musicdl 用 `c.musicapp.migu.cn/v1.0/content/search_all.do`，可增加 jadeite 签名搜索作为备选）。
4. **B 站音源（playurl + dash）独立于后端直连**，与 §4.7.1 记录一致。
5. **咪咕音源独立性**：青听的咪咕播放依赖 musicserver 后端（当前不支持 mg，报 `UPSTREAM_RESOLVE_FAILED`），**但 musicdl 的 `migu.py` 有独立完整的咪咕音源解析**（`c.musicapp.migu.cn/strategy/listen-url/h5/v2.4` + `app.pd.nf.migu.cn/MIGUM3.0/.../listenSong.do`），不依赖任何第三方后端。**青听的咪咕缺陷不影响 musicdl**。
6. **网易云 Cookie 无价值**（见 §4.8.3 实测），其余凭证（酷狗 Cookie/酷我伪造 IP/QQ QIMEI）均为低价值或非凭证。
7. **`music.json` 只是洛雪格式的启停配置**，不包含 API 端点或密钥。实际音源解析逻辑在青听客户端内置代码中。

#### 4.8.5 QQ 无损下载机制（跨平台酷我重搜）

**实测发现**：musicserver 对 `tx`（QQ）音源返回的 URL 全部是**酷我 CDN**（`car-lv/car-lw.kuwo.cn`），文件名是酷我媒体 ID（如 `F000000oURwi0kKqDR.flac`），**不是 QQ 官方 CDN**。用多首 QQ 歌曲验证均如此——**青听的"QQ 无损"实际是跨平台在酷我重搜同名曲后，用 nmobi 解析酷我无损 FLAC**。

**完整链路**（已复现验证）：

```
1. 输入 QQ songmid（如 002JA4VZ0pp7M9）
2. QQ 详情接口拿歌名：u.y.qq.com/cgi-bin/musicu.fcg
   (module: music.trackInfo.UniformRuleCtrl/CgiGetTrackInfo, 带 QIMEI 设备信息)
   → 歌名"锈 (Live)"
3. 酷我搜索同名曲：search.kuwo.cn/r.s?client=kt&all={歌名}
   → 得到酷我 rid（如 631514298）
4. nmobi 无损解析：nmobi.kuwo.cn/mobi.s?f=web&source=kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk
   &type=convert_url_with_sign&br=2000kflac&sig=0&rid={酷我rid}
   → 返回酷我 CDN FLAC（2000kflac 无损）
```

**本质**：这正是 §4.1 记录的 **P-04 腾讯音乐插件"QQ 全挂→酷我重搜同名曲"跨平台兜底思路**的工程化实现。青听把它作为 QQ 音源的主路径，用酷我的无损音源替代 QQ 的 VIP 限制。

**对 musicdl 的可借鉴性**（✅ 高）：
- musicdl 的 **kuwo.py 已有 `_parsewithofficialapiv1`**（`mobi.kuwo.cn/mobi.s?f=kuwo` 加密版，2000kflac 无损可用），能力完备
- musicdl 的 **qq.py 没有跨平台回退**——只需在 `_parsewiththirdpartapis` 的 l3/l4 层末尾增加"酷我重搜"兜底：`QQ songmid → 详情拿歌名 → KuwoMusicClient 搜索 → _parsewithofficialapiv1`
- 实现要点：酷我搜索用 `client=kt&all={歌名}`（注意 `&` 需 URL 编码）、rid 用 `DC_TARGETID`、nmobi 的 `source=kwplayercar_ar_6.0.0.9_B_jiakong_vh.apk` 渠道实测可用
- **比直接调 QQ 官方 Vkey 更可靠**：QQ 官方需用户登录 Cookie（§4.4.1 实测匿名拿不到 purl），而酷我 nmobi 完全匿名可用

#### 4.8.6 瘦客户端架构：客户端无有效凭证，凭证全在服务器端

**核心结论（2026-08-07 实测）**：青听客户端（app.asar）**本身不含任何能解析音源的有效凭证**，全部有效凭证集中在闭源的 `musicserver.haitangw.cc` 服务器端。

**客户端本地全部凭证清单**：

| 凭证 | 位置 | 有效性 |
|------|------|--------|
| 网易云 Cookie（`MUSIC_U=` 空） | main.js | ❌ 无效（未登录，实测无解锁能力） |
| 酷狗 `kg_mid=1; kg_dfid=1` | main.js | ❌ 无效占位（实测直连 status=0） |
| 咪咕签名盐 + deviceId + channel | main.js | ✅ 有效（**仅搜索用**） |
| QQ QIMEI | main.js | ⚠️ 设备信息，非凭证 |

渲染进程（界面代码）**零凭证**（grep 无任何 Cookie/token/secret）。

**架构**：
```
青听客户端（无有效凭证，瘦客户端）
   │  POST /v1/music/resolve-url {source, rid, level}  ← 只传 3 个字段
   ▼
musicserver 后端（持有全部有效凭证）
   │  网易云 Cookie / 酷狗 Cookie / 酷我设备 / QQ 设备（闭源）
   ▼
各平台官方 API ──▶ CDN URL（自包含授权参数）
   │
   ▼
客户端直接下载（无需凭证）
```

**证据链**：
1. 客户端本地无任何能解析音源的凭证（网易云 Cookie 空、酷狗占位无效、无酷我/QQ 凭证）
2. 但 musicserver 后端 4/5 源能解析——网易云返回 `iot*.music.126.net`、酷狗返回 `fsandroid.tx.kugou.com`、酷我返回 FLAC，客户端零凭证也能拿到
3. `resolve-url` 响应**只返回 `url` 字段**（4 个源均验证），不返回 `headers`/`playbackHeaders`——即使渲染进程代码有解析这些字段的逻辑，后端实际不暴露
4. 后端无任何信息泄露端点：`/v1/health` 外全 404（含 `/config`、`/debug`、`/env`、`/openapi.json` 等）

**服务器端凭证可获取性**：❌ **基本不可获取**。后端是闭源服务，只暴露 `resolve-url`（返回自包含 URL）和 `health`（仅状态）两个端点。没有配置/调试/文档接口泄露内部凭证。唯一可观察的是**行为**（能解析哪些源），无法提取后端持有的 Cookie/密钥。咪咕源在后端不可用（503）也侧面说明后端凭证是有选择地配置的。

**对 musicdl 的意义**：无法从青听客户端或服务器端提取可复用的音源凭证（咪咕搜索签名除外）。musicdl 应继续走**自建凭证路线**（匿名 nmobi、官方公开 API、用户配置 Cookie），不依赖任何第三方"瘦客户端"后端。

### 4.9 各平台直接下载能力实测（2026-08-07）

> 回答"能否直接从各平台下载"的实测结论。

#### 4.9.1 QQ 音乐

**✅ 无损/320k 可下载（第三方免费 API），官方匿名仅 128k——2026-08-07 实测**

**核心发现**：musicdl 的 QQ 无损来自 **l1 层 `_parsewithvkeysapi`**（`api.vkeys.cn/music/tencent/song/link`）。**关键：quality 参数必须用数字枚举值**（`14/13/12/11/10/9/8`），不是名称。musicdl 源码遍历 `ThirdPartVKeysAPISongFileType.ID_TO_NAME` 的 key 倒序 `[2:8]` = `[14,13,12,11,10,9]`，**第一个可用的即返回**（14=AI00 母带优先）。

**vkeys 数字 quality 实测**：

| quality | 编码 | 样本 `0019tNGN1TJbLT` | 周杰伦经典歌（晴/稻香） |
|---------|------|----------------------|------------------------|
| 14 | `AI00` 臻品母带2.0 | ❌ code=110000（**该歌无母带档**） | ✅ **晴天 209.5MB / 稻香 187MB**（fLaC 可下） |
| 11 | `RS01` Hi-Res 24bit | ❌ 本歌 errorcode -46（歌无此档） | ✅ 晴天/稻香 可下 |
| 10 | `F000` FLAC 无损 | ✅ **58.7MB fLaC 可下载** | ✅ 晴天 35.8MB / 稻香 55.4MB |
| 9 | `O800` 320k ogg | ✅ 可下 | — |
| 8 | **`M800` 320k MP3** | ✅ **11.2MB ID3 验证可下载**（实测 HEAD 200） | — |
| 7/5/4 | `O600`/`O400`/`C600` | ✅ 更低音质可下 | — |
| 12 | `Q001` 杜比 | ❌ code=110000 | — |

> **⚠️ 关键修正（2026-08-07）**：vkeys q=14 母带**是否可用取决于歌曲有无母带档**——样本歌 `0019tNGN1TJbLT` 返回 code=110000 是"该歌无母带"而非接口失效；对**有母带档的歌**（周杰伦《晴天》《稻香》）q=14 直接返回 **AI00 臻品母带 187-210MB**。这正是用户群晖运行 musicdl 搜索周杰伦《太阳之子》专辑时看到 **142-207MB FLAC** 的来源（§4.9.1 下方对照）。musicdl 的 `_parsewithvkeysapi` 按 `[14,13,12,11,10,9]` 优先取 14，**母带优先**——有母带档的歌直接给 AI00（100MB+），无母带档才降级到 F000 FLAC（44-58MB）。

**官方 GetVkey 匿名（无 Cookie，2026-08-07 补测）**：**只有 M500 128k 能拿到 purl**；**M800 320k / F000 FLAC / AI00 母带全空**——官方匿名通道只给试听级 128k，320k 与无损必须真实登录 Cookie。

**TuneHub 备用 API**（`api.yexin.de5.net/api/tunehub/parse`）：**必须带 header `X-API-Key: th_dd6c3fd1af25e9256f869b5839268bdca29ab70df9fe85f2`**（源码 `REQUEST_API_KEYS` base64 解密），缺此头 code=0 但无 url。实测 `quality=320k→M800`、`flac→F000`、`flac24bit→F000`（无 24bit 时回落）三档全通，返回 `wx.music.tc.qq.com` 官方 CDN。

| 途径 | 实测 | 音质 |
|------|------|------|
| **vkeys（数字 quality）**（musicdl `_parsewithvkeysapi` l1） | ✅ **可用**，返回 QQ 官方 CDN `ws.stream.qqmusic.qq.com`，**免费无 key** | **q=14 AI00 臻品母带（187-210MB）/ q=10 F000 FLAC / q=8 320k mp3**（母带优先，需歌有母带档）⭐⭐⭐ |
| **xianyuw**（musicdl `_parsewithxianyuwapi` l2，`br=hires`） | ✅ **可用**，返回 `F000` FLAC（58.7MB fLaC，与 vkeys q=10 同体积同源） | **F000 FLAC**（需 `sk-` key） |
| **TuneHub 备用 API**（`api.yexin.de5.net/api/tunehub/parse`，**需 `X-API-Key` 头**） | ✅ 可用，返回 `wx.music.tc.qq.com` | **320k/flac**（flac24bit 回落 F000） |
| **TuneHub 主 API**（`tunehub.sayqz.com`） | ❌ 401（key 无效） | — |
| **nki.pw** | ⚠️ 25s 超时（此前可用 m4a） | 仅 C400/C200 m4a |
| **lx 签名版**（88.lxmusic.xn--fiqs8s） | ✅ 128k 可用 | 仅 128k |
| **cyapi**（quality=lossless） | ⚠️ 名义 lossless 实返 **320k MP3**（11.2MB） | 320k（非无损） |
| **lxmusicapi.onrender**（flac 档） | ⚠️ 降级 MP3 4.4MB | 非无损 |
| **xunhuisi** | ⚠️ m4a 6.7MB | 非无损 |
| **xingmian / 317ak / xcvts / hk0cc / tang / yutangxiaowu / lpz** | ❌ 失效或异常 | — |
| **官方 GetVkey 匿名** | 🟡 **仅 128k（M500）有 purl**；320k/FLAC/母带全空 | 仅 128k |
| 官方 GetVkey（真实 VIP Cookie） | ⚠️ 需用户配置 `musicid`+`musickey`，按 `SongFileType` 从母带→FLAC→320k 降级 | FLAC/320k（VIP） |
| **QQ→酷我重搜**（§4.8.5） | ✅ 匿名 | 酷我 FLAC（2000kflac 级） |

**结论（最终修正，2026-08-07）**：
1. **官方站点匿名拿不到无损，也拿不到 320k**——匿名 GetVkey 只回 128k（M500），320k（M800）与无损（F000/AI00）都必须真实登录 Cookie（`musicid`+`musickey`，§4.4.3）才有 purl。
2. **无损与 320k 的免费公开途径是第三方**：**vkeys 免费无 key**，数字 quality 直接给 QQ 官方 CDN——**q=8 是 320k MP3、q=10 是 FLAC 无损**（fLaC 魔数实测可下）。**xianyuw `br=hires`** 也返回同源 `F000` FLAC（需 `sk-` key）。**TuneHub 备用 API**（带 `X-API-Key`）同样出官方 CDN 320k/flac。
3. **"无损只能从 vkeys 获得"不准确**——实测共 **3 条无损通道**：vkeys q=10（免费）、xianyuw br=hires（sk- key）、TuneHub 备用（X-API-Key）；配真实 VIP Cookie 后官方 GetVkey 也能出无损。但在 **musicdl 当前默认（无 Cookie）配置下**，无损确实只来自这 3 个第三方端点，官方路径走不通。群晖那 5 条 142-207MB FLAC 的来源 = vkeys（"那天下雨了" 142.1MB 与群晖 142.12MB 精确匹配）。

**vkeys 数字 quality 历史实测（周杰伦"那天下雨了"）**：

| quality | 编码 | 实测体积 | 群晖对照 |
|---------|------|---------|---------|
| 14 | `AI00` 臻品母带2.0 | **142.1 MB** | ✅ **群晖 142.12 MB 精确匹配** |
| 13 | `Q000` 臻品全景声 | — | — |
| 11 | `RS01` Hi-Res 24bit | 74-78 MB | — |
| 10 | `F000` FLAC 无损 | 44-47 MB | — |
| 12 | `Q001` 杜比 | ❌ code=110000 | — |

**⚠️ 注意**：① vkeys 的 quality 参数是**数字枚举**（14 母带/11 Hi-Res/10 FLAC），传名称（`flac`/`SQ_LOSSLESS_QUALITY`）会失败——这是我此前误判"vkeys 失效"的原因；② CDN URL 的 vkey 有时效，需实时解析（§2.4.3）。

#### 4.9.2 酷我音乐

**✅ 无需 Cookie/登录——musicdl 内置官方路径匿名直出真无损 FLAC（2026-08-07 复测）**

**核心澄清（2026-08-07 复测修正）**：musicdl 内置酷我官方路径 **`mobi.kuwo.cn/mobi.s?f=kuwo&q={encryptquery}`** 用 `user=0` 完全匿名（无 Cookie），query 用 `SECRET_KEY_SONG=b"ylzsxkwm"` DES 加密（防爬签名，非用户凭证）。**关键：格式参数是 `format=flac`（对应 22000 档）与 `format=mp3`（320 档）**（kuwo.py:36 `MUSIC_QUALITIES`），**不是** nmobi 明文版的 `br=2000kflac` 参数。实测（format=flac）：

| 歌曲 | rid | 实测 | 结果 |
|------|-----|------|------|
| 童话镇-暗杠 | 27825043 | ✅ `format=flac bitrate=2000` | **FLAC 无损 26.1MB**（fLaC 魔数） |
| 七里香-周杰伦 | 94237 | ✅ `format=flac bitrate=2000` | **FLAC 无损 35.8MB** |
| 孤勇者-陈奕迅 | 198554068 | ✅ `format=flac bitrate=2000` | **FLAC 无损 53.3MB** |
| 七里香 / 童话镇 | — | `format=mp3` | 320k / 128k MP3（完整版，非试听） |

**nmobi 明文版（P-04 端点，`nmobi.kuwo.cn/mobi.s?f=web&source=kwplayer_ar_1.1.9_oppo_118980_320.apk&type=convert_url_with_sign&rid=&br=`）2026-08-07 复测**：⚠️ **`br=2000kflac` 已回落 11 秒试听版**（`format=mp3 bitrate=1 dur=11`，仅 185KB）——酷我对该明文接口的 `2000kflac` 档已收紧；`br=320kmp3` 部分歌可给完整 320k（陈发发儿版 9.3MB），部分歌仍回落试听。**文档此前"nmobi 匿名 FLAC 直出"记录已过期**，当前 musicdl 应优先走内置 `f=kuwo` 加密版（`format=flac`），而非 nmobi 明文版。

**其他第三方酷我源（2026-08-07 复测）**：`kw-api.cenguigui.cn`（lossless）✅ 可用；`music.nxinxz.com/kw.php`（lossless）✅ 302 重定向；lx 签名版（88.lxmusic.xn--fiqs8s）128k/320k/flac ✅ 全通；`kw.006lp.ccwu.cc`、`api.liuyunidc.cn`、`music-api.gdstudio.xyz`、`www.guyuei.com` ❌ 失效或禁用。

**结论**：**酷我下载无损不需要 Cookie，也不需要用户密钥**——musicdl 内置 `SECRET_KEY_SONG`（`kuwoutils.py:38`，`b"ylzsxkwm"` 硬编码，8 字节，用于 DES 加密 query 防爬）即可匿名直出真无损 FLAC（`format=flac` → 2000 bitrate）。这与其他平台（QQ 需 Cookie、酷狗解析需 Cookie）形成对比：**酷我是唯一官方路径完全匿名可下无损的平台**。注意：`ENC_MUSIC_QUALITIES`（4000kflac/2000kflac 等 br 命名档）对应的是加密 mgg 格式（需 `_decrypt`），但 `MUSIC_QUALITIES`（`format=flac`/`format=mp3`）是明文可播放档——musicdl 官方路径实际走的是后者，天然可下无损。

**🎯 酷我母带（Master）能力——2026-08-07 新实测**：酷我平台**存在母带级无损**，且可通过 musicdl 内置第三方源 `kwdec.liuyunidc.cn`（`_parsewithliuyunidcapi`，RC4 密钥 `b"yeelion666"`）匿名获取。该源支持 5 档，`kwurl` 返回 `kwstream?data=` 流 URL（RC4 解密 JSON 响应）：

| 档位 | 实测（七里香 4:29 / 孤勇者 4:24 / 童话镇 3:52） | 魔数 |
|------|-----------------------------------------------|------|
| **master** | ✅ **199.8MB / 160.6MB / 151.6MB**（~5000kbps，24bit 高规格） | fLaC ✅ |
| **atmos_plus** | ✅ 62.6MB（童话镇） | fLaC ✅ |
| **atmos** | ✅ 24.1MB（童话镇） | fLaC ✅ |
| flac | ✅ 26.1MB（标准无损） | fLaC ✅ |
| 320k | ✅ 10MB MP3 | ID3 ✅ |

**⚠️ 但 musicdl 代码主动跳过了母带档**：`_parsewithliuyunidcapi` 里 `MUSIC_QUALITIES = ['master','atmos_plus','atmos','flac','320k'][:-1]` 后用 `MUSIC_QUALITIES[3:]` 只试 `flac/320k`（注释"some qualities require decryption which is not stable"）——master/atmos 三档被注释跳过。**修改 `[3:]` 为 `[:]`（并处理 kwstream 直链探测）即可解锁酷我母带**。kwstream 流是 `kwdec.liuyunidc.cn` 自托管 CDN（非 kuwo 官方域名），返回 `application/octet-stream` 但内容为 fLaC，可直接下载。ccwu（`kw.006lp.ccwu.cc`，`level=jymaster`）当前返回 407 区域版权限制不可用。对比：青听（§4.8）酷我最高仅 `lossless`；haitangw.cc 支持 `hires` 但青听只传 standard/exhigh/lossless。

#### 4.9.3 酷狗音乐

**⚠️ 解析需有效 Cookie（凭证在后端），下载环节匿名**

**关键区分（2026-08-07 实测修正）**：

| 环节 | 是否需要 Cookie | 实测证据 |
|------|----------------|---------|
| **解析**（play/getdata → 拿 CDN URL） | ✅ **需要有效 Cookie** | `wwwapi.kugou.com/yy/index.php?r=play/getdata` 直连（无 Cookie 或 `kg_mid=1; kg_dfid=1` 占位）全部返回 `status=0` 失败 |
| **下载**（CDN URL → 音频文件） | ❌ 不需要 | musicserver 返回的 `fsandroid.tx.kugou.com` CDN URL 无 Cookie 200 可下（audio/mpeg 5.2MB） |

**青听客户端为何"看似无 Cookie"**：凭证在 **musicserver 后端**。客户端 POST `{source, rid, level}` 给青听服务器，**服务器持有有效酷狗 Cookie** 去调酷狗 API，返回自包含授权的 CDN URL。所以：
- 客户端 → 青听后端：不传 Cookie（凭证在服务器端）
- 青听后端 → 酷狗：**需要有效 Cookie**（后端口袋里有）

**与酷狗概念版 API 的一致性**：酷狗官方 `play/getdata` 接口**本身要求有效 Cookie**（概念版 API 必须 Cookie 才能搜索下载与此一致）。青听的 `at()` 函数里硬编码的 `kg_mid=1; kg_dfid=1` 是**无效占位**（实测直连失败），实际播放走 musicserver 后端。

**对 musicdl 的意义**：musicdl 的 kugou.py 若走 `wwwapi.kugou.com/yy/index.php?r=play/getdata` 解析，**需要有效酷狗 Cookie**（`kg_mid`/`kg_dfid` 需真实值，非占位）。或走 `trackercdn.kugou.com/i/v2`（musicdl 现有 `_parsewithofficialapiv1` 用的路径，带 `hash+key=md5` 签名）。**酷狗音源必须用 hash**（非数字 id）。

**🎯 酷狗高级音质实测（2026-08-07）**：青听 musicserver 持有有效酷狗凭证，`level=hires` 实测返回 **真 FLAC 36.8MB**（比 lossless 35.8MB 略大，URL 含 `quhigh` 授权参数，匿名可下载）。musicdl 自身酷狗高音质档：`kugouutils.py:30 MUSIC_QUALITIES = ('viper_tape', 'viper_clear', 'viper_atmos', 'flac', 'high', '320', '128')`——**含 viper_atmos（全景声）**，但 `gateway.kugou.com/v5/url` 需要设备注册流程（`/risk/v2/r_register_dev` + AES/RSA），且需有效 Cookie；`118.24.104.108:3456`（super/viper 档）已失效；haitangw 酷狗 error。**酷狗高级音质当前无 musicdl 独立可用通道**（viper 系列需凭证+设备注册），仅青听后端可出 hires。

**🎯 自建概念版 API 实测（2026-08-07，`http://10.10.10.2:3001`，MakcRe/KuGouMusicApi + 有效 Cookie）——酷狗 24bit Hi-Res 可下载！**：
- **接口格式**：`/search?keywords={词}&cookie={cookie串}`（参数是 `keywords` 不是 `keyword`，cookie 走 **query 参数**，文档 §API-SERVICES 旧插件 kugou v2.3.js 的 `kgGet` 实现）；`/song/url?hash={hash}&album_id={aid}&quality={128|320|flac|high}&cookie=...`
- **搜索返回的音质字段**：`FileHash`（128k）/ `HQ.Hash`（320k）/ `SQ.Hash`（**FLAC 标准无损**）/ `Res.Hash`（**Hi-Res**，BitRate 897-1642kbps）
- **实测规格（FLAC STREAMINFO 解析）**：

| quality 档 | 对应 hash 字段 | 青花瓷实测 | 晴天实测 |
|-----------|---------------|-----------|---------|
| `128` | FileHash | MP3 3.8MB | — |
| `320` | HQ.Hash | MP3 9.6MB | — |
| `flac` | SQ.Hash | **FLAC 44.1kHz/16bit/2ch** 26.2MB | 16bit |
| **`high`** | **Res.Hash** | **FLAC 44.1kHz/24bit/2ch ⭐** 26.9MB | **24bit（Res BitRate 1642）** |

- **结论**：**酷狗概念版 API 的 `quality=high`（Res 档）返回 24bit Hi-Res FLAC，规格超过标准 16bit FLAC**——这是 musicdl 之外、用户自建 API 独有的高级无损通道（官方 v5/url 的 `high` 档对应 `Res` 同一 hash）。`super`/`hires`/`master`/`viper_atmos` 档不识别或降级（super→320k MP3）。酷狗**无母带档**（viper_tape 是音效非音质），Hi-Res 24bit 即酷狗最高可下载规格。**musicdl 集成建议**：kugou.py 官方路径 `getsongurl` 的 `MUSIC_QUALITIES` 已含 `high`，但需有效 Cookie + 设备注册；若自建 API 可用，直接 `quality=high` + Res.Hash 即可拿 24bit Hi-Res。

#### 4.9.4 咪咕音乐

**✅ musicdl 独立可用，青听后端失效**

| 途径 | 实测 |
|------|------|
| 青听 musicserver `mg` | ❌ 503（UPSTREAM_RESOLVE_FAILED，青听后端缺陷） |
| **musicdl migu.py** | ✅ **完整独立**：`c.musicapp.migu.cn/strategy/listen-url/h5/v2.4`（带 `signature: 1` 头 + `_decryptresp` 解密）+ `app.pd.nf.migu.cn/MIGUM3.0/.../listenSong.do` 兜底 |

**🎯 咪咕高级音质实测（2026-08-07）**：`migu.py:30 MUSIC_QUALITIES = {'LQ': 'mp3', 'PQ': 'mp3', 'HQ': 'mp3', 'SQ': 'flac', 'ZQ': 'flac', 'Z3D': 'flac', 'ZQ24': 'flac', 'ZQ32': 'flac'}`——**有 ZQ24（24bit）/ZQ32（32bit 浮点）高级无损与 Z3D（全景声）**。但注意代码 `_parsewithofficialapiv1` 第 77 行 `if format_type in {'Z3D'}: continue`（Z3D 加密跳过），且搜索按 filesize 降序取最大——ZQ32/ZQ24 理论上会被优先尝试。**实测限制**：① 咪咕搜索接口（`c.musicapp.migu.cn/v1.0/content/search_all.do` 返回空、`jadeite.migu.cn` 403 风控）当前无法稳定拿到 contentId/copyrightId，导致 ZQ24/ZQ32 档无法端到端验证；② 即使拿到，`listen-url/h5/v2.4` 是否有 ZQ32 权限取决于账号。**咪咕具备母带级音质定义（ZQ24 24bit / ZQ32 32bit），但无可用公开凭证验证**。
| 咪咕搜索（签名） | ✅ `jadeite.migu.cn` + MD5 签名（§4.8.3） |

**结论**：咪咕在青听失效（后端不支持），但 **musicdl 的 `migu.py` 有独立完整的音源解析**（含解密逻辑），不受影响。

---

## 5. getMediaSource 解析范式总结

etc/ 插件按"如何用 song_id 拿到播放 URL"分为三种范式，这对 musicdl 的 `resolve_url` 设计直接相关：

| 范式 | 机制 | 代表插件 | 对 musicdl resolve_url 的启示 |
|------|------|---------|------------------------------|
| **A：直调第三方吃 song_id** | GET/POST 一个端点，响应里直接是 url，不重搜索 | P-01/P-03/P-04/P-05/P-10/P-12/P-13 | **最适合 musicdl 按需重解析**——后端 `resolve_url(id)` 可直接调这些端点，无需重跑搜索。musicdl 现有 `_parsewith*` 多数也属此范式，但入参是 `search_result` dict 而非 bare id，需重构 |
| **B：签名 URL** | path + 密钥签名，端点按 path 段返回 url | P-02/P-09 | 同样适合按 id 重解析，且无鉴权状态，实现最干净。一套密钥(QQ+酷我)即可 |
| **C：服务端 303 两步** | 服务端返回后续请求描述符，客户端二次请求+谓词校验 | P-08/P-11 | 反爬强但实现复杂，musicdl 集成需在 `_parsewith*` 复刻两步逻辑，收益有限 |

**关键结论**：范式 A/B 的端点都接受 bare song_id，**天然支持 musicdl 的 `resolve_url(id)` 按需重解析**，绕过了"必须重搜索"的困境。这是 etc/ 插件给 musicdl 改造的最大馈赠——不是新端点本身，而是证明了"按 id 直接解析"的可行路径。

---

## 6. 架构模式总结与对 musicdl 的启示

### 6.1 两种打包风格
- **Parcel 打包**（P-01/P-02/P-03/P-09/P-13 等）：`$parcel$interopDefault`/`$parcel$export` + 哈希前缀变量。你们项目的 `shared/build.js` 模式是更可控的替代。
- **纯 module.exports**（P-04/P-08/P-10 等）：手写，单 axios 依赖。P-04 腾讯音乐是其中最完整的。

### 6.2 同族插件的代码复用
QQ 系（P-01/P-02/P-03/P-06）的 search/album/artist/toplist/import 代码几乎复制粘贴，差异**只在 getMediaSource**（有时加 getLyric）。酷我系同理。这印证了你们 `shared/runtime.js` + `src.js` 拆分的正确性——共享层放搜索/元数据，平台层只写 URL 解析。

### 6.3 对 musicdl 的三点核心启示

1. **多源回退阶梯是静态 l1-l4 的动态版**：P-04 腾讯音乐的 GetVkey→ikunshare→haitangw→lxmusicapi→酷我重搜，正是 musicdl 静态 l1-l4 列表应有的运行时形态。musicdl 应在 `_parsewiththirdpartapis` 加健康度缓存 + 动态排序（见 REVIEW 文档第 4 章）。

2. **VIP 判定 + 登录态校验可直接搬入**：P-04 的 `type==1` VIP 门控、`qm_keyst` 前缀校验、`uin` 存在性检查，是 musicdl `detector.py` 的现成逻辑。当前 musicdl 配了过期 Cookie 会"跳过第三方 → 官方 API 空 purl → 静默无结果"死路，P-04 的"未登录/VIP 曲直接走代理链"是更优解。

3. **按 id 解析的可行性已验证**：etc/ 几乎所有插件都用 song_id 直调第三方（范式 A/B），证明 musicdl 的 `resolve_url(id)` 完全可行——只需把现有 `_parsewith*` 的"从 search_result 取 id"那步抽出来重构成"直接吃 song_id"，或新增一批直接吃 id 的 `_parsewith*` 方法（用 etc/ 的端点）。

---

## 7. 成果总结

1. **23 个插件全部编号解析**（P-01 ~ P-23），覆盖 QQ 系 7 个、酷我系 8 个、聚合/歌词 8 个。
2. **提取 14 个第三方解析端点**，其中 10 个对 musicdl 代码是真新增（#1–#10），3 个已内置可作交叉验证（#11–#13），1 个歌词源（#14）。其中 #10（nmobi.kuwo.cn）与 #9（kwdec 七级音质）在 `MUSICFREE-API-PLAN.md` 第 6 章已先行记录，属"代码未覆盖但文档已记录"；相对 PLAN 的真增量见 4.1 对照结论的交叉核对注。
3. **提取 6 组密钥**（含 lx-music 签名密钥对，一套双平台）和 5 类 Cookie 字段（含 QQ 兜底 token）。
4. **归纳 3 种 getMediaSource 解析范式**，证明 musicdl 按 song_id 重解析可行，绕过"必须重搜索"困境。
5. **定位 P-04 腾讯音乐**为最值得借鉴的参考实现（唯一带 VIP 判定 + 多源回退阶梯 + 登录态校验 + 酷我跨平台重搜兜底）。
6. **明确 musicdl 改造的三个钩子点**：`_parsewiththirdpartapis`（健康度+动态排序）、`_parsewithofficialapiv1`（Cookie/VIP 探测前置）、新增 `detector.py`（统一账号检测）。
7. **实测 2026-08-07**：14 个端点 7 可用 / 4 不可用 / 2 有条件可用 / 1 需 token（详见 4.1 实测列与对照结论）。lx-tx 高音质受限、yunzhiapi 需 token、kwdec 与 ikunshare 域名已挂，是集成前必须知晓的三个坑。
8. **官方端点与凭证实测（§4.4）**：酷我 `nmobi.kuwo.cn/mobi.s` 是**唯一实测可用的官方音源端点**（完全匿名、FLAC 无损直返 CDN）；QQ 官方 GetVkey 的硬编码兜底 token 已失效，必须用户配置真实登录 Cookie；酷我官方歌词双通道匿名可用，QQ 歌词接口返回 -1310 需排查。
9. **musicdl 源码端点全景（§4.5）**：`scripts/analyze_musicdl.py` 扫描 28 个源，共发现 **~200 个 API 端点、60+ 个密钥、计数器**。其中 qq.py 15 个、kuwo.py 12 个第三方解析方法。修正了 §4.1 表 4 处标注——#3 nki、#4 cyapi、#6 haitangw.net、#7 lxmusicapi 已在 musicdl 源码中内置，并非新增。**真正对 musicdl 为新增的第三方解析端点**是 #1 lx 签名版 QQ、#2 lx 签名版酷我、#5 ikunshare（已挂）、#8 lerd 303、#9 kwdec（已挂）、#10 nmobi、#14 yunzhiapi。
10. **lx/ 目录音源分析（§4.6）**：34 个 JS 文件提取到 10 个去重端点，实测 `www.kuwo.cn/api/v1/www/music/playUrl` 需动态 `Secret` token 仍返回 illegal，**不可用**；`share-v3` 和 `e82ckenh8dichen8` 交叉验证与 musicdl 一致；flower/grass/sixyin 等重度混淆源需远程 source-info 无法直接复用。
11. **musicfree-new/ 目录音源分析（§4.7）**：174 个 JS 文件提取 446 个 URL、21 组密钥，探测 71 个端点。**新增可用端点**：`antiserver.kuwo.cn/anti.s`（酷我官方音源）、`api.vkeys.cn/v2/music/tencent`（vkeys v2）、`kuwo.cn/api/www/lyric/lyric`（酷我歌词）、`5sservice.kugou.com/song/getsongurl`（酷狗官方）等。12 处 `lxmusicapi` 全 403（share-v2 失效）、4 处 ikunshare DNS 挂，印证 §4.1 #5/#7 结论。
12. **青听音乐客户端分析（§4.8）**：逆向 `青听音乐.exe`（Electron app.asar），提取全部 6 音源真实端点。`musicserver.haitangw.cc/v1/music/resolve-url` 后端 **4/5 源可用**（kw/tx/wy/kg，level 须用 `standard/exhigh/lossless` 格式，酷狗 rid 须用 hash），仅 mg 不可用。**唯一高价值凭证是咪咕搜索签名算法**（`md5(keyword+3盐+timestamp)`，实测有效）；网易云移动端 Cookie 的 `MUSIC_U=` 为空值、实测无解锁能力，**无集成价值**。咪咕音源在 musicdl 的 `migu.py` 中独立完整可用（`listen-url/h5/v2.4`），不受青听后端缺陷影响。**QQ 无损下载是跨平台酷我重搜**（§4.8.5）：QQ songmid → 详情拿歌名 → 酷我搜索 → nmobi 解析酷我 FLAC，musicdl 可借鉴（kuwo.py 已有 `_parsewithofficialapiv1`，只需在 qq.py 加跨平台兜底）。**瘦客户端架构（§4.8.6）**：客户端无有效凭证（全部凭证在闭源 musicserver 服务器端），后端仅暴露 `resolve-url`+`health`，**凭证不可从客户端或服务器端提取**。
13. **各平台直接下载能力（§4.9）**：**QQ 无损来自 vkeys 数字 quality 参数**（`_parsewithvkeysapi`，`api.vkeys.cn` + quality=14/11/10，返回 AI00 母带/RS01 Hi-Res/F000 FLAC，实测"那天下雨了" 142.1MB 与群晖精确匹配）；TuneHub 备用 API（`api.yexin.de5.net`）是另一备选无损源。l1-l4 其他源（xcvts/xingmian/317ak/nki/cyapi 等）失效或仅 m4a。酷我 nmobi 匿名可用但**非所有歌无损**（VIP/新歌返回加密 mgg）；**酷狗解析需有效 Cookie（凭证在青听后端），CDN 下载环节匿名**；咪咕在 musicdl 独立完整可用（含解密）。

下一步转入"音源插件专题"对话：基于本文件的总表，在 musicdl 的 `qq.py`/`kuwo.py` 实现新的 `_parsewith*` 方法，并新建 `detector.py` 与 `resolve_url` 快路径。


> 📝 2026-08-07 由 tools/analyze.js 自动同步：新增端点 0 条、密钥 1 条、Cookie 字段 0 条。
