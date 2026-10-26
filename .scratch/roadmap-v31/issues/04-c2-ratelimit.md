# C2 限流：仅外网来源

Status: resolved
Type: task

roadmap §2 C2：仅外网（非 TRUSTED_NETWORKS）限流，429 + X-RateLimit 头，内网免限。
实现说明（对 roadmap 的工具名偏差，待用户确认）：roadmap 写 SlowAPI，但 slowapi/limits
无法表达「可信网段豁免」这一核心语义，且给 NAS 弱机加依赖链不合算；
按验收标准自研固定窗口中间件（server/ratelimit.py，零依赖，复用 auth 的可信网段判定）。
RATE_LIMIT env（默认 120/minute，空 = 关闭）。

## Comments
