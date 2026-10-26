# D1 webgui app.py 模块化

Status: resolved
Type: task

roadmap §3 D1：examples/musicdlwebgui/app.py（1280 行）拆模块；import 副作用（写配置/建目录）挪进 lifespan。
行为不变（webgui 冒烟 21/21 为回归判据）。

## Comments
## Comments

- 2026-10-27: 完成（commit c047244）。1281→533 行，五模块单向依赖 config→quality→kwqq_api→library→downloads→app；import 副作用挪 lifespan；PLATFORM_TAG_TIER 留 app.py（server 离线冒烟 §5 ast 依赖）。冒烟 21/21 两轮 + server 离线 40/40。注意：本机跑 webgui 走 API 路径需 MUSICDL_WEBGUI_CONFIG 指向带 kwqq_api_key 的配置（NAS 已开 key 门控）。
