# ADR-0003: quality module 留在 server 内部，直至第二消费方出现

日期：2026-10-26 ｜ 状态：Accepted

## Context

音质档位知识（tier 定义、白名单、192k snap、lossless 门、假无损守卫）散落 config、9 个 adapter、webgui、核心库四层，已产生不一致（192k 三义、LOSSLESS_EXTS 子集漂移）。架构审查（C1）提出 deep module 收编。

第二个潜在消费方是 webgui（`examples/musicdlwebgui/`，位于上游路径 `examples/`），共享意味着仓库级包与 upstream merge 冲突面。

## Decision

音质 module 落在 **`server/quality.py`**（server 内部 module），interface：`normalize` / `allowed_tiers` / `guard_lossless`。平台私有参数映射（ZHENPIN_BR、LEVELS、QUALITY_IDS 等）留各 adapter，tier 字符串引用 module 常量。

## 拒绝记录

- **一步到位仓库级共享包**：webgui 是 hypothetical 第二消费方（"one adapter = hypothetical seam, two = real"）；纯函数 module 无依赖，将来提升为共享包是零成本搬移。过渡期用 `ast` 解析两端 dict 字面量的离线断言兜底漂移。

## Consequences

- 新增/修改档位从"改四层"变为"改 module 一处 + adapter 参数映射一行 + docs/QUALITY-MATRIX.md 文档"。
- 库层 37 处假无损守卫**不在**收编范围（upstream churn，另行评估）。
- 192k 语义统一：有真 192k 档的源用真档（netease→higher），否则 snap 到最近的不低于 192k 的档（多数源→320k）；bilibili 白名单补 192k→320k（行为收紧：不再落 auto）。
