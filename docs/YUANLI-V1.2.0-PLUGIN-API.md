# 元力QQ / 元力KW v1.2.0 插件接口全解（长青SVIP音源）

> 分析日期：2026-08-07
> 分析对象：`etc/musicfree/元力QQ v1.2.0.js`、`etc/musicfree/元力KW v1.2.0.js`
> 分析方法：Node `vm` 沙箱加载混淆插件 → 插桩 axios 捕获每个方法的**精确请求**（URL/参数/请求头）→ 再用真实 axios 端到端实测返回格式
> 用途：MusicFree 插件开发参考；musicdl 端点盘点
> 相关文档：`ETC-PLUGINS-ANALYSIS.md` §4.1 表 #19/#20、P-15b 小节

---

## 0. 一句话结论

**`getMediaSource`（下载链接）不直连官方端点，而是请求元力菌的私有中转服务器**（付费 SVIP 服务，`@name 长青SVIP音源`）。搜索/歌词/歌单/榜单/专辑等**元数据**接口走各平台官方公开端点（匿名，`Cookie:uin=` 占位）。插件**无任何凭证/密钥**——所以单独调用"官方取流端点"必失败，而在 MusicFree 里能播，是因为元力私有后端替客户端完成了官方 API 解析。

---

## 1. 插件元信息

| 项 | 元力QQ v1.2.0.js | 元力KW v1.2.0.js |
|----|-------------------|-------------------|
| @name | 长青SVIP音源 | 长青SVIP音源 |
| @version（头注释） | 1.0.0 | 1.0.0 |
| platform（运行时） | `元力QQ` | `元力KW` |
| version（运行时） | `1.2.0` | `1.2.0` |
| author | 微信公众号:元力菌 | 微信公众号:元力菌 |
| srcUrl（自更新） | `https://13413.kstore.vip/yuanli/qq.js` | `https://13413.kstore.vip/yuanli/kw.js` |
| cacheControl | `no-cache` | `no-cache` |
| primaryKey | `['id','songmid']` | 无（默认） |
| supportedSearchType | `['music','album','sheet','artist','lyric']` | `['music','album','sheet','artist']` |
| 依赖 | axios + he + crypto-js | axios + he |
| 打包 | 混淆（`_0x4a03` 自定义 base64 + `_0x2637` base64+RC4），`module.exports` | 同左 |
| 凭证/密钥/userVariables | **无**（`Cookie:'uin='` 占位、`g_tk=5381` 固定） | **无**（同左） |

**导出方法（两插件一致的部分）**：`search`、`getMediaSource`、`getLyric`、`getAlbumInfo`、`getArtistWorks`、`importMusicSheet`、`getTopLists`、`getTopListDetail`、`getRecommendSheetTags`、`getRecommendSheetsByTag`、`getMusicSheetInfo`。元力KW 另有 `getMusicInfo`。

**hints**：两插件均**未声明** `quality` 提示（MusicFree 以默认 low/standard/high/super 四档调用 getMediaSource），仅提供 `importMusicSheet` 分享格式提示。

---

## 2. getMediaSource —— 播放/下载链接（核心）

### 2.1 元力QQ

```
GET http://175.27.166.236/kgqq1/qq.php?id={songmid}&type=json&level={level}
```

- `id`：QQ 歌曲 `songmid`（如 `0019tNGN1TJbLT`）
- `type`：固定 `json`
- `level`：**音质档**（见下）
- 鉴权：无；无请求头要求

**音质映射（MusicFree quality → level 参数）**

| quality | level | 实际返回 |
|---------|-------|---------|
| low / standard / high | `exhigh` | 320k MP3（CDN 文件名 `M800{songmid}.mp3`） |
| super | `lossless` | FLAC（CDN 文件名 `F000{songmid}.flac`） |

**返回 JSON（实测样例）**

```json
{
  "code": 200,
  "msg": "换源成功，换源度100%",
  "data": {
    "rid": "0019tNGN1TJbLT",
    "media_mid": "0019tNGN1TJbLT",
    "name": "游向陆地的鱼",
    "artist": "梓渝",
    "album": "梓渝",
    "error": "免费",
    "quality": "高音质 MP3",
    "size": "10.65 MB",
    "pic": "https://y.qq.com/music/photo_new/T002R300x300M000...jpg",
    "url": "https://car-lv.kuwo.cn/.../M8000037sca74gKHMO.mp3"
  }
}
```

