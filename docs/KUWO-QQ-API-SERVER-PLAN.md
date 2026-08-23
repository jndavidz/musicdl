# musicdl → 酷我+QQ音乐 自托管 API 服务计划（kw-qq-music-api）

> 创建日期：2026-08-12
> 前置文档：`docs/MUSICFREE-API-PLAN.md`（v3，MusicFree 插件向）、`docs/MUSICFREE-API-PLAN-REVIEW.md`、`docs/ETC-PLUGINS-ANALYSIS.md`、`docs/YUANLI-V1.2.0-PLUGIN-API.md`
> 决策记录：端点风格 = 仿 kugou/netease RESTful；部署形态 = 单服务双源单端口；首要消费者 = MusicFree 插件（kuwo.js / qq.js）

---

## 1. 目标与背景

### 1.1 NAS 现有 API 服务布局

| 服务 | 内网 | 外网 | 容器/项目 | 说明 |
|------|------|------|-----------|------|
| 网易云 API | `http://10.10.10.2:3000` | `https://ncmapi.pegbiotec.com:4433`（经 Lucky） | NeteaseCloudMusicApiEnhanced | 插件 netease.js 在用 |
| 酷狗 API | `http://10.10.10.2:3001` | `https://kgapi.pegbiotec.com:4433`（经 Lucky） | KuGouMusicApi | 插件 kugou.js 在用 |
| Cookie 服务 | `http://10.10.10.2:3002` | 经 Lucky | shared/cookie-server.js | 凭证分发 |

**本项目**：新建 **酷我 + QQ 音乐** 自托管 API 服务（对标上述两个服务的定位），端口规划 **3003**，单容器双源，外网 `kwqq-api.pegbiotec.com:4433`（经 Lucky 反代 + Basic Auth，与现有一致）。

### 1.2 为什么基于 musicdl 做（而不是找现成的 QQ/酷我 API 项目）

- QQ/酷我没有像 NeteaseCloudMusicApi / KuGouMusicApi 那样成熟可自托管的仿官方开源项目（QQ 系有零散项目但维护差、依赖账号 Cookie）。
- musicdl 内置了 **22 个针对 QQ/酷我的第三方无损解析 API**（免 Cookie 出 FLAC/Hi-Res），且带顺序 fallback、URL 有效性验证（`AudioLinkTester`）、元数据补全——这套解析链就是核心资产。
- musicdl 是纯 Python，包一层 FastAPI 即可服务化；Docker 部署规避 NAS 裸装编译问题。

---

## 2. 通读结论：可复用资产与关键改造点

### 2.1 可复用资产盘点（源码直读）

| 能力 | QQ（`qq.py`, 442 行） | 酷我（`kuwo.py`, 376 行） |
|------|----------------------|--------------------------|
| 搜索 | `u.y.qq.com/cgi-bin/musicu.fcg` POST（`DoSearchForQQMusicMobile`，分页 page_num/num_per_page） | `www.kuwo.cn/search/searchMusicBykeyWord`（pn/rn/all，JSON） |
| 第三方解析链 | l1 SVIP: vkeys.cn / xcvts / xingmian / 317ak<br>l2 VIP: xianyuw / nki / hk0cc / tang<br>l3 MP3级: cyapi / xunhuisi / lxmusic / yutangxiaowu<br>l4 不稳定: lpz | l1 SVIP: liuyunidc（RC4，`[:1]` 只剩它）<br>l2 VIP: cenguigui / lxmusic / nxinxz / haitangw / nobb<br>l3 已禁用: guyuei / yyy001 / gdstudio |
| 官方兜底 | `music.vkey.GetVkey / GetEVkey`（匿名可拿低档 purl） | `mobi.kuwo.cn/mobi.s` convert_url2（des 加密 query，匿名可拿 flac/mp3） |
| 歌词 | `c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg`（base64） | `newlyric.kuwo.cn/newlyric.lrc`（des 解码）＋ h5 `songinfoandlrc` |
| 元数据补全 | `_getsongmetainfo(mid)` → `music.pf_song_detail_svr` | `_getsongmetainfo(id)` → h5 `songinfoandlrc`，失败回退 HTML 页解析 |
| 歌单 | `fcg_ucc_getcdinfo_byids_cp.fcg` | `m.kuwo.cn/newh5app/wapi/.../playListInfo`（分页） |

