# D3 dedupe 统计 UI 呈现 + 周期落盘

Status: resolved
Type: task

roadmap §3 D3：/api/stats/dedupe 的 UI 呈现 + 周期落盘（ADR-0001 再议数据基座的持久化）。

## Comments
## Comments

- 2026-10-27: 完成。落盘 .state/dedupe_stats.json（原子写，10min 节流 + lifespan finally flush + 启动容错恢复）；UI 为页脚 details 折叠块。边界：硬 kill 丢最后节流窗尾；NAS compose stop 走优雅路径不受影响。
