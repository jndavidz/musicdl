# K-02: 实施严格 v2 播放 profile 与真实质量声明

Status: resolved
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

- 2026-10-29 完成（离线）：新增 `server/playback_profile.py`——原始 quality 拼写先过白名单再归一化
  （`flac`/`hires`/`master`/`surround51` 请求 400，不回落 auto）；候选侧 FLAC/加密件(ekey)/>320k/
  非 mp3 一律 415；AAC 家族仅 `target=media_prepare` 且持 `media:prepare` scope 时作为转码输入放行
  （`requires_transcode=true`、`ready=false`、`delivered_quality=null`）。`server/playback.py` 中 v2
  `verified` 恒 false、`requires_byte_verification` 恒 true，`delivery_quality` 由实测码率推出并如实
  标注 `downgraded` / 证据不足。v1 质量、无损与 ekey 语义不变，质量知识仍只在 server。
  证据：`server/tests/test_contract.py` 54 项 PASS（假后缀/MIME、FLAC/M4A-AAC、加密件、>320k、真实降档、
  透传档位、AAC 直投与其他 scope 拒绝、拒绝候选不入缓存）；v1 回归 `test_offline.py` 46 项；commit `7a71724`。
  NOT RUN：Songloft 准备链（S-03）联调、真实上游与 NAS 验收。