**⚠️ 关键事实**：返回的 `url` 是**酷我（kuwo）CDN**（`car-lv.kuwo.cn` / `car-er.kuwo.cn`），文件名音质码 `M800`=320k MP3、`F000`=FLAC。即元力 QQ 后端对 QQ 歌曲采用**跨平台酷我重搜兜底**（同 P-04 腾讯音乐、青听 §4.8.5 的策略）。`code!=200` 或 `data.url` 为空 = 该曲解析失败（换源失败）。

### 2.2 元力KW

```
GET https://music.haitangw.cc/music1/kw.php?id={rid}&level={level}
```

- `id`：酷我歌曲 `rid`（如 `392634142`）
- `level`：**音质档**（见下）
- 鉴权：无

**音质映射**

| quality | level | 实际返回 |
|---------|-------|---------|
| low / standard | `exhigh` | 320k MP3（`M800{rid}.mp3`） |
| high / super | `lossless` | FLAC（`F000{rid}.flac`） |

**返回 JSON（实测样例）**

```json
{
  "code": 200,
  "msg": "解析成功",
  "data": {
    "url": "https://car-er.kuwo.cn/.../F000002B9mwN0w9UR6.flac"
  }
}
```

插件取 `response.data.data.url` 直接返回。

### 2.3 对 MusicFree 插件开发的要点

- 两插件都只做**一层匿名 GET**，无签名/无 Cookie/无 Referer 依赖，接入成本极低
- 但服务为**元力菌私人付费后端**（非公开稳定，`code:200` 之外的失败态不可控），不适合作为开源插件的主源，可作高优先级兜底
- QQ 的 `level=exhigh` 返回 320k 而非 128k：若需要 128k 请自建（本插件无 128k 档）

---

## 3. search —— 搜索

### 3.1 元力QQ

```
POST https://u.y.qq.com/cgi-bin/musicu.fcg
```

**请求体（JSON，`data` 字段）**

```json
{
  "req_1": {
    "method": "DoSearchForQQMusicDesktop",
    "module": "music.search.SearchCgiService",
    "param": { "num_per_page": 20, "page_num": 1, "query": "周杰伦", "search_type": 0 }
  }
}
```

**search_type 与 supportedSearchType 的映射**：`music=0`、`artist=1`、`album=2`、`sheet(playlist)=3`、`lyric=7`

**请求头**：`referer: https://y.qq.com`、`user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/106.0.0.0 Safari/537.36`、`Cookie: uin=`；另设 `xsrfCookieName: 'XSRF-TOKEN'`、`withCredentials: true`（axios 配置，实际无真实凭据）。

**返回 → musicItem（格式化后字段）**

```json
{ "id": 97773, "songmid": "0039MnYb0qxYhV", "title": "晴天", "artist": "周杰伦",
  "artwork": "https://y.gtimg.cn/music/photo_new/T002R800x800M000000MkMni19ClKG.jpg",
  "album": "叶惠美", "albumid": 8220, "albummid": "000MkMni19ClKG" }
```

- 歌单（sheet）条目：`{id, title, createAt, description, playCount, worksNums, artwork, artist}`
- 专辑（album）条目：`{id, albumMID, title, artwork, date, singerID, artist, singerMID}`（注意字段是 `albumMID`/`singerMID` 大写，与 music 条目的 `songmid`/`albummid` 不同——下游方法对字段依赖强，见 §5 缺陷）

### 3.2 元力KW

```
GET http://search.kuwo.cn/r.s
```

**music 类型参数**

| 参数 | 值 | 说明 |
|------|-----|------|
| client | `kt` | 客户端标识 |
| all | 关键词 | 搜索词 |
| pn | 页号-1（0 起） | 页码 |
| rn | `30` | 每页条数（`pageSize=30`） |
| uid | `2574109560` | 固定假 uid |
| ver | `kwplayer_ar_8.5.4.2` | 客户端版本伪装 |
| vipver | `1` | |
| ft | `music` | 搜索类型 |
| cluster | `0` / strategy `2012` | |
| encoding | `utf8` | |
| rformat | `json` | |
| vermerge | `1` / mobi `1` | |

