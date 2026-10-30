# K-06: 迁移七插件兼容门面并收口消费方验收

Status: resolved
Type: task
Blocked by: 01, 02, 04, 05
External blocked by: open-xiaoai B-05/B-06，Songloft S-03（跨区联调）（已解除：对端票均 resolved）

## Body

按现役方法清单迁移网易、酷狗、QQ、酷我、咪咕、千千、B站插件的搜索、元数据、歌词与播放操作。播放回传完整 TrackRef；至少五插件官方元数据直连纳入 kwqq 兼容能力。网易／酷狗透传只保留明确兼容用途，酷狗播放不再回落 FLAC，runtime 对 HTTP 429 不换 host。

### DoD

- 七插件现有方法形状与未迁移能力有明确清单，不为“唯一解析”盲删登录、凭据或现役元数据操作。
- B站 cid/page、咪咕 copyrightId 在取链和缓存中保留；非 MP3／ekey 不进入播放。
- 网络错误可按既有策略切 host，HTTP 429 直接暴露并遵守冷却；构建产物与源码断言一致。
- v1 旧插件有迁移窗口；跨项目 consumers-seven、quality-profile、singleflight 和 download-identity 通过。
- API-REFERENCE／OpenAPI／质量与 ADR 文档同步；公开分发前记录 PolyForm NC 与 README 冲突的澄清结果及实际 AGPL 组件源码提供义务，不把家庭私用外推为公开授权。

### Tests

- 扩展 axios mock：七插件 v2、TrackRef 往返、分 P、FLAC 最终失败分支、非 MP3 拒绝、429 备用 host 零请求和网络故障切换。
- 运行 MusicFree 全套、server offline、WebGUI smoke；真实插件发布与在线验收单独记录。

### Rollback

回发上一版插件，server 保留 v1，无需回滚 v2 或删除新能力；旧插件继续可用但不列最终合规。

## Authorization

不改 MusicFree 宿主、不发布插件、不刷新真实 Cookie、不调用账号写接口；发布与真实上游另行批准。

## Comments

- 2026-10-29 完成（本地范围）：七插件（网易/酷狗/QQ/酷我/咪咕/千千/B站）`getMediaSource` 改为 v2 优先，
  回传完整 TrackRef；未配置 `serviceToken` 或旧服务端回落 v1 迁移窗口；回落只在 **HTTP 404**（路由缺失）
  发生，业务未命中是 `200 + code 404`；429 直接暴露并冷却、不换 host、不回落；酷狗不再回落 FLAC、
  兼容链拒绝非 mp3；B站 cid/page 进 TrackRef（多分 P 展开保留身份、身份缺失明确报错、v1 路径回传
  cid/page），咪咕 copyrightId 必带；v2 解析不带平台 cookie（身份只由 TrackRef 表达）；官方元数据/
  歌词/榜单/评论直连全部保留，未迁移项见清单。
  文档：姊妹仓 `docs/PLUGIN-COMPAT.md`（方法清单 / 未迁移项 / 许可开放项）、`docs/API-REFERENCE.md`
  §4.6–4.10 + 变更记录、`docs/QUALITY-MATRIX.md`、ADR-0004。
  证据：`node tests/run.js` 152 项 PASS（TrackRef 往返、分 P、AAC、FLAC 最终失败、非 MP3、业务 404、
  429 备用 host 零请求、网络故障切 host、v1 分 P、v2 不带 cookie）；`node shared/build.js` 后产物与
  源码一致（diff 无残留）；commits `5cde8ed` + `de4a6db`（musicfree-plugins）。
  NOT RUN（不计为通过）：`music_ecosystem` runner 的 `consumers-seven`/`quality-profile`/`singleflight`/
  `download-identity` 跨项目 case（依赖 open-xiaoai B-01 与 B-05/B-06、Songloft S-03）；插件发布与
  真实客户端在线验收。
  许可：PolyForm NC 与 README 分发表述的冲突、实际 AGPL 组件源码提供义务仍为开放项（PLUGIN-COMPAT §6）。
- 2026-10-30 发布与真机在线验收收口：七插件已于 2026-10-29 部署 NAS `/volume2/web/plugin/`（见
  PLUGIN-COMPAT §5.1）；`kwqq-playback` serviceToken 下发至七插件用户变量，服务端准入探针先行
  （假 token 401 / 真 token 过鉴权进业务层），真机逐插件点播播放全部通过。上条 NOT RUN 中
  「插件发布与真实客户端在线验收」就此关闭；跨项目 case 的 NOT RUN 仍按上条归 B-08。
- 2026-10-30 **跨项目 case 全部有结果**（runner `--device --require-approval`）：
  - `consumers-seven` PASS：七插件构建产物 md5 与 NAS `/volume2/web/plugin/` **7/7 一致**；
    v2 路由鉴权探针（假 token 401；真 token 走通到上游 502 说明准入已过）。
  - `quality-profile` PASS：musicdl 侧身份拒绝 3/3（缺 copyrightId / 缺 cid / 未知 source 均 400）
    + 跨 scope 5 项（playback↛invalidate、playback↛media_prepare、invalidate→resolve 403 等）。
  - `singleflight` PASS（8 并发同 payload、串行续跑缓存 2/2）；
    `timeout-capacity` PASS（12 路全部终态、event loop 最大 39ms）；
    `download-identity` PASS（search→下载→容器内 stat 校验 644/无 .tmp→清理）；
    `ingest-scan` PASS（Songloft ingest 拒绝矩阵 2/2 显式 422，一个 500 缺陷已修）。
  - 发布面：插件已同名覆盖到 NAS（2026-10-29/30，v2 产物），用户已在 MusicFree 逐插件点播通过；
    许可已定案「私有、不分发」（插件仓补 UNLICENSED LICENSE、仓库转 private）。
