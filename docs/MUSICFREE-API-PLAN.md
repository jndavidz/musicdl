# musicdl → MusicFree API 改造计划

> 创建日期：2026-08-07（v1），2026-08-07（v2 - 补充 etc/ 插件分析 + 能力评估），2026-08-07（v3 - 评审整合修订）
> 目标版本：musicdl v2.13.4
> 项目地址：`/volume2/dev/projects/musicdl`（`X:\python\projects\musicdl`）

## 修订记录

> v3 基于 `docs/MUSICFREE-API-PLAN-REVIEW.md` 评审与第三方分析反馈整合修订。核心变更（按优先级）：
>
> | 优先级 | 修正项 | 类型 | 位置 |
> |--------|--------|------|------|
> | 🔴 P0 | resolve_url 没有现成入口，需新建按 song_id 直调的快路径 | 架构盲点 | §2.4.3、§4 阶段 0/1 |
> | 🔴 P0 | 需加阶段 0 技术验证 Spike | 实施顺序 | §4 |
> | 🔴 P0 | 绕过 MusicClient 直接实例化源客户端 | 实施修正 | §4 阶段 1 |
> | 🔴 P1 | QQ 官方 API "需要 Cookie" 因果说反 | 事实错误 | §3.1 |
> | 🔴 P1 | 酷我音质列表不存在（杜撰） | 事实错误 | §3.2 |
> | 🟡 P2 | lx-music 签名版标注"已覆盖"系误读 | 标注错误 | §6.1.5/§6.2.6 |
> | 🟡 P2 | 音质映射规则未具体化 | 遗漏 | §4 阶段 2 |
> | 🟡 P2 | getMusicInfo 应单开 /info 端点 | 优化 | §4 阶段 2 |
> | 🟡 P2 | 插件需加 cacheControl: no-cache | 遗漏 | §4 阶段 2 |
> | 🟢 P3 | QQ search_url 描述不完整 | 细节修正 | §3.1 |
> | 🟢 P3 | 能力评估补充：TIDAL 模板、Cookie 失效死路、测速重点为 parser 延迟 | 完善 | §7 |
>
> v3 复核补充（源码直读）：
> - 🔴 `MusicClient.parseplaylist` 未定义（`musicdl.py:216` CLI `-p` 死路径）→ 进一步支持绕过 MusicClient 的决策 → §4 阶段一 1.2
> - 🟡 `_parsewithvkeysapi` 端点订正：实际为 `api.vkeys.cn/music/tencent/song/link?mid={id}&quality={q}`（`qq.py:61`），非 `/v2/music/tencent/geturl` → §3.1 表格
> - 🟡 酷我 SVIP 池 `[:1]` 后实际只剩 `_parsewithliuyunidcapi`，`_parsewithccwuapi` 不在调用列表 → §3.2 表格
> - 🟡 源客户端实例化需显式传 `search_size_per_source`/`quark_parser_config`（不继承 MusicClient 硬编码）→ §4 阶段一 1.2b

---

## 1. 环境与系统概况

### 1.1 群晖 NAS 硬件环境

| 项目 | 描述 |
|------|------|
| 型号 | Synology NAS（DSM） |
| Python | 3.12.13（DSM 套件） |
| Docker | 运行多个容器 |
| 存储 | volume1（系统/数据）、volume2（开发/项目） |

### 1.2 目录映射

| 群晖路径 | Windows 映射 | 用途 |
|----------|-------------|------|
| `/volume2/dev/projects/musicdl` | `X:\python\projects\musicdl` | musicdl 项目代码 |
| `/volume2/dev/web/projects/musicfree-plugins` | `X:\web\projects\musicfree-plugins` | MusicFree 插件项目 |

### 1.3 已有 API 服务

| 服务 | 内网地址 | 外网地址 | 容器 | 说明 |
|------|---------|---------|------|------|
| 网易云音乐 API | `http://10.10.10.2:3000` | `https://ncmapi.pegbiotec.com:4433` | `ncm-api` | NeteaseCloudMusicApiEnhanced |
| 酷狗音乐 API | `http://10.10.10.2:3001` | `https://kgapi.pegbiotec.com:4433` | `kugou-api` | KuGouMusicApi 自托管 |
| Cookie 服务 | `http://10.10.10.2:3002` | 通过 Lucky 反代 | — | `shared/cookie-server.js` |

### 1.4 网络架构

```
外网 → Lucky 反向代理（HTTP Basic 认证）
         ├─ ncmapi.pegbiotec.com:4433 → 10.10.10.2:3000（网易云）
         ├─ kgapi.pegbiotec.com:4433  → 10.10.10.2:3001（酷狗）
         ├─ *.pegbiotec.com/cookie    → 10.10.10.2:3002（Cookie 分发）
         └─ (未来) musicdl-api        → 10.10.10.2:5000（本项目的 API 服务）

内网 → 10.10.10.2 直连（无认证）
```

### 1.5 MusicFree 插件项目现状

`musicfree-plugins` 项目结构：

```
musicfree-plugins/
├── netease/
│   ├── netease.js          # 构建产物（插件）
│   └── src.js              # 平台专属源码
├── kugou/
│   ├── kugou.js            # 构建产物（插件）
│   └── src.js              # 平台专属源码
├── shared/
│   ├── runtime.js          # 共享运行时（内外网切换、Cookie 管理、认证）
│   └── build.js            # 构建脚本
├── etc/                    # 参考插件（勿修改）
│   ├── 腾讯音乐 v2025.09.13.js
│   ├── QQ.js, QQ(独家音源) v4.js, QQ(迟言接口) v1.js
│   ├── 酷我 v0.1.0.js, 酷我(独家音源) v4.js, 酷我JHMS v0.1.0.js
│   ├── 闻音酷我 v1.0.0.js, yibai酷我流式 v1.js
│   ├── 元力KW v1.1.0.js, 元力QQ v0.1.0.js
│   ├── 碳酸氢钠 v1.39.js（聚合音源）
│   └── ...
└── docs/
    ├── API-SERVICES.md     # 现有 API 服务详情
    ├── COOKIE-MANAGEMENT.md # Cookie 管理说明
    └── TODO.md             # 任务单
```

**已有插件模式**：每个插件由 `shared/runtime.js`（共享运行时）+ 平台 `src.js`（平台逻辑）通过 `shared/build.js` 合并构建为单文件插件。

---

## 2. musicdl 源码理解

### 2.1 项目概览

| 项目 | 值 |
|------|-----|
| 版本 | v2.13.4 |
| 源码行数 | 约 15,000+ 行 |
| 音乐源数量 | 56 个（28 个主流平台 + 5 个有声书 + 6 个聚合网关 + 17 个第三方下载站） |
| 许可证 | PolyForm-Noncommercial-1.0.0（非商业用途） |
| Python 依赖 | 31 个（requests, curl-cffi, cryptography, mutagen, rich 等） |

### 2.2 核心架构

