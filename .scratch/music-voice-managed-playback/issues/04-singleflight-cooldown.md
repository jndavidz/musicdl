# K-04: 实现结构化缓存 singleflight 与一致冷却

Status: resolved
Type: task
Blocked by: 01, 03
External blocked by: —

## Body

在结构化 TrackRef 键上实现 singleflight，同键并发只有一个 leader，其他等待者共享结果。完善逻辑 parser 的 429／Retry-After 冷却，host 别名、内外网或备用入口不得重置同一冷却；一个等待者取消不能误取消其他合法等待者。媒体服务可用独立 scope 按当前身份主动失效已成功但已陈旧的缓存，一次失败最多受控重解析一次，端到端重试预算由最外层命令持有。

### DoD

- N 个同键请求只执行一次上游解析；不同 cid/page/copyright/策略永不合并。
- leader 失败不形成永久坏缓存或等待者惊群，后续可按预算重试。
- 429 后备用 host 零请求且不作为成功缓存，冷却到期才允许重试；本地与上游限流分类清晰。
- 仅有效 invalidation scope 可失效当前身份；跨 scope 拒绝，旧 URL 最多受控重解析一次，各层不叠加重试。

### Tests

- 并发计数、异常后重试、身份隔离、等待者取消和 Retry-After 测试。
- 证明 host 切换不能绕冷却；运行 singleflight 与现有缓存回归。

### Rollback

回退缓存／健康度提交并重启清空内存态；不引入 Redis 或改变部署 workers 模型。

## Authorization

仅进程内实现与离线测试；不调用真实上游制造 429。

## Comments

- 2026-10-29 完成（离线）：新增 `server/singleflight.py`（同键一个 leader，等待者经 `asyncio.shield`
  共享，取消互不波及；leader 失败不写负缓存）；`server/cache.py` 全部路由共用 `cached()`，flight 键用
  TTLCache 稳定 `uid`（避免 `id()` 复用串扰）。`server/parsers_health.py` 429 按**逻辑入口**冷却并
  保留 Retry-After、429 永不入成功缓存，识别收紧为 HTTP 状态/明确措辞（id/URL 含 "429" 不再误冷却）；
  透传端点（`routes/passthrough.py`）与 netease search 复用同一逻辑入口，429 不再被旁路。
  `POST /v2/cache/invalidate` 按当前身份 + 策略 + 代次精确失效（无通配、跨 scope 403）；
  `freshness=revalidate` 先失效再经 singleflight 重解析一次并把新值写回；kwqq 自身不叠加重试。
  证据：`server/tests/test_resilience.py` 35 项 PASS（并发计数、等待者取消隔离、失败后重试、身份
  永不合并、429 跨 host 零请求、Retry-After 保留、本地/上游分类、失效精确性、revalidate 刷新）；
  commits `3c8e76a` + `ff68005`。
  NOT RUN：真实上游 429（授权禁止制造）。
