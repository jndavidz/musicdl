# K-05: 实现 WebGUI 严格来源与身份快照

Status: resolved
Type: task
Blocked by: 01, 02
External blocked by: —

## Body

保持 API 为主和 ADR-0001 冻结兜底：新增 `kwqq_only`，开启时禁止六源进程内 library 兜底；未开启时旧兜底保持冻结，不扩功能。下载任务快照升级为身份白名单，恢复／重试重新解析，不再整体持久化 api_extra、URL 或 ekey。下载在同文件系统使用隔离临时文件并原子发布，完成后写有界 outbox 通知 Songloft S-08；WebGUI 下载／探测有独立静态资源分区。

### DoD

- 搜索、创建、恢复、重试均执行同一来源策略；严格模式无 library 旁路。
- 快照只含 TrackRef、下载目标和必要用户选择，伪造 source/extra/ekey 不被信任；运行时旧下载仍可按 ADR-0002 使用 ekey。
- 启用已有入站鉴权并区分出站 API key，匿名写被拒绝；旧任务无法识别时暂停而非自动重跑。
- 路径根约束、临时／加密件隔离和原子发布有效；重复通知幂等，进程中断无半文件入库，WebGUI 活跃与 waiter 有界。

### Tests

- 覆盖 API 成功、显式 fallback、kwqq_only、伪造身份、快照恢复、敏感字段不落地和 WebGUI auth。
- 覆盖原子发布、重复 outbox、路径穿越、下载中断和资源饱和；运行现有 WebGUI smoke、下载／ekey 回归及 runner download-identity/webgui-auth/ingest-scan。

### Rollback

关闭 kwqq_only 并还原路由提交，恢复显式旧兜底；不删除历史任务、下载文件或冻结 library 代码。

## Authorization

不改下载目录、用户配置或 NAS 文件；真实浏览器与部署验收另行批准。

## Comments

- 2026-10-29 完成（离线）：webgui 新增 `kwqq_only` 严格来源（`library.py` 来源策略，搜索/创建/恢复/
  重试同一判据，严格模式禁用六源进程内兜底；未开启时旧兜底保持冻结）；下载任务快照升级为身份白名单
  （TrackRef / 平台+identifier，不落 URL/Cookie/ekey/api_extra），无法识别或违反策略的条目暂停
  `paused` 而非自动重跑；下载走同文件系统 `.tmp/` 隔离件 + 单次 `os.replace` 原子发布，中断与取消
  都不留半文件（审查补：按同一 stem 全量清理临时件、取消后重试可用）；`outbox.py` 有界幂等 completed
  通知 + `GET /api/outbox`；入站 `api_key` 与出站 `kwqq_api_key` 分离，匿名写 401；队列
  `max_queued_items` 有界（满 503）；条目字段创建时定型，`/api/tasks` 快照不再有 dict 尺寸变化风险。
  证据：`examples/musicdlwebgui/tests/test_offline.py` 34 项 PASS（API 成功、显式 fallback、kwqq_only、
  伪造身份、旧快照暂停、敏感字段不落地、路径穿越、中断清理、重复 outbox、鉴权、取消/重试回归）；
  commits `0a25b83` + `ff68005`。
  NOT RUN：真实浏览器与 NAS 部署验收（需单独授权）。

### 范围说明（2026-10-30 收尾）
DoD 的「匿名写被拒绝」**只在配置了 `api_key` 时成立**：现网 webgui 未配 key（局域网开放），
写接口按设计放行；测试覆盖的是「配置 key 后无 key 请求 401」。该项按条件语义验收，
不宣称默认配置下也失败关闭。
