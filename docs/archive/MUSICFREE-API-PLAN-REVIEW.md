# MUSICFREE-API-PLAN 评审与修订

> 创建日期：2026-08-07
> 评审对象：`docs/MUSICFREE-API-PLAN.md`（v2，含第 6/7 章）
> 评审依据：musicdl 源码交叉验证（精确到行号）+ MusicFree 插件协议官方文档 + etc/ 23 个参考插件深度解析
> 关联文档：`docs/ETC-PLUGINS-ANALYSIS.md`（etc/ 插件专题，已单独成文）

---

## 0. 评审结论速览

| 维度 | 评级 | 说明 |
|------|------|------|
| 环境调研（第 1 章） | ⭐⭐⭐⭐⭐ | 网络/目录/API 服务梳理清晰，可直接用 |
| 源码理解（第 2-3 章） | ⭐⭐⭐⭐ | 架构、流程、第三方 API 列表准确率高，但存在 4 处事实性错误（见第 2 章） |
| etc/ 插件分析（第 6 章） | ⭐⭐⭐⭐ | 端点/密钥/Cookie 提取详实，但与 musicdl 现有源的重叠关系标注有遗漏 |
| 能力评估（第 7 章） | ⭐⭐⭐ | 方向正确（测速/Cookie/VIP 均可加），但实施位置描述有偏差 |
| 设计决策（第 5 章） | ⭐⭐⭐⭐ | 不配 Cookie 走第三方、选 musicdl 的论证扎实 |
| **可行性（第 4 章实施清单）** | ⭐⭐ | **核心环节 resolve_url 存在结构性盲点，工作量被低估** |

**三条最关键的修订**：
1. 🔴 `resolve_url` 按需重解析没有现成入口——需新建"按 song_id 直接解析"的快路径（etc/ 插件已证明可行，见第 4 章）
2. 🔴 计划有 4 处事实错误需订正（QQ 官方 API 不要求 Cookie、酷我音质列表系杜撰等，见第 2 章）
3. 🟡 后端应绕过 `MusicClient` 直接用源客户端，避免 rich 输出与 Hi-Fi 过滤干扰（见第 3 章）

---

## 1. 计划准确部分的确认

以下断言经代码行号交叉验证为**准确**，可直接据此实施：

| 计划断言 | 验证位置 |
|---------|---------|
| 架构图：MusicClient → BaseMusicClient → 各源；SongInfo dataclass；AudioLinkTester | `base.py`/`data.py`/`misc.py` 一致 |
| 搜索流程：ThreadPoolExecutor(10) → 每源 search() → _constructsearchurls → 每页并行 _search → _parsewiththirdpartapis → 回退 _parsewithofficialapiv1 → 去重 | `base.py:128-166`、`musicdl.py:161-176` |
| Hi-Fi 过滤 `if raw_ext == 'mp3' or filesize_mb < 10.0: continue` | `musicdl.py:116` |
| 过滤仅在 CLI 显示路径，库层 search() 返回未过滤结果 | `search()`(161-176) 直接返回 |
| 保存路径硬编码 `/volume1/music/download` | `musicdl.py:52` |
| music_sources 参数可限定加载源 | `__init__`(39/47 行) |
| QQ：配 Cookie 时 _parsewiththirdpartapis 提前 return 跳过第三方 | `qq.py:316` |
| QQ 第三方 API 分层 l1-l4 与方法名 | `qq.py:317-321` |
| 酷我 l1 切 [:1]、l3 切 [:0] 禁用 | `kuwo.py:251-253` |
| 酷我 search_url 为纯字符串 URL | `kuwo.py:51-55,309,317` |
| parseplaylist 默认 raise NotImplementedError | `base.py:242-243` |
| 不配 Cookie 走第三方以获 FLAC 的 Cookie 策略 | 与代码行为一致 |

第 1 章环境/网络/目录映射、第 5.2 节与现有 `shared/runtime.js`+`build.js` 模式整合的描述，与 `runtime.js` 实际代码一致。

---

## 2. 计划错误部分的订正

### ❌ 错误 1：QQ 官方 API "需要 Cookie"——因果说反

**计划 §3.1 表格**：`_parsewithofficialapiv1 | 官方 API | 需要 Cookie，否则音质受限`