### 2.2 🔑 关键洞察：by-id 快路径几乎零成本实现

旧计划 v3 认为"需新写一批 `_parsewith*byid` 方法"。通读后发现**不必**：

每个 `_parsewithXxxApi(search_result)` 的第一行都是从 `search_result` 提取 id，且当元数据字段缺失时会**自动调 `_getsongmetainfo(song_id)` 补全整条 track_info**：

```python
# qq.py 各 parser 共同模式
song_id = search_result.get('mid') or search_result.get('songmid')
if not (safeextractfromdict(search_result, ['album', 'title'], None) or search_result.get('albumname')):
    search_result.update(self._getsongmetainfo(song_id=song_id, ...))   # ← 自动补全

# kuwo.py 各 parser 共同模式
song_id = str(search_result.get('MUSICRID') or search_result.get('musicrid')).removeprefix('MUSIC_')
if not (search_result.get('SONGNAME') or search_result.get('name') or search_result.get('songName')):
    search_result.update(self._getsongmetainfo(song_id=song_id, ...))   # ← 自动补全
```

因此 adapter 层只需构造**最小 dict** 即可复用全部第三方解析链：

```python
qq_min   = {'mid': song_mid}                  # QQ
kw_min   = {'musicrid': f'MUSIC_{song_id}'}   # 酷我
song_info = client._parsewiththirdpartapis(qq_min, {})   # 免 Cookie（不配 default_cookies 时走第三方链）
```

注意前置守卫：`_parsewiththirdpartapis` 在 `self.default_cookies or request_overrides.cookies` 非空时直接返回空——**服务化时绝不给这两个客户端配 Cookie**（这也正是 §5.3 旧计划的 Cookie 策略，顺带规避了"过期 Cookie 死路"问题）。

优化点：多个 parser 连锁尝试会对同一首歌重复触发 `_getsongmetainfo`，应在客户端上加实例级 memo（见 §4）。

### 2.3 必须绕过/改造的点

| # | 问题 | 位置 | 对策 |
|---|------|------|------|
| 1 | `MusicClient.search()` 强依赖 rich Progress（无 TTY 报错）+ CLI Hi-Fi 过滤（<10MB/MP3 剔除） | `musicdl.py:162-176,116` | **绕过 MusicClient**，adapter 直接实例化源客户端（`disable_print=True`） |
| 2 | `BaseMusicClient.search()` 无条件创建 work_dir 并写 `search_results.pkl` | `base.py:154-163` | 给 `search()` 加 `persist_results: bool = True` 开关；server 侧关闭 |
| 3 | 每个 parser 内部都做 `AudioLinkTester.test()`（HEAD + GET 8K 采样），单次 0.5~2s | `misc.py:347` | 保留（保证直链有效、拿到重定向后最终 URL 与 size/ext），但收紧 timeout 至 `(3, 8)` 可配；提供 `verify=false` 快速模式跳过探测 |
| 4 | 第三方链是"从高到低试到第一个有效"，不支持指定音质 | 各 parser 的 `MUSIC_QUALITIES` | 音质策略路由（§3.4）：无损/超清 → 第三方链拿最高；明确低档 → 官方匿名端点按参出链，失败回退第三方 |
| 5 | `SongInfo.download_url` 是搜索期一次性解析，时效有限 | — | API 每次 `/song/url` 实时解析 + 短 TTL 缓存（10min），插件侧 `cacheControl: no-cache` |

---

## 3. 架构设计

### 3.1 部署拓扑

```
MusicFree 插件 kuwo.js / qq.js（或其他客户端/脚本）
        │ HTTPS
        ▼
Lucky 反向代理（HTTP Basic Auth，沿用现有模式）
        │  kwqq-api.pegbiotec.com:4433
        ▼
FastAPI server  10.10.10.2:3003（Docker，NAS /volume2/docker/musicdl-api/）
 ├─ /kuwo/*  → KuwoAdapter ─┐  asyncio.to_thread（同步 musicdl 调用不阻塞事件循环）
 ├─ /qq/*    → QQAdapter  ──┤  每源 Semaphore(4) 限并发
 ├─ /healthz /status        │
 └─ 进程内 TTL 缓存（url≈10min / search≈5min / lyric·info≈24h）
内网 10.10.10.2:3003 直连无认证（与 3000/3001 一致）
```