**album / artist 类型**：`ft=album|artist` + `itemset=web_2013` + `pcjson=1`（无 uid/strategy 等）。

**返回 → musicItem（格式化后）**

```json
{ "id": "228908", "artwork": "https://img4.kuwo.cn/star/albumcover/1080/s3s94/93/211513640.jpg",
  "title": "晴天", "artist": "周杰伦", "album": "叶惠美", "albumId": "1293", "artistId": "336" }
```

- 专辑条目：`{id, artist, title, artwork, description, date, artistId}`
- 歌单条目：`{id, title, artist(创建者), artwork, playCount, description, worksNum}`

---

## 4. getLyric —— 歌词

### 4.1 元力QQ

```
GET http://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={songmid}&pcachetime={ts}&g_tk=5381&loginUin=0&hostUin=0&inCharset=utf8&outCharset=utf-8&notice=0&platform=yqq&needNewCode=0
```

- 请求头：`Referer: https://y.qq.com`、`Cookie: uin=`
- 注意是 **http**（非 https）
- 返回：`lyric`/`trans` 字段为 **base64** → `he.decode(CryptoJs.enc.Utf8.stringify(CryptoJs.enc.Base64.parse(...)))` → 返回 `{rawLrc, translation}`
- 入参是 **musicItem 对象**（读 `songmid` 字段），传裸 id 会得到 `songmid=undefined`

### 4.2 元力KW

```
GET http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={rid}&httpStatus=1
```

- 入参读 musicItem 的 `id`（rid）
- 返回：`data.data.lrclist`（`[{time, lineText}]`）→ 拼成 `[mm:ss]lineText` 的 rawLrc
- 注意：部分歌曲该接口 `lrclist` 为 null（实测会抛异常），歌词可靠性一般

---

## 5. getAlbumInfo / getArtistWorks —— 专辑与歌手作品

### 5.1 元力QQ

```
POST https://u.y.qq.com/cgi-bin/musicu.fcg  (data 参数, GET/POST 皆可)
```

- **getAlbumInfo**：`module: music.musichallAlbum.AlbumSongList`、`method: GetAlbumSongList`、`param: {albumID: 0, begin: 0, num: 999, order: 2}`
  - ⚠️ **已知 bug**：`albumID` 恒为 `0`，返回 `musicList: []`。此方法实际不可用（原样照抄会得空列表）
- **getArtistWorks(album)**：`module: music.web_singer_info_svr`、`method: get_singer_album`、`param: {order:'time', begin:0, num:20, exstatus:1}`（`singermid` 参数疑似缺失/读不到 → 实测抛错）
- 请求头同 §3.1（referer/UA/Cookie uin=）

### 5.2 元力KW

```
GET http://search.kuwo.cn/r.s
```

- **getAlbumInfo**：`stype=albuminfo&albumid={albumId}&pn=0&rn=100&sortby=0&alflac=1&show_copyright_off=1&pcmp4=1&encoding=utf8&plat=pc&thost=search.kuwo.cn&vipver=MUSIC_9.1.1.2_BCS2&devid=38668888&newver=1&pcjson=1`
- **getArtistWorks(album)**：`stype=albumlist&artistid={artistid}&pn=0&rn=30&sortby=1&...`（同族参数）
- 入参读 musicItem 的 `albumid`/`artistid` 字段

### 5.3 getMusicInfo（元力KW 独有）

```
GET http://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={rid}&httpStatus=1
```

- 与 getLyric 同一端点，解析 `data.data.songinfo` → 返回 `{artwork}`（实测部分歌曲 `songinfo` 为 null 会抛错）

---

## 6. 榜单 getTopLists / getTopListDetail

### 6.1 元力QQ

```
GET/POST https://u.y.qq.com/cgi-bin/musicu.fcg
```

