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