**代码事实**（`qq.py:333-370`）：`_parsewithofficialapiv1` **不要求 Cookie**。`Credential().fromcookiesdict(self.default_cookies or request_overrides.get('cookies', {}))` 传空 dict 也能跑；`fromcookiesdict({})` 合法。真正受 Cookie 控制的是 `_parsewiththirdpartapis`（**有** Cookie 时跳过第三方，`qq.py:316`）。

**订正**：
- QQ 官方 API：**不要求 Cookie**，传空凭据即可调用；无 Cookie 时仍可解析，但高音质可能返回空 purl（VIP 限制，非 Cookie 限制）
- 真正的 Cookie 门控逻辑是：有 Cookie → 跳过第三方 → 走官方；无 Cookie → 走第三方

### ❌ 错误 2：酷我音质遍历列表系杜撰

**计划 §3.2**：
```python
['acc', 'wma', 'ogg', 'standard', 'exhigh', 'ape',
 'lossless', 'hires', 'zp', 'hifi', 'sur', 'jymaster'][::-1][3:]
```

**代码事实**：该列表在 `kuwo.py` 全文及全仓库**均不存在**。实际各第三方 API 的音质序列各不相同：
- `_parsewithliuyunidcapi`（`kuwo.py:192`）：`['master','atmos_plus','atmos','flac','320k'][:-1]`
- `_parsewithnxinxzapi`/`_parsewithhaitangwapi`：`['lossless','exhigh','standard']`
- 官方：`MUSIC_QUALITIES = [(22000,'flac'),(320,'mp3')]`（`kuwo.py:36`）
- `jymaster` 只作为 `_parsewithccwuapi` 固定 URL 的 query 参数（`kuwo.py:83`），不是遍历列表元素

**订正**：删除该杜撰列表，按各 `_parsewith*` 的实际序列重写。

### ⚠️ 错误 3：QQ search_url 描述不完整

**计划 §3.1**："`search_url` 为 `dict`，含 `url` + `data`"

**代码事实**（`qq.py:38-52`）：每个 search_url dict 还**必带 `page_no`**（int），加密端点时带 `params: {"sign": ...}`；且 `data` 是序列化后的 **bytes**（`json.dumps(...).encode("utf-8")`），不是 dict。

**订正**：`search_url` = `{'url': str, 'data': bytes, 'page_no': int, 'params'?: dict}`，`_constructsearchurls` 返回此 dict 的 list。

### ⚠️ 错误 4：酷我方法名笔误

**计划 §3.2 表**：把 cenguigui 端点的方法写成 `_parsewithcenguiguiapi`。

**代码事实**：实际方法名是 `_parsewithcggapi`（cenguigui 只是端点域名 `kw-api.cenguigui.cn`，`kuwo.py:60`）。计划正文用的 `_parsewithcggapi` 正确，需统一表格。

### ⚠️ 第 6 章遗漏：与 musicdl 现有源的重叠标注

计划 §6.1.5/§6.2.5 标注了 musicdl 已覆盖的情况，但遗漏了关键重叠：
- `_parsewithhaitangwapi` 对应 etc/ 的 `music.haitangw.cc`（P-04 回退链第 2 级、P-05 元力菌生态）——计划未标
- `_parsewithlxmusicapi` 与 etc/ 的 lx-music **签名版**（`88.lxmusic.xn--fiqs8s`）**不是同一套**：musicdl 现有的是非签名 lx 源，etc/ 的是签名 v4 协议——计划暗示"已覆盖"是误读

**订正**：见 `ETC-PLUGINS-ANALYSIS.md` 第 4 章总表，明确标注 #1/#2 lx 签名版对 musicdl 是**真新增**。

---

## 3. 结构性盲点

### 🔴 盲点一：resolve_url 按需重解析没有现成入口

**计划 §2.4.3 + §4.1.4** 声称：
> 在 getMusicUrl 接口中**实时重新解析**，利用 `_parsewiththirdpartapis()` 或 `_parsewithofficialapiv1()` 按需解析

