# docs/ 文档索引

> 本目录混合了两类内容：**官方项目文档**（readthedocs 构建，见 `index.rst`）与**本仓库工作文档**（音乐 API 服务相关的计划/调研/接口文档，不入 sphinx 构建）。

## 工作文档（当前有效）

| 文档 | 定位 | 状态 |
|------|------|------|
| [KUWO-QQ-API-SERVER-PLAN.md](KUWO-QQ-API-SERVER-PLAN.md) | **现行主计划**：musicdl → 酷我+QQ 自托管 API 服务（单服务双源、RESTful、3003 端口、Docker/NAS/Lucky 部署），含阶段 0-3 执行记录、端点存活探测表、决策记录 | ✅ 已执行完毕（阶段 4 插件对接未启动） |
| [API-REFERENCE.md](API-REFERENCE.md) | **现行接口开发文档**：认证模型、端点参考、音质路由、配置、部署运维、开发指南 | ✅ 与服务现状一致（v1.0） |

## 历史调研文档（archive/，仅供溯源，勿作现行依据）

| 文档 | 原定位 | 与现行文档的关系 |
|------|--------|------------------|
| [archive/MUSICFREE-API-PLAN.md](archive/MUSICFREE-API-PLAN.md) | 旧版 MusicFree 插件改造计划（v1-v3，`/api/{source}` 风格、5000 端口、MusicFree 专属后端） | **旧设计**：已被 KUWO-QQ-API-SERVER-PLAN.md 取代（RESTful、3003、通用服务）。保留价值：第三方解析链/音质映射的调研结论 |
| [archive/MUSICFREE-API-PLAN-REVIEW.md](archive/MUSICFREE-API-PLAN-REVIEW.md) | 对旧计划的评审（行号级论证：resolve_url 盲点、4 处事实订正、绕过 MusicClient 等） | 评审结论已整合进旧计划 v3；REVIEW 本身是**论证过程档案**（证据链参考） |
| [archive/ETC-PLUGINS-ANALYSIS.md](archive/ETC-PLUGINS-ANALYSIS.md) | 23 个 MusicFree 参考插件的深度解析（端点/密钥/音质范式，§4 总表） | **端点情报库**：现行服务备用端点池的来源（阶段 5.a 已复用并复测） |
| [archive/YUANLI-V1.2.0-PLUGIN-API.md](archive/YUANLI-V1.2.0-PLUGIN-API.md) | 元力 QQ/KW 插件接口全解（私有 SVIP 中转） | 情报参考：2026-08-12 复测该中转已失效，不集成 |

### 文档间关系速记

```
archive/MUSICFREE-API-PLAN-REVIEW.md ──评审──▶ archive/MUSICFREE-API-PLAN.md（v3 已整合）
                                                      │ 旧设计（未执行，被取代）
                                                      ▼
                                       KUWO-QQ-API-SERVER-PLAN.md（现行主计划，含执行记录）
                                                      │ 落地后生成
                                                      ▼
                                       API-REFERENCE.md（现行接口文档）

archive/ETC-PLUGINS-ANALYSIS.md ──§4 端点总表──▶ KUWO-QQ-API-SERVER-PLAN.md §阶段5.a（已复测集成）
archive/YUANLI-V1.2.0-PLUGIN-API.md ──情报──▶ 同上（复测失效，仅留档）
```

## 官方文档（readthedocs，勿动）

`Disclaimer / Install / Quickstart / Clients / API / Playground / Changelog / Recommend / Author` —— 由 `index.rst` toctree 引用，属于项目公开文档；`conf.py / make.bat / Makefile / requirements.txt / logo.png / pikachu.jpg / screenshot/` 为 sphinx 构建配套。