```
┌─────────────────────────────────────────────────────────┐
│                    MusicClient                          │
│  (musicdl/musicdl.py)                                   │
│  高层入口：管理所有源客户端，协调搜索/下载               │
├─────────────────────────────────────────────────────────┤
│                    BaseMusicClient                       │
│  (musicdl/modules/sources/base.py)                      │
│  抽象基类：统一 HTTP(get/post)、搜索框架、下载框架       │
│  - search() → _constructsearchurls() → _search() × N    │
│  - download() → _download() × N                         │
│  - 进度条（rich）、AudioLinkTester 验证                  │
├─────────────────────────────────────────────────────────┤
│  各源客户端（继承 BaseMusicClient）                      │
│  ┌───────┬───────┬───────┬───────┬───────┬──────┐      │
│  │ Netease│  QQ   │ Kuwo  │ Kugou │ Migu  │ ...  │      │
│  └───────┴───────┴───────┴───────┴───────┴──────┘      │
├─────────────────────────────────────────────────────────┤
│                    SongInfo (dataclass)                  │
│  song_name, singers, album, ext, file_size, duration,   │
│  lyric, cover_url, download_url, protocol(HLS/HTTP),    │
│  identifier, source, episodes, ...                      │
├─────────────────────────────────────────────────────────┤
│                    Utils                                 │
│  AudioLinkTester  → URL 验证 + 格式识别 + 文件大小      │
│  SongInfoUtils    → 标签写入(mutagen)、歌词保存、封面嵌入 │
│  LyricSearchClient → 多后端歌词搜索(lrclib/musixmatch)   │
│  cmd.py           → FFmpeg/Metaflac/MP4Box 命令工厂     │
│  XXXutils.py      → 各平台加密/签名工具                 │
└─────────────────────────────────────────────────────────┘
```

### 2.3 搜索流程（核心）

```
MusicClient.search(keyword)
  │
  ├── ThreadPoolExecutor (max_workers=10, 并行搜索所有源)
  │     │
  │     └── 每个源的 BaseMusicClient.search()
  │           │
  │           ├── _constructsearchurls(keyword, rule)
  │           │   → 构造分页 URL 列表
  │           │   → 返回 [search_url, ...] 或 [{url, data}, ...]
  │           │
  │           ├── ThreadPoolExecutor (每页并行)
  │           │     └── _search(keyword, search_url, ...)
  │           │           ├── HTTP 请求 → 解析 JSON
  │           │           └── 对每个搜索结果:
  │           │                 ├── 1. _parsewiththirdpartapis()
  │           │                 │    → 遍历第三方 API 列表（按优先级）
  │           │                 │    → 每个尝试获取下载链接
  │           │                 │    → 用 AudioLinkTester 验证
  │           │                 │    → 返回 SongInfo
  │           │                 └── 2. _parsewithofficialapiv1()
  │           │                      → 官方 API 获取下载链接
  │           │                      → 补充歌词信息
  │           │                      → 返回 SongInfo
  │           │
  │           └── 去重 → 返回 list[SongInfo]
  │
  └── 合并各源结果 → 返回 dict[str, list[SongInfo]]
```

### 2.4 关键设计决策

#### 2.4.1 第三方 API 优先策略

**musicdl 的关键优势**：对于 QQ 音乐、酷我音乐、网易云等平台，内置了大量第三方解析 API。这些第三方 API **无需平台 Cookie 即可获取 FLAC 无损音质的下载链接**。

代码中的关键逻辑（以 QQ 为例）：

```python
def _parsewiththirdpartapis(self, search_result, request_overrides):
    # 如果配置了 Cookie → 跳过第三方 API（走官方 API）
    if self.default_cookies or request_overrides.get('cookies'):
        return SongInfo(source=self.source)
    # 按优先级遍历第三方 API
    l1_parser_funcs = [SVIP 级别]  # 最高优先级
    l2_parser_funcs = [VIP 级别]
    l3_parser_funcs = [普通级别]
    for parser_func in (l1 + l2 + l3):
        song_info = parser_func(search_result, request_overrides)
        if song_info 有效: break
    return song_info
```

#### 2.4.2 Hi-Fi 过滤

当前 `musicdl.py` 硬编码了 Hi-Fi 过滤逻辑：

```python
# 在 printandselectsearchresults() 中
if raw_ext == 'mp3' or filesize_mb < 10.0:
    continue  # 排除 MP3 及小于 10MB 的文件
```

API 模式下需绕过此过滤（或使其可配置）。

#### 2.4.3 下载链接时效性（⚠️ 含结构性盲点）

搜索过程中通过 `AudioLinkTester` 验证的下载链接可能有时效性（部分平台 CDN 链接几小时后过期）。API 模式需要实时重新解析，而非返回搜索时缓存的链接。

> 🔴 **结构性盲点（v3 修订）**：musicdl 全仓库**不存在** `resolve_url`/按 song_id 重解析的入口。
>
> - `_parsewith*` 函数入参是搜索时的原始 `search_result` 字典（从中提取 `MUSICRID`/`musicrid`，如 `kuwo.py:62,80,97`），**不是** bare song_id
> - 因此 `getMediaSource(item, quality)` 收到已存的 `musicItem`（含 `id`）后，**不能直接** `_parsewiththirdpartapis(musicItem.id)`
> - `SongInfo.download_url` 在 `_search` 期间一次性解析存入，之后无按 identifier 刷新的路径
>
> **解决方案**：新建一批吃 song_id 的 `_parsewith*byid` 方法（etc/ 插件已验证可行——其 `getMediaSource` 几乎全部用 song_id 直调第三方端点拿 URL，不重搜索）。详见 §4 阶段 0 技术验证与阶段 5 能力增强。
>
> ⏱️ **MusicFree 10 秒超时约束**：插件每次方法调用 **10 秒执行超时**（`musicfree-protocol.md:30,86`）。musicdl 一次完整搜索（多源并行 + 每候选 `AudioLinkTester` HEAD/GET 探测 + 遍历多第三方 API）远超 10 秒。因此 `getMediaSource` 必须是**一次快速 HTTP 调用** `/api/{source}/url?id=xxx`，后端按 id 直调快路径，**不能重跑完整搜索**。
>
> 🔴 **Cookie 失效死路**：当前配了过期 Cookie 会走 `_parsewiththirdpartapis` 第 316 行 return 空 → 跳过第三方 → 官方 API 空 purl → 静默无结果。检测到 Cookie 失效应**自动回退第三方 API** 而非死等（见 §7.4 detector 设计）。

---

## 3. 目标源详细分析（QQ 音乐 + 酷我音乐）

### 3.1 QQ 音乐 (QQMusicClient)

#### 基本信息

| 属性 | 值 |
|------|-----|
| 类名 | `QQMusicClient` |
| source | `'QQMusicClient'` |
| 搜索端点 | `https://u.y.qq.com/cgi-bin/musicu.fcg`（加密/普通两种） |
| 搜索方法 | `_search`（`search_url` 为 `dict`，含 `url` + `data` + `page_no`，加密端点时带 `params`，`data` 为序列化后的 bytes） |
| 搜索参数 | `search_type=7`（歌曲）、`num_per_page`、`page_num` |
| 歌词获取 | 官方 API `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg` |
| 封面 URL | `https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg` |

#### 第三方 API 列表（按优先级）