**代码事实**：
1. 全仓库**不存在** `resolve_url`/`refresh_url` 类方法（`base.py`/`qq.py`/`kuwo.py` 均无）
2. `_parsewith*` 函数入参是**搜索时的原始 `search_result` 字典**（从中提取 `MUSICRID`/`musicrid`，如 `kuwo.py:62,80,97`），**不是** bare song_id
3. `SongInfo.download_url` 在 `_search` 期间一次性解析并经 `AudioLinkTester.test()` 验证后存入；之后没有按 identifier 刷新的路径

**后果**：MusicFree 的 `getMediaSource(item, quality)` 收到的是已存 `musicItem`（含 `id`），要"实时重解析"过期链接，**无法**直接调 `_parsewiththirdpartapis(musicItem.id)`。

**解决方案**（etc/ 插件已验证可行，见 `ETC-PLUGINS-ANALYSIS.md` 第 5 章）：

etc/ 插件几乎全部用范式 A/B（直接用 song_id 调第三方端点拿 URL，不重搜索）。这证明 musicdl 可新增一批**直接吃 song_id 的 `_parsewith*` 方法**，用 etc/ 提取的端点：

```python
# 新增：按 song_id 直接解析，绕过搜索
def _parsewithlxmusicsignedapi_byid(self, song_id, quality, request_overrides):
    """lx-music v4 签名协议，一套密钥双平台（QQ+酷我）"""
    request_path = f"/lxmusicv4/url/{self.lx_path_prefix}/{song_id}/{quality}"
    sign = sha256(request_path + SCRIPT_MD5 + SECRET_KEY)
    url = f"https://88.lxmusic.xn--fiqs8s{request_path}?sign={sign}"
    resp = self.get(url, headers={'x-request-key': 'lxmusic', 'user-agent': 'lx-music-mobile/2.0.0'})
    # 解析 resp.data.url

def _parsewithnmobikuwobyid(self, song_id, br, request_overrides):
    """酷我官方 mobi.s，无 Cookie，直接 convert_url_with_sign"""
    url = f"http://nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid={song_id}&br={br}"
    # 无需 Cookie 即可返回 FLAC
```

后端 `resolve_url(source, song_id, quality)` 路由到这些方法，失败回退官方 API（按 id 调 vkey）。**这是整个改造工作量最大的一块**，比 §4 待办项暗示的"调用一下 `_parsewiththirdpartapis`"重得多，应单列阶段并先做 spike 验证。

### 🔴 盲点二：10 秒超时 × musicdl 重搜索 = 必超时

**MusicFree 沙箱约束**（`musicfree-protocol.md:30,86`）：每次方法调用 **10 秒执行超时**。

musicdl 的 `search()` 跑多源并行 ThreadPoolExecutor + 每源分页并行 + 每候选 AudioLinkTester HEAD/GET 探测 + 遍历多第三方 API，**一次完整搜索远超 10 秒**。

**正确架构**（与现有 `runtime.js` 一致）：插件侧 `getMediaSource` 只做**一次快速 HTTP 调用** `/api/{source}/url?id=xxx&quality=xxx`，重活全在后端。但后端这次调用必须快——即盲点一的"按 id 直接解析"快路径，**不能走完整搜索**。

**插件元字段**：必须设 `cacheControl: "no-cache"`（协议 `musicfree-protocol.md:60,185`），否则 MusicFree 缓存 getMediaSource 结果，过期链接播不了。计划待办未提此项，应补进 §4.2/§4.3。

### 🟡 盲点三：MusicClient 自身的 rich 输出无法关闭

**计划 §4.1.2**："初始化 MusicClient（仅加载目标源，不传 Cookie）"

**代码事实**：`music_sources` 能限定源 ✅，但 `disable_print` **只传给底层源客户端**（`musicdl.py:76` 的 `init_music_client_cfg`），`MusicClient` 自己的 `search()` 仍**无条件**用 `rich.progress.Progress` 和 logger（`musicdl.py:162-176`）。API 服务里 rich 输出会污染日志或无 TTY 时抛异常。

**建议**：后端**绕过 MusicClient，直接实例化目标源客户端**（`QQMusicClient(...)`、`KuwoMusicClient(...)`），自己编排 search/resolve/lyric 三个端点。这同时规避 Hi-Fi 过滤、rich 输出、多源并发。

