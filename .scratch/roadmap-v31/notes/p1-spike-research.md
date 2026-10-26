# P1 spike 调研报告：songloft-player 三问 → D-1 裁决素材

- 日期：2026-10-27
- 调研方式：联网调研（GitHub 仓库/issue/commit、npm registry、官方文档、第三方评测文章）；未做真机实测
- 对应 issue：`../issues/08-p1-spike.md`

## 0. 仓库身份确认

**songloft-player 真实存在**，GitHub 组织为 `songloft-org`（前身 MiMusic，v2.0 起更名 Songloft）。生态全景（star 数 / 最近推送，GitHub API 实测于 2026-10-27）：

| 仓库 | 语言 | Stars | 最近推送 | 角色 |
|---|---|---|---|---|
| [songloft-org/songloft](https://github.com/songloft-org/songloft) | Go | 2041 | 2026-10-26 | 自托管音乐服务器（QuickJS JS 插件宿主） |
| [songloft-org/songloft-player](https://github.com/songloft-org/songloft-player) | Dart/Flutter | 211 | 2026-10-26 | 跨平台播放器（六端：iOS/Android/macOS/Windows/Linux/Web） |
| [songloft-org/plugin-toolchain](https://github.com/songloft-org/plugin-toolchain) | TS | 3 | 2026-10-14 | JS 插件工具链（plugin-sdk / client-sdk / builder / 脚手架） |
| [songloft-org/songloft-plugin-go-music-dl](https://github.com/songloft-org/songloft-plugin-go-music-dl) | JS | 11 | 2026-10-16 | **音源插件实例**（接入 go-music-dl） |
| [songloft-org/songloft-plugin-miot](https://github.com/songloft-org/songloft-plugin-miot) | TS | 65 | 2026-10-26 | MIoT 投放插件（小爱音箱） |
| [songloft-org/songloft-plugin-mpd](https://github.com/songloft-org/songloft-plugin-mpd) | TS | 4 | 2026-08-18 | MPD 播放插件（有线/蓝牙/DLNA 设备） |

**判定：不是「不存在或极小众」**。主仓库 2k+ stars、当日仍有推送、npm 包 46 个版本持续发版（最新 2.18.0，2026-10-14）。但生态确实是**单人主导**（作者 hanxi）、第三方插件 star 个位数到两位数——活跃度健康，bus factor 低。

---

## 一问：Bundle 模式下 JS 音源插件可用性

### 结论

**可用（高置信推断 + 间接证据，未见一句明确的官方声明，建议真机复核一处）。**

Bundle 模式 = Flutter 客户端**内嵌同一个 Go 后端**（移动端 gomobile 编译为 .aar/.xcframework 经 MethodChannel 调用；桌面端作为 `songloft-server` 子进程；Web 不支持）。JS 插件系统**运行在 Go 后端内**（每个插件一个独立 QuickJS VM Actor，由 ServiceScheduler 调度），不是跑在 Flutter/Dart 层——因此 Bundle 内嵌后端与独立部署后端共享同一套 jsplugins 能力，播放器端有 `features/jsplugin/`（JS 插件管理 UI）模块。

### 证据

1. **三种部署模式**：songloft-player README 明确 standalone / embedded / **bundle**（"客户端内嵌 Go 后端"，`--dart-define=HAS_BACKEND=true`，产物名 `songloft-bundled-*`，移动端 gomobile 内嵌、桌面端子进程、Web 不支持）。来源：[songloft-player README](https://github.com/songloft-org/songloft-player/blob/main/README.en.md)、[songloft README](https://github.com/songloft-org/songloft)
2. **JS 插件跑在后端**：官方指南原文——"Songloft JS 插件系统允许开发者使用 JavaScript 扩展**音乐服务器**功能，无需编译 Go 代码"；架构为 Manager → PackageManager / ServiceScheduler（多个 JSService Actor，各持独立 QuickJS VM）/ HotReloader / HealthChecker；管理 API `POST /api/v1/jsplugins/upload`，运行时路由 `/api/v1/jsplugin/<entryPath>/*`。来源：[songloft/docs/js-plugin-development-guide.md](https://github.com/songloft-org/songloft/blob/main/docs/js-plugin-development-guide.md)、[后端架构文档](https://github.com/songloft-org/songloft/blob/main/docs/architecture_backend.md)
3. **播放器端插件管理 UI 存在**：player 项目结构含 `features/jsplugin/`（注释"JS 插件管理"）与设置页"插件"项。来源：[songloft-player README](https://github.com/songloft-org/songloft-player/blob/main/README.en.md)
4. **音源插件已被真实消费**：`songloft-plugin-go-music-dl` 是官方维护的音源插件，且 SDK 2.18.0 导出 `createSearchHandler` / `createMusicUrlHandler`（见第三问），类型注释写明"**符合主程序约定**的 POST /api/search、POST /api/music/url handler"——即存在播放器/后端消费音源插件的固定协议，与部署模式无关。

### 残留不确定性

未找到一句话级别的官方声明「bundle 版构建包含 jsplugins 模块」。缓解：bundle 内嵌的就是同一个 Go 后端（同仓库同代码路径），jsplugins 是后端核心模块而非可选编译项的任何证据都没找到反面；真机复核判据见末节。

---

## 二问：DLNA/投送能力（目标设备：小爱音箱 LX06）

### 结论

**支持 DLNA 投送（ControlPoint，即手机→设备方向），且有两条到小爱音箱的路径。**「DLNA 服务器/渲染器」方向（设备来拉库）**未实现**，有人提了 open issue。

### 证据

1. **播放器内置 DLNA 投屏模块**：songloft-player 项目结构含 `features/dlna/`，注释"DLNA 投屏"。来源：[songloft-player README](https://github.com/songloft-org/songloft-player/blob/main/README.en.md)
2. **实现链路有 commit 佐证**：[issue #222「看到有人做了dlna 能集成吗」](https://github.com/songloft-org/songloft/issues/222)（2026-06-25，已关闭标 completed）记录了 4 个 commit：① 为 JS 插件新增 UDP socket Bridge API（`songloft.net`，SSDP 发现设备所需）；② UDP API 单测+文档；③ **"feat: DLNA 投屏功能（ControlPoint）"——落在 songloft-player 仓库**；④ plugin-toolchain SDK 增补 UDP 类型声明。即 DLNA 控制点实现在 Flutter 播放器内，SSDP 发现能力同步开放给了 JS 插件（`net` 权限覆盖 UDP/SSDP/DLNA，见 [plugin-toolchain](https://github.com/songloft-org/plugin-toolchain)）。
3. **社区插件佐证**：issue #222 引用的社区作品 [febfebfebqq/songloft-dlna-plugin](https://github.com/febfebfebqq/songloft-dlna-plugin)；官方 [songloft-plugin-mpd](https://github.com/songloft-org/songloft-plugin-mpd) 描述含"DLNA 设备远程播放"。
4. **视频投屏也做了**：[issue #76](https://github.com/songloft-org/songloft/issues/76) 引用 commit "feat(dlna): 支持视频投屏并修复投屏 mime 硬编码"；官方 [FAQ](https://songloft.hanxi.cc/faq.html) 提到"带画面的文件可投到 DLNA 电视/盒子"。
5. **反向未实现**：[issue #492「建议增加DLNA服务的功能」](https://github.com/songloft-org/songloft/issues/492)（2026-10-02，open）请求把音乐库以 DLNA 服务暴露给电视/音响——用户原话"现在只能把音乐推送给小爱音响播放"。这同时是**正向投送已被用户实际用于小爱音箱**的旁证。
6. **第三方教程**：[知乎：小爱一句话点播 NAS 里的歌，Docker 一键部署 Songloft](https://zhuanlan.zhihu.com/p/2057850641268094071)、[什么值得买：Songloft 私有音乐库搭建指南](https://post.smzdm.com/p/a708nknd)（"播放页一键将当前歌曲投送到已配置的小爱音箱播放"）。
7. **小爱侧前置条件**：小米官方 DLNA 手册——手机/音箱同 WiFi，需在「小爱音箱 App → 我的 → DLNA 音乐播放」打开开关。来源：[小米官方 DLNA 使用手册](https://cdn.cnbj1.fds.api.mi-img.com/ics-resources/articles/6066c6ebe4801400d6db9c70.html)。LX06 属于支持 DLNA 的型号（该手册覆盖系列；具体以 App 内开关出现为准）。

### 到 LX06 的两条路径

| 路径 | 机制 | 证据强度 |
|---|---|---|
| A. 播放器内置 DLNA ControlPoint | Flutter 侧 SSDP 发现 + AVTransport 投送；LX06 需先在小爱音箱 App 打开 DLNA 开关 | commit + 模块 + FAQ（强） |
| B. songloft-plugin-miot 投放插件 | MIoT/mina 控制面（设备列表 / play-url / pause / volume / status），专为小爱设计；go-music-dl 插件直接复用其 `/mina/*` 控制面 | 官方插件 + 使用文档（强）；适配 MIoT 6 秒超时预算，口令搜索只扇出 8 个快源 |

注意 B 路径的直链地址推导约束（go-music-dl 文档）：直链 host 按 `serverHost` → baseUrl host → `getHostUrl` → 网卡 LAN 地址四级推导，"宿主只监听 127.0.0.1 时需手动填对外可达地址，否则直推 url 会置空"——**Bundle 模式下后端在手机 localhost 上，投送时手机就是服务器**，此配置项是实测时的关键检查点。

---

## 三问：@songloft/plugin-sdk 接口形状 + 与 MusicFree 插件对比 + kwqq-api 包装工作量

### 结论

**接口形状已确认，且存在与 MusicFree 同构的官方音源插件约定，包装 kwqq-api 工作量小（预计 1–2 天含联调）。**

### npm 包实况（registry API 实测 2026-10-27）

| 包 | latest | 首发时间 | 版本数 |
|---|---|---|---|
| `@songloft/plugin-sdk` | 2.18.0（2026-10-14 发） | 2026-05-29 | 46 |
| `@songloft/client-sdk` | 2.18.0 | 2026-07-16 | 20 |
| `@songloft/plugin-builder` | 2.18.0 | 2026-05-29 | 46 |

另有 `create-songloft-plugin` 脚手架（`npx create-songloft-plugin@latest`）。npm 包本体无 README，以下接口形状直接取自 tarball 内 `dist/index.d.ts`（1134 行，本报告引用处已核对原文）。

### 运行模型（与 MusicFree 根本不同点）

- **插件不是 npm 库被 import，而是后端内的 HTTP 服务 Actor**：`plugin.json` manifest（强制 `entryHash`/`zipHash` 校验）+ `main.js`，打包为 `{entryPath}.jsplugin.zip` 上传；入口挂 `onHTTPRequest(req) → {statusCode, headers, body}`、`onInit()`/`onDeinit()`。
- API 经全局 `songloft` 对象：`storage` / `songs` / `playlists` / `tags` / `comm`（插件间 send/call）/ `plugin.getToken()/getHostUrl()` / `net`（UDP/TCP/httpStream）/ `lyrics.registerProvider` / `covers.registerProvider` / `crypto`。**全局 fetch 无需权限**（这正好覆盖调 kwqq-api 的需求）；`net` 权限覆盖 UDP/SSDP/DLNA。来源：[js-plugin-development-guide.md](https://github.com/songloft-org/songloft/blob/main/docs/js-plugin-development-guide.md)
- SDK 便捷层（`@songloft/plugin-sdk` 导出）：`createRouter()`（:param 路由）、`jsonResponse(body, status)`、Cookie 工具族、`createSearchHandler`、`createMusicUrlHandler`。

### 音源插件官方约定（SDK 2.18.0 index.d.ts 原文摘录）

```ts
// POST /api/search   "符合主程序约定的 handler"
// Request:  { keyword: string, page?: number, page_size?: number }
// Response: { results: SearchResultItem[] }
interface SearchResultItem {
  title: string; artist: string; album?: string; duration: number;
  cover_url?: string;
  source_data: Record<string, unknown>;   // opaque，主程序原样存进 song 表，music_url 时回传
  is_video?: boolean;
}

// POST /api/music/url
// Request:  { source_data, fallback?: { enabled, title, artist, duration? } }
// Response 200: { url, headers?, source_data?, used_fallback? }
// Response 404: { error: 'source_not_available' }
type ResolvedMusicUrl = string | { url: string; headers?: Record<string,string> };
createMusicUrlHandler({ resolveUrl, fallbackSearch? }): RouteHandler;
```

`resolveUrl` 失败时主程序可下发 `fallback` hint，插件用 `fallbackSearch(title, artist)` 自搜换源后重试——即内置了换源重试协议。

### 与 MusicFree 插件约定对比

| 维度 | MusicFree（musicfree-plugins 生态） | Songloft 音源插件 |
|---|---|---|
| 搜索 | `search(keyword, page, type)` → `{isEnd, dataList[]}` | `createSearchHandler` → `POST /api/search`，`{results[]}`，页码从 1 起 |
| 取直链 | `getMediaSource(source, musicItem)` → `{url, ...}` | `createMusicUrlHandler` → `POST /api/music/url`，入参 `source_data`，返回 `{url, headers?}` |
| 元数据 | `getMusicInfo` / `getAlbumInfo` / `getArtistInfo` 等 | 无独立约定；专辑/歌手信息塞进 `SearchResultItem` 或省略 |
| 歌词 | `getLyric(musicItem)` | 独立机制：`songloft.lyrics.registerProvider` + `/lyric-search` 端点（200 JSON `{lyric, tlyric?...}`，15s first-match-wins） |
| 状态载体 | `musicItem`（含 `songmid`/`id` 等）在播放器内存中流转 | `source_data` opaque JSON，**主程序持久化进 song 表** |
| 失败兜底 | 插件自行处理 | 内建 `fallbackSearch` 换源协议 |
| 运行环境 | 玩家端 JS 运行时（React Native） | 后端 QuickJS 沙箱（禁 Node 内置模块，es2020 iife） |

**同构度评估**：核心两接口（search / getMediaSource ↔ /api/search / /api/music/url）概念一一对应，映射机械；差异在状态持久化语义（songloft 会把搜索结果落 song 表）与歌词走独立 provider。

### kwqq-api 包装工作量评估

kwqq-api 是 HTTP API（`/{source}/search`、`/{source}/song/url`，`{code,msg,data,timestamp}` 信封，二段式：search 只出元数据、按 id 再取直链）。包装插件形状：

```
onHTTPRequest(req) → router.handle(req)
  POST /api/search      → fetch kwqq /{source}/search → 拆 {code,msg,data} 信封
                          → data[] 映射 SearchResultItem{title, artist, album, duration, cover_url,
                             source_data: {source, songmid, ext候选, ...}}
  POST /api/music/url   → fetch kwqq /{source}/song/url?id=source_data.songmid → 拆信封
                          → 返回 {url, headers?}（若 CDN 需 Referer/UA，SDK 原生支持 headers 字段）
  POST /lyric-search    → （可选）kwqq 若有歌词端点则接
```

工作量判断依据：
- **有利**：① 全局 fetch 免权限，插件只需 fetch 两个端点；② 信封拆包在 server/adapters 里已有同构逻辑（`SourceAdapter.search_items` / `song_url`），映射规则可直接照抄；③ kwqq 二段式与 songloft 的 search/resolveUrl 两段协议天然对齐（`source_data` 保存 id，直链在播放时才解析，不存在直链过期问题）；④ SDK `createSearchHandler`/`createMusicUrlHandler` 连错误响应（400/500）都代劳；⑤ `@songloft/plugin-builder` 的 build/validate/dev 全流程现成。
- **风险/注意**：① 搜索结果被主程序**持久化进 song 表**——kwqq 搜索结果入库策略需实测确认（是否有去重/清理机制，本地库会不会被在线搜索灌满），这是与 MusicFree 瞬态搜索最大的行为差异；② `fallbackSearch` 建议实现（失败换源），否则体验降级但可用；③ Bundle 模式下插件访问 kwqq-api 走手机网络（公网或家庭 LAN），地址要做成插件设置项（`songloft.storage`）；④ 直链 host 推导问题（第二问末）在 DLNA 投送场景要留意——但走 `/api/music/url` 返回原始 CDN url 时，是设备直连 CDN 还是经宿主代理拉流需实测确认。
- **估计**：核心插件 200–300 行 TS + 脚手架配置，半天到一天可出可跑版本；含联调（真机 + kwqq-api + LX06）1–2 天。

来源：[@songloft/plugin-sdk 2.18.0 tarball index.d.ts](https://registry.npmjs.org/@songloft/plugin-sdk/-/plugin-sdk-2.18.0.tgz)（本报告引文逐句核对）、[js-plugin-development-guide.md](https://github.com/songloft-org/songloft/blob/main/docs/js-plugin-development-guide.md)、[plugin-toolchain](https://github.com/songloft-org/plugin-toolchain)、[songloft-plugin-go-music-dl usage.md](https://github.com/songloft-org/songloft-plugin-go-music-dl/blob/main/docs/usage.md)、npm registry API（版本/时间数据）。

---

## 四、D-1 裁决素材摘要

**支持「切换 songloft」的证据（偏多）：**
1. Bundle 模式架构成立且与独立部署共享插件系统 → JS 音源插件随包可用（高置信）。
2. DLNA ControlPoint 已实现在播放器内（commit + 模块 + FAQ 三重证据），到小爱另有 MIoT 官方插件路径。
3. SDK 已内置与 MusicFree 同构的音源插件约定（/api/search + /api/music/url + 换源 fallback），kwqq-api 包装成本低。
4. 生态活跃：主仓库 2k stars、当日有推送、npm 46 个版本；go-music-dl 插件证明「HTTP 上游聚合源接成音源插件」这条路已被走过。

**支持「MusicFree 保留 / 谨慎」的证据：**
1. 单人主导项目（hanxi），bus factor 低；插件生态体量小（音源插件 11 stars）。
2. 播放器本体 211 stars，移动端成熟度（后台播放、保活、投送稳定性）未经验证。
3. 搜索结果持久化进 song 表的行为差异未实测；Bundle 模式下「手机即服务器」的直链推导/代理拉流路径未实测。
4. DLNA 反方向（渲染器）未实现——但不在本 spike 三问范围内。

**未找到证据、需真机补齐的**：bundle 版构建包含 jsplugins 管理界面的直接声明；LX06 实投成功率。

**倾向性判断（置信度：中高）**：三问均未出现否决性障碍，D-1 可朝「P2 做最小 kwqq-api→songloft 插件 spike + 真机 DLNA 实测」方向推进；MusicFree 是否保留取决于实测体验，不建议本阶段直接裁决淘汰。

## 五、DLNA 实测步骤建议（真机：手机装 songloft-player + LX06）

前置：LX06 与手机同 WiFi；「小爱音箱 App → 我的 → DLNA 音乐播放」开关打开（若 App 内无此开关，说明该批次固件未开放 DLNA，路径 A 直接判负，转路径 B）。

1. **装 Bundle 版**：从 [songloft Releases](https://github.com/songloft-org/songloft/releases) 下载 `songloft-bundled-*` APK（Android），装到手机；首次启动点「使用本地模式」选一个含几首歌的目录（默认账号 admin/admin）。
2. **复核一问判据**：设置页找「插件」项 → 从 [songloft-plugin-go-music-dl Releases](https://github.com/songloft-org/songloft-plugin-go-music-dl/releases) 下载 `.jsplugin.zip` 上传 → 能上传、启用、列表出现 = Bundle 模式 JS 插件系统可用（这是本报告唯一的高置信推断需落地确认项）。PASS 判据：插件状态非 error 且能在插件页完成一次搜索。
3. **路径 A（DLNA）实测**：播放器播放任一本地歌曲 → 找投屏/DLNA 入口（`features/dlna` 对应 UI）→ 等待 SSDP 发现列表（10–30s）→ 选中 LX06 → 判据：音箱开始出声、手机端进度/暂停可控制。记录：发现耗时、起播延迟、投 10 分钟是否断流、切歌是否需重新发现。
4. **路径 B（MIoT 插件）实测**：安装 songloft-plugin-miot 的 zip → 插件设置页选 LX06（小米账号扫码或 token）→ 用 go-music-dl 插件页搜索并在播放页投放 → 判据同上；另测「小爱语音口令播放」是否经 MIoT OnlineSearcher 生效。
5. **Bundle 特有检查**：插件设置里「对外可达地址」是否需手填手机 LAN IP（go-music-dl 文档警告：不填则直推 url 置空）；观察投放时流量走向（音箱直连 CDN 还是经手机中转，看手机流量/发热）。
6. **失败兜底记录**：若 DLNA 起播失败，用手机抓 SSDP/AVTransport（如 `ssdp-sniffer` 或路由器抓包）确认是发现失败还是 SetAVTransportURI 被拒，留档给 D-1。
