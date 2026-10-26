# ADR-0001: API 为主定位，webgui 六源库通道冻结为兜底

日期：2026-10-26 ｜ 状态：Accepted

## Context

webgui（`examples/musicdlwebgui/`）支持双后端：远程 kw-qq-music-api（`server/`）与进程内库直连。主流六源双通道并行导致同一领域逻辑（酷我直链构造、DTO 映射、音质定档）在库、server、webgui 三层各持一份，已产生漂移。2026-10 架构审查（C3/C5）需要定位投入方向。

## Decision

**webgui 以 API 后端为主**：主流六源（网易/酷狗/酷我/QQ/千千/咪咕）解析走 kw-qq-music-api；进程内库直连通道**冻结保留**为兜底（API 故障时的独立保险），代码不再演进，README 标注"能力止于冻结时点"。库直连仅对 59 个小众平台保持现役。

## 拒绝记录

- **删除六源库通道**：单向门，失去 API 故障保险且库直链/解密复制代码仍有保险价值；观察兜底长期未被使用后再议。

## Consequences

- 库 interface 改造（ADR 见 C5 批次：`search_metadata`、progress/lyric 注入）只需服务兜底通道，投入有上限。
- webgui 的 "zero modification" 声明改为显式 patch 清单契约（数量只减不增），清单清空 = 库 interface 改造完成。
- 双端音质 tag 表以 `ast` 离线断言兜底（`server/tests/test_offline.py`），漂移即红。
