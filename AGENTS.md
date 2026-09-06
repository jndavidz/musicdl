# AGENTS.md — musicdl

CharlesPikachu/musicdl 的 fork：纯 Python 音乐下载库。本仓库在其上扩展出三件套——**核心库**（`musicdl/`）、**kw-qq-music-api 服务**（`server/`，FastAPI 多源解析 API）、**Web 下载界面**（`examples/musicdlwebgui/`）。日常开发全部发生在 `api-server` 分支。

## 分支拓扑

| 分支 | 角色 |
|------|------|
| `api-server` | 唯一开发分支：`server/`、webgui、`docs/` 与库层增强（kuwo liuyunidc FLAC 解锁、Hi-Fi 过滤、stage-1 base）全在这条线上 |
| `master` | 上游镜像（`upstream` = CharlesPikachu/musicdl，`origin` = jndavidz/musicdl）；现为 v2.11.0 历史快照（落后上游），暂不随上游更新 |
| tag `archive/hifi` | 已归档的前库层增强分支，内容已 100% 并入 `api-server`（2026-09-06 治理），勿在其上开发 |

同步上游：fetch `upstream` 后在 `api-server` 上直接 merge `upstream/master`，一步到位（单分支治理后不再有中间同步线）。

## 目录角色

- `musicdl/modules/sources/*.py` — 每个音乐平台一个客户端类（继承 `BaseMusicClient`）；`musicdl/modules/utils/` 是配套加解密/签名工具
- `server/app.py` — FastAPI 入口与路由；`server/adapters/` — `SourceAdapter` 包装层；`server/config.py` — 全部环境变量配置
- `examples/musicdlwebgui/` — Web GUI（端口 3004）；其余 `examples/*` 为原作者示例
- `deploy/docker-compose.yml` — NAS 部署编排
- `docs/` — 设计计划、接口契约、端点台账（见文末文档指针）
- `.state/` — 运行时状态目录（所有进程以 `XDG_STATE_HOME=$PWD/.state` 启动；探测脚本、缓存、一次性实验都落这里，已 gitignore）
- 根目录的 `dl2*`、`sources_*.json` 是本地实验残留（已 gitignore），非项目代码

## 开发与验证循环

uv 工作流，Python 3.12，`.venv` 已就绪：

```bash
# 依赖（requirements 变更后重跑；-e . 让 server/ 直接 import 核心库）
uv pip install -p .venv/bin/python -r requirements.txt -r server/requirements.txt -e .

# 起 API 服务（3003；XDG_STATE_HOME 前缀不可省）
XDG_STATE_HOME=$PWD/.state .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 3003

# 冒烟验证（需服务已起；全 PASS 即通过）
XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://127.0.0.1:3003
```

webgui 同构验证：`XDG_STATE_HOME=$PWD/.state uv run python examples/musicdlwebgui/app.py`（3004）起服务后跑 `examples/musicdlwebgui/tests/test_smoke.py http://127.0.0.1:3004`。

本仓库没有 pytest 单测——**验证 = 起真实服务跑冒烟**，改动的每个组件都要有对应的冒烟全 PASS 才算完成。端点/协议探测脚本写进 `.state/`，不进版本库。

Makefile 的 `install`/`publish` 是上游 PyPI 发布遗留；本仓库的发布形态是 NAS compose 部署（命令见 `server/README.md`），twine 上传勿执行。

## 关键不变量

违反以下任何一条会静默破坏解析链或行为契约：

- **免 Cookie**：server 路径下酷我/QQ 客户端零 Cookie 构造——客户端一旦带上 Cookie，第三方解析链 `_parsewiththirdpartapis` 直接返回空结果。设计缘由见 PLAN §2.2。
- **二段式**：API 搜索只发单次元数据请求（走 `SourceAdapter.search_items`）；直链解析只发生在按 id 调 `/song/url` 时。整条 API 路径绕开 `client.search()`——它会给每条候选逐一解析直链。
- **音质封顶且如实**：无损档默认关闭（`ENABLE_LOSSLESS=false`，插件场景封顶 320k）；响应永远返回实测的 `ext` / `bitrate_kbps` / `size_bytes`，降级了就报降级值。
- **并发模型**：阻塞调用一律经 `asyncio.to_thread` + 每源信号量 + 硬超时（即 `SourceAdapter.run`）；进程内 TTL 缓存的一致性依赖 `workers=1`。

## 新增一个解析源（adapter）

1. 写 `server/adapters/<key>.py`：继承 `SourceAdapter`，实现 `_build_client()`（优先复用 `musicdl/modules/sources/` 里现成的客户端类，零 Cookie）、`_search_raw()`、`item_from_raw()`、`song_url()`。
2. 注册两处：`server/adapters/__init__.py` 的 `ADAPTER_CLASSES` + `server/config.py` 的 `SOURCES` 元组。
3. 给 `server/tests/test_smoke.py` 补该源的检查项。
4. 文档三处：`docs/API-REFERENCE.md` 补源与接口说明；新引入的上游端点登记进 `docs/MUSIC-SOURCES-REGISTRY.md` 台账；有取舍决策时记入 PLAN。
5. 起服务 → 冒烟全 PASS → 以 conventional commits 提交（`feat(server): ...`，历史 scope 见 git log：server / webgui / api / docs）。

## 文档指针

- `server/README.md` — 端点表、环境变量表、架构图、NAS 部署与验收命令。**改配置或部署前读它**（本文件的命令只覆盖最短开发环）。
- `docs/API-REFERENCE.md` — 对外接口契约：认证双层模型、响应包裹语义（业务未命中 = HTTP 200 + code 403/404，上游故障 = 502/504）、各源能力。**改任何路由语义前读它**。
- `docs/MUSIC-SOURCES-REGISTRY.md` — 全部解析端点/凭证的存活台账（含失效条目，供考古与恢复）。**每次探测端点后更新其状态列**，新端点追加登记。
- `docs/KUWO-QQ-API-SERVER-PLAN.md` — 设计决策记录。**想知道某处为什么这么设计时读它**，而不是重新发明方案。
- `examples/musicdlwebgui/README.md` — webgui 功能矩阵与双后端（kwqq-API 六源 + 进程内库）分工说明。
