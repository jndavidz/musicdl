# T0.2 deploy/deploy.sh（双跳部署流程固化）

Status: resolved
Type: task

roadmap §5 0.2：office → 家庭 PC → NAS 双跳 tar 管道同步 → compose up -d --build →
healthz 探活 → 失败回滚上一镜像。本次验收的手工流程写成脚本（Git Bash）。
部署事实：ssh david@10.10.10.6 → ssh zxsadmin@10.10.10.2，docker 在 /usr/local/bin/docker，
目标 /volume2/docker/musicdl-api/src/。

## Comments
## Comments

- 2026-10-27: 完成（commit 9c93920 + 5be4651 修复），实跑两次验证（C 批次与 bilibili 修复批次部署均经此脚本）；坑位记录：home PC 登录 shell 为 PowerShell，内层命令须单引号。