### 🟡 盲点四：现有 runtime.js 是瘦客户端，后端工作量被低估

`runtime.js` 的 `request()` 只是把 HTTP 请求转发给 Node API 容器——**URL 解析发生在 Node API 服务端**，插件侧零解析。计划 §5.2 说"后端从 Node.js API 改为 musicdl 的 Python API"，这话只对了一半：插件侧可复用 `runtime.js`，但 musicdl **没有等价的 `/song/url` 端点**，要从零造（见盲点一）。

### 🟡 盲点五：音质映射规则未具体化

MusicFree quality 仅 4 档 `low/standard/high/super`，且 APP 自动按更高/更低重试（`musicfree-protocol.md:80-84`），插件无需自行降级。计划 §2.3/§3.3 只说"音质映射"未给规则。

**建议规则**：
- `super → FLAC/MASTER/RS01(Hi-Res)`
- `high → 320/OGG_320`
- `standard → 128/M4A`
- `low → ACC_48`

让 APP 自动兜底，插件逻辑极简。

### 🟡 盲点六：getMusicInfo 实现路径

协议明确"播放时先 getMediaSource 再 getMusicInfo 补封面/专辑/时长"（`musicfree-protocol.md:90`）。计划 §4.2.4 说 getMusicInfo 调 `/api/qq/search` 获取详情——但 search 返回列表，还要按 id 过滤。

**建议**：后端单开 `/api/{source}/info?id=xxx` 端点，直接返回单曲元数据，插件一次调用拿齐 cover/album/duration。

---

## 4. 能力评估修订（测速 / Cookie / VIP）

### 4.1 计划第 7 章的准确与偏差

| 计划断言 | 评审 |
|---------|------|
| 实时测速 ❌ 没有，AudioLinkTester 只采样 8KB 识别格式 | ✅ 准确（`misc.py:339-374`，无 latency 字段） |
| 测速可实现，在 _download 流式下载加 time.time() | ⚠️ **偏差**：这只测下载速度，不测"多源 parser 哪个快"。计划第 7.1 节的 `AudioLinkTester.speed_test()` 方案测的是最终 URL 速度，不是 parser API 速度 |
| Cookie 有效性 ❌ 没有统一机制 | ✅ 准确，但遗漏：TIDAL 有完整实现（`tidalutils.py:430-447` 的 `getsubscription/valid/isvipaccount`）应作为模板强调 |
| VIP 检测 ❌ 没有，l1 注释只是静态排序 | ✅ 准确（`qq.py:317-321` 等，first-wins 静态） |
| 在 utils/ 下建 detector.py | ✅ 方向正确 |

### 4.2 测途回答（精确版）

**问题**：musicdl 对某平台（如 QQ）的多个源，是否有实时测速和检测 Cookie 有效性/VIP 级别能力？

**回答**：

| 能力 | 当前状态 | 实现位置 | 可实现性 |
|------|---------|---------|---------|
| **实时测速（多 parser API 延迟排名）** | ❌ 完全没有 | chokepoint 在各平台 `_parsewiththirdpartapis`（`qq.py:315`/`kuwo.py:248`/`netease.py:608`/`kugou.py:221`/`qobuz.py:257`/`deezer.py:224`） | ✅ 可加：在该方法里把每个 `parser_func(...)` 包 `time.perf_counter()`，记录到 `self._parser_health`，迭代前按健康度排序 |
| **下载速度测速** | ❌ 没有 | `base.py:_download` 流式下载循环 | ✅ 可加，但只对最终 URL，不影响源选择 |
| **Cookie 有效性检测** | ❌ 无统一机制，仅 TIDAL 有 | TIDAL 模板在 `tidalutils.py:430-447`；钩子在 `@useparseheaderscookies` 装饰器（`misc.py:92-124`） | ✅ 可加：照 TIDAL 模板给 QQ/酷我/Qobuz 补 `validcookie()` |
| **VIP 级别检测** | ❌ 仅 TIDAL（`tidal.py:98` 调 `isvipaccount`） | 各平台 `_parsewithofficialapiv1` 前置（`qq.py:332`/`kuwo.py:280`/`qobuz.py:267`） | ✅ 可加：QQ 有 `music.VipQueryServer.GetUserVipInfo`，酷我有 `/api/vip/user/info`，Qobuz 有 `/user/get` 返回 `credential/subscription` |

