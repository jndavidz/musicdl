#!/usr/bin/env bash
# deploy/deploy.sh — musicdl NAS 部署（镜像在 WSL 侧构建 → 传到 NAS → compose up）
# 单镜像双容器：musicdl:latest 同时承载 api(:3003) 与 webgui(:3004)。
# 前提：在 **WSL 内**运行（docker 只在 WSL；NAS 免密 ssh 从 WSL 可用）。
#       NAS 的 docker 在 /usr/local/bin/docker；NAS compose 与仓库 compose 是两份文件，
#       NAS 侧保留自己的 API_KEY / ENABLE_LOSSLESS=true（本脚本不覆盖 compose）。
# 坑位记录：构建必须在 WSL（DS416play 上构建极慢）；镜像经 WSL 内直管管道传输，
#       不要用 wsl.exe 把二进制导到 Windows 再转发（wsl.exe 会损坏二进制流）。
# 用法（WSL）：cd /mnt/d/_work/repos/musicdl && bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

NAS="zxsadmin@10.10.10.2"
NAS_DIR="/volume2/docker/musicdl-api"
DOCKER="/usr/local/bin/docker"
IMAGE="musicdl:latest"
TAR_EXCLUDES=(--exclude='.git' --exclude='.venv' --exclude='.state' --exclude='.scratch'
              --exclude='__pycache__' --exclude='*.pyc' --exclude='dl2*' --exclude='sources_*.json'
              --exclude='*.egg-info' --exclude='.zcode' --exclude='node_modules'
              --exclude='config.json' --exclude='*.bak*' --exclude='.webgui-downloads')

command -v docker >/dev/null || { echo "docker 不可用：请在 WSL 内运行本脚本"; exit 1; }

echo "[1/6] 同步构建上下文 → $NAS:$NAS_DIR/src/"
tar -cf - "${TAR_EXCLUDES[@]}" \
    AGENTS.md CITATION.cff CODE_OF_CONDUCT.md GLOSSARY.md LICENSE MANIFEST.in Makefile README.md \
    docs deploy examples/musicdlwebgui musicdl server requirements.txt requirements-optional.txt setup.py \
  | ssh "$NAS" "mkdir -p $NAS_DIR/src && tar -xf - -C $NAS_DIR/src"

echo "[2/6] 本地构建镜像 $IMAGE（WSL）"
docker build -t "$IMAGE" .

echo "[3/6] NAS 侧预留回滚 tag"
ssh "$NAS" "$DOCKER tag $IMAGE ${IMAGE%%:*}:previous 2>/dev/null || true"

echo "[4/6] 镜像传输 → NAS（直管 gzip 管道）"
docker save "$IMAGE" | gzip -3 | ssh "$NAS" "$DOCKER load"

echo "[5/6] compose up -d --no-build"
ssh "$NAS" "cd $NAS_DIR && $DOCKER compose up -d --no-build"

echo "[6/6] 探活（api 3003 / webgui 3004，最长 120s + 60s）"
ok=""
for _ in $(seq 1 24); do
  if curl -fs --max-time 8 http://10.10.10.2:3003/healthz >/dev/null 2>&1; then ok=1; break; fi
  sleep 5
done
if [ -z "$ok" ]; then
  echo "api healthz 探活失败 → 回滚到上一镜像"
  ssh "$NAS" "cd $NAS_DIR && $DOCKER tag ${IMAGE%%:*}:previous $IMAGE && $DOCKER compose up -d --no-build"
  echo "已回滚；查日志：ssh $NAS '$DOCKER logs --tail 100 musicdl-api'"
  exit 1
fi

ok4=""
for _ in $(seq 1 12); do
  if curl -fs --max-time 8 http://10.10.10.2:3004/ >/dev/null 2>&1; then ok4=1; break; fi
  sleep 5
done
[ -z "$ok4" ] && echo "⚠️ webgui 3004 未探活（api 已就绪）；查日志：ssh $NAS '$DOCKER logs --tail 100 musicdl-webgui'"

echo "部署完成。验收命令："
echo "  .venv/bin/python server/tests/test_smoke.py http://10.10.10.2:3003 --all"
echo "  .venv/bin/python examples/musicdlwebgui/tests/test_smoke.py http://10.10.10.2:3004"
