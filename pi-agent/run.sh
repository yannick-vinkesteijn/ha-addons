#!/usr/bin/env bash
# Pi Agent add-on startup. render_config.py (next to this script's install, in /usr/local/lib/pi-agent)
# does all the configuration work; this script only starts the services.
# Structure adapted from Robson Felix's Claude Code add-on.
set -uo pipefail

# stdout = `export NAME=value` lines, stderr = log lines (shown in the add-on Log tab).
RENDERED=$(python3 /usr/local/lib/pi-agent/render_config.py) || { echo "[ERROR] configuration failed; not starting" >&2; exit 1; }
eval "$RENDERED"

if [ "$PI_UI_THEME" = "dark" ]; then
  COLORS='background=#1e1e2e,foreground=#cdd6f4,cursor=#f5e0dc'
else
  COLORS='background=#eff1f5,foreground=#4c4f69,cursor=#dc8a78'
fi
if [ "$PI_UI_SESSION_PERSIST" = "true" ]; then SHELL_CMD=(tmux new-session -A -s pi); else SHELL_CMD=(bash --login); fi

echo "[INFO] Pi $(pi --version 2>/dev/null || echo '(version check failed)'); agent dir: $PI_CODING_AGENT_DIR"
WORKDIR=$PI_UI_WORKDIR
[ -d "$WORKDIR" ] || { echo "[WARN] working_directory $WORKDIR missing; using /"; WORKDIR=/; }
cd "$WORKDIR" || true

nginx -t -c /etc/nginx/pi-agent.conf >/dev/null 2>&1 || { echo "[ERROR] nginx config is invalid"; exit 1; }
# nginx runs in the foreground inside a restart loop, so a crash does not silently break ingress.
( while true; do nginx -c /etc/nginx/pi-agent.conf; echo "[WARN] nginx exited; restarting"; sleep 1; done ) &
exec ttyd --interface 127.0.0.1 --port 7682 --writable --ping-interval 30 --max-clients 5 \
  -t fontSize="$PI_UI_FONT_SIZE" \
  -t fontFamily=Monaco,Consolas,monospace \
  -t scrollback=20000 \
  -t macOptionClickForcesSelection=true \
  -t "theme=$COLORS" \
  "${SHELL_CMD[@]}"
