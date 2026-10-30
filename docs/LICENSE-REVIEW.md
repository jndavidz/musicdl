# 许可与分发澄清（2026-10-29）

> 工程事实记录，**不是法律意见**。结论按"最保守可执行"给出；对外分发前需上游/法务确认。

## 1. 为什么需要这份文档

主 spec 要求"公开分发前记录 PolyForm NC 与 README 分发表述冲突的澄清结果，以及实际 AGPL 组件的源码提供义务"。本文只回答三个问题：实际引入了什么、冲突在哪、当前姿态下有什么义务。

## 2. 实际许可事实（本机实测）

| 项 | 事实 | 取证方式 |
|---|---|---|
| 本项目代码 | `LICENSE` = PolyForm Noncommercial 1.0.0（CharlesPikachu, 2018–2026） | 读 `LICENSE` |
| README 分发表述 | 仅教育/研究用途；禁止商业使用；**未经明确许可禁止再分发、转售或打包分发（含衍生打包物）** | `README.md` L83–86 |
| 服务镜像 | `python:3.12-slim` + pip 安装 `requirements.txt` / `server/requirements.txt`；**不安装 ffmpeg 可执行文件** | `Dockerfile` |
| AGPL / Affero 组件 | **0 个**（对 venv 全量 dist 元数据扫描 `GPL|AGPL|AFFERO`） | `.venv` 内 `importlib.metadata` 扫描 |
| GPL 组件（实际存在） | `pywidevine` **GPL-3.0-only**；`Unidecode` **GPL-2.0-or-later** | 同上 |
| GPL 组件是否被服务加载 | `pywidevine` **会在 `import server.app` 时进入 `sys.modules`**（经 musicdl 的 apple/soundcloud 工具链）；`Unidecode` 未加载 | `import server.app` 后查 `sys.modules` |
| FFmpeg | 无 ffmpeg 二进制；但 `av`（PyAV 17.1，BSD-3-Clause）的 manylinux 轮子**捆绑** FFmpeg 共享库（`av.libs/libav*.so`），其中含 `libx264`、`libx265`（GPL-2.0） | 检查 `av.libs/` 目录 |
| 其余依赖 | MIT / BSD / Apache-2.0（fastapi、uvicorn、pydantic、requests、lxml、bleach、orjson、cryptography、pycryptodome(x)、m3u8、aigpy、filetype 等） | dist 元数据 |
| 插件仓（`musicfree-plugins`） | 运行时依赖 axios / cheerio / crypto-js / he（均 MIT）；**仓库自身无 LICENSE 文件**，`package.json` 声明 `"license": "ISC"` | 读 `package.json`、目录 |

结论：**"实际 AGPL 组件"为空**，AGPL 的"网络交互即分发"义务不触发。真正需要评估的是 GPL-2/GPL-3（pywidevine、Unidecode、PyAV 轮子里的 x264/x265）。

## 3. 冲突点与仲裁

- PolyForm Noncommercial 1.0.0 允许**非商业用途**，并允许在非商业目的下分发副本（须随附许可条款）。
- README L85 另行禁止**任何**未经许可的再分发/打包分发。
- 两者对"非商业再分发"的口径不一致；README 更严格。按最保守解释执行：**以 README 为准，不做任何形式的对外分发**，直到上游澄清或以书面许可解除。

家庭内部自用（自己的 NAS、自己的账号、自己的设备）不属于上述"分发"，故当前部署不落入冲突。

## 4. 当前姿态下的义务

| 场景 | 义务 |
|---|---|
| 家庭内自用部署（当前） | GPL 仅约束"分发"，私有运行不产生源码提供义务；保留本文件即可 |
| 对外发布插件（2026-10-29 已发布到 NAS 静态目录） | 插件为独立 JS，不含 GPL/AGPL 代码，依赖均 MIT；**但插件仓没有 LICENSE 文件**，公开发布前应补一份明确许可（见 §5） |
| 对外分发镜像（未做） | 需同时满足：① PolyForm NC + README 的分发限制（当前冲突未解，视为禁止）；② pywidevine GPL-3、Unidecode GPL-2+、PyAV 轮子内 x264/x265 的 GPL 源码提供与许可声明；③ 所有 MIT/BSD/Apache 依赖的 NOTICE/License 合集；④ 基础镜像（Debian slim）的许可清单 |
| 网络服务形式（自建 API） | GPL-3 **不**因网络交互触发（非 AGPL）；但若未来引入任何 AGPL 组件，则必须提供对应源码 |

## 5. 未闭环事项（2026-10-30 更新）

1. **上游澄清（已定执行口径）**：PolyForm NC 正文与 README L85 的分发限制冲突。**决策：按更严格一方执行——
   不做任何对外分发**（镜像、插件包、打包物均不发）；冲突本身仍需上游书面确认，但不再阻塞当前私用，
   只在"要公开发布"时重新开启。
2. **插件仓许可（已收口，2026-10-30）**：`musicfree-plugins` 已补根级 `LICENSE`
   （All rights reserved / UNLICENSED）+ `package.json` `"license": "UNLICENSED", "private": true`，
   `docs/PLUGIN-COMPAT.md` §6 同步定案为"私有、不再分发"。此前 ISC 声明不再使用（它覆盖不了继承片段）。
   **剩余动作**：GitHub 仓库可见性应设为 private（仓库设置操作，非代码改动）。
3. **PyAV 轮子许可证**：`av` 为 BSD-3，但其捆绑的 FFmpeg 共享库含 GPL-2 编码器；若将来分发镜像，需按实际 build flags 提供 FFmpeg 源码与许可声明（当前不分发，仅记录）。
4. **GPL 依赖裁剪**：`pywidevine`（GPL-3）在服务启动时被加载，但目前 kwqq 的七个源都不走 Widevine。若要彻底避免 GPL 依赖进入镜像，可评估拆分 `requirements.txt`（仅装服务所需子集）——**未做**，需单独验证 musicdl 客户端的导入链。
5. 本文不覆盖内容合法性：只处理软件许可；音乐内容的授权与使用范围另见 README Disclaimer。

## 6. 复核命令（可重跑）

```bash
# venv 内 GPL/AGPL 扫描
.venv/bin/python -c "import importlib.metadata as md; [print(d.metadata['Name'], (d.metadata.get('License') or '')) for d in md.distributions() if 'GPL' in ((d.metadata.get('License') or '') + ' '.join(d.metadata.get_all('Classifier') or [])).upper()]"
# 服务启动时的导入图
.venv/bin/python -c "import server.app, sys; print('pywidevine' in sys.modules, 'av' in sys.modules, 'Unidecode' in sys.modules)"
# PyAV 捆绑库
ls .venv/lib/python*/site-packages/av.libs | grep -iE 'x264|x265|avcodec'
```