### 3.2 目录规划（musicdl 仓库内新增 `server/`，不动上游结构）

```
server/
├── app.py                # FastAPI 入口 + lifespan 初始化客户端单例池
├── config.py             # PORT=3003 / TTL / 超时 / 并发 / 开关（环境变量可覆盖）
├── adapters/
│   ├── base.py           # SourceAdapter 抽象：search / song_url / song_info / lyric / playlist
│   ├── kuwo.py           # 包装 KuwoMusicClient（含音质路由与最小 dict 构造）
│   └── qq.py             # 包装 QQMusicClient
├── schemas.py            # Pydantic 响应模型（统一 {code,msg,data} 包裹）
├── cache.py              # TTL+锁 的进程内缓存（不引 Redis，规模不需要）
├── parsers_health.py     # parser 成功率/延迟统计（供 /status 与动态排序）
├── requirements.txt      # fastapi / uvicorn[standard] / musicdl(本仓 editable)
├── tests/test_smoke.py   # 端点冒烟（真搜一首→拿 url→HEAD 校验）
├── Dockerfile            # python:3.12-slim
├── docker-compose.yml    # restart: unless-stopped + healthcheck（对齐 NAS 部署习惯）
└── README.md             # 端点文档 + 部署手册
```

musicdl 核心改动保持最小侵入（见 §4）。

### 3.3 端点设计（仿 kugou/netease 风格，`{source}` ∈ `kuwo` | `qq`）

统一响应包裹：`{"code": 200, "msg": "...", "data": {...}, "timestamp": ...}`；错误码 404=无此资源、429=并发超限、502=上游解析全部失败。

| Method | Path | 参数 | musicdl 对应能力 |
|--------|------|------|------------------|
| GET | `/{source}/search` | `keywords`必填, `page`=1, `limit`=20, `type`=song | `client.search()`（限页大小，关 pkl） |
| GET | `/{source}/song/url` | `id`必填, `quality`∈auto/flac/hires/320k/128k（默认 auto=320k，见 §3.4） | by-id 快路径（§2.2）＋音质路由（§3.4） |
| GET | `/{source}/song/info` | `id` | `_getsongmetainfo`（封面/专辑/时长，供 getMusicInfo） |
| GET | `/{source}/lyric` | `id` | QQ base64 歌词端点 / 酷我 newlyric+h5 双路 |
| GET | `/{source}/playlist` | `id`, `page`=1, `limit`=100 | `parseplaylist` 轻量改造（仅曲目列表，逐轨解析放二阶段） |
| GET | `/{source}/album` · `/{source}/artist`（可选） | `id` | 官方公开端点直通 |
| GET | `/healthz` · `/status` | — | 存活探针 / parser 健康度+缓存命中统计 |

`/song/url` 成功响应示例（字段覆盖 MusicFree `getMediaSource` 所需）：

```json
{
  "code": 200, "msg": "success",
  "data": {
    "id": "0039MnYb0qxYhV", "source": "qq", "quality": "flac",
    "url": "https://dl.stream.qqmusic.qq.com/...",
    "ext": "flac", "size_bytes": 31457280, "duration_s": 245,
    "cover": "https://y.gtimg.cn/music/photo_new/T002R800x800M000....jpg",
    "verified": true,
    "headers": {},
    "parser": "_parsewithvkeysapi",
    "elapsed_ms": 850
  }
}
```

### 3.4 音质策略路由（修订：插件场景封顶 320kbps）

MusicFree 插件协议中 `getMediaSource(musicItem, quality)` 的 `quality` 为 `"low"/"standard"/"high"/"super"` 四档字符串（协议本身不规定码率，映射由插件决定；参考本仓 `musicfree-plugins/.agents/skills/musicfree-plugin-dev/references/plugin-protocol.md:88`）。**本项目约定：插件消费场景一律封顶 320kbps**，在线流播场景稳定第一（官方匿名端点出链率最高、不依赖第三方 SVIP 接口）；无损能力保留给 hifi 下载场景（§8.5）。

