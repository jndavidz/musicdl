# Spec pointer: 家庭音乐／语音托管播放（musicdl／MusicFree）

唯一跨项目主 spec：[open-xiaoai `.scratch/music-voice-managed-playback/spec.md`](../../../open-xiaoai/.scratch/music-voice-managed-playback/spec.md)。
架构证据：[现行架构报告](file:///D:/_work/dev/docs/projects/base/music-voice-managed-playback-architecture.md)。
验收结果（2026-10-30）：[托管播放验收报告](file:///D:/_work/repos/open-xiaoai/docs/plan/music-managed-playback-acceptance-20261030.md)。

本文件不复制需求或契约。musicdl 负责 v2 TrackRef、严格播放 profile、真实并发与 singleflight、WebGUI 严格来源、身份快照、原子发布和 completed outbox；MusicFree 七插件兼容属于同一工作流。旧 v1 下载、`ekey`、WebGUI 冻结兜底和质量 module 的既有 ADR 边界不变。Songloft 与 musicdl 分别限制本进程资源，跨项目验收聚合系统总量。

## 本地依赖图

- K-01：无本地阻塞。
- K-02：Blocked by K-01。
- K-03：无本地阻塞。
- K-04：Blocked by K-01、K-03。
- K-05：Blocked by K-01、K-02。
- K-06：Blocked by K-01、K-02、K-04、K-05。

每张 ticket 使用 `Status: ready-for-agent`。bridge／Songloft 的联调依赖在主 spec 和对应 ticket 的 External blocked by 中记录，不在本区重复实现。真实上游、NAS 部署和插件发布分别授权。
