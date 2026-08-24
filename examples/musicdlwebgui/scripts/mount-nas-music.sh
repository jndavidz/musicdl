#!/usr/bin/env bash
# mount-nas-music.sh (v2): mount Synology /volume1/music into WSL2 at the same path,
# so musicdl-webgui can download straight into the NAS music library.
#
# Usage (in WSL2, needs sudo):
#     sudo bash examples/musicdlwebgui/scripts/mount-nas-music.sh            # NFS (auto-negotiate v4/v3)
#     sudo bash examples/musicdlwebgui/scripts/mount-nas-music.sh --smb      # SMB fallback
#
# v2 changes:
#   * cleans stale state first (dead autofs placeholder + old fstab line)
#   * probes mount parameter sets in order and prints the REAL error of each attempt
#   * only trusts /proc/mounts fs-type check (autofs placeholder is NOT "mounted")
set -euo pipefail

NAS=10.10.10.2
MP=/volume1/music          # mount point == NAS path, keeps download_dir identical on both sides
CRED=/root/.smbcredentials.musicdl

[[ $EUID -eq 0 ]] || { echo '请用 sudo 运行: sudo bash '$0; exit 1; }

is_nfs_mounted() { awk -v p="$MP" '$2==p && $3 ~ /^nfs/{found=1} END{exit !found}' /proc/mounts; }
is_cifs_mounted() { awk -v p="$MP" '$2==p && $3 == "cifs"{found=1} END{exit !found}' /proc/mounts; }
fstype_at() { awk -v p="$MP" '$2==p{print $3}' /proc/mounts | head -1; }

if is_nfs_mounted || is_cifs_mounted; then
  echo ">> $MP 已挂载 ($(fstype_at))，无需操作"; exit 0
fi

echo '>> 清理残留状态(旧的 autofs 占位与 fstab 条目) ...'
systemctl stop "$(systemd-escape -p --suffix=automount "$MP")" 2>/dev/null || true
umount "$MP" 2>/dev/null || true          # detach possibly-dead autofs placeholder
sed -i "\#${NAS}:${MP}#d; \#//${NAS}/music#d" /etc/fstab
mkdir -p "$MP"

MODE=${1:-'--nfs'}

if [[ $MODE == '--nfs' ]]; then
  EXPORTED=$(showmount -e "$NAS" 2>/dev/null | awk -v p="$MP" '$1==p{print $1}')
  if [[ -z "$EXPORTED" ]]; then
    cat <<'TIP'
!! NAS 尚未把 music 共享夹导出给本网段。请在 DSM 操作一次：

  控制面板 → 共享文件夹 → music → 编辑 → NFS 权限 → 新增：
    网段/主机 : 10.10.10.0/24
    权限      : 可读写
    Squash    : 无映射
    勾选「允许在此文件夹的子文件夹中装载」   ← NFSv4 必需，务必勾选

保存后重新运行本脚本。（或改用 SMB: sudo bash <本脚本> --smb）
TIP
    exit 2
  fi
  echo ">> 发现导出 $EXPORTED ，开始逐组参数实测挂载 ..."
  COMMON='soft,timeo=100,retrans=2,noatime'
  TRY=(
    "nfs4|$COMMON"
    "nfs|vers=4,$COMMON"
    "nfs|vers=3,tcp,nolock,$COMMON"
  )
  OK_OPTS=''
  for spec in "${TRY[@]}"; do
    fst=${spec%%|*}; opts=${spec#*|}
    echo "   尝试: mount -t $fst -o $opts ..."
    if mount -t "$fst" -o "$opts" "$NAS:$MP" "$MP" 2>/tmp/webgui-mount.err; then
      OK_OPTS="$fst|$opts"; break
    fi
    echo "     ✗ $(tail -1 /tmp/webgui-mount.err)"
    umount "$MP" 2>/dev/null || true
  done
  if [[ -z $OK_OPTS ]]; then
    cat <<'TIP'
!! 三种参数组合均失败。请检查：
  1) journalctl --no-pager | grep -i automount | tail -20    看 automount 报错
  2) DSM 控制面板 → 文件服务 → NFS 是否启用、「最大NFS协议」版本
  3) music 共享夹 NFS 规则是否勾选「允许在此文件夹的子文件夹中装载」
  或改用 SMB: sudo bash <本脚本> --smb