- **getTopLists**：`module: musicToplist.ToplistInfoServer`、`method: GetAll`、`param: {}`（comm 含 `uin:123456`、`g_tk:5381`、`platform:'h5'`）
- **getTopListDetail**：`module: musicToplist.ToplistInfoServer`、`method: GetDetail`、`param: {topId, offset:0, num:100, period:''}`
- 返回：`groups[].toplist[]` → `{id, title, period, coverImg, description}`（实测 `period` 为榜单日期如 `2026-08-07`）

### 6.2 元力KW

- **getTopLists**：`GET http://wapi.kuwo.cn/api/pc/bang/list`
- **getTopListDetail**：

```
GET http://kbangserver.kuwo.cn/ksong.s?from=pc&fmt=json&pn=0&rn=80&type=bang&data=content&id={bangId}&show_copyright_off=0&pcmp4=1&isbang=1&userid=0&httpStatus=1
```

- 返回：`{title:'官方榜'..., data:[{id, coverImg, title, description}]}`（酷我榜单 id 为字符串，如 `'16'`）

---

## 7. 歌单 getMusicSheetInfo / importMusicSheet / getRecommendSheets

### 7.1 元力QQ

- **importMusicSheet**（歌单导入）：

```
GET http://i.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?type=1&utf8=1&disstid={歌单id}&loginUin=0
```

  - 请求头：`Referer: https://y.qq.com/n/yqq/playlist`、`Cookie: uin=`
  - 可识别输入：`https://y.qq.com/n/ryqq/playlist/{id}`、`https://i.y.qq.com/n2/m/share/details/taoge.html?...id={id}`、纯数字 id
  - 返回：`json.cdlist[0].songlist[]` → musicItem 列表（分页循环，每页 50 条）

- **getMusicSheetInfo(sheetId)**：本质是调 `importMusicSheet` 后再格式化（`{isEnd:true, data: songs}`）
- **getRecommendSheetTags**：`GET https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_tag_conf.fcg?format=json&inCharset=utf8&outCharset=utf-8`（Referer: `https://y.qq.com/`）
- **getRecommendSheetsByTag**：`GET https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_by_tag.fcg` + params `{inCharset:'utf8', outCharset:'utf-8', sortId:5, categoryId:{tagId}, sin:(page-1)*pageSize, ein:page*pageSize-1}`

### 7.2 元力KW

- **getMusicSheetInfo**：

```
GET http://nplserver.kuwo.cn/pl.svc?op=getlistinfo&pn={page-1}&rn=30&encode=utf8&keyset=pl2012&vipver=MUSIC_9.1.1.2_BCS2&newver=1
```

- **importMusicSheet**：识别酷我歌单链接（`www.kuwo.cn/playlist_detail/{pid}`、`m.kuwo.cn/h5app/playlist/{pid}`、纯数字）→ 循环调 `getMusicSheetResponseById`
- **getRecommendSheetTags**：`GET http://wapi.kuwo.cn/api/pc/classify/playlist/getTagList?cmd=rcm_keyword_playlist&user=0&prod=kwplayer_pc_9.0.5.0&vipver=9.0.5.0&source=kwplayer_pc_9.0.5.0&loginUid=0&loginSid=0&appUid=76039576`
- **getRecommendSheetsByTag**：`GET http://mobileinterfaces.kuwo.cn/er.s?type=get_pc_qz_data&f=web&id={tagId}&prod=pc`

---

## 8. 通用参数/请求头惯例（两插件一致）

| 项 | 值 |
|----|----|
| QQ 元数据接口 Cookie | `uin=`（空 uin 占位） |
| QQ g_tk | 固定 `5381` |
| QQ UA | Chrome/106 Windows |
| QQ Referer | `https://y.qq.com/`（或 `https://y.qq.com/n/yqq/playlist`） |
| KW UA | 无显式 UA（用默认） |
| axios 配置 | `xsrfCookieName:'XSRF-TOKEN'`、`withCredentials:true`（QQ 系） |
| 分页 | QQ `num_per_page=20`；KW `rn=30` |
| 编码 | 统一 `encoding=utf8/utf-8` |

---

## 9. 已知缺陷汇总（照抄前注意）