**插件侧映射（kuwo.js / qq.js 统一采用，参考现有 netease/kugou 插件惯例：`netease/src.js QUALITY_LEVEL`、`kugou/src.js pickHash`）**：

| MusicFree quality | 请求 API 的 quality | 实际音质 | 出链路径 |
|-------------------|--------------------|----------|----------|
| `low` | `128k` | 128kbps MP3 | QQ `GetVkey M500` / 酷我 `mobi.s format=128kmp3` 匿名直出 |
| `standard` | `128k` | 128kbps MP3 | 同上 |
| `high` | `320k` | **320kbps MP3**（默认档，与现有 kugou 插件 high→320k 惯例一致） | QQ `GetVkey M800` / 酷我 `mobi.s format=320kmp3` 匿名直出 |
| `super` | `320k` | 320kbps MP3（封顶） | 同上 |

**API 层完整路由**：

| 请求 quality | 路径 | 说明 |
|--------------|------|------|
| `auto`（默认）/ `320k` / `128k` | ① 官方匿名端点按参直出 → ② 失败回退第三方解析链并如实标注实际档位 | 默认路径，服务插件与语音播放 |
| `flac` / `hires` | 第三方 SVIP 解析链（QQ: vkeys.cn→xcvts→…；酷我: liuyunidc master→cenguigui lossless→…） | **仅供 hifi 下载器/自用脚本显式请求**；可用配置开关 `ENABLE_LOSSLESS=false` 一键关闭 |

原则：**永远如实返回实际得到的 ext/size/quality**；请求档位高于可得档位时不报错，由客户端按返回值决定重试策略。

### 3.5 缓存与可靠性

- **TTL 缓存**：`song/url` 成功结果 10 min（CDN 直链通常数小时有效，宁短勿长）；`search` 5 min；`lyric`/`song/info` 24 h；键含全部请求参数。
- **parser 健康度**：每次 `_parsewiththirdpartapis` 的逐 parser 结果记入 `parsers_health`（成功/失败/延迟滑动窗口），`/status` 暴露；后续可升级为"健康度动态排序"替代静态 l1→l4（旧计划 §5.5 的落地位置在 adapter 层即可完成，不必改 musicdl 核心）。
- **并发**：uvicorn workers=1（进程内缓存一致性）+ 每源 `asyncio.Semaphore(4)`；musicdl 内部线程池保持默认。
- **超时预算**：`/song/url` 目标 P95 < 3s（`AudioLinkTester` timeout 收紧为 (3,8)，`requests` 层 10s 不变）；整体 Hard Timeout 8s 返回 502。

---

## 4. musicdl 核心代码改动清单（最小侵入）

| # | 文件 | 改动 | 目的 |
|---|------|------|------|
| 1 | `modules/sources/base.py` | `search(..., persist_results: bool = True)`：False 时跳过 `_constructuniqueworkdir` + `_savetopkl` | API 高频搜索不落盘 |
| 2 | `modules/sources/base.py` | `AudioLinkTester` 实例 timeout 参数透传（构造器已有 timeout，仅需让源客户端可配置） | 收紧探测超时 |
| 3 | `modules/sources/qq.py` / `kuwo.py` | `_getsongmetainfo` 加实例级 memo（`self._meta_cache: dict[id, dict]`，容量上限 512 LRU） | 同曲多 parser 不重复补元数据；`/song/info` 直接受益 |
| 4 | `modules/sources/qq.py` / `kuwo.py` | （不改签名）确认 `_parsewiththirdpartapis` 对最小 dict 输入的健壮性，补 try/except 兜底 | by-id 快路径稳定性 |
| 5 | `modules/utils/misc.py` | 无改动（timeout 经构造器传入即可） | — |

> 不新增 `_parsewith*byid` 系列——§2.2 的最小 dict 方案已达成同效果且零重复代码。CLI 行为完全不受影响（所有新参数均带默认值）。

---

## 5. 实施步骤与验收标准

### 阶段 0：技术验证 Spike（0.5 天，本机 WSL2）