TIP
    exit 3
  fi
  fst=${OK_OPTS%%|*}; opts=${OK_OPTS#*|}
  echo ">> 实测成功 ($fst)，写入 fstab + systemd automount ..."
elif [[ $MODE == '--smb' ]]; then
  if [[ ! -f $CRED ]]; then
    read -rp 'NAS 用户名: ' SMB_USER
    read -rsp 'NAS 密码: ' SMB_PASS; echo
    printf 'username=%s\npassword=%s\n' "$SMB_USER" "$SMB_PASS" > "$CRED"
    chmod 600 "$CRED"
  fi
  # 关键: 归属到真实运行用户(sudo 下 id -u 是 0, 会导致普通用户对挂载树无写权限)
  RUN_UID=${SUDO_UID:-$(id -u "${SUDO_USER:-user}")}
  RUN_GID=${SUDO_GID:-$(id -g "${SUDO_USER:-user}")}
  fst=cifs
  opts="credentials=$CRED,uid=$RUN_UID,gid=$RUN_GID,iocharset=utf8,file_mode=0664,dir_mode=0775,soft,_netdev"
  if ! mount -t cifs -o "$opts" "//${NAS}/music" "$MP" 2>/tmp/webgui-mount.err; then
    echo "!! CIFS 挂载失败: $(tail -2 /tmp/webgui-mount.err)"; exit 3
  fi
  echo ">> 实测成功 (cifs, uid=$RUN_UID:$RUN_GID)，写入 fstab + systemd automount ..."
else
  echo "用法: sudo bash $0 [--nfs|--smb]"; exit 1
fi

FSTAB_LINE="$NAS:$MP $MP $fst ${opts},_netdev,x-systemd.automount,x-systemd.idle-timeout=600 0 0"
[[ $MODE == '--smb' ]] && FSTAB_LINE="//${NAS}/music $MP $fst ${opts},x-systemd.automount,x-systemd.idle-timeout=600 0 0"
echo "$FSTAB_LINE" >> /etc/fstab
umount "$MP" 2>/dev/null || true          # re-mount through automount to validate persistence path
systemctl daemon-reload
AUTOMOUNT_UNIT="$(systemd-escape -p --suffix=automount "$MP")"
systemctl enable --now "$AUTOMOUNT_UNIT" 2>/dev/null || true

echo '>> 等待 automount 触发(最多20秒) ...'
TRIGGERED=0
for i in $(seq 1 10); do
  ls "$MP" >/dev/null 2>&1 || true        # access triggers the automount
  sleep 2
  if is_nfs_mounted || is_cifs_mounted; then TRIGGERED=1; break; fi
done

if ! (is_nfs_mounted || is_cifs_mounted); then
  echo '>> automount 未触发, 回退 mount -a 直接挂载 ...'
  systemctl stop "$AUTOMOUNT_UNIT" 2>/dev/null || true
  mount -a 2>/dev/null || true
  sleep 1
fi

if ! (is_nfs_mounted || is_cifs_mounted); then
  echo "!! 挂载仍未就绪，当前 fs 类型: '${fstype_at:-none}'"
  echo "   手动验证: sudo mount -a && ls $MP；或查看: journalctl --no-pager | grep -iE 'automount|cifs|nfs' | tail"
  exit 4
fi
echo ">> 挂载成功: $(df -h "$MP" | tail -1)"

TARGET="$MP/download"
RUN_AS=${SUDO_USER:-user}
mkdir -p "$TARGET"
chown "$RUN_AS" "$TARGET" 2>/dev/null || true
if su -s /bin/bash "$RUN_AS" -c "touch '$TARGET/.write_test' && rm '$TARGET/.write_test'" 2>/dev/null; then
  echo ">> 可写性验证通过: $TARGET (用户 $RUN_AS)"
else
  echo "!! $TARGET 对用户 $RUN_AS 不可写 —— 检查 DSM 共享夹权限或 NFS Squash 设置"
  exit 5
fi
echo ">> 完成。musicdl-webgui 的下载目录已指向 $TARGET"
