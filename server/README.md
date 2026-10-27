# kw-qq-music-api

自托管酷我+QQ音乐 API 服务，基于 musicdl（hifi 分支解析链）+ FastAPI，单容器双源。
计划与决策记录见仓库根 `docs/KUWO-QQ-API-SERVER-PLAN.md`。

## 端点

统一响应包裹 `{"code": 200, "msg": "...", "data": ..., "timestamp": ...}`；业务性未命中返回 HTTP 200 + `code` 403/404，上游故障返回 502/504。

| Method | Path | 参数 | 说明 |
|--------|------|------|------|
| GET | `/{source}/search` | `keywords`*、`page`=1、`limit`=20(>50 截断到 50) | 元数据搜索（单上游请求，无解析链，~200ms） |
| GET | `/{source}/song/url` | `id`*、`quality`=auto\|320k\|192k\|128k\|flac\|hires\|master\|surround51（MusicFree 四档：low=128k/standard=192k/high=320k/super 封顶 320k；后两档仅酷我，无损档仅下载有效）、`copyright`（仅 migu：搜索项 `extra.copyrightId` 回传） | 播放直链（酷我 nmobi 直出 ~120ms；QQ 第三方链 1–11s，长尾由健康度冷却收敛） |
| GET | `/{source}/song/info` | `id`*、`copyright`（仅 migu） | 单曲元数据（封面/专辑/时长） |
| GET | `/{source}/lyric` | `id`* | LRC 歌词（migu/qianqian/bilibili/deezer 恒空） |
| GET | `/healthz` | — | 存活探针（豁免 API key 与限流） |
| GET | `/status` | — | parser 健康度（`<source>:<parser>` 键）+ 缓存统计 |
| GET | `/metrics` | — | Prometheus 文本格式（请求计数/延迟直方图/parser 健康 gauge/缓存命中率 gauge；非信封包裹，豁免限流； Grafana scrape 配置见下文部署节） |
| POST | `/kugou/vip/day` · `/kugou/vip/upgrade` | — | 酷狗概念版 VIP 领取（语义化包裹） |
| GET | `/kugou/vip/status` | — | VIP 权益结构化视图 |
| GET/POST | `/kugou/api/{path}` · `/netease/api/{path}` | 任意容器端点 | 通用透传（自动注入账号 cookie，屏蔽登出/验证码等危险路径；上游错误原样透传） |

`{source}` ∈ `kuwo` | `qq` | `qianqian` | `migu` | `netease` | `kugou` | `bilibili`（注册表唯一定义处：`server/adapters/__init__.py` 的 `ADAPTER_CLASSES`）。

### 音质路由

| quality | 酷我 | QQ |
|---------|------|-----|
| auto/320k | nmobi 直出（真 320kbps，码率不足回退 mobi.s → 第三方链） | 第三方解析链（vkeys 优先） |
| 128k | nmobi 128kmp3 | 同上 |
| flac/hires/master/surround51 | 默认 403（`ENABLE_LOSSLESS=false`）；开启后酷我 nmobi 2000kflac（flac）/ 20900kmflac（master，192k/24bit，mflac+ekey 需 QMC 解密）/ 20501kmflac（surround51，6ch）→ 第三方链 | 默认 403；开启后走链取最优 |

响应永远如实返回实际 `ext` / `bitrate_kbps` / `size_bytes`。

## 配置（环境变量）

