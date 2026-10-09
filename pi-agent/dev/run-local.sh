#!/usr/bin/env bash
# Run the add-on image locally with Docker, without Home Assistant.
#
#   ./dev/run-local.sh              build + run, open http://localhost:7681, type `pi`
#   ./dev/run-local.sh --mock-ha    also run a fake HA API so ha-safe-write / ha-reload work
#   ./dev/run-local.sh --detach     run in the background (docker logs -f pi-agent-dev)
#   ./dev/run-local.sh --stop       stop the background container
#
# State lives in $PI_TEST_DIR (default ~/pi-test): data/ (= /data), config/ (= /config),
# homeassistant/ (= /homeassistant). Keep it outside the repo and under your home directory
# so Docker can see it. Edit data/options.json to add your API keys; it is created once.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${PI_TEST_DIR:-$HOME/pi-test}"
PORT="${PORT:-7681}"
NAME=pi-agent-dev
MOCK=0; DETACH=0

for a in "$@"; do
  case "$a" in
    --mock-ha) MOCK=1 ;;
    --detach)  DETACH=1 ;;
    --stop)    docker rm -f "$NAME" >/dev/null 2>&1 && echo "stopped $NAME" || echo "$NAME is not running"; exit 0 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

mkdir -p "$DIR"/{data,config,homeassistant}
if [ ! -f "$DIR/data/options.json" ]; then
  cat > "$DIR/data/options.json" <<'JSON'
{
  "default_provider": "",
  "default_model": "",
  "enable_mcp": false,
  "session_persistence": true,
  "restrict_sensitive_files": true,
  "terminal_font_size": 14,
  "terminal_theme": "dark",
  "working_directory": "/homeassistant",
  "builtin_api_keys": [
    {"env_var": "MISTRAL_API_KEY", "api_key": "REPLACE_ME"}
  ],
  "custom_providers": [
    {"name": "aki", "base_url": "https://aki.io/openai/v1", "api_key": "REPLACE_ME", "models": []}
  ]
}
JSON
  echo "Created $DIR/data/options.json - edit it and put in your real API keys (delete entries you don't use)."
fi
[ -f "$DIR/homeassistant/configuration.yaml" ] || printf 'homeassistant:\n  name: Test\n' > "$DIR/homeassistant/configuration.yaml"
[ -f "$DIR/homeassistant/secrets.yaml" ] || printf 'wifi_password: not-a-real-secret\n' > "$DIR/homeassistant/secrets.yaml"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker build -t pi-agent-test "$HERE"

ARGS=(--name "$NAME" -p "$PORT:7681"
  -v "$DIR/data:/data" -v "$DIR/config:/config" -v "$DIR/homeassistant:/homeassistant"
  -e SUPERVISOR_TOKEN=dummy)
CMD=(/usr/local/bin/run.sh)
if [ "$MOCK" = 1 ]; then
  ARGS+=(-e HA_API_URL=http://127.0.0.1:8123/api -v "$HERE/dev/mock-ha.py:/opt/mock-ha.py:ro")
  CMD=(bash -c 'python3 /opt/mock-ha.py & exec /usr/local/bin/run.sh')
  echo "Mock HA API enabled. touch $DIR/homeassistant/.mock-fail to make its config check fail."
fi
if [ "$DETACH" = 1 ]; then ARGS+=(-d); else ARGS+=(--rm -it); fi

echo "Open http://localhost:$PORT and type: pi"
exec docker run "${ARGS[@]}" pi-agent-test "${CMD[@]}"
