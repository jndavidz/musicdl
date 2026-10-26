# Context

musicdl 是 CharlesPikachu/musicdl 的 fork：纯 Python 音乐下载库，在其上扩展出**三件套**——核心库、kw-qq-music-api 服务、Web 下载界面。分支拓扑与目录角色见 `AGENTS.md`（权威）。

## Language

**三件套**:
本仓库的构成：核心库（`musicdl/`）+ kw-qq-music-api 服务（`server/`，FastAPI 多源解析）+ Web 下载界面（`examples/musicdlwebgui/`）。
_Avoid_: 子项目、模块

**api-server 分支**:
唯一开发分支。`server/`、webgui、`docs/` 与库层增强全在这条线上。
_Avoid_: dev 分支、main

**上游镜像（master）**:
`master` 分支只作 upstream（CharlesPikachu/musicdl）镜像，现为 v2.11.0 历史快照，不随上游更新；勿在其上开发。
_Avoid_: 主分支（本仓库开发不走 master）

**SourceAdapter**:
`server/adapters/` 的包装层：把 `SourceAdapter` 语义套在核心库的各平台客户端上。平台客户端本身在 `musicdl/modules/sources/*.py`（每平台一个类，继承 `BaseMusicClient`）。
_Avoid_: 适配器模式（泛称）

**.state 目录**:
运行时状态目录：所有进程以 `XDG_STATE_HOME=$PWD/.state` 启动，探测脚本、缓存、一次性实验落这里（已 gitignore）。
_Avoid_: tmp、运行目录

**音质档位（quality tier）**:
跨源统一的档位语义：128k / 192k / 320k / flac / hires / master / surround51 / auto。总册见 `docs/QUALITY-MATRIX.md`；服务端归一/白名单/守卫收敛在 `server/quality.py`（ADR-0003）。192k = 有真档用真档（netease higher），否则 snap 到不低于请求档的最近档。
_Avoid_: 音质等级、码率档（泛称）

**兜底通道（fallback channel）**:
webgui 主流六源的进程内库直连，API 为主定位下**冻结保留**（ADR-0001）：代码不演进，仅 API 故障时作独立保险；库直连只对 59 个小众平台保持现役。
_Avoid_: 双通道（六源已不再是并行双轨）

**消费方（consumers）**:
kw-qq-music-api 的两类消费方及其能力边界：MusicFree 插件**只消费 ≤320k mp3**；webgui 消费全档（含 mflac+ekey 加密件，经 QMC 解密钩子得明文，ADR-0002）。master/surround51 加密档的现实唯一消费方是 webgui。**API 不入播放链**（2026-10-27 定案）：保真层只消费本地文件，播放类消费链只吃 ≤320k mp3，API 直链永不直接进播放。
_Avoid_: 用户、客户端（不区分能力边界）
