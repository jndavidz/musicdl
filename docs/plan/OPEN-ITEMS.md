# musicdl 未完成事项（本仓）

> 范围：**仅 musicdl 仓库**（库层 / server / webgui / docs / scripts）。songloft、open-xiaoai 侧事项不入本文。
> 快照：2026-10-28；验收 = 离线冒烟 46/46、NAS `--all` **58/58**。
> 进度与跨区契约以 `D:\_work\dev\docs\projects\MUSICDL\music-ecosystem-roadmap.md` 为准；本文只列"还没做完"。

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
