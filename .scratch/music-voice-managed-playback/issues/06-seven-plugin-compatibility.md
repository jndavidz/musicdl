# K-06: 迁移七插件兼容门面并收口消费方验收

Status: ready-for-agent
Type: task
Blocked by: 01, 02, 04, 05
External blocked by: open-xiaoai B-05/B-06，Songloft S-03（跨区联调）

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
