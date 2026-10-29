# K-02: 实施严格 v2 播放 profile 与真实质量声明

Status: ready-for-agent
Type: task
Blocked by: 01
External blocked by: —

## Body

在 v2 对七源统一播放候选策略：原始 quality 白名单先于归一化，已知 FLAC／AAC／M4A、加密 ekey、>320k 或证据不足不得直接 ready。仅为 Songloft 媒体准备 scope 提供 AAC 规范化输入，响应明确 `requires_transcode`，不得直投；其他调用方及加密件仍拒绝。修正 `verified` 语义，HEAD／后缀／MIME／8KB sniff 不再被标成完整编码验证；最终文件验证由 Songloft 准备链完成。

### DoD

- `requested_quality`、`delivered_quality`、codec、实际来源、降级原因和验证等级如实返回。
- 证据不足时 `requires_byte_verification=true`，不得返回 ready 或完整验证成功；AAC 规范化输入必须同时标 `requires_transcode`，酷狗 FLAC 回落不伪装成 MP3。
- v1 下载、无损和 ekey 契约保持；质量 module 留在 server，API 不进入 Lyrion。

### Tests

- mock 覆盖假后缀／MIME、FLAC／AAC／M4A、加密件、>320k、真实降档和透传档位；Songloft scope 的 AAC 可进入转码准备，AAC 直投和其他 scope 均拒绝。
- Songloft 联调只接受后续完整文件验证通过的表示；运行 quality-profile 与 v1 回归。

### Rollback

停用 v2 严格入口，保留 v1；不通过放宽验证标签或恢复原码播放兜底回滚。

## Authorization

不新增转码服务、不改 Lyrion；真实上游与 NAS 验收另行批准。

## Comments
