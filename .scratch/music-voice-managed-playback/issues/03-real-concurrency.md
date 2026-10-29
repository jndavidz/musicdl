# K-03: 修复 adapter 超时的真实并发边界

Status: resolved
Type: task
Blocked by: —
External blocked by: —

## Body

调整 SourceAdapter 执行层：调用方可按硬预算超时，但 semaphore／工作容量必须等同步线程真实退出后才释放。为同步请求设置自身 socket 超时，将网易高档 HEAD 及其他裸同步 I/O 纳入同一 measured execution，不宣称能强杀 Python 线程。kwqq 的活跃与 waiter 采用静态分区，跨项目验收与 Songloft／WebGUI 汇总系统总预算。

### DoD

- 两次调用超时后，未退出的旧工作仍占容量，不出现 semaphore=1 而线程峰值 2。
- 慢 HEAD 不阻塞事件循环；工作有自身上限，队列有界，迟到结果不得投送。
- v1/v2 外部响应契约不变，失败按预算返回明确 504／capacity 错误。

### Tests

- 用 Event 阻塞 fake worker，断言超时后容量仍占用、实际退出后才恢复。
- 构造慢 HEAD 验证 event loop 可响应；覆盖 waiter 上限与迟到结果丢弃，运行 timeout-capacity。

### Rollback

回退 server 执行层提交，无数据迁移；不通过删除超时或无限扩容回滚。

## Authorization

只改 server 包装层与离线测试，不重构整个核心库线程模型。

## Comments

- 2026-10-29 完成（离线）：`server/adapters/base.py` 改为每源独立线程池，容量只在 worker 线程真正退出
  （done-callback）后释放，调用方超时只归还调用方自己；等待者为有界静态分区 `MAX_WAITERS`，满则 503
  capacity；迟到结果丢弃并计入 `late_dropped`；所有裸同步 I/O 走 `IO_TIMEOUT_S`（含 bilibili urlopen、
  buvid 取指纹、netease 高档 HEAD）。`/status.runtime` 暴露 active/waiting/timed_out/late_dropped 供
  跨项目汇总。
  证据：`server/tests/test_concurrency.py` 13 项 PASS（Event 阻塞 fake worker：超时后容量仍占用、
  第二任务不启动、线程峰值=1、真实退出后才恢复；慢 HEAD 期间事件循环持续 tick；waiter 上限 503；
  迟到结果丢弃；v1 超时 504 信封且不缓存）；commits `f4d0d09` + `ff68005`。
  NOT RUN：跨项目总量验收（需 Songloft/WebGUI 同环境汇总，runner case `timeout-capacity`）。