- [ ] 0.1 最小 dict 快路径实测：QQ `{mid}` / 酷我 `{musicrid}` 各取 10 首歌（热门+冷门+纯音乐），统计出链成功率、实际 ext 分布、单次耗时
- [ ] 0.2 官方低档直出实测：酷我 `mobi.s format=320kmp3`、QQ `GetVkey M500/M800` 匿名出链率
- [ ] 0.3 记录各 parser 成功率/延迟基线表（写入本文档附录）
- [ ] 0.4 若第三方链整体失效（可能性低，2026-08 仍在用），退路：启用 `docs/ETC-PLUGINS-ANALYSIS.md` 第 4 章备选端点池

**验收**：≥8/10 出链且 P95 < 3s，即进入阶段 1。

### 阶段 1：musicdl 核心小改（1 天）

- [ ] 1.1 完成 §4 清单 1–4 项 + 回归测试（CLI 正常搜索下载不受影响；`pytest` 新增 by-id 快路径用例）

### 阶段 2：server/ FastAPI 服务（2–3 天）

- [ ] 2.1 `schemas/cache/config/adapters/app.py` 全套实现
- [ ] 2.2 端点：search / song/url / song/info / lyric（playlist 视进度顺延）
- [ ] 2.3 本机 `uvicorn server.app:app --port 3003` 冒烟：curl 真实链路（搜索→url→HEAD 206 校验→lyric）
- [ ] 2.4 `tests/test_smoke.py` 入库

**验收**：四类端点全部可用，`/song/url` verified=true 占比 ≥90%。

### 阶段 3：Docker 化与 NAS 部署（1 天）

- [ ] 3.1 Dockerfile + compose（python:3.12-slim；curl_cffi/cryptography 用 manylinux wheel，禁本地编译）
- [ ] 3.2 SSH 部署至 NAS：`/volume2/docker/musicdl-api/`，`/usr/local/bin/docker compose up -d`，端口 3003，healthcheck=`/healthz`
- [ ] 3.3 Lucky 反代：`kwqq-api.pegbiotec.com:4433 → 10.10.10.2:3003`，挂 HTTP Basic Auth（与现有一致）
- [ ] 3.4 更新 musicfree-plugins 侧 `docs/API-SERVICES.md` 登记新服务

**验收**：内外双通道均可访问；容器重启后自动恢复。

### 阶段 4：MusicFree 插件对接（musicfree-plugins 项目，另立计划）

- [ ] 4.1 `kuwo/src.js`、`qq/src.js`：`getMediaSource → /{src}/song/url`（`cacheControl: no-cache`）、`search/getLyric/getMusicInfo` 对接
- [ ] 4.2 `shared/build.js` 构建 → 发布 `web.pegbiotec.com:4433/plugin/{kuwo,qq}.js`
- [ ] 4.3 真机回归：搜索/播放/歌词/音质降级重试

### 阶段 5：运维增强（后续迭代）

- [ ] 5.1 `/status` parser 健康度可视化 + 每日保活探测（定时打已知歌曲，失活 parser 告警日志）
- [ ] 5.2 playlist 端点完整化（异步任务化逐轨解析）
- [ ] 5.3 按同一 adapter 协议扩展第三源（咪咕 ⭐⭐⭐ / B站 ⭐⭐⭐ / 汽水 ⭐⭐，见旧计划 §3.3 优先级）

---

## 6. 风险与对策

| 风险 | 等级 | 对策 |
|------|------|------|
| 第三方公共 parser 失效/限流（最大风险） | 高 | 多 parser 顺序 fallback 已内置；健康度统计快速感知；`ETC-PLUGINS-ANALYSIS.md` 备选端点池随时补充；极端情况给 liuyunidc/vkeys 类私有端点换卡密 |
| CDN 直链短时效 | 中 | 10min TTL + 插件 no-cache 实时取；`download_url` 返回的是重定向后最终 URL，播放器直连 |
| `nmobi/mobi.s`、`GetVkey` 匿名策略变动 | 中 | 低档路由失败自动回退第三方链，功能不中断 |
| NAS 内存压力（DS416play 8G，已跑多容器） | 低 | Python 单容器常驻 ≈150–250MB；workers=1；无后台线程常驻任务 |
| 合规 | — | 仅个人/家庭内网与自有插件使用；Lucky Basic Auth 保护；不对公网匿名开放；遵循 musicdl PolyForm-NC 许可（非商业） |

