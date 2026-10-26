# T0.2 deploy/deploy.sh（双跳部署流程固化）

Status: open
Type: task

roadmap §5 0.2：office → 家庭 PC → NAS 双跳 tar 管道同步 → compose up -d --build →
healthz 探活 → 失败回滚上一镜像。本次验收的手工流程写成脚本（Git Bash）。
部署事实：ssh david@10.10.10.6 → ssh zxsadmin@10.10.10.2，docker 在 /usr/local/bin/docker，
目标 /volume2/docker/musicdl-api/src/。

## Comments
