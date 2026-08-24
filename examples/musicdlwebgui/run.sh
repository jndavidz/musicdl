#!/usr/bin/env bash
# musicdl-webgui launcher: run from anywhere.
#   musicdl                 start the web GUI (http://127.0.0.1:3004)
#   musicdl --host 0.0.0.0  LAN access
#   musicdl-mount           mount Synology /volume1/music into WSL (sudo, first time only)
set -euo pipefail
REPO=/mnt/d/repos/musicdl
case "${1:-start}" in
  start|"")
    shift || true
    cd "$REPO"
    XDG_STATE_HOME="$REPO/.state" exec uv run python examples/musicdlwebgui/app.py "$@"
    ;;
  mount)
    sudo bash "$REPO/examples/musicdlwebgui/scripts/mount-nas-music.sh" "${2:---smb}"
    ;;
  stop)
    pkill -f 'examples/musicdlwebgui/app.py' && echo 'musicdl-webgui stopped' || echo 'not running'
    ;;
  *)
    echo "用法: musicdl [start|--port N|--host H] | musicdl mount [--smb|--nfs] | musicdl stop"
    exit 1 ;;
esac