---

## 7. 决策记录与遗留问题

### 7.1 已确认决策（2026-08-12）

| # | 问题 | 决策 | 依据 |
|---|------|------|------|
| 1 | 端口 3003 是否空闲？ | ✅ **已实测空闲**（SSH 至 NAS netstat 核实：300x 段仅 3000 ncm-api / 3001 kugou-api 监听） | 2026-08-12 检查 |
| 2 | 外网子域形态 | ✅ **单一子域** `kwqq-api.pegbiotec.com:4433` 承载双源（Lucky 反代 → 10.10.10.2:3003） | 与单服务双源形态一致 |
| 3 | 登录态增强 | ✅ **无自有账号，全匿名路线锁定**：不配任何 Cookie，纯第三方解析链 + 官方匿名端点；原阶段 5 的 Cookie/detector 相关项标记为「待有账号再议」 | 用户确认 |
| 4 | 插件音质封顶 | ✅ 320kbps（§3.4 映射表），`high → 320k` | 用户指定 + 现有 netease/kugou 插件惯例 |
| 5 | DAC 接口偏好 | ✅ **USB 直入**（NUC → USB → DAC → 模拟进功放，bit-perfect 最短路径）；预算未限定，选型默认按入门~进阶档（约 ¥300–1500）出推荐清单，采购前可再调档 | 用户确认 |
| 6 | 小爱音箱分工 | ✅ **LX06 客厅主力**（open-xiaoai 已刷机，语音入口 + 主播放端）、**L05B 书房背景音乐**（xiaomusic 播放端） | 用户确认 |

### 7.2 遗留问题

无——全部前置决策已闭环（NAS 上 xiaomusic/open-xiaoai 系「配置就绪未运行」的现状已纳入 §8.1/§8.6 P1），计划可直接进入执行，下一步为阶段 0 Spike。

---

## 8. 家庭智能音乐系统集成蓝图（扩展规划）

> 目标：以本次 API 服务为在线流入口、musicdl hifi 分支为无损入库工具，把现有硬件组织成"**高保真主链 + 全屋便捷播**"双链路，HA 统一控制。

### 8.1 资产盘点与角色定位

