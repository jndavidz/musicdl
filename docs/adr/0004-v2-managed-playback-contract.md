# ADR-0004: v2 托管播放契约（TrackRef 身份、scoped 凭据、严格准入、真实并发）

日期：2026-10-29 ｜ 状态：Accepted

## Context

家庭音乐／语音托管播放（跨项目主 spec：`open-xiaoai/.scratch/music-voice-managed-playback/spec.md`）
要求 kwqq 成为唯一在线搜索与直链解析层，而现有 v1 契约有三个确定性缺陷（架构报告 §3.6）：

- 身份不完整：B站固定 `pages[0]`（分 P 串播）、咪咕只给 contentId 不强制 copyrightId，缓存键不含身份；
- 播放准入不是全源不变量：`verified` 由 HEAD/后缀/MIME/8KB sniff 推出，FLAC/AAC/加密件可被当作可播；
- 执行层超时与真实并发脱节：`wait_for(to_thread(...))` 超时后 semaphore 立即释放而线程仍在跑；
  缓存无 singleflight，上游 429 换个 host 即绕过。

同时 WebGUI 会把整个 `api_extra`（可含 ekey）与 URL 持久化进任务快照，恢复时重新信任旧凭据。

## Decision

新增**版本化 v2 契约**，v1 完全保留（下载/ekey/无损语义不变）：

1. **身份**：`TrackRef = {kind:"remote", provider:"kwqq", source, id, extra}`，`extra` 只保留影响身份的字段
   （migu `copyrightId`、bilibili `cid`/`page`），其余一律丢弃。migu 缺 copyrightId、bilibili 缺
   cid/page 直接 400。缓存键 = 身份摘要 + 播放策略 + 凭据代次（`v2:` 独立命名空间）。
2. **凭据**：v2 只接受独立 scoped service credential（`X-Service-Token`，`SERVICE_TOKENS` JSON），
   scope 分 `playback:issue` / `cache:invalidate` / `media:prepare`；`API_KEY` 不自动获得任何 scope，
   `/v2/*` 也不受内网免 key 影响。
3. **准入**：原始 quality 拼写先过白名单（无损请求 400 而不是回落 auto）；无损容器、加密件/ekey、
   >320k、非 mp3 一律 415；AAC 仅作为 `target=media_prepare` + `media:prepare` scope 的**转码输入**
   （`requires_transcode=true`、`ready=false`），永不直投。`verified` 在 v2 恒 false，
   `requires_byte_verification` 恒 true——完整文件验证归 Songloft 准备链。
4. **执行层**：每源独立线程池，容量=worker 数，只在 worker 线程真正退出（done-callback）后释放；
   调用方超时只归还调用方；等待者为有界静态分区（`MAX_WAITERS`，满则 503）；所有裸同步 I/O 带
   `IO_TIMEOUT_S`；迟到结果丢弃并计数（`/status.runtime`）。
5. **缓存**：`cached()` 走进程内 singleflight（同键一个 leader、等待者取消互不影响、失败不写负缓存）；
   上游 429 按**逻辑入口**冷却并保留 `Retry-After`，换 host/备用入口不重置冷却、429 不入成功缓存；
   `cache:invalidate` 可按当前身份精确失效，一次失效对应一次受控重解析。
6. **WebGUI**：任务快照升级为身份白名单（TrackRef / 平台+identifier），不落 URL/Cookie/ekey；
   下载走同文件系统 `.tmp` 隔离件并单次 `os.replace` 原子发布，完成后写有界幂等 outbox（Songloft S-08）；
   `kwqq_only` 严格模式禁用库兜底；无法识别或违反策略的条目暂停 `paused` 而非自动重跑。

## 拒绝记录

- **把 v2 做成 v1 的默认行为**：v1 有 MusicFree/WebGUI 等现役消费方与旧下载/ekey 契约，直接收紧会破坏
  兼容窗口（spec 明确要求迁移窗口）。因此 v2 是新增端点 + 新凭据，由消费方显式 opt-in。
- **服务端完整校验/转码后交付**：见 ADR-0002（服务端解密被拒）与 ADR-0003（质量知识留在 server），
  kwqq 只给候选与如实证据，最终字节验证与转码在 Songloft 准备链。
- **Redis 或跨进程 singleflight/冷却**：部署模型是 `workers=1`，进程内实现即可；引入外部依赖会破坏
  "不新增常驻服务"的首版约束。
- **删除超时或无限扩容来"修复"并发**：容量必须覆盖真实工作生命周期；超时语义只约束调用方，不谎称线程已被杀死。

## Consequences

- 未配置 `SERVICE_TOKENS` 时 v2 全部 401——部署须显式签发，插件未配置 `serviceToken` 时回落 v1（迁移窗口）。
- 无损档在 v2 永远不可播；需要无损的消费方只能走 v1 下载 + 本地解密（ADR-0002）。
- 冷却按逻辑入口记账：新增 host 别名/备用入口时必须复用同一逻辑名，否则冷却会被新入口绕过。
- 跨项目验收需汇总 `/status.runtime`（active/waiting/timed_out/late_dropped）与 Songloft 侧资源计数，
  单进程 PASS 不等于系统预算 PASS。