**关键补充**（计划第 7 章遗漏）：
- 当前 musicdl 配了过期 Cookie 会"跳过第三方（`_parsewiththirdpartapis` 第 316 行 return 空）→ 官方 API 空 purl → 静默无结果"**死路**。P-04 腾讯音乐插件的"未登录/VIP 曲直接走代理链"是更优解，detector 检测到 Cookie 失效应**自动回退第三方**而非死等。
- TIDAL 的 `getsubscription/valid/isvipaccount`（`tidalutils.py:430-447`）是现成模板，直接照搬到 QQ/酷我/Qobuz。
- l1-l4 的 `# svip`/`# vip` 注释是**作者人工判断**，非实测；酷我 l3 `[:0]` 是人工永久禁用。

### 4.3 detector.py 实施建议（修订计划第 7.4 节）

计划提出 `AccountDetector`，方向对，但应明确：

```python
# musicdl/modules/utils/detector.py
class AccountDetector:
    @staticmethod
    def detect(cookies: dict, platform: str) -> dict:
        """统一入口，返回 {valid, level, nickname, available_qualities}"""
        # platform 路由到 _detect_qq / _detect_kuwo / _detect_qobuz / _detect_tidal

    @staticmethod
    def _detect_qq(cookies):
        """照 TIDAL tidutusils.py:430-447 模板"""
        # 1. valid: 调 music.userInfo 或 GetVkeyServer 探测
        # 2. level: music.VipQueryServer.GetUserVipInfo → is_annual_vip/is_vip
        # 3. available_qualities: 据等级返回 [MASTER, FLAC, MP3_320, ...]
```

**优先级**（同意计划）：Cookie 检测 > VIP 检测 > 测速。但补充：Cookie 失效时**必须自动回退第三方 API**，否则检测了也没用。

---

## 5. etc/ 插件分析与提取成果

详见 `docs/ETC-PLUGINS-ANALYSIS.md`。此处摘要关键结论：

### 5.1 提取的端点/密钥

| 类别 | 数量 | 对 musicdl 新增 |
|------|------|----------------|
| 第三方解析端点 | 14 个 | 10 个真新增 + 3 个已内置(交叉验证) + 1 个歌词源 |
| 密钥 | 6 组 | 含 lx-music 签名密钥对(一套双平台)、nki/cyapi apikey、ikunshare/lxmusicapi request-key |
| Cookie 字段 | 5 类 | QQ uin/qm_keyst/authst/g_tk/兜底token、酷我 kw_token |

### 5.2 最高价值的 3 个发现

1. **lx-music v4 签名协议**（P-02/P-09）：`SCRIPT_MD5=1888f98...` + `SECRET_KEY=JaJ?a7...`，一套密钥同时覆盖 QQ（`/url/tx/{mid}`）和酷我（`/url/kw/{id}`），无鉴权状态，实现最干净。
2. **酷我无 Cookie 官方端点**（P-04 回退终点）：`nmobi.kuwo.cn/mobi.s?f=web&type=convert_url_with_sign&rid={id}&br=BR`，无 Cookie 即可返回 FLAC，可作为酷我无 Cookie 主源。
3. **P-04 腾讯音乐插件**是 etc/ 里唯一带 VIP 判定（`type==1`）+ 登录态校验（`qm_keyst` 前缀 `W_X`/`Q_H_L`）+ 多源回退阶梯（GetVkey→ikunshare→haitangw→lxmusicapi→酷我重搜）的参考实现，是 musicdl 静态 l1-l4 列表的动态版原型。

### 5.3 对 resolve_url 盲点的馈赠

etc/ 插件几乎全部用范式 A/B（直接用 song_id 调第三方端点拿 URL，不重搜索）。这**证明了 musicdl 按 song_id 重解析的可行路径**——不是新端点本身，而是证明了"按 id 直接解析"绕过"必须重搜索"困境的可行性。

---

## 6. 修订后的实施清单

基于上述评审，对计划第 4 章实施清单的修订建议：

### 阶段 0：技术验证（新增，最高优先）

