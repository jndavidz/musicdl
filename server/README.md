# kw-qq-music-api

自托管酷我+QQ音乐 API 服务，基于 musicdl（hifi 分支解析链）+ FastAPI，单容器双源。
计划与决策记录见仓库根 `docs/KUWO-QQ-API-SERVER-PLAN.md`。

## 端点

统一响应包裹 `{"code": 200, "msg": "...", "data": ..., "timestamp": ...}`；业务性未命中返回 HTTP 200 + `code` 403/404，上游故障返回 502/504。

| Method | Path | 参数 | 说明 |
|--------|------|------|------|
| GET | `/{source}/search` | `keywords`*、`page`=1、`limit`=20(≤50) | 元数据搜索（单上游请求，无解析链，~200ms） |
| GET | `/{source}/song/url` | `id`*、`quality`=auto\|320k\|192k\|128k\|flac\|hires\|master\|surround51（MusicFree 四档：low=128k/standard=192k/high=320k/super 封顶 320k；后两档仅酷我，无损档仅下载有效） | 播放直链（酷我 nmobi 直出 ~120ms；QQ 第三方链 1–11s，长尾由健康度冷却收敛） |
| GET | `/{source}/song/info` | `id`* | 单曲元数据（封面/专辑/时长） |
| GET | `/{source}/lyric` | `id`* | LRC 歌词 |
| GET | `/healthz` | — | 存活探针 |
| GET | `/status` | — | parser 健康度（`<source>:<parser>` 键）+ 缓存统计 |

`{source}` ∈ `kuwo` | `qq`。

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

## 本机开发

```bash
uv venv --python 3.12 && uv pip install -p .venv/bin/python -r requirements.txt -r server/requirements.txt -e .
XDG_STATE_HOME=$PWD/.state .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 3003
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://127.0.0.1:3003   # 15 项冒烟
```

## NAS 部署

```bash
# 同步构建上下文（排除开发产物）到 NAS，然后：
ssh zxsadmin@10.10.10.2 "cd /volume2/docker/musicdl-api && /usr/local/bin/docker compose up -d --build"
# 验收
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://10.10.10.2:3003
```

compose 位于 `deploy/docker-compose.yml`（NAS 侧 `/volume2/docker/musicdl-api/docker-compose.yml`），`restart: unless-stopped` + 内置 healthcheck。

## 架构速览

```
client → FastAPI(app.py) → SourceAdapter(adapters/{kuwo,qq}.py)
                              ├─ TTLCache(cache.py)          url 10min / search 5min / meta·lyric 24h
                              ├─ ParserHealth(parsers_health) 连败3次冷却5min，跳过失效源
                              └─ musicdl 源客户端（免 Cookie，第三方解析链 + 官方匿名端点）
                                  酷我: nmobi → mobi.s → 第三方链(nxinxz/nobb/…)
                                  QQ:   第三方链(vkeys→…→nki) → 3e0 兜底
```

所有阻塞调用经 `asyncio.to_thread` + 每源信号量 + 硬超时包装；`workers=1` 保证进程内缓存一致性。
