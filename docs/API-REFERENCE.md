# kw-qq-music-api 接口开发文档

> 版本：1.0 · 更新：2026-08-23 · 源码分支：`api-server`（musicdl 仓库）
> 服务定位：自托管多源音乐 API（酷我/QQ/千千/咪咕），基于 musicdl hifi 分支解析链（免 Cookie 第三方无损链 + 官方匿名端点）
> 计划与决策：见 `docs/KUWO-QQ-API-SERVER-PLAN.md`；快速上手见 `server/README.md`

---

## 1. 服务拓扑

```
MusicFree 插件 / 自研客户端
   │
   ├─ 外网: https://kwqq-api.pegbiotec.com:4433
   │        └─ Lucky 反代(AX6000) ──► 10.10.10.2:3003  [Lucky 层 Basic Auth：仅拦截 "/" 路径]
   │                服务层 API Key 校验（全部功能路径，401 拦截）
   │
   └─ 内网: http://10.10.10.2:3003                     [免 key（来源 IP 白名单）]
          └─ musicdl-api 容器 (Docker, host 网络模式)
               ├─ FastAPI (uvicorn workers=1, 端口 3003)
               ├─ adapters: kuwo / qq / qianqian / migu
               ├─ TTL 缓存: url 10min / search 5min / meta·lyric 24h
               ├─ ParserHealth: 第三方解析源健康度（连败 3 次冷却 5min）
               └─ musicdl 源客户端（零 Cookie）
```

## 2. 认证

### 2.1 双层模型

| 层 | 机制 | 覆盖范围 | 配置 |
|----|------|----------|------|
| Lucky 反代 | HTTP Basic | 仅根路径 `/`（Lucky 子规则行为，kgapi 同样如此） | Lucky WebUI |
| **服务层** | **API Key** | **全部功能路径**（/search /song/url /song/info /lyric /status） | `API_KEY` 环境变量 |

> 结论（2026-08-23 实测）：Lucky 的 Basic Auth 只挑战 `/` 精确路径，功能路径穿透——**必须依赖服务层 API Key**，不要依赖 Lucky 层。

### 2.2 API Key 校验规则

- `API_KEY` 为空 → 校验关闭（任何来源免认证，仅适合纯内网部署）
- `API_KEY` 非空时：
  - **内网免 key**：来源 IP ∈ `TRUSTED_NETWORKS`（默认 `127.0.0.0/8, 10.10.10.0/24, 172.16.0.0/12, 192.168.0.0/16`）且不在 `UNTRUSTED_HOSTS`（默认 `10.10.10.1` = Lucky 路由器入口，**外网流量经它转发，必须排除**）→ 免认证
  - **其余来源**（即经 Lucky 进来的外网流量，源 IP = 10.10.10.1）→ 必须带 key
  - `/healthz` 恒豁免（供监控探针）

### 2.3 客户端携带 key 的方式（二选一，与 kugou 插件模式一致）

```
Authorization: Basic base64(API_KEY + ":")
# 等价写法：X-API-Key: <API_KEY>
```

- 校验成功返回 200；失败返回 `401 + WWW-Authenticate: Basic realm="Authorization Required"`
- 401 body：`{"code": 401, "msg": "unauthorized: missing or invalid API key", "data": null, "timestamp": ...}`

### 2.4 插件侧示例（MusicFree）

```js
async getMediaSource(musicItem, quality) {
  return axios.get(`${BASE}/qq/song/url`, {
    params: { id: musicItem.id, quality: '320k' },
    headers: { Authorization: 'Basic ' + encodeBase64(API_KEY + ':') },
  }).then(r => ({ url: r.data.data.url, headers: r.data.data.headers || {} }));
}
```

---

## 3. 统一响应格式

所有端点返回 HTTP 200（业务错误码在 body 内）或 HTTP 401/502/504：

```json
{ "code": 200, "msg": "success", "data": { ... }, "timestamp": 1787452419600 }
```

| HTTP | code | 含义 |
|------|------|------|
| 200 | 200 | 成功 |
| 200 | 403 | 无损档被禁用（ENABLE_LOSSLESS=false 时请求 flac/hires） |
| 200 | 404 | 未知 source / 歌曲无可用音源 |
| 401 | 401 | API Key 缺失或错误（服务层） |
| 502 | 502 | 上游解析全部失败/上游异常 |
| 504 | 504 | 超过 `HARD_TIMEOUT_S` 硬超时 |