| 级别 | 方法名 | 端点 | 说明 |
|------|--------|------|------|
| **SVIP** | `_parsewithvkeysapi` | `api.vkeys.cn/music/tencent/song/link?mid={id}&quality={q}` | 最高优先级，稳定返回 FLAC（v3 复核：原写 `/v2/music/tencent/geturl` 有误，见 `qq.py:61`） |
| **SVIP** | `_parsewithxcvtsapi` | 第三方 | 备选 |
| **SVIP** | `_parsewithxingmianapi` | 第三方（星冕） | 备选 |
| **SVIP** | `_parsewith317akapi` | 第三方（317ak） | 备选 |
| **VIP** | `_parsewithxianyuwapi` | 第三方（xianyuw） | 仅无 Cookie 时可用 |
| **VIP** | `_parsewithnkiapi` | 第三方（nki） | 备选 |
| **VIP** | `_parsewithhk0ccapi` | 第三方（hk0cc） | 备选 |
| **VIP** | `_parsewithtangapi` | 第三方（tang） | 备选 |
| 普通 | `_parsewithcyapi` | 第三方 | 仅 MP3/M4A |
| 普通 | `_parsewithxunhuisiapi` | 第三方 | 仅 MP3/M4A |
| 普通 | `_parsewithlxmusicapi` | 第三方 | 仅 MP3/M4A |
| 普通 | `_parsewithyutangxiaowuapi` | 第三方 | 仅 MP3/M4A |
| 不稳定 | `_parsewithlpzapi` | 第三方 | 不稳定 |
| 官方 | `_parsewithofficialapiv1` | 官方 API | **不要求 Cookie**，传空凭据可调；有 Cookie 时 `_parsewiththirdpartapis` 提前返回跳过第三方走官方 |

#### 音质映射

```python
# 官方 API 音质等级（SongFileType.SORTED_QUALITIES，高→低）
# 依据 qqutils.py:38-52
MASTER   AI00 .flac  臻品母带2.0
ATMOS_2  Q000 .flac  臻品全景声
ATMOS_51 Q001 .flac  杜比全景声
FLAC     F000 .flac  无损
OGG_640  O801 .ogg   640kbps
OGG_320  O800 .ogg   320kbps
MP3_320  M800 .mp3   320kbps  （注意：M800 是 MP3 320kbps，不是 FLAC）
MP3_128  M500 .mp3   128kbps
ACC_192  C600 .m4a   192kbps
ACC_96   C400 .m4a   96kbps
ACC_48   C200 .m4a   48kbps

# 加密端点（EncryptedSongFileType）对应 .mflac/.mgg 格式
# 第三方 API（ThirdPartVKeysAPISongFileType）vkeys.cn 等自动返回最高可用音质
```

#### 关键代码路径

```python
# 初始化：不传 Cookie 以启用第三方 API
QQMusicClient(search_size_per_source=10, disable_print=True)

# 搜索构造
_constructsearchurls(keyword, rule, request_overrides) → list[dict]

# 搜索执行
_search(keyword, search_url, request_overrides, song_infos, progress)

# 解析流程（每个搜索结果）
_parsewiththirdpartapis(search_result, request_overrides)
  → 遍历 l1→l4 parser_funcs
  → 每个返回 SongInfo(with_valid_download_url)
  → 第一个有效即停止

# 回退（不要求 Cookie，传空凭据亦可调）
_parsewithofficialapiv1(search_result, song_info_flac, ...)
  → 有 Cookie 时走此路径，无 Cookie 时第三方已成功则跳过
```

### 3.2 酷我音乐 (KuwoMusicClient)

#### 基本信息

| 属性 | 值 |
|------|-----|
| 类名 | `KuwoMusicClient` |
| source | `'KuwoMusicClient'` |
| 搜索端点 | `http://www.kuwo.cn/search/searchMusicBykeyWord?` |
| 搜索方法 | `_search`（`search_url` 为 `str` URL） |
| 搜索参数 | `pn`（页码）、`rn`（每页数）、`all`（关键词） |
| 歌词获取 | 官方 API `m.kuwo.cn/newh5/singles/songinfoandlrc` |
| 封面 URL | 从搜索结果中提取 `imgXXX.kuwo.cn/star/albumcover/` |

#### 第三方 API 列表（按优先级）

| 级别 | 方法名 | 端点 | 说明 |
|------|--------|------|------|
| **SVIP** | `_parsewithliuyunidcapi` | `kwdec.liuyunidc.cn` | 高优先级；`[:1]` 切分后 SVIP 池实际**只剩此方法** |
| **SVIP** | `_parsewithccwuapi` | 第三方 | 被 `[:1]` 排除，实际不在调用列表（v3 复核：原"同上"表述模糊） |
| **VIP** | `_parsewithcggapi` | `cenguigui.cn` | 稳定，返回 FLAC |
| **VIP** | `_parsewithlxmusicapi` | 第三方 | 备选 |
| **VIP** | `_parsewithnxinxzapi` | 第三方 | 备选 |
| **VIP** | `_parsewithhaitangwapi` | 第三方（海棠） | 备选 |
| **VIP** | `_parsewithnobbapi` | 第三方 | 备选 |
| 不稳定 | `_parsewithguyueiapi` | 第三方 | 当前已禁用 [:0] |
| 不稳定 | `_parsewithyyy001api` | 第三方 | 当前已禁用 [:0] |
| 不稳定 | `_parsewithgdstudioapi` | 第三方 | 当前已禁用 [:0] |
| 官方 | `_parsewithofficialapiv1` | 官方 API | **不要求 Cookie**（同 QQ，有 Cookie 时 `_parsewiththirdpartapis` 跳过第三方走官方） |

#### 音质映射

```python
# 酷我音质定义
MUSIC_QUALITIES = [(22000, 'flac'), (320, 'mp3')]  # 非加密（kuwo.py:36）
ENC_MUSIC_QUALITIES = [(4000, '4000kflac'), (2000, '2000kflac'),
                       (320, '320kmp3'), (192, '192kmp3'), (128, '128kmp3')]  # 加密

# ⚠️ v3 修订：各第三方 API 的音质序列各不相同，不存在统一的遍历列表
# _parsewithliuyunidcapi (kuwo.py:192): ['master','atmos_plus','atmos','flac','320k'][:-1]
# _parsewithnxinxzapi / _parsewithhaitangwapi: ['lossless','exhigh','standard']
# _parsewithcggapi: ['standard','exhigh','lossless','hires']
# 官方: MUSIC_QUALITIES 从高到低
```

#### 关键代码路径

```python
# 初始化：不传 Cookie 以启用第三方 API
KuwoMusicClient(search_size_per_source=10, disable_print=True)

# 搜索构造
_constructsearchurls(keyword, rule, request_overrides) → list[str]

# 搜索执行
_search(keyword, search_url, request_overrides, song_infos, progress)

# 解析流程
_parsewiththirdpartapis(search_result, request_overrides)
  → 先尝试 l1_parser_funcs[:1]（仅取第一个 SVIP）
  → 再遍历 l2_parser_funcs（VIP）
  → 最后 l3_parser_funcs（不稳定，目前 [:0] 禁用）
  → 第一个有效即停止

# 回退（不要求 Cookie，传空凭据亦可调）
_parsewithofficialapiv1(search_result, song_info_flac, ...)
  → 有 Cookie 时走此路径，无 Cookie 时第三方已成功则跳过
```

### 3.3 其他源（后续加入）

