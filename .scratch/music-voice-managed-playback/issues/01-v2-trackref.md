# K-01: 建立 v2 TrackRef 与完整身份契约

Status: ready-for-agent
Type: task
Blocked by: —
External blocked by: —

## Body

新增版本化 playback resolve 契约，TrackRef 至少包含 source/id 及影响身份的 extra。调用方使用独立 scoped-service-credential，播放签发与缓存主动失效分别授权，既有下载 key 不自动获得新权限。B站支持受验证的 bvid＋cid/page，不再固定 pages[0]；咪咕保留 contentId＋copyrightId。定义结构化规范编码供缓存与 singleflight 使用，旧 v1 路由和 ekey 下载行为不变。

### DoD

- 同 BV 不同 page/cid、同 migu id 不同 copyrightId 不串解析或缓存；缺字段明确拒绝。
- 搜索保持元数据单请求，不为补全每个候选做 view／直链 N+1；选中项可补全 TrackRef。
- v2 返回原请求身份、实际解析来源和结构化 TrackRef；缓存键包含身份、播放策略与凭据代次；跨 scope 请求明确拒绝。

### Tests

- create_app/FakeAdapter 覆盖分 P、copyright、缺字段、规范编码和 v1 兼容。
- 运行 server offline；真实上游只作后续单独验收。

### Rollback

关闭 v2 路由，v1 与旧缓存命名空间继续服务；重启清空内存态。

## Authorization

仅 server 与离线测试；不部署、不改真实 Cookie 或上游容器。

## Comments
