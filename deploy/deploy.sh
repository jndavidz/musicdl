#!/usr/bin/env bash
# deploy/deploy.sh — kw-qq-music-api NAS 部署（office → 家庭 PC → NAS 双跳）
# 固化 2026-10-27 架构审查批次验证过的手工流程：
#   tar 管道同步构建上下文 → 预留回滚 tag → compose build + up -d → healthz 探活 → 失败回滚上一镜像。
# 前提：office → david@10.10.10.6（家庭 PC）与家庭 PC → zxsadmin@10.10.10.2（NAS）均 ssh 免密；
#       NAS 的 docker 在 /usr/local/bin/docker；部署现状：NAS compose ENABLE_LOSSLESS=true（见 server/README.md）。
# 用法：仓库根目录运行  bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

JUMP="david@10.10.10.6"                       # 家庭 PC（跳板）
NAS="zxsadmin@10.10.10.2"
NAS_DIR="/volume2/docker/musicdl-api"
DOCKER="/usr/local/bin/docker"
TAR_EXCLUDES=(--exclude='.git' --exclude='.venv' --exclude='.state' --exclude='.scratch'
              --exclude='__pycache__' --exclude='*.pyc' --exclude='dl2*' --exclude='sources_*.json'
              --exclude='*.egg-info' --exclude='.zcode')

run_nas() { ssh "$JUMP" "ssh $NAS \"$*\""; }

echo "[1/5] 同步构建上下文 → $NAS:$NAS_DIR/src/"
tar -cf - "${TAR_EXCLUDES[@]}" \
    AGENTS.md CITATION.cff CODE_OF_CONDUCT.md GLOSSARY.md LICENSE MANIFEST.in Makefile README.md \
    docs deploy musicdl server requirements.txt requirements-optional.txt setup.py \
  | run_nas "mkdir -p $NAS_DIR/src && tar -xf - -C $NAS_DIR/src"

echo "[2/5] 预留回滚镜像 tag"
run_nas "cd $NAS_DIR && $DOCKER tag musicdl-api:latest musicdl-api:previous 2>/dev/null || true"

echo "[3/5] compose build + up -d"
run_nas "cd $NAS_DIR && $DOCKER compose up -d --build"

echo "[4/5] healthz 探活（最长 120s）"
ok=""
for _ in $(seq 1 24); do
  if run_nas "$DOCKER exec musicdl-api python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:3003/healthz', timeout=5)\"" >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 5
done
if [ -z "$ok" ]; then
  echo "healthz 探活失败 → 回滚到上一镜像"
  run_nas "cd $NAS_DIR && $DOCKER tag musicdl-api:previous musicdl-api:latest && $DOCKER compose up -d --no-build"
  echo "已回滚；请查日志：run_nas docker logs --tail 100 musicdl-api"
  exit 1
fi

echo "[5/5] 部署完成。验收命令："
echo "  XDG_STATE_HOME=\$PWD/.state .venv/Scripts/python.exe server/tests/test_smoke.py http://10.10.10.2:3003 --all"