| 变量 | 默认 | 说明 |
|------|------|------|
| `KWQQ_PORT` | 3003 | 监听端口 |
| `ENABLE_LOSSLESS` | false | 无损档总开关（插件场景保持 false，封顶 320kbps） |
| `HARD_TIMEOUT_S` | 35 | 单请求硬超时 |
| `TESTER_TIMEOUT` | 3,8 | 直链 HEAD/GET 探测超时（连接,读取） |
| `MAX_CONCURRENCY` | 4 | 每源并发信号量 |
| `PARSER_FAIL_THRESHOLD` | 3 | 连续失败 N 次进入冷却 |
| `PARSER_COOLDOWN_S` | 300 | 冷却时长（期间该 parser 被跳过） |
| `URL_CACHE_TTL` / `SEARCH_CACHE_TTL` / `META_CACHE_TTL` | 600/300/86400 | 各缓存 TTL（秒） |
| `SEARCH_SIZE_DEFAULT` / `SEARCH_SIZE_MAX` | 20/50 | 搜索默认条数 / 上限（超过截断） |
| `API_KEY` | 空（关闭） | 服务级 API key；`X-API-Key` 或 `Basic base64(KEY+":")` |
| `TRUSTED_NETWORKS` / `UNTRUSTED_HOSTS` | 127/8、10.10.10.0/24、10.20.0.0/24、172.16/12、192.168/16 / 10.10.10.1 | 免 key 网段（10.20.0.0/24 = 办公室 WG）/ 强制走 key 的来源 IP（Lucky 反代必须列入） |
| `RATE_LIMIT` | 120/minute | **仅外网**固定窗口限流（`N/second\|minute\|hour\|day`，空 = 关闭）；可信网段完全豁免，外网（经 Lucky 中继后同源 IP）共享一个桶，429 带 `X-RateLimit-*` + `Retry-After` 头 |
| `NCM_API_BASE` / `KUGOU_API_BASE` | 10.10.10.2:3000/3001 | NAS 侧 ncm-api / kugou-api 容器地址 |
| `KUGOU_TOKEN_FILE` / `NETEASE_COOKIE_FILE` | /app/secrets/* | 酷狗 token / 网易 cookie 挂载路径（网易缺省匿名转发） |
| `BILI_SESSDATA` | 空 | bilibili 账号 cookie（解锁 Hi-Res/Dolby） |
| `COOKIE_REFRESH_S` | 1800 | 酷狗 cookie 缓存刷新周期（秒） |

## 本机开发

```bash
uv venv --python 3.12 && uv pip install -p .venv/bin/python -r requirements.txt -r server/requirements.txt -e .
XDG_STATE_HOME=$PWD/.state .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 3003
# 离线冒烟（无需任何上游/NAS；信封/鉴权/缓存/音质表契约，~1.5s）
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_offline.py
# live 冒烟默认档 kuwo/qq/migu/qianqian（公网匿名端点）；--all 追加 kugou/bilibili + passthrough（需 NAS 容器）
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://127.0.0.1:3003 [--all]
```

验证双轨：改动后离线 + live 默认档全 PASS 即可在本机收工；NAS 容器相关源与 passthrough 以部署后 `--all` 全 PASS 为验收。

## NAS 部署

```bash
bash deploy/deploy.sh     # WSL 内运行：同步源码 → 本地 docker build → gzip 管道传 NAS → compose up -d --no-build
                          # → api:3003 / webgui:3004 双探活 → 失败自动回滚（musicdl:previous）
# 验收（全量档）
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://10.10.10.2:3003 --all
XDG_STATE_HOME=$PWD/.state .venv/bin/python examples/musicdlwebgui/tests/test_smoke.py http://10.10.10.2:3004
```

**单镜像双容器（2026-10-28）**：`musicdl:latest` 一个镜像跑两个容器——`musicdl-api`(3003) 与
`musicdl-webgui`(3004)；webgui 的 fastapi/uvicorn/pydantic 是 server 依赖的子集，不额外增重。
镜像**在 WSL 侧构建**（DS416play 上构建太慢），经 `docker save | gzip | ssh 'docker load'` 传输；
不要用 `wsl.exe` 把二进制导到 Windows 再转发（会损坏流）。

compose 位于 `deploy/docker-compose.yml`（NAS 侧 `/volume2/docker/musicdl-api/docker-compose.yml`，
**两份文件**，NAS 侧保留自己的 `API_KEY` 与 `ENABLE_LOSSLESS=true`），`restart: unless-stopped` + 内置 healthcheck。

**webgui 容器**：`network_mode: host`（3004 直绑宿主，回环调 `127.0.0.1:3003` 属可信网段免 key）；
`restart: "no"` **按需拉起**（平时不用，`docker start|stop musicdl-webgui`）；
卷 `/volume1/music:/music`（下载落 NAS 本地盘）+ `/volume2/docker/musicdl-webgui:/cfg`（`config.json` 与
`.state` 队列快照）；配置用 `MUSICDL_WEBGUI_*` 环境变量注入，镜像内不含 config.json。
⚠️ 容器 root 写 Synology 共享会得到 `000` 权限（ACL 生效），webgui 落盘后显式 `chmod 644`
（`MUSICDL_DOWNLOAD_FILE_MODE` 可调），否则 Lyrion 等下游消费方读不到。

**部署现状注记（2026-10-27）**：NAS 侧实际运行 compose 的 `ENABLE_LOSSLESS=true`（无损档在 NAS 上是活的，含 master/surround51 加密档），与仓库 compose 默认 `false` 不同——以 NAS compose 为准，修改后需同步本注记与 `docs/QUALITY-MATRIX.md` / `docs/API-REFERENCE.md`。

**Grafana / Prometheus 对接**（dashboard 16110）：Prometheus 抓取任务（NAS 内网来源免 key）：

```yaml
- job_name: kwqq-music-api
  static_configs: [{ targets: ['10.10.10.2:3003'] }]
  metrics_path: /metrics
```

可用指标：`kwqq_requests_total{endpoint,status}`、`kwqq_request_latency_seconds`（histogram）、`kwqq_parser_up` / `kwqq_parser_fail_streak{parser}`、`kwqq_cache_hit_rate` / `kwqq_cache_items{cache}`。

## 架构速览

```
client → FastAPI(create_app) → 路由处理器（读 request.app.state）
            ├─ app.state: settings / 4×TTLCache / ParserHealth / adapters（可注入替换，离线冒烟靠它）
            ├─ SourceAdapter(adapters/*.py, 7 源)
            │     ├─ TTLCache(cache.py)          url 10min / search 5min / meta·lyric 24h
            │     ├─ ParserHealth(parsers_health) 连败3次冷却5min，跳过失效源
            │     └─ musicdl 源客户端（免 Cookie，第三方解析链 + 官方匿名端点）
            │         酷我: nmobi → mobi.s → zhenpin(master/surround51) → haitangw → xcloudv
            │         QQ:   第三方链(vkeys→…→nki) → 3e0 兜底
            └─ proxy.py 通用透传 → NAS 侧 kugou-api / ncm-api 容器
```

所有阻塞调用经 `asyncio.to_thread` + 每源信号量 + 硬超时包装；`workers=1` 保证进程内缓存一致性。
