# K-05: 实现 WebGUI 严格来源与身份快照

Status: ready-for-agent
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