| 源 | 模块 | 第三方 API | 配置需求 | 优先级 |
|----|------|-----------|---------|--------|
| 咪咕音乐 | `MiguMusicClient` | 无（仅官方 API） | 无需 Cookie，免费 FLAC | ⭐⭐⭐ |
| B站音源 | `BilibiliMusicClient` | 无（仅官方 API） | 有默认 Cookie，开箱即用 | ⭐⭐⭐ |
| YouTube Music | `YouTubeMusicClient` | 8 个 | 无需 Cookie，ytmusicapi | ⭐⭐⭐ |
| 汽水音乐 | `SodaMusicClient` | 1 个（qiuyu520） | 可能需要 device_id/x_helios | ⭐⭐ |
| Apple Music | `AppleMusicClient` | 无 | 无 Cookie 只能预览 30s | ⭐ |
| Qobuz | `QobuzMusicClient` | 7 个 | 有内置免费账户 | ⭐⭐ |
| TIDAL | `TIDALMusicClient` | 无 | 必须自己账号 Cookie | ⭐ |

---

## 4. 后续实施清单

> v3 修订：由原 5 阶段扩展为 6 阶段。新增**阶段 0（技术验证）**作为最关键的前置步骤，新增**阶段 5（musicdl 能力增强）**，并修订阶段 1（绕过 MusicClient）、阶段 2/3（补 cacheControl/音质映射/getMusicInfo 路径）、阶段 4（Docker 部署）。

### 阶段 0：技术验证 Spike（新增，最高优先）

**目标**：在整个改造前，验证最核心的可行性假设——"绕过搜索、用 song_id 直接调第三方/官方端点拿到 FLAC"。

**待办项**：

- [ ] 0.1 写一个 50 行脚本，验证"用 song_id 直接调 lx-music 签名 API（`88.lxmusic.xn--fiqs8s/lxmusicv4/url/{tx|kw}/{id}/{quality}`）拿到 FLAC/24bit"
- [ ] 0.2 验证"用 song_id 直接调酷我无 Cookie 官方端点 `nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid={id}&br=2000kflac` 拿到 FLAC"
- [ ] 0.3 验证"`_parsewiththirdpartapis` 现有函数的 `search_result` → id 那步能否抽出为独立函数复用"
- [ ] 0.4 计时：单次按 id 解析往返耗时是否 < 500ms（满足 MusicFree 10 秒超时余量）
- [ ] 0.5 如 0.1/0.2 均失败，退回"搜索时缓存链接 + 短 TTL"折中方案，并重新评估整体可行性

### 阶段一：FastAPI 后端服务（musicdl 层，修订）

**目标**：在群晖上运行一个 FastAPI 服务，将 musicdl 的搜索/URL解析/歌词功能包装为 HTTP API。

**待办项**：

- [ ] 1.1 创建 `server/` 目录，放置 API 服务代码
- [ ] 1.2 **绕过 MusicClient，直接实例化目标源客户端**（`QQMusicClient(...)`、`KuwoMusicClient(...)`），自己编排 endpoint。原因：① `MusicClient.search()` 无条件用 `rich.progress.Progress` 和 logger（`musicdl.py:162-176`），API 模式无 TTY 会报错；② **`MusicClient` 未定义 `parseplaylist` 方法**（`musicdl.py:216` 的 CLI `-p` 是死路径，会 AttributeError），编排层本身有 bug；③ 源客户端 `disable_print=True` 已可静默
- [ ] 1.2b **显式传入源客户端参数**：实例化时传 `search_size_per_source` 与 `quark_parser_config`（`MusicClient.__init__` 硬编码了 `source_limits` 与内嵌 Quark cookie，`musicdl.py:57-79`，直接实例化不会继承）
- [ ] 1.3 实现通用路由模式：
  - `GET /api/{source}/search?q=xxx&page=1` → 搜索（走 `client.search()`）
  - `GET /api/{source}/url?id=xxx&quality=flac` → **按 song_id 快速解析**（阶段 5 的 `_parsewith*byid` 方法，或阶段 0 验证的快路径）
  - `GET /api/{source}/info?id=xxx` → 单曲元数据（封面/专辑/时长，供 getMusicInfo）
  - `GET /api/{source}/lyric?id=xxx` → 歌词
- [ ] 1.4 实现 `resolve_url()` 核心函数：
  - 根据 `source` 路由到对应源客户端
  - **按 id 调用 `_parsewith*byid` 获取最新链接**（非重跑搜索）
  - 失败时回退官方 `_parsewithofficialapiv1`（按 id 调 vkey）
  - 返回 `{url, format, size, headers}`
- [ ] 1.5 移除 Hi-Fi 过滤（API 模式不需要；绕过 MusicClient 后天然规避）
- [ ] 1.6 歌词：使用 `LyricSearchClient` 多后端搜索
- [ ] 1.7 后端用 `asyncio.to_thread` 包裹同步调用（musicdl 是同步 + 线程池），避免阻塞 FastAPI 事件循环
- [ ] 1.8 测试：验证 QQ 和酷我的搜索/URL解析均正常，且单次 url 解析 < 500ms

### 阶段二：QQ 音乐插件（修订）

**目标**：在 `musicfree-plugins` 项目中创建 QQ 音乐插件，遵循现有的 `shared/runtime.js` 模式。

**待办项**：

- [ ] 2.1 在 `musicfree-plugins/qq/` 下创建 `src.js`
- [ ] 2.2 实现插件接口：
  - `search(query, page, type)` → 调用 `/api/qq/search`
  - `getMediaSource(mediaItem, quality)` → 调用 `/api/qq/url?id=xxx`（**只做一次快速 HTTP 调用，不重跑搜索**）
  - `getMusicInfo(musicItem)` → 调用 `/api/qq/info?id=xxx`（**单开 info 端点，非 search 后过滤**）
  - `getLyric(musicItem)` → 调用 `/api/qq/lyric`
- [ ] 2.3 **插件元字段必须设 `cacheControl: "no-cache"`**（否则 MusicFree 缓存过期链接，播放失败）
- [ ] 2.4 音质映射规则（MusicFree `low/standard/high/super` → QQ）：
  - `super → MASTER/FLAC(RS01/F000)`、`high → MP3_320(M800)`、`standard → MP3_128(M500)`、`low → ACC_48(C200)`
  - 依赖 APP 自动按更高/更低重试，插件逻辑极简
- [ ] 2.5 数据转换：`SongInfo` → MusicFree 的 `musicItem` 格式
- [ ] 2.6 构建：运行 `shared/build.js` 生成 `qq.js`
- [ ] 2.7 测试：在 MusicFree 中加载插件，验证搜索/播放/歌词

### 阶段三：酷我音乐插件（修订）

**目标**：类似 QQ 音乐，创建酷我音乐插件。

**待办项**：

- [ ] 3.1 在 `musicfree-plugins/kuwo/` 下创建 `src.js`
- [ ] 3.2 实现插件接口（同 QQ 模式，含 getMediaSource 快速调用 + getMusicInfo 走 /info）
- [ ] 3.3 元字段设 `cacheControl: "no-cache"`
- [ ] 3.4 音质映射：`super→hires`、`high→lossless/flac`、`standard→exhigh/320k`、`low→standard/128k`
- [ ] 3.5 构建：运行 `shared/build.js` 生成 `kuwo.js`
- [ ] 3.6 测试：验证搜索/播放/歌词

### 阶段四：部署与运维（修订）

**目标**：在群晖上部署 API 服务，配置开机自启和反向代理。

