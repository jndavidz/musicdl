# musicdl 未完成事项（本仓）

> 范围：**仅 musicdl 仓库**（库层 / server / webgui / docs / scripts）。songloft、open-xiaoai 侧事项不入本文。
> 快照：2026-10-29；离线冒烟 = server 46+58+13+41 项、webgui 38 项全 PASS（七插件 153 项在姊妹仓）。
> 进度与跨区契约以 `D:\_work\dev\docs\projects\MUSICDL\music-ecosystem-roadmap.md` 为准；本文只列"还没做完"。

## P0 · v2 托管播放（K-01…K-06 已离线 + NAS 实网验收）

已实现（离线可验）：`POST /v2/playback/resolve`、`POST /v2/cache/invalidate`、严格播放准入、
真实并发边界、singleflight/429 冷却、WebGUI 严格来源+身份快照+原子发布+outbox、
七插件 v2 优先（列表在姊妹仓 `D:\_work\repos\musicfree-plugins\docs\PLUGIN-COMPAT.md`）。

**NAS 部署与实网验收（2026-10-29，授权执行）**

| 项 | 值 |
|---|---|
| 源代码 | `api-server` `f29d0f3`（K-01…K-06 + 审查/评审修复 + 探测哨兵修复） |
| 镜像 | 首次 `ead4f0a67c94`（v2 404）→ `b19e5f6ca09d` → 当前 `edfa0e388758`；`musicdl:previous` = `b19e5f6ca09d` |
| 容器 | `musicdl-api` healthy / `musicdl-webgui` running（同一镜像重建） |
| 回滚 | `docker tag musicdl:previous musicdl:latest && docker compose up -d --no-build`（旧镜像忽略 `SERVICE_TOKENS`，回滚安全） |
| 凭证 | `/volume2/dev/data/api-secrets/musicAPI/kwqq_service_tokens.json`（600；3 个 token：`kwqq-playback` / `kwqq-invalidate` / `kwqq-media-prepare`，generation 2；compose 里以 token 为键） |
| 验收（当前镜像） | v2 实网 24/24（kuwo/migu 解析、bilibili 415+AAC 转码输入、鉴权矩阵、失效、v1 回归）；评审修复补充 4/4（别名拼写共享缓存/别名校验失效/非 ASCII token 401）；live 冒烟 `--all` 58/58 |

仍未完成：

- **跨项目联调**：Songloft S-03（media_prepare 消费）、bridge B-05/B-06（v2 TrackRef 消费）未开始；`music_ecosystem` runner 的 `singleflight`/`timeout-capacity`/`download-identity`/`ingest-scan`/`consumers-seven` case 需两侧就绪后运行。
- **插件发布**：七插件构建产物已更新但未发布（`srcUrl` 仍指向旧包），插件侧 `serviceToken` 尚未下发——未配置时插件继续走 v1；发布与真实客户端验收需单独授权。
- **webgui 下载冒烟**：`examples/musicdlwebgui/tests/test_smoke.py` 会向 `/music/download` 落一个文件，未在本次授权内执行（只读验收 6/6）。
- **许可澄清**：PolyForm NC 正文与 README 分发表述冲突未解；公开分发前须确认 AGPL 组件源码提供义务，家庭私用不构成公开授权。

## P1 · 接口扩源（消费方已在等）

### 1. kuwo 专辑曲目通道

- 现状：专辑候选可搜（`search.kuwo.cn/r.s?ft=album`）；曲目列表 wapi `/api/www/album/musicList` 需 `kw_token` cookie，curl 拿不到（JS 注入），nmobi albuminfo 空响应。
- 下一步：找 token 获取通道（页面 meta/JS 或 nmobi 加密通道），接 `SourceAdapter.album()` 后 `/album` 200 + 有序 `track_no`。

### 2. QQ 专辑通道

- 现状：匿名受限（search_type=3 空结果、`AlbumSongList`/`AlbumInfoEx` 500003）。
- 定位：**默认不投入**；仅当引入登录态方案时再评估。

### 3. 歌单扩源

| 源 | 现状 | 结论 |
|---|---|---|
| kugou | 容器 `/playlist/detail`、`/playlist/track/all` 均 error_code **20010** | 容器侧故障，不可接；同容器 `/lyric` 同病 |
| qianqian | 仅 `/v1/tracklist/info` by id，无按名检索 | 需外部歌单 ID，当前不接 |
| kuwo / QQ | 无公开按名检索通道 | 不接 |

- 完成判据（任一源接通）：`/{source}/playlist` 200 + 有序 items；探测结论回写 `docs/MUSIC-SOURCES-REGISTRY.md` §3.1。

## P2 · 门控（等触发，不主动开工）

- **C4 `search_metadata` 下沉**：门控 = `/api/stats/dedupe`；2026-10-28 实测 `contested=0, wins={api:0,lib:0}` → 不启动。
- **上游同步**：上游 v2.15.x 预计 2026-11 月中，按 `docs/UPSTREAM-SYNC-SOP.md` 执行。

## P3 · 收尾（仅剩一条需管理员权限）

- C7 音流 POC 已退役：代码资产归档 `scripts/subsonic-poc/`（冻结不维护），本机 `dlna-proxy` / Subsonic 门面进程已停。
- **剩余**：删除残留 portproxy 规则 `10.10.10.6:58091 → 172.17.191.78`（`netsh` 需管理员）：
  `netsh interface portproxy delete v4tov4 listenaddress=10.10.10.6 listenport=58091`