1. **QQ getAlbumInfo 恒传 `albumID=0`** → 返回空列表，方法不可用
2. **QQ getArtistWorks(song)** 缺 `singermid` 读取 → 实测抛 `undefined` 错误
3. **QQ getLyric / KW 歌词接口**：部分歌曲返回空/抛异常（`lrclist`/`songinfo` 为 null）
4. **getMediaSource 的中转服务是私有付费**：无 SLA、无错误码规范、可能随时失效/限流；`code!=200` 时的 `msg` 文本无稳定契约
5. 混淆版本 `@version 1.0.0` 与运行时 `version 1.2.0` 不一致，更新判断建议以 `srcUrl` 拉取为准

---

## 10. 对 MusicFree 插件开发的建议

- **模板价值**：这套插件是"官方元数据 + 私有中转取流"的典型结构。若要开发自己的插件，直接复用其 **search/getLyric/榜单/歌单** 的官方匿名端点（全部实测可匿名），只替换 getMediaSource 为你的取流方案
- **音质档语义**：中转 `level` 用 `exhigh/lossless`（非 `128k/320k`），返回音质由 CDN 文件名 `M800/F000` 决定；若用其他解析服务需注意语义差异
- **Cookie/UA 是硬要求**：QQ 系接口无 UA/Referer 会被拒（实测带 Cookie `uin=` 即可匿名通过，无需真实登录）
- **不要照抄缺陷**：QQ getAlbumInfo/getArtistWorks 的字段读取 bug 应修复后再用（改为从 musicItem 取 `albummid`/`singerMID` 并正确填参）

---

## 11. 母带级能力实测（2026-08-07）

> 验证"元力酷我能否拿母带"的对照试验：元力KW 中转 vs musicdl 内置 `kwdec.liuyunidc.cn`。

### 11.1 元力KW 中转：**上限即 FLAC，无母带**

对 `music.haitangw.cc/music1/kw.php` 用 7 个 level 值实测，全部塌缩：

| 传参 level | 实际返回 CDN 文件名 | 实际音质 |
|---|---|---|
| `exhigh` | `M800*.mp3` | 320k MP3 |
| `lossless` | `F000*.flac` | **FLAC（最高档）** |
| `hires` / `master` / `atmos` / `jymaster` / `zply` | 全部 `M800*.mp3` | 回落 320k MP3 |

**结论**：元力KW 中转只实现了 `exhigh→320k`、`lossless→FLAC` 两档语义，母带/Hi-Res/ATMOS 参数被后端无视。**想要母带不能靠元力KW。**

### 11.2 musicdl 内置 `kwdec.liuyunidc.cn`（`_parsewithliuyunidcapi`）：**母带级可拿**

`kwurl`（RC4 密钥 `b"yeelion666"`）支持 5 档音质标准 `master/atmos_plus/atmos/flac/320k`。实测三首歌 `q=master` 全部返回 **kwstream fLaC 流**（魔数 `66 4c 61 43`=fLaC，`Content-Type: application/octet-stream`，直链无需解密），总大小与酷我官方元数据 `zply`（至臻母带）档一致：

| 歌曲 | rid | master | atmos_plus | atmos | flac(对照) |
|---|---|---|---|---|---|
| 七里香 | `94237` | **209.5MB**（=元数据199.79Mb✓） | 88.6MB | 34.9MB | 35.8MB |
| 孤勇者 | `198554068` | **168.5MB**（=160.65Mb✓） | 67.3MB | 26.2MB | 53.3MB |
| 童话镇 | `392634142` | **159.0MB** | 68.9MB | 27.2MB | 49.9MB |

**音质标准对照**：
- 元力KW 标准：`exhigh(320k) / lossless(FLAC)` —— **无母带**
- liuyunidc 标准：`master / atmos_plus / atmos / flac / 320k` —— **master 即至臻母带**（mflac, 实测可用）

> ⚠️ musicdl 源码 `kuwo.py` 原用 `MUSIC_QUALITIES[3:]` 只跑 `flac`（跳过 master/atmos），已改为 `[:]` 解锁母带（见 git 提交）。