**待办项**：

- [ ] 4.1 **用 Docker 部署**（与现有 ncm-api/kugou-api 一致）。原因：musicdl 依赖 `curl_cffi`/`cryptography`/`pywidevine`，DSM 裸装 Python 3.12 编译易缺系统库
- [ ] 4.2 构建 image：`pip install musicdl fastapi uvicorn`，`uvicorn main:app --workers 1 --host 0.0.0.0 --port 5000`
- [ ] 4.3 配置 DSM 开机自启（Docker 容器 auto-restart）
- [ ] 4.4 配置 Lucky 反向代理：
  - 子域名：`musicdl-api.pegbiotec.com:4433` → `10.10.10.2:5000`
  - 添加 HTTP Basic 认证（与现有模式一致）
- [ ] 4.5 更新 `docs/API-SERVICES.md` 和 `docs/TODO.md`

### 阶段五：musicdl 能力增强（新增）

**目标**：把 etc/ 插件提取的端点/密钥和账号检测能力真正集成进 musicdl，补齐 `resolve_url` 快路径。

**待办项**：

- [ ] 5.1 新增 `_parsewithlxmusicsignedapi`（lx-music v4 签名协议，一套密钥双平台：QQ `/url/tx/{mid}` + 酷我 `/url/kw/{id}`）
- [ ] 5.2 新增 `_parsewithnmobikuwobyid`（酷我无 Cookie 官方 `nmobi.kuwo.cn/mobi.s`，直接 convert_url_with_sign）
- [ ] 5.3 新增 `_parsewithikunshareapi`/`_parsewithnkipwbyid`/`_parsewithcyapibyid` 等（etc/ 提取的端点，见 `docs/ETC-PLUGINS-ANALYSIS.md` 第 4 章）
- [ ] 5.4 新建 `detector.py`：Cookie 有效性 + VIP 级别检测（照 TIDAL 模板 `tidalutils.py:430-447`）
- [ ] 5.5 在 `_parsewiththirdpartapis` 加 parser 健康度缓存（成功/失败计数 + 冷却跳过 + 动态排序，替代静态 l1-l4）
- [ ] 5.6 **Cookie 失效时自动回退第三方 API**（修复 §2.4.3 的死路）

---

## 5. 关键设计决策记录

### 5.1 为什么选择 musicdl 而非第三方公共 API

| 对比项 | musicdl | 第三方公共 API（如 etc/ 中的插件） |
|--------|---------|-----------------------------------|
| 维护性 | 一个代码库维护所有源 | 每个插件独立维护，来源不一 |
| 稳定性 | 内置多个备用 API，自动切换 | 单一 API 失效即全挂 |
| 音质 | 自动选择最高可用音质（FLAC） | 部分仅支持 MP3 |
| 可控性 | 自有代码，可自行修复 | 依赖第三方维护 |
| 部署 | 需 Python 环境 | 纯 JS，无额外依赖 |

### 5.2 与现有插件架构的整合

现有 `netease/` 和 `kugou/` 插件使用 `shared/runtime.js` + `shared/build.js` 模式。新插件（QQ、酷我）应遵循相同模式，但后端从 Node.js API 服务改为 musicdl 的 Python API 服务。

**差异点**：
- 现有网易云/酷狗插件 → 后端是 Node.js API（Docker 容器）
- 新插件（QQ/酷我） → 后端是 Python musicdl API（直接在群晖上运行）

### 5.3 Cookie 策略

| 源 | 策略 | 说明 |
|----|------|------|
| QQ 音乐 | **不配置 Cookie**，走第三方 API | 第三方 API 更稳定，音质更高 |
| 酷我音乐 | **不配置 Cookie**，走第三方 API | 同 QQ 音乐 |
| 咪咕/B站/YouTube | 无 Cookie 需求 | 开箱即用 |
| 其他 | 视情况配置 | 按需处理 |

---

## 6. etc/ 参考插件分析（QQ 音乐 + 酷我音乐）

> 以下分析基于 `musicfree-plugins/etc/` 目录中的现有 MusicFree 插件，提取其 API 端点、认证方式、音质映射等关键信息，用于改进 musicdl 的 API 实现。

### 6.1 QQ 音乐插件分析

#### 6.1.1 插件清单

| 文件 | 平台名 | 版本 | 作者 |
|------|--------|------|------|
| `QQ.js` | QQ音乐 | 2 | 自用 |
| `QQ(独家音源) v4.js` | QQ(独家音源) | 4 | 竹佀＆玥然OvO |
| `QQ(迟言接口) v1.js` | QQ(迟言接口) | 1 | 竹佀 |
| `腾讯音乐 v2025.09.13.js` | 腾讯音乐 | 2025.09.13 | Thomas喲 |
| `元力QQ v0.1.0.js` | 元力QQ | 0.1.0 | 科技长青 |
| `西瓜糖(Q音) v2 (已配置key).js` | QQ音乐2 | 2 | 玥然OvO |

#### 6.1.2 官方 API 端点（所有插件通用）

| 功能 | 端点 | 方法 | 说明 |
|------|------|------|------|
| **搜索** | `https://u.y.qq.com/cgi-bin/musicu.fcg` | POST | module: `music.search.SearchCgiService`, method: `DoSearchForQQMusicDesktop` |
| **专辑信息** | `https://u.y.qq.com/cgi-bin/musicu.fcg` | GET | module: `music.musichallAlbum.AlbumSongList` |
| **歌手歌曲** | `http://u.y.qq.com/cgi-bin/musicu.fcg` | GET | module: `music.web_singer_info_svr` |
| **歌单** | `http://i.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg` | GET | 参数: `disstid={id}` |
| **排行榜** | `https://u.y.qq.com/cgi-bin/musicu.fcg` | GET | module: `musicToplist.ToplistInfoServer` |
| **推荐标签** | `https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_tag_conf.fcg` | GET | 无需认证 |
| **歌词** | `http://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg` | GET | 返回 Base64 编码的 JSONP，需解码 |
| **Vkey(音源)** | `https://u6.y.qq.com/cgi-bin/musicu.fcg` | POST | module: `vkey.GetVkeyServer`, 需要 `uin` + `qm_keyst` Cookie |

#### 6.1.3 第三方音源 API（核心差异点）

| 插件 | 域名 | 认证方式 | 音质映射 | 说明 |
|------|------|---------|---------|------|
| **QQ.js** | `api.nki.pw` | URL 参数 `apikey`（硬编码 `ed34917b...`） | `low→hq, standard→accom, high→pq, super→sq` | 字段名非标准，注意映射 |
| **独家音源 v4** | `88.lxmusic.xn--fiqs8s` | SHA-256 签名（`SCRIPT_MD5=1888f98...` + `SECRET_KEY=JaJ?a7...`） | `low→128k, standard→320k, high→flac, super→flac24bit` | 签名算法: `sha256(path + md5 + key)` |
| **迟言接口 v1** | `cyapi.top` | 硬编码 key `1ffdf573...` | 忽略 quality，返回单一 URL | 最简单的实现 |
| **腾讯音乐** | 多层回退 | `uin` + `qm_keyst` Cookie / ikunshare 卡密 / 元力菌 / Huibq | `low→M500.mp3, standard→M800.mp3, high→F000.flac, super→RS01.flac` | 最复杂的回退策略 |
| **元力QQ** | `musicapi.haitangw.net` | 无 | `low/standard/high→exhigh, super→lossless` | 简单直接 |
| **西瓜糖(Q音)** | `api.nki.pw` | 同 QQ.js | 同 QQ.js | 同 QQ.js 同一代码 |