| 资产 | 现状 | 在系统中的角色 |
|------|------|----------------|
| NAS DS416play `10.10.10.2` | Docker 运行中: HA / Node-RED / mariadb / neteasecloudmusicapi(3000) / KuGouMusicApi(3001) 等 11 容器；**Music Assistant 未部署**（仅剩 `music-assistant/data` 目录）；`xiaomusic/` compose 就绪未启动；`open-xiaoai-server`(migpt)/`oxa-server`(xiaozhi桥) 配置就绪未启动 | 控制中枢(HA)、API 服务族(3000/3001/**3003**)、音乐库存储(`/volume1/music`) |
| NUC D34010WYB `10.10.10.3` | 装 Daphile（待定） | **高保真音源主机**（Daphile 内置 LMS，bit-perfect 输出）；亦可跑 squeezelite |
| 外置 DAC（拟购） | — | Hi-Fi 解码核心，决定音质上限 |
| 安桥 TX-SR674 + TANNOY Arena 5.1 | 同轴接电视输出端口（现状不理想） | 功放/音箱终端；音乐场景建议 Pure Audio 立体声 |
| G&W TW-05D 电源净化滤波器 | 已有 | 给 NUC/DAC/声源设备净化供电（功放功耗大，建议直墙插对比噪声再定） |
| 小爱音箱 Pro LX06 `10.10.10.20` | 已刷 open-xiaoai 固件 + client-rust | **客厅主力**：语音入口 + xiaomusic 主播放端 |
| 小爱音箱 PLAY L05B `10.10.10.21` | 原厂 | **书房背景音乐**播放端（xiaomusic） |
| 家庭 PC（本机，hifi 分支） | musicdl CLI 已可用 | **无损下载/入库工作站**（§8.5） |
| 手机 | MusicFree App | 移动场景：自建插件 ≤320k 在线流 |

### 8.2 高保真主链路建议

```
NUC(Daphile/LMS) ──USB──▶ 外置 DAC ──RCA模拟──▶ TX-SR674 (Pure Audio直通) ──▶ TANNOY Arena 前置主箱
                                        （功放仅做音量/放大，解码交给 DAC）
```

- **DAC 选型（已锁定：USB 直入，§7.1 #5）**：NUC USB → DAC → RCA 模拟进功放，bit-perfect 最短路径。推荐清单（均为 USB 输入、按档位）：
  - 入门（¥300–600）：**SMSL SU-1**（CS43131，USB 直入，测评分水岭之上）、FiiO K11（带同轴/光纤备用接口，可推耳机）
  - 进阶（¥700–1500）：**Topping E30 II / E30 II Lite**（USB+同轴+光纤全接口）、SMSL DO200 Pro（双 ES9039Q，带遥控）
  - 更高（>¥1500，按需再议）：Geshelli Archel2.5+Dayo、JDS Labs Atom DAC 2 类
  - 落地建议：先入 SU-1 级别跑通全链路验证提升，不满意再升级——DAC 在本链路是"短板补齐"，音箱房间声学同样影响听感。
- **Daphile 要点**：输出设为 USB Audio（DAC 型号直出）、关闭所有软件处理（bit-perfect）、SMB 挂载 NAS `/volume1/music` 扫库；其内置 LMS 可同时服务其他 Squeezelite 端。
- **功放/音箱要点**：TX-SR674 为 2006 年 AV 功放——数字输入用它的 DAC 不如外置 DAC；听音乐选 **Pure Audio/Stereo** 模式只推前置主箱；Arena 卫星箱系统分频点建议 ~100Hz 给低音炮，音量留足余量。
- **现状"电视同轴输出"链路评价**：经电视取声会限制采样率且多一层电视 DSP，建议降级为看视频用，音乐主链改为上图路径。

### 8.3 全屋便捷播放链路

```
小爱 LX06(客厅主力,10.10.10.20) ─┐
                                  ├─(xiaomusic @NAS Docker)─▶ 播 NAS 本地库(HTTP流) / 自建3003 API在线搜歌
小爱 L05B(书房背景,10.10.10.21) ─┘
      ▲                    │
      └── open-xiaoai client-rust(LX06): 本地接管语音意图 → 转发 HA 自动化 ──┘
Music Assistant(NAS待部署): 统一控制 Squeezelite/DLNA/AirPlay 端；可注册 Daphile 的 LMS 为 player provider
```

- **xiaomusic**（hanxi/xiaomusic）：让小爱音箱直接播放本地/NAS 音乐的成熟方案，跑在 NAS Docker（音箱 128M 内存无压力，逻辑全在服务端）；支持歌单、口令换歌，有 HA 集成组件。**NAS 上 `/volume2/docker/xiaomusic/` compose 已就绪（镜像 `docker.hanxi.cc/hanxi/xiaomusic`，端口映射 58090:8090），当前未启动——P1 直接 `docker compose up -d` 并配好小爱账号即可**。
- **open-xiaoai 与 xiaomusic 的关系**：xiaomusic 传统模式走云端接口轮询播放指令；open-xiaoai 刷机后可**本地接管**（自定义技能词→HTTP 回调 HA/自建后端），响应更快且不依赖云端。两者控制通道可能冲突，建议：优先尝试 open-xiaoai 接管模式对接 HA，xiaomusic 作为播放执行器或回退方案。
- **Music Assistant 定位**：NAS 上尚未部署（§8.1）——部署后可把 Daphile(LMS)、DLNA 设备、手机 MusicFree 场景统一到 HA 音乐卡片；进阶可写基于 3003 API 的 MA custom provider（Python，工作量另估，属远期）。
- 手机端 MusicFree + kuwo.js/qq.js 插件：移动场景 ≤320k 在线流（§3.4）。

### 8.4 数据流闭环

```
[无损入库] musicdl hifi (家庭PC, §8.5) ──SMB──▶ NAS /volume1/music/download ──▶ Daphile/LMS 扫库 ──▶ DAC 主链
[在线流]   kw-qq-api :3003 ──≤320k──▶ MusicFree插件 / xiaomusic(小爱) / (未来)MA provider
[无损点播] 小爱语音 → HA → xiaomusic 指定曲目（来自已入库 FLAC 库转码流）
[控制]     HA 中枢：MA 播放卡 + xiaomusic 实体 + open-xiaoai 语音意图
```

### 8.5 musicdl hifi 分支完善清单（家庭 PC 无损下载管理）

现有基础（已具备）：Hi-Fi 过滤（剔 MP3/<10MB）、下载后 TinyTag 解析码率/采样率、歌词 .lrc 同名保存+内嵌、封面嵌入（`songinfoutils.py`）、目标目录 `/volume1/music/download`、可选 WhisperLRC。

| # | 完善项 | 说明 | 优先级 |
|---|--------|------|--------|
| 1 | **目录归档策略** | 现为时间戳平铺目录 + `{歌名}-{identifier}.flac`；改为 `歌手/专辑/01-歌名.flac` 归档（标签写完后重命名），LMS/Daphile 扫库体验显著更好 | ⭐⭐⭐ |
| 2 | **查重与增量同步** | 按 identifier/歌手-标题查已入库文件跳过；支持"收藏歌单增量同步"模式（歌单新曲自动补下） | ⭐⭐⭐ |
| 3 | **过滤参数化** | `<10MB 或 MP3 剔除`硬编码 → CLI 参数 `--min-size-mb / --allow-mp3 / --min-bitrate` | ⭐⭐⭐ |
| 4 | **save_path 配置化** | `/volume1/music/download` 硬编码 → env/CLI 参数；家庭 PC 经 SMB 写入时先写本地 tmp 再原子 mv，避免网络抖动产生半截文件 | ⭐⭐⭐ |
| 5 | **歌单批量增强** | `parseplaylist` 逐轨串行慢 → 并发化 + 失败清单导出（JSON）供重试 | ⭐⭐ |
| 6 | **复用 3003 API 解析** | 可选 `--use-api http://10.10.10.2:3003`：URL 解析走自建 API（同一套链路集中管理/统计），家庭 PC 只负责下载落盘 | ⭐⭐ |
| 7 | **质量校验报告** | 利用已有 TinyTag 结果汇总 CSV/JSON 报告（码率/采样率/时长），人工抽检假无损 | ⭐ |
| 8 | **Web UI（远期）** | 基于 `examples/claudeai-modern-web-music-player/app.py`（现成 Flask 参考实现）改造：搜索→试听→勾选入库 | ⭐ |

### 8.6 实施顺序建议

| 阶段 | 内容 | 依赖 |
|------|------|------|
| P1（可与 API 项目并行） | ① 启动 NAS 已就绪的 xiaomusic compose（`/volume2/docker/xiaomusic/`），跑通"NAS 曲库→小爱"链；② Daphile 装机扫库，跑通"NAS 曲库→DAC/功放"高保真链；③ 决定是否补部署 Music Assistant（目录在但从未部署） | 现有硬件即可 |
| P2 | 外置 DAC 采购接入（USB 直入已锁定，推荐清单见 §8.2；预算默认入门~进阶档），bit-perfect 调校 | P1 |
| P3 | open-xiaoai 语音意图接 HA 自动化（客厅 LX06 为主；migpt/xiaozhi 桥按需取舍） | P1 |
| P4 | hifi 分支按 §8.5 清单迭代（1–4 项先行） | 与 P1 并行 |
| P5（远期） | Music Assistant 正式部署 → MA custom provider 对接 3003；hifi Web UI | API 项目上线后 |

---

## 附录 A：与 MUSICFREE-API-PLAN.md（v3）的关系

- **继承**：绕过 MusicClient 直实例化源客户端、免 Cookie 走第三方链、阶段 0 Spike 先行、`cacheControl: no-cache`、音质映射规则。
- **修订**：① 端点从 `/api/{source}/*` 改为仿 kugou/netease RESTful（`/{source}/search` 等），便于与现有两服务心智统一；② "新建 `_parsewith*byid` 方法"简化为"最小 search_result dict 复用既有链"（§2.2）；③ 服务定位从"MusicFree 专属后端"泛化为"自托管音乐 API 服务"（插件只是首要消费者）；④ 部署端口 5000→3003，纳入现有 300x 服务族。
