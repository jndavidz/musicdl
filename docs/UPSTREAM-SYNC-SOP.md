# 上游月度同步 SOP（musicdl 上游 → api-server）

> 适用于上游 CharlesPikachu/musicdl 发新版本（v2.15.x 预计 2026-11 中）或每月例行同步。
> 分支拓扑见 AGENTS.md：单分支治理，`api-server` 是唯一开发分支，`master` 是上游镜像。

## 流程

1. **fetch 与评估**
   ```bash
   git fetch upstream
   git log api-server..upstream/master --oneline          # 上游新增了什么
   git diff api-server...upstream/master --stat           # 影响面：musicdl/ 库层为主
   ```

2. **merge 一步到位**（不再有中间同步线）
   ```bash
   git merge upstream/master
   ```
   冲突处理原则：
   - `musicdl/` 库层冲突 = 本仓库加过的文件（liuyunidc FLAC 解锁、Hi-Fi 过滤、stage-1 base、`search_metadata` 契约接口等）——**上游改动优先，本仓库增强以"只加不改"重放**（新文件或纯追加块，见 AGENTS.md 库层新文件模式）。
   - `server/`、`examples/musicdlwebgui/` 是本仓库领地，上游不应触碰；出现冲突即说明上游动了同名文件，逐处人工判断。

3. **端点台账同步**：上游引入/更换的解析端点逐个登记进 `docs/MUSIC-SOURCES-REGISTRY.md`（状态列标"随上游 v2.x 引入，未实测"），可探测的顺手探测后更新状态。

4. **双轨冒烟**：离线 + live 默认档全 PASS 本机收工；若上游动了音质表/解析链结构 → 追加 `docs/QUALITY-MATRIX.md` 对照检查。

5. **NAS 部署 + `--all` 验收**：WSL 内 `bash deploy/deploy.sh`（本地构建 → 传镜像 → compose up），然后
   `XDG_STATE_HOME=$PWD/.state .venv/bin/python server/tests/test_smoke.py http://10.10.10.2:3003 --all`；
   webgui 侧 `examples/musicdlwebgui/tests/test_smoke.py http://10.10.10.2:3004`

6. **提交**：merge commit 保留（上游版本号写进 merge message，如 `merge upstream v2.15.0`）。

## 回退

merge 后问题发现于部署前：`git reset --hard ORIG_HEAD`（未 push 时）。
已部署才发现：NAS 侧回滚走 `deploy/deploy.sh` 的 `musicdl:previous` 镜像（脚本探活失败会自动回滚；手动回滚 = retag previous → `docker compose up -d --no-build`）。

## 关联

- 凭证：push 失败走 `D:\_work\dev\docs\repos\git-credentials.md`
- 分支治理定案：`docs/KUWO-QQ-API-SERVER-PLAN.md`（单分支治理节）