#### 6.1.4 QQ 音质编码对照表

| 内部编码 | 前缀 | 扩展名 | 比特率 | 说明 |
|---------|------|--------|--------|------|
| size_48aac | C200 | .m4a | 48kbps | 最低 |
| size_96aac | C400 | .m4a | 96kbps | 低 |
| size_128mp3 | M500 | .mp3 | 128kbps | 标准 |
| size_192aac | C600 | .m4a | 192kbps | 中等 |
| size_320mp3 | M800 | .mp3 | 320kbps | 高 |
| size_96ogg | O400 | .ogg | 96kbps | OGG 低 |
| size_192ogg | O600 | .ogg | 192kbps | OGG 高 |
| size_ape | A000 | .ape | 无损 | APE 无损 |
| size_flac | F000 | .flac | 无损 | FLAC 无损 |
| size_hires | RS01 | .flac | 24bit/96kHz | Hi-Res |
| size_new[2] | Q001 | .flac | — | 杜比全景声 |
| size_new[1] | Q000 | .flac | — | 臻品全景声 |
| size_new[0] | AI00 | .flac | — | 臻品母带2.0 |

#### 6.1.5 现有 musicdl QQ 已覆盖的情况

musicdl 的 `QQMusicClient` 已内置了上述第三方 API 中的：
- `_parsewithvkeysapi` → 对应 `api.nki.pw` 类似逻辑（vkeys.cn）
- `_parsewithxingmianapi` → 对应第三方
- `_parsewithxcvtsapi` → 对应第三方
- `_parsewith317akapi` → 对应第三方
- `_parsewithlxmusicapi` → LXMusic 生态（**⚠️ v3 修订**：现有为**非签名版**；etc/ 独家音源 v4 的是**签名 v4 协议** `88.lxmusic.xn--fiqs8s`，两者**非同一套**，签名版对 musicdl 为新增，见 §4 阶段 5.1）
- 官方 API 已有 `_parsewithofficialapiv1` → 对应腾讯音乐官方 Vkey 流程

**新增建议**：可从 etc/ 插件中提取以下有用信息补充到 musicdl：
- `api.nki.pw` 的 API key（已硬编码在插件中，可添加到 musicdl 作为备用）
- `cyapi.top` 的 API key（已硬编码）
- `musicapi.haitangw.net` 的 API 端点（元力菌）
- 腾讯音乐的完整 Cookie 字段清单（`uin`, `qm_keyst`, `authst` 等）
- 更完整的音质映射表（特别是 RS01 Hi-Res 和 Q000/Q001 新格式）

### 6.2 酷我音乐插件分析

#### 6.2.1 插件清单

| 文件 | 平台名 | 版本 | 作者 |
|------|--------|------|------|
| `酷我 v0.1.0.js` | 酷我 | 0.1.0 | JHMS_Channel |
| `酷我(独家音源) v4.js` | 酷我(独家音源) | 4 | 竹佀＆玥然OvO |
| `酷我(念心音源) v1.0.0.js` | 酷我(念心音源) | 1.0.0 | 玥然OvO |
| `酷我JHMS v0.1.0.js` | 酷我JHMS | 0.1.0 | JHMS_Channel |
| `闻音酷我 v1.0.0.js` | 闻音酷我 | 1.0.0 | 竹佀 |
| `闻音酷我 v2重构版.js` | 闻音酷我 | 2 | 竹佀 |
| `yibai酷我流式 v1.js` | yibai酷我流式 | 1 | 竹佀 |
| `元力KW v1.1.0.js` | 元力KW | 1.1.0 | 科技长青（代码混淆） |

#### 6.2.2 官方 API 端点（所有插件通用）

| 功能 | 端点 | 方法 | 参数 |
|------|------|------|------|
| **搜索歌曲** | `http://search.kuwo.cn/r.s` | GET | `client=kt&all={keyword}&pn={page}&rn=30&uid=2574109560&ver=kwplayer_ar_8.5.4.2&vipver=1&ft=music&cluster=0&encoding=utf8&rformat=json` |
| **搜索专辑/歌手** | 同上 | GET | 同上，`ft` 改为 `album`/`artist` |
| **歌词** | `https://kuwo.cn/openapi/v1/www/lyric/getlyric` | GET | `musicId={id}&httpStatus=1` |
| **歌曲信息** | `http://m.kuwo.cn/newh5/singles/songinfoandlrc` | GET | `musicId={id}&httpStatus=1` |
| **排行榜列表** | `http://wapi.kuwo.cn/api/pc/bang/list` | GET | 无 |
| **排行榜详情** | `http://kbangserver.kuwo.cn/ksong.s` | GET | `from=pc&fmt=json&type=bang&data=content&id={id}` |
| **歌单详情** | `http://nplserver.kuwo.cn/pl.svc` | GET | `op=getlistinfo&pid={id}&pn={page}&rn={size}` |
| **推荐歌单标签** | `http://wapi.kuwo.cn/api/pc/classify/playlist/getTagList` | GET | `cmd=rcm_keyword_playlist` |
| **推荐歌单列表** | `http://wapi.kuwo.cn/api/pc/classify/playlist/getTagPlayList` | GET | `id={tag.id}&pn={page}` |
| **封面图片** | `https://img4.kuwo.cn/star/albumcover/` | GET | 路径拼接 |

#### 6.2.3 第三方音源 API（核心差异点）

| 插件 | 域名 | 认证方式 | 音质映射 | 说明 |
|------|------|---------|---------|------|
| **酷我 v0.1.0** | `api.music.lerd.dpdns.org` | POST JSON | `low→128k, standard→320k, high→flac, super→hires` | 支持 code=303 动态跳转 |
| **独家音源 v4** | `88.lxmusic.xn--fiqs8s` | SHA-256 签名 | `low→128k, standard→320k, high→flac, super→flac24bit` | 同 QQ 独家音源的同套签名 |
| **念心音源 v1** | `music.nxinxz.com` | 无 | `low→standard, standard→exhigh, high→lossless, super→lossless` | `super` 无 hires |
| **闻音酷我 v1** | `kw-api.cenguigui.cn` | 无 | `low→standard, standard→exhigh, high→lossless, super→hires` | 全功能代理（搜索+音源） |
| **闻音酷我 v2** | `kw-api.cenguigui.cn` | 无 | `low→standard, standard→exhigh, high→lossless, super→hires` | 仅音源+歌词代理 |
| **yibai酷我流式** | `kwdec.942240.xyz` | 无 | 7级：`128k→320k→flac→hires→atmos→atmos_plus→master` | 支持最多音质等级 |
| **元力KW** | 代码混淆（推测直连官方） | 无显式 | `low→128k, standard→320k, high→flac, super→hires` | 代码混淆，无法提取 |

#### 6.2.4 酷我音质对照表