---

## 4. 端点参考

`{source}` ∈ `kuwo` | `qq` | `qianqian` | `migu`。全部为 GET。

### 4.1 GET /{source}/search — 搜索（仅元数据）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keywords | string | ✅ | 搜索关键词 |
| page | int | — | 页码，默认 1，≥1 |
| limit | int | — | 每页条数，默认 20，≤50 |

特点：单次上游请求（不经解析链，~200ms），返回无 download_url 的元数据——**播放时须再调 /song/url 实时取链**（链有时效）。

```json
{
  "code": 200, "data": {
    "keywords": "林俊杰", "page": 1, "total": 20,
    "items": [{
      "id": "93157", "name": "江南", "singer": "林俊杰", "album": "...",
      "ext": null, "size_bytes": null, "duration_s": 267,
      "cover": "https://img4.kuwo.cn/star/albumcover/...jpg", "source": "kuwo"
    }]
  }
}
```

### 4.2 GET /{source}/song/url — 播放直链（核心）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 歌曲 id（kuwo 数字 rid / qq songmid / qianqian TSID / migu contentId） |
| quality | string | — | auto(默认)/320k/128k/flac/hires；也接受 low/standard/high/super 别名（映射见 §5） |
| copyright | string | — | **仅 migu**：search 返回的 `extra.copyrightId` 原样回传（咪咕 by-id 必需） |

成功响应：

```json
{
  "code": 200, "data": {
    "id": "93157", "source": "kuwo", "quality": "320k",
    "url": "https://car-er.kuwo.cn/.../F000...flac?bitrate$2000...",
    "ext": "mp3", "size_bytes": 10485760, "bitrate_kbps": 320,
    "duration_s": 267, "cover": null,
    "verified": true, "headers": {},
    "parser": "nmobi.direct", "elapsed_ms": 151, "cached": false
  }
}
```

字段说明：`url` 为经 AudioLinkTester 验证的**最终直链**（可能含重定向后地址）；`ext/bitrate_kbps/size_bytes` 如实反映实际音质；`parser` 标注出链通道（nmobi.direct / mobi.s.direct / 第三方链 / 3e0.relay）；`cached=true` 表示命中 TTL 缓存。

**音质路由**（服务端自动选择，见 §5）。

### 4.3 GET /{source}/song/info — 单曲元数据

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 歌曲 id |

```json
{ "code": 200, "data": {
  "id": "93157", "source": "kuwo", "name": "江南", "singer": "林俊杰",
  "album": "第二天堂", "duration_s": 267,
  "cover": "https://img4.kuwo.cn/star/albumcover/...jpg",
  "raw": { "kw_meta": { ... 原始字段快照 ... } }
}}
```

### 4.4 GET /{source}/lyric — 歌词（LRC 纯文本）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✅ | 歌曲 id |

```json
{ "code": 200, "data": { "id": "93157", "source": "kuwo", "lyric": "[00:00.00]词曲..." , "cached": false } }
```

酷我走 `newlyric.kuwo.cn`（DES 解密，musicdl 同源工具链），失败回退 h5 `lrclist`；QQ 走官方 `fcg_query_lyric_new.fcg`（Base64 解码）。

### 4.5 GET /healthz — 存活探针

```json
{ "code": 200, "data": { "status": "up", "uptime_s": 3853 } }
```
恒免认证。Docker healthcheck 每 60s 调用。

### 4.6 GET /status — 运行状态

```json
{ "code": 200, "data": {
  "uptime_s": 3853,
  "parsers": { "QQMusicClient:_parsewithvkeysapi": { "attempts": 1, "ok": 1, "success_rate": 1.0,
    "fail_streak": 0, "last_ms": 1181, "cooled_down": false, "last_error": null } },
  "caches": { "url": {"items": 2, "ttl": 600}, "search": {...}, "meta": {...}, "lyric": {...} },
  "settings": { "enable_lossless": false, "tester_timeout": [3,8], "hard_timeout_s": 35, "max_concurrency_per_source": 4 }
}}
```

`parsers` 键为 `<源客户端>:<parser方法名>`，`cooled_down=true` 表示该第三方源正被健康度机制跳过。

---

## 5. 音质策略

### 5.1 请求档位归一化

`low→128k`、`standard→128k`、`high→320k`、`super→320k`、`auto→320k 级`（与 MusicFree 四档及现有 netease/kugou 插件映射惯例一致，**线上封顶 320kbps**）。