- [ ] 0.1 Spike：验证"绕过搜索、用 song_id 直接调 lx-music 签名 API / nmobi.kuwo.cn mobi.s 拿到 FLAC"可行
- [ ] 0.2 如 spike 失败，退回"搜索时缓存链接 + 短 TTL"折中方案

### 阶段 1：FastAPI 后端（修订）

- [ ] 1.1 **绕过 MusicClient，直接实例化 QQMusicClient/KuwoMusicClient**（避免 rich/Hi-Fi 干扰）
- [ ] 1.2 实现 `/api/{source}/search?q=xxx&page=1` → 搜索
- [ ] 1.3 **实现 `/api/{source}/url?id=xxx&quality=xxx` 按需解析快路径**（用阶段 0 验证的 song_id 直调方案）
- [ ] 1.4 实现 `/api/{source}/info?id=xxx` → 单曲元数据（封面/专辑/时长）
- [ ] 1.5 实现 `/api/{source}/lyric?id=xxx` → 歌词
- [ ] 1.6 后端用 `asyncio.to_thread` 包裹同步调用，避免阻塞事件循环

### 阶段 2-3：插件（修订）

- [ ] 2.1 插件元字段**必须设 `cacheControl: "no-cache"`**
- [ ] 2.2 音质映射：`super→FLAC/MASTER, high→320, standard→128, low→ACC_48`，依赖 APP 自动兜底
- [ ] 2.3 getMusicInfo 调 `/api/{source}/info`（非 search）

### 阶段 4：部署（修订）

- [ ] 4.1 **用 Docker 而非裸装**（与现有 ncm-api/kugou-api 一致，规避 curl_cffi/cryptography 编译问题）
- [ ] 4.2 `--workers 1`，配合 to_thread

### 阶段 5（新增）：musicdl 能力增强

- [ ] 5.1 新增 `_parsewithlxmusicsignedapi`（lx 签名，QQ+酷我双平台）
- [ ] 5.2 新增 `_parsewithnmobikuwobyid`（酷我无 Cookie 官方 mobi.s）
- [ ] 5.3 新增 `_parsewithikunshareapi`/`_parsewithnkipwbyid`/`_parsewithcyapibyid` 等（etc/ 提取的端点）
- [ ] 5.4 新建 `detector.py`：Cookie 有效性 + VIP 级别检测（照 TIDAL 模板）
- [ ] 5.5 在 `_parsewiththirdpartapis` 加 parser 健康度缓存（成功/失败计数 + 冷却跳过 + 动态排序）
- [ ] 5.6 Cookie 失效时自动回退第三方 API（修复当前死路）

---

## 7. 附录：关键文件索引

| 文件 | 用途 | 评审引用 |
|------|------|---------|
| `musicdl/musicdl.py` | MusicClient + CLI | Hi-Fi 过滤(116)、search(161-176)、硬编码路径(52) |
| `musicdl/modules/sources/base.py` | BaseMusicClient | search 编排(128-166)、_download 协议分派(174-194)、parseplaylist(242) |
| `musicdl/modules/sources/qq.py` | QQ 客户端 | _parsewiththirdpartapis(315-325)、_parsewithofficialapiv1(332-370)、Cookie 启发式(384) |
| `musicdl/modules/sources/kuwo.py` | 酷我客户端 | l1/l2/l3(251-253)、_parsewithofficialapiv1(280-306) |
| `musicdl/modules/utils/misc.py` | AudioLinkTester + 装饰器 | test(339-374, 无 latency)、@useparseheaderscookies(92-124) |
| `musicdl/modules/utils/tidalutils.py` | TIDAL 工具 | getsubscription/valid/isvipaccount(430-447) — **detector 模板** |
| `musicfree-plugins/docs/references/musicfree-protocol.md` | 插件协议 | getMediaSource(80)、10s 超时(30,86)、cacheControl(60,185) |
| `musicfree-plugins/shared/runtime.js` | 共享运行时 | 瘦客户端模式，后端需造等价 /url 端点 |
| `docs/ETC-PLUGINS-ANALYSIS.md` | etc/ 插件专题 | 14 端点/6 密钥/3 范式，本评审依据 |