| 内部编码 | 比特率 | 格式 | 第三方 API 参数 |
|---------|--------|------|----------------|
| 128kmp3 | 128kbps | MP3 | `standard` |
| 320kmp3 | 320kbps | MP3 | `exhigh` |
| 2000kflac | CD 无损 | FLAC | `lossless` |
| 4000kflac | 24bit/96kHz | FLAC | `hires` |
| 20000kflac | 24bit/192kHz | FLAC | 部分插件支持 |
| atmos | 杜比全景声 | — | yibai酷我流式专用 |
| master | 母带 | — | yibai酷我流式专用 |

#### 6.2.5 重要发现：酷我无 Cookie 官方端点

**`nmobi.kuwo.cn/mobi.s`** 是酷我音乐一个**无需 Cookie 即可获取无损音源**的官方端点（来自 `腾讯音乐 v2025.09.13.js` 的最终回退链）：

```
http://nmobi.kuwo.cn/mobi.s?f=web&source={source}&user=0&type=convert_url_with_sign&rid={songId}&br={br}
```

| 参数 | 说明 |
|------|------|
| `rid` | 酷我歌曲 ID（数字） |
| `br` | 音质：`128kmp3`、`320kmp3`、`2000kflac`、`20000kflac` |
| `source` | 渠道标识（如 `kwplayerhd_ar_4.3.0.8_tianbao_T1A_qirui.apk`） |
| `user` | 用户 ID（可填 `0` 或随机值） |

**特点**：完全匿名、无需任何 Cookie；支持 FLAC 无损（2000kflac）和 Hi-Res（20000kflac）；返回 302 重定向到真实 CDN。**musicdl 目前未覆盖，新增价值极高。**

#### 6.2.6 现有 musicdl 酷我已覆盖的情况

musicdl 的 `KuwoMusicClient` 已内置了上述第三方 API 中的：
- `_parsewithcggapi` → 对应 `cenguigui.cn`（闻音酷我使用）
- `_parsewithlxmusicapi` → LXMusic 生态（**⚠️ v3 修订**：现有为**非签名版**；etc/ 独家音源 v4 的是**签名 v4 协议** `88.lxmusic.xn--fiqs8s`，两者**非同一套**）
- `_parsewithnxinxzapi` → 对应 `music.nxinxz.com`（念心音源使用）
- `_parsewithhaitangwapi` → 对应元力菌生态
- `_parsewithliuyunidcapi` → 对应第三方

**新增建议**：
- 可添加 `api.music.lerd.dpdns.org` 作为备用（酷我 v0.1.0/JHMS 使用，支持 code=303 动态跳转）
- 可添加 `kwdec.942240.xyz` 作为备用（yibai酷我流式，支持 atmos/master 音质）
- 可添加 `kw-api.cenguigui.cn` 作为备用（闻音酷我使用，但 cggapi 已覆盖）

### 6.3 提取有用的密钥/接口到 musicdl

#### 已提取的第三方 API 密钥

| 来源 | 域名 | 密钥 | 用途 |
|------|------|------|------|
| QQ.js | `api.nki.pw` | `apikey=ed34917b6e3ca97d609a82e73c82599c176a07a4bcad5f5f7ab4ee95b3fa90ba` | QQ 音源解析 |
| QQ(迟言) | `cyapi.top` | `apikey=1ffdf5733f5d538760e63d7e46ba17438d9f7b9dfc18c51be1109386fd74c3a1` | QQ 音源解析 |
| QQ(独家) | `88.lxmusic.xn--fiqs8s` | `SCRIPT_MD5=1888f9865338afe6d5534b35171c61a4`, `SECRET_KEY=JaJ?a7Nwk_Fgj?2o:znAkst` | QQ+酷我 独家音源 |
| 腾讯音乐 | `api.ikunshare.com` | 用户自定义 `ikun_key` 卡密 | QQ 音源回退 |
| 腾讯音乐 | `lxmusicapi.onrender.com` | `X-Request-Key: share-v2` | QQ 音源回退 |

#### 已提取的 Cookie 字段

| 平台 | 字段 | 说明 | 来源 |
|------|------|------|------|
| QQ | `uin` | QQ 号（数字） | 腾讯音乐 v2025.09.13 |
| QQ | `qm_keyst` | 完整 Cookie 串（含 `W_X` 或 `Q_H_L` 前缀） | 腾讯音乐 v2025.09.13 |
| QQ | `authst` | 认证令牌 | 腾讯音乐 v2025.09.13 |
| QQ | `g_tk` | 从 `uin` 计算得出 | 腾讯音乐 v2025.09.13 |
| 酷我 | `kw_token` | 硬编码 `123456`（仅歌词请求使用） | 闻音酷我 v1.0.0 |

---

## 7. 能力评估：实时测速、Cookie 有效性检测、VIP 会员级别

### 7.1 实时测速

| 问题 | 当前状态 |
|------|---------|
| musicdl 是否有实时测速能力？ | **❌ 没有** |
| 当前做了什么？ | `AudioLinkTester.test()` 只采样前 8192 字节用于识别格式，不测量下载速度 |
| 下载时做了什么？ | 下载进度的 `downloading_text` 显示已下载量/总量，但**不计算速度** |

**是否可实现？** ✅ **完全可以**。在 `AudioLinkTester` 或 `BaseMusicClient._download` 中增加速度测量：

```python
# 实现思路（已在 _download 的流式下载中预留）
start_time = time.time()
for chunk in resp.iter_content(chunk_size=chunk_size):
    if chunk:
        fp.write(chunk)
        downloaded_size += len(chunk)
        elapsed = time.time() - start_time
        if elapsed > 0:
            speed_mbps = (downloaded_size / 1024 / 1024) / elapsed
            # 如果 speed_mbps < 阈值，标记为慢速
```

**建议**：在 `AudioLinkTester` 中增加 `speed_test(url, timeout=10)` 方法，返回 `{speed_mbps, ok}`。然后在 API 服务的 `resolve_url` 中可选择性调用，为 MusicFree 提供速度信息。

### 7.2 Cookie 有效性检测

| 问题 | 当前状态 |
|------|---------|
| musicdl 是否有 Cookie 有效性检测？ | **❌ 没有统一的检测机制** |
| 当前做了什么？ | 仅检查 Cookie 是否存在（如 `if self.default_cookies`），但不验证其有效性 |
| 是否有例外？ | TIDAL 的 `isvipaccount()` 会调用 API 检查 Cookie 是否有效，但仅 TIDAL 有 |

**是否可实现？** ✅ **可以实现**。思路：

```python
# 通用 Cookie 验证接口
class CookieValidator:
    @staticmethod
    def validate_qq(cookies: dict) -> dict:
        """调用 QQ 的用户信息 API 验证 Cookie，返回 {valid, level, nickname}"""
        resp = requests.get('https://u.y.qq.com/cgi-bin/musicu.fcg', 
            params={'data': '{"comm": {"uin": cookies.get("uin")}}'},
            cookies=cookies)
        data = resp.json()
        return {
            'valid': data.get('code') == 0,
            'level': detect_vip_level(data),  # 见下一节
            'nickname': data.get('user', {}).get('nick', ''),
        }

    @staticmethod
    def validate_kuwo(cookies: dict) -> dict:
        """调用酷我的用户信息 API"""
        resp = requests.get('https://kuwo.cn/api/user/info', cookies=cookies)
        ...
```

将这些验证逻辑添加到 `musicdl/modules/utils/` 下新的 `cookievalidator.py` 模块中。

