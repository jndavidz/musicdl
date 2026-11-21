#!/bin/bash
# musicdl（统一门面）NAS 部署前置：以代码库为唯一权威。
#
# 规则（2026-11-21）：仓库 deploy/docker-compose.yml 是形态唯一来源；NAS 出现仓库没有的
# 配置行 = 漂移，先回写仓库再部署；凭据只以 .env 值存在于 NAS（键名见 deploy/.env.example）。
# 用法：bash deploy/preflight.sh        （WSL 侧）
# 退出码：0 = 可部署；1 = 漂移或必填键缺失。
set -u
NAS=${NAS:-zxsadmin@10.10.10.2}
DIR=${DIR:-/volume2/docker/musicdl-api}
HERE=$(cd "$(dirname "$0")" && pwd)
rc=0

tmp=$(mktemp)
if ssh -o BatchMode=yes "$NAS" "cat $DIR/docker-compose.yml" > "$tmp" 2>/dev/null; then
  d=$(mktemp)
  diff -u "$HERE/docker-compose.yml" "$tmp" > "$d" 2>/dev/null || true
  lost=$(grep -E '^\+[^+]' "$d" | sed 's/^+//' | grep -vE '^[[:space:]]*(#|$)' || true)
  if [ -n "$lost" ]; then
    echo "🔴 docker-compose.yml: NAS 有仓库没有的内容（漂移；先回写仓库）："
    echo "$lost" | sed 's/^/    /'
    rc=1
  else
    echo "OK  docker-compose.yml: 无 NAS 独有内容"
  fi
  rm -f "$d"
else
  echo "WARN: 读不到 NAS $DIR/docker-compose.yml（跳过漂移检查）"
fi
rm -f "$tmp"

echo "=== 必填 .env 键 ==="
REQUIRED="API_KEY SERVICE_TOKENS"
envkeys=$(ssh -o BatchMode=yes "$NAS" "sed -n 's/^\\([A-Za-z_0-9]*\\)=.*/\\1/p' $DIR/.env" 2>/dev/null || true)
if [ -z "$envkeys" ]; then
  echo "🔴 读不到 NAS .env（见 deploy/.env.example）"
  rc=1
else
  for k in $REQUIRED; do
    if echo "$envkeys" | grep -qx "$k"; then echo "OK   .env $k"; else echo "🔴 .env 缺键: $k"; rc=1; fi
  done
fi

if [ "$rc" -ne 0 ]; then echo "❌ 禁止部署：先回写仓库 / 补 NAS .env"; fi
exit "$rc"