### 5.2 服务端路由（2026-08-12 实测校准）

| 请求档位 | 酷我 | QQ |
|----------|------|-----|
| auto/320k/128k | ① `nmobi.kuwo.cn` 明文直出（**精确档位不降档**，~120ms）→ ② `mobi.kuwo.cn` 加密版（会静默降档，作备胎）→ ③ 第三方解析链（nxinxz/nobb 等，出无损则优先）→ ④ 降级直出（如实标注 bitrate） | 第三方解析链（vkeys→xcvts→xingmian→317ak→xianyuw→nki→hk0cc→tang→cyapi→xunhuisi→lxmusic→yutangxiaowu→lpz，健康度排序+冷却）→ 链全挂则 `music.3e0.cn` 聚合兜底（代理流 320k 级） |
| flac/hires | `ENABLE_LOSSLESS=true` 才开放：nmobi 2000k/20000kflac → 第三方链无损 | 同上开关；链返回什么如实标注 |

原则：**永远如实返回**实际 `ext/bitrate_kbps/size_bytes`；请求档位高于可得档位时返回较低的实际结果（不报错），由客户端按返回值决定。

### 5.3 已知行为边界

- QQ 官方匿名 `GetVkey` 拿不到 purl（Spike 全灭）——QQ 出链完全依赖第三方链，存在外部依赖风险
- 第三方公共解析源会不定期失效：`/status` 可观察，连败 3 次自动冷却 5 分钟（`PARSER_FAIL_THRESHOLD`/`PARSER_COOLDOWN_S` 可调）
- 酷我直出链路（nmobi/mobi）为官方匿名端点，稳定性高，是主推路径
- 备选端点池记录：`docs/KUWO-QQ-API-SERVER-PLAN.md` §阶段5.a 表（2026-08-12 复测：元力/haitangw.cc/lx-v4 已死，nmobi/3e0 存活）

---

## 6. 配置项全表（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `KWQQ_PORT` | 3003 | 监听端口（host 网络模式直接绑宿主） |
| `API_KEY` | 空 | 服务层 API Key；空=关闭校验 |
| `TRUSTED_NETWORKS` | `127.0.0.0/8,10.10.10.0/24,172.16.0.0/12,192.168.0.0/16` | 免 key 来源网段 |
| `UNTRUSTED_HOSTS` | `10.10.10.1` | 强制要求 key 的来源 IP（Lucky 入口，转发所有外网流量） |
| `ENABLE_LOSSLESS` | false | 无损档开关（flac/hires） |
| `HARD_TIMEOUT_S` | 35 | 单请求硬超时（秒） |
| `TESTER_TIMEOUT` | `3,8` | 直链验证超时（连接,读取） |
| `MAX_CONCURRENCY` | 4 | 每源并发信号量 |
| `PARSER_FAIL_THRESHOLD` | 3 | 第三方源连败阈值 |
| `PARSER_COOLDOWN_S` | 300 | 冷却时长（秒） |
| `URL_CACHE_TTL` | 600 | song/url 缓存（秒，CDN 链时效短，勿调大） |
| `SEARCH_CACHE_TTL` | 300 | search 缓存 |
| `META_CACHE_TTL` | 86400 | song/info 与 lyric 缓存 |

---

## 7. 部署与运维

### 7.1 部署（NAS）

```bash
# 1. 同步代码（本机）→ NAS
tar czf - --exclude='.git' --exclude='.venv' --exclude='.uvcache' --exclude='.state' \
    --exclude='scripts' --exclude='examples' --exclude='mcp' --exclude='.github' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='deploy' ./ \
  | ssh zxsadmin@10.10.10.2 "tar xzf - -C /volume2/docker/musicdl-api/src/"

# 2. 重建重启
ssh zxsadmin@10.10.10.2 "cd /volume2/docker/musicdl-api && /usr/local/bin/docker compose up -d --build"
```

- compose 位置：NAS `/volume2/docker/musicdl-api/docker-compose.yml`（**host 网络模式**，容器直绑 3003，源 IP 真实可判定）
- 升级/回滚：`docker compose up -d --build` 重建；镜像 tag `musicdl-api:latest`

### 7.2 验收

