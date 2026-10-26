# P1 spike：songloft-player 三问 → D-1 裁决素材

Status: resolved
Type: research

roadmap §4 P1：① Bundle 模式 JS 插件可用性；② DLNA 投 LX06 实测；③ @songloft/plugin-sdk 接口形状
（对照 songloft-org/songloft 的 js-plugin-development-guide）。三问有答案后 D-1 才能裁决（P2/P3 依赖它）。
①③可联网调研；②需真机（手机装 songloft-player + LX06），agent 只能给出实测步骤与判据。

## Comments
## Comments

- 2026-10-27: ①③两问已联网调研落档（notes/p1-spike-research.md）：Bundle JS 插件可用性=高置信可用（QuickJS 沙箱，建议真机复核）；SDK 接口与 MusicFree 概念一一对应，包装 kwqq-api 预计 1-2 天；②DLNA=代码与 FAQ 均支持 ControlPoint，另有 songloft-plugin-miot 路径，**LX06 实测需真机**（步骤已写进报告）。风险：单人项目、211 stars。P2/P3 ticket 待 D-1 裁决后立。