### 7.3 VIP 会员级别检测

| 问题 | 当前状态 |
|------|---------|
| musicdl 是否有 VIP 级别检测？ | **❌ 没有统一的检测机制** |
| 当前做了什么？ | 代码中有 `l1_parser_funcs`（SVIP）、`l2_parser_funcs`（VIP）等注释，但**只是静态排序，不是动态检测** |
| 是否有例外？ | TIDAL 的 `isvipaccount()` 会查询订阅状态返回 `True/False`，但仅限 TIDAL |

**是否可实现？** ✅ **可以实现**。QQ 音乐和酷我音乐都有会员信息 API：

```python
# QQ 音乐 VIP 检测
def detect_qq_vip_level(cookies: dict) -> str:
    """返回: 'none' | 'vip' | 'svip' | 'music_package'"""
    resp = requests.get('https://u.y.qq.com/cgi-bin/musicu.fcg', params={
        'data': json.dumps({
            "comm": {"uin": cookies.get("uin")},
            "vip": {"module": "music.VipQueryServer", 
                    "method": "GetUserVipInfo",
                    "param": {"userid": int(cookies.get("uin", 0))}}
        })
    })
    data = resp.json()
    vip_info = data.get('vip', {}).get('data', {})
    if vip_info.get('is_annual_vip'): return 'svip'
    if vip_info.get('is_vip'): return 'vip'
    return 'none'

# 酷我音乐 VIP 检测
def detect_kuwo_vip_level(cookies: dict) -> str:
    """返回: 'none' | 'vip' | 'svip'"""
    resp = requests.get('https://kuwo.cn/api/vip/user/info', cookies=cookies)
    ...
```

### 7.4 综合实施建议

在 `musicdl/modules/utils/` 下新增 `accountutils.py` 或 `detector.py` 模块，提供以下功能：

```python
class AccountDetector:
    """账号检测器：Cookie 有效性 + VIP 级别 + 音质可用性"""
    
    @staticmethod
    def detect(cookies: dict, platform: str) -> dict:
        """统一入口，返回 {valid, level, nickname, available_qualities}"""
        ...

    @staticmethod
    def detect_quality_limit(cookies: dict, platform: str) -> list:
        """根据 VIP 级别返回可用的音质列表"""
        ...
```

**优先级**：Cookie 检测比 VIP 检测更重要，因为：
1. 了解 Cookie 是否有效影响走官方 API 还是第三方 API 的决策
2. VIP 级别影响音质选择（SVIP → Hi-Res, VIP → FLAC, 普通 → 320kbps）
3. 可在 API 服务的 `/api/{source}/status` 端点暴露这些信息，供 MusicFree 插件配置参考

### 7.5 关键补充（v3 修订）

以下补充基于代码交叉验证，修正第 7 章的 3 处偏差：

#### 7.5.1 测速重点：多 parser API 延迟排名，而非下载速度

第 7.1 节的 `AudioLinkTester.speed_test()` 方案测的是**最终 URL 的下载速度**，不影响源选择。真正影响搜索质量的是**多第三方 parser API 的延迟排名**——决定用哪个备用 API 返回结果更快。

**正确钩子**：在 `_parsewiththirdpartapis`（`qq.py:315`/`kuwo.py:248`/`netease.py:608` 等）把每个 `parser_func(...)` 调用包 `time.perf_counter()`，记录到 `self._parser_health`，迭代前按健康度排序。

#### 7.5.2 TIDAL 是完整体现成的 detector 模板

第 7 章提到"TIDAL 有但仅限 TIDAL"，但未强调其**可直接照搬的推广价值**：

| TIDAL 实现（`tidalutils.py:430-447`） | 推广到 QQ/酷我 |
|--------------------------------------|---------------|
| `getsubscription()` → GET `/users/{id}/subscription` → `type` 字段 | QQ：`music.VipQueryServer.GetUserVipInfo` → `is_vip`/`is_annual_vip` |
| `valid()` → GET `/sessions` → `status_code == 200` | QQ：`music.userInfo` 或 `GetVkeyServer` 探测 |
| `isvipaccount()` → `premiumAccess or subscription.type != 'FREE'` | 酷我：`/api/vip/user/info` → `isVip`/`isSvip` |
| `refresh()` → 无条件刷新 token | Qobuz：`/user/get` → `credential`/`subscription` |

**结论**：`detector.py` 应直接照 `tidalutils.py:430-447` 的接口签名（`valid()/getsubscription()/isvipaccount()`），各平台各自实现。

#### 7.5.3 Cookie 失效的"死路"与修复

当前配过期 Cookie 的完整执行链：
1. `_parsewiththirdpartapis`（`qq.py:316`）：`if self.default_cookies: return SongInfo(source=self.source)` → **跳过所有第三方**
2. `_parsewithofficialapiv1`（`qq.py:345,360`）：`Credential().fromcookiesdict(expired_cookies)` → **无人声称过期**
3. 高音质 `purl` 为空 → `continue` 到下一音质 → 最终所有音质遍历完，返回空 SongInfo
4. **用户看到搜索结果但无下载链接**，无任何错误提示

**修复方案**：`detector.py` 检测 Cookie 失效后，应：
- 设置一个标识 `self.cookies_valid = False`
- `_parsewiththirdpartapis` 改为：`if self.default_cookies and self.cookies_valid: return empty`（有效才跳过第三方）
- 失效时**自动回退第三方 API**，如同未配 Cookie

---

## 8. 附录

### 6.1 参考资料

- musicdl 官方文档：https://musicdl.readthedocs.io/
- musicdl 源码：https://github.com/CharlesPikachu/musicdl
- MusicFree 项目：https://github.com/maotoumao/MusicFree
- MusicFree 插件协议：`musicfree-plugins/.agents/skills/musicfree-plugin-dev/references/plugin-protocol.md`
- 现有 API 服务详情：`musicfree-plugins/docs/API-SERVICES.md`

### 6.2 相关文件索引

| 文件 | 用途 |
|------|------|
| `musicdl/musicdl.py` | 主入口 MusicClient + CLI |
| `musicdl/modules/sources/base.py` | 基类 BaseMusicClient |
| `musicdl/modules/sources/qq.py` | QQ 音乐客户端（441 行） |
| `musicdl/modules/sources/kuwo.py` | 酷我音乐客户端（374 行） |
| `musicdl/modules/utils/data.py` | SongInfo 数据类 |
| `musicdl/modules/utils/misc.py` | AudioLinkTester 验证器 |
| `musicdl/modules/utils/lyric.py` | 歌词搜索 + WhisperLRC |
| `musicdl/modules/utils/songinfoutils.py` | 标签写入工具 |
| `musicdl/modules/utils/qqutils.py` | QQ 音乐加密/签名工具 |
| `musicdl/modules/utils/kuwoutils.py` | 酷我音乐工具 |
| `musicdl/examples/claudeai-modern-web-music-player/app.py` | 现成的 Flask Web 播放器（参考实现） |
| `musicdl/mcp/server_local.py` | MCP 服务示例（FastMCP） |
| `musicfree-plugins/shared/runtime.js` | 共享运行时（插件基础） |
| `musicfree-plugins/shared/build.js` | 构建脚本 |
| `musicfree-plugins/netease/netease.js` | 网易云插件（参考实现） |