```bash
# 内网（免 key）
python server/tests/test_smoke.py http://10.10.10.2:3003
# 外网（带 key；注意本机若命中 DNS 负缓存可用 --resolve 强制域名→公网 IP）
python server/tests/test_smoke.py https://kwqq-api.pegbiotec.com:4433 --auth <API_KEY>:
```

冒烟 15 项：healthz / status / 双源 search / song-url（含真实下载 206 验证）/ 缓存命中 / song-info / lyric / 无损门控。

### 7.3 日志与监控

- `docker logs musicdl-api`（json-file，max-size 10m × 3）
- `/healthz`：Docker healthcheck 内置
- `/status`：parser 健康度 + 缓存命中统计（建议接入告警：`cooled_down` 增多或 `success_rate` 骤降）

### 7.4 常见故障

| 现象 | 排查 |
|------|------|
| 外网 401 | 未带 key / key 与 NAS compose `API_KEY` 不一致 |
| 外网 502 | 上游第三方链全挂或硬超时；看 `/status` parsers 冷却状态 |
| 外网 403 | 请求了 flac/hires 但 `ENABLE_LOSSLESS=false` |
| 内网 401 | 来源 IP 不在 `TRUSTED_NETWORKS`（如换网段）或命中 `UNTRUSTED_HOSTS` |
| song/url 慢 | QQ 第三方链长尾（正常 1~11s）；命中缓存后 <30ms |

---

## 8. 开发指南

### 8.1 代码结构

```
server/
├── app.py            # FastAPI 入口、路由、API Key 中间件、统一响应
├── config.py         # 全部配置（env 可覆盖）
├── cache.py          # 线程安全 TTL 缓存
├── parsers_health.py # 第三方源健康度（连败冷却 + 快照）
├── schemas.py        # Pydantic 响应模型
├── adapters/
│   ├── base.py       # SourceAdapter 抽象（run/semaphore/search_items/urldata 转换）
│   ├── kuwo.py       # nmobi→mobi.s→第三方链 音质路由 + 轻量搜索 + 歌词
│   └── qq.py         # 第三方链 + 3e0 兜底 + 轻量搜索 + 歌词
└── tests/test_smoke.py  # 15 项冒烟（支持 --auth）
```

### 8.2 核心设计约定

1. **不配 Cookie**：源客户端零 Cookie 初始化——`_parsewiththirdpartapis` 有 Cookie 时会跳过第三方链（`qq.py:316`/`kuwo.py:251`），配了反而失去免 Cookie 无损能力
2. **search 不做解析**：`/search` 走 `_search_raw`（单请求元数据）；`client.search()`（全解析链）只适合 CLI——API 若误用会分钟级超时
3. **by-id 快路径**：`_parsewiththirdpartapis({'mid': id})`（QQ）/ `({'musicrid': f'MUSIC_{id}'})`（酷我）——最小 dict 触发 `_getsongmetainfo` 自动补元数据，无需重搜索
4. **健康度包装**：`parsers_health.wrap_client()` 用 `inspect.getsource` 提取 parser 方法名逐一包装，键带 `<source>:` 前缀防跨平台重名
5. **新增源**：实现 `SourceAdapter` 子类（`_build_client`/`_search_raw`/`item_from_raw`/`song_url`/`song_info`/`lyric`），注册进 `adapters/__init__.py:ADAPTER_CLASSES`，即获得路由/缓存/认证/健康度全套能力

### 8.3 本机开发

```bash
uv venv --python 3.12
uv pip install -p .venv/bin/python -r requirements.txt -r server/requirements.txt -e .
XDG_STATE_HOME=$PWD/.state .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 3003
# 带 key 起本地服务验证认证：
API_KEY=test .venv/bin/python -m uvicorn server.app:app --port 3003
```

### 8.4 测试

```bash
# 回归（核心层改动后）：scripts/regress_stage1.py（8 项）
# Spike 基线：scripts/spike_byid.py --platform qq|kuwo --hot 5 --cold 5
# 冒烟：server/tests/test_smoke.py <base_url> [--auth user:pass]
```

---

## 9. 变更记录

| 日期 | 变更 |
|------|------|
| 2026-08-12 | v1 上线：FastAPI 服务 + NAS 部署 + 内网验收 15/15 |
| 2026-08-12 | nmobi 直出主通道 + 3e0 兜底（端点存活探测后） |
| 2026-08-23 | 服务层 API Key 守卫（Lucky 只护 `/` 的补偿）；内网来源 IP 免 key；host 网络模式部署；外网验收 15/15 |
