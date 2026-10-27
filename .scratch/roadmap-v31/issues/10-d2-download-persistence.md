# D2 下载任务持久化（重启恢复队列）

Status: resolved
Type: task

roadmap §3 D2。依赖 D1 落定模块边界后再动。

## Comments

- 2026-10-27 完成：`downloads.py` 新增任务快照（`.state/download_tasks.json`，原子 tmp+replace，
  最近 20 个任务，任务/条目状态跃迁写盘 + lifespan 停机 flush）。直链不落盘（10min 过期），
  恢复时 api 条目按 `api_id+api_source` 重走 `/song/url`，lib 条目按平台+identifier（兜底
  normkey+ext）重搜；`downloading` 条目按 `_inflight` 删除半文件后重新入队；重启前的取消照常生效；
  无法重新标识的条目落 failed 并提示重新搜索。`retry_item` 支持重启后无 RESULT_STORE 时按快照重解析。
  验证：逻辑脚本 20/20（快照往返/恢复状态机/损坏文件容错）、SIGKILL 实测 15/15（两条目下载中杀进程，
  重启后均成功落盘）、webgui 冒烟 21/21、server 离线 40/40。
