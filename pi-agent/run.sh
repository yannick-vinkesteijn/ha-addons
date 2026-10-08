#!/usr/bin/env bash
# Pi Agent add-on startup. Structure adapted from Robson Felix's Claude Code add-on.
#
# Ownership model:
#   - models.json, settings.json defaults, mcp.json  -> regenerated from add-on options each start
#   - AGENTS.md, skills, installed packages          -> seeded once, never overwritten
#   - /config/models.override.json                   -> optional user file merged over models.json
set -uo pipefail

OPTIONS="${OPTIONS_FILE:-/data/options.json}"
DATA_DIR="${DATA_DIR:-/data}"
CONFIG_DIR="${CONFIG_DIR:-/config}"
SEED_DIR="${PI_SEED_DIR:-/opt/pi-seed}"
DEFAULTS_DIR="${DEFAULTS_DIR:-/opt/defaults}"

log()  { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err()  { echo "[ERROR] $*"; }

opt() { jq -r --arg k "$1" --arg d "${2:-}" 'if has($k) and .[$k] != null then .[$k] else $d end' "$OPTIONS"; }

PROVIDER=$(opt default_provider)
MODEL=$(opt default_model)
ENABLE_MCP=$(opt enable_mcp true)
SESSION_PERSIST=$(opt session_persistence true)
FONT_SIZE=$(opt terminal_font_size 14)
THEME=$(opt terminal_theme dark)
WORKDIR=$(opt working_directory /homeassistant)

export PI_CODING_AGENT_DIR="$DATA_DIR/pi-agent"
AGENT_DIR="$PI_CODING_AGENT_DIR"
mkdir -p "$AGENT_DIR" /root/.config/mcp

# --- Seed (never clobber user edits) ---------------------------------------
if [ -d "$SEED_DIR" ]; then cp -an "$SEED_DIR"/. "$AGENT_DIR"/ 2>/dev/null || true; fi
# Packages are refreshed from the image when a pinned version differs, so add-on updates take effect.
# The whole seeded npm tree is copied over (overwriting same-named files), so dependencies stay consistent;
# packages the user installed themselves are left alone.
NEED_SYNC=0
for PKG in pi-permission-system pi-mcp-adapter @juicesharp/rpiv-web-tools; do
  SEED_PKG="$SEED_DIR/npm/node_modules/$PKG"; LIVE_PKG="$AGENT_DIR/npm/node_modules/$PKG"
  [ -d "$SEED_PKG" ] || { err "$PKG missing from the image ($SEED_PKG)"; [ "$PKG" = pi-permission-system ] && exit 1; continue; }
  if [ "$(jq -r .version "$SEED_PKG/package.json")" != "$(jq -r .version "$LIVE_PKG/package.json" 2>/dev/null)" ]; then NEED_SYNC=1; log "$PKG will be updated to $(jq -r .version "$SEED_PKG/package.json")"; fi
done
if [ "$NEED_SYNC" = 1 ]; then
  mkdir -p "$AGENT_DIR/npm" && cp -a "$SEED_DIR/npm/." "$AGENT_DIR/npm/" || { err "could not update the bundled extensions"; exit 1; }
fi
[ -d "$AGENT_DIR/npm/node_modules/pi-permission-system" ] || { err "permission extension is not installed; refusing to start without it"; exit 1; }
[ -f "$AGENT_DIR/AGENTS.md" ] || cp "$DEFAULTS_DIR/AGENTS.md" "$AGENT_DIR/AGENTS.md"
mkdir -p "$AGENT_DIR/skills"
if [ -d "$DEFAULTS_DIR/skills" ]; then cp -an "$DEFAULTS_DIR/skills"/. "$AGENT_DIR/skills"/ 2>/dev/null || true; fi

# --- Providers --------------------------------------------------------------
# models.json is regenerated from the custom_providers option on every start.
MODELS_JSON="$AGENT_DIR/models.json"
echo '{"providers":{}}' > "$MODELS_JSON"

# Keys for Pi's built-in providers, e.g. MISTRAL_API_KEY, OPENAI_API_KEY (see Pi's providers.md)
N_BUILTIN=$(jq '(.builtin_api_keys // []) | length' "$OPTIONS")
for ((i = 0; i < N_BUILTIN; i++)); do
  ENV_VAR=$(jq -r --argjson i "$i" '.builtin_api_keys[$i].env_var' "$OPTIONS")
  ENV_KEY=$(jq -r --argjson i "$i" '.builtin_api_keys[$i].api_key' "$OPTIONS")
  [ -n "$ENV_VAR" ] && [ -n "$ENV_KEY" ] || continue
  export "$ENV_VAR=$ENV_KEY"
  log "Built-in provider key set: $ENV_VAR"
done

# Any OpenAI-compatible endpoint (AKI.IO, ...). Keys are resolved by Pi from the
# options file by index, so they are never written into models.json.
# If a provider lists no models, they are discovered from <base_url>/models.
N_CUSTOM=$(jq '(.custom_providers // []) | length' "$OPTIONS")
for ((i = 0; i < N_CUSTOM; i++)); do
  CNAME=$(jq -r --argjson i "$i" '.custom_providers[$i].name' "$OPTIONS")
  if [ "$(jq --argjson i "$i" '(.custom_providers[$i].models // []) | length' "$OPTIONS")" = 0 ]; then
    CURL_URL=$(jq -r --argjson i "$i" '.custom_providers[$i].base_url' "$OPTIONS")
    CKEY=$(jq -r --argjson i "$i" '.custom_providers[$i].api_key' "$OPTIONS")
    DISCOVERED=$(curl -sf --max-time 15 -H "Authorization: Bearer $CKEY" "${CURL_URL%/}/models" \
      | jq -c '[.data[]?.id | select(. != null)]' 2>/dev/null || true)
    [ -n "$DISCOVERED" ] && [ "$DISCOVERED" != "[]" ] || { warn "$CNAME: no models configured and discovery from ${CURL_URL%/}/models failed"; DISCOVERED='[]'; }
  else
    DISCOVERED='null'
  fi
  jq --argjson i "$i" --argjson disc "$DISCOVERED" --slurpfile o "$OPTIONS" --arg opts "$OPTIONS" '
    ($o[0].custom_providers[$i]) as $c
    | .providers[$c.name] = {
        baseUrl: $c.base_url,
        api: "openai-completions",
        apiKey: ("!jq -r '"'"'.custom_providers[\($i)].api_key'"'"' " + $opts),
        compat: {supportsDeveloperRole: false, supportsReasoningEffort: false,
                 supportsUsageInStreaming: false, maxTokensField: "max_tokens"},
        models: (($disc // $c.models) | map(select(. != null and . != "")) | unique | map({id: .}))
      }' "$MODELS_JSON" > "$MODELS_JSON.tmp" && mv "$MODELS_JSON.tmp" "$MODELS_JSON"
  log "Custom provider: $CNAME ($(jq --arg n "$CNAME" '.providers[$n].models | length' "$MODELS_JSON") models)"
done

OVERRIDE="$CONFIG_DIR/models.override.json"
if [ -f "$OVERRIDE" ]; then
  if jq -e . "$OVERRIDE" > /dev/null 2>&1; then
    jq -s '.[0] * .[1]' "$MODELS_JSON" "$OVERRIDE" > "$MODELS_JSON.tmp" && mv "$MODELS_JSON.tmp" "$MODELS_JSON"
    log "Merged $OVERRIDE"
  else
    err "$OVERRIDE is not valid JSON; ignoring it"
  fi
fi

if [ -n "$PROVIDER" ] && ! jq -e --arg p "$PROVIDER" '.providers[$p]' "$MODELS_JSON" > /dev/null 2>&1 \
   && [ "$(jq '(.builtin_api_keys // []) | length' "$OPTIONS")" = 0 ]; then
  warn "default_provider '$PROVIDER' is neither a custom provider nor backed by a builtin_api_keys entry"
fi
if [ "$(jq '(.custom_providers // []) | length' "$OPTIONS")" = 0 ] && [ "$(jq '(.builtin_api_keys // []) | length' "$OPTIONS")" = 0 ]; then
  err "No provider configured. Add an entry under builtin_api_keys or custom_providers and restart."
fi

# --- settings.json: merge defaults, keep everything else Pi wrote ----------
SETTINGS="$AGENT_DIR/settings.json"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
jq --arg p "$PROVIDER" --arg m "$MODEL" '
  (if $p != "" then .defaultProvider = $p else del(.defaultProvider) end) | if $m != "" then .defaultModel = $m else del(.defaultModel) end' \
  "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

# --- Permission policy (pi-permission-system) -------------------------------
# Regenerated on every start so the add-on options stay authoritative. Order matters:
# the LAST matching rule wins, so broad rules come first and denies come last.
# Reads are free inside the mapped folders; writes, edits and bash ask first.
# Bash patterns match the whole command string, so denies there are a speed bump, not a sandbox.
RESTRICT=$(opt restrict_sensitive_files true)
POLICY="$AGENT_DIR/pi-permissions.jsonc"
jq -n --argjson restrict "$RESTRICT" --arg agent "$AGENT_DIR" '
  def protected_paths: ["*secrets.yaml*", "/homeassistant/.storage/*", "/homeassistant/.cloud/*", "/homeassistant/.git/*",
                        "/ssl/*", "/backup/*", "*.key", "*.pem", "/data/options.json", "/data/pi-agent/auth.json",
                        "/root/.config/mcp/*", "/proc/*/environ",
                        "/addon_configs/*/secrets*", "*.env", "*credentials*"];
  # Files that control or could disable enforcement: never writable by the agent.
  def control_files: [($agent + "/pi-permissions.jsonc"), ($agent + "/settings.json"), ($agent + "/models.json"),
                      ($agent + "/extensions/*"), ($agent + "/npm/*"), "/opt/pps/*", "/config/*override*",
                      "*/.pi/*", "/data/options.json"];
  {
    defaultPolicy: {tools: "ask", bash: "ask", mcp: "ask", skills: "allow", special: "ask"},
    tools: (
      {read: "allow", grep: "allow", find: "allow", ls: "allow", write: "ask", edit: "ask",
       # Web: searching is allowed; fetching always asks, because a URL can carry data out and can point at internal hosts.
       web_search: "allow", web_fetch: "ask"}
      + (if $restrict then
          ([protected_paths[] | ("read:" + .), ("grep:" + .), ("find:" + .)] | map({key: ., value: "deny"}) | from_entries)
        else {} end)
      # Never editable by the agent: protected files and its own policy.
      + ([protected_paths[], control_files[], "/opt/*", "/usr/*", "/etc/*", "/root/.bash*", "/root/.profile"]
         | map(("write:" + .), ("edit:" + .)) | map({key: ., value: "deny"}) | from_entries)
    ),
    bash: (
      {"*": "ask", "sudo *": "deny", "rm -rf /*": "deny", "rm -rf /": "deny", "*pi-permissions.jsonc*": "deny", "*.pi/*": "deny"}
      + (if $restrict then
          {"*secrets.yaml*": "deny", "*/.storage/*": "deny", "*/.cloud/*": "deny", "*/data/options.json*": "deny", "*/proc/*/environ*": "deny"}
        else {} end)
    ),
    mcp: {
      "*": "ask",
      "homeassistant:get_*": "allow", "homeassistant:list_*": "allow",
      "homeassistant:search_*": "allow", "homeassistant:domain_summary*": "allow"
    },
    skills: {"*": "allow"},
    special: ({
      doom_loop: "deny",
      external_directory: "ask",
      "external_directory:/homeassistant/*": "allow", "external_directory:/addon_configs/*": "allow",
      "external_directory:/config/*": "allow", "external_directory:/share/*": "allow",
      "external_directory:/media/*": "allow", "external_directory:/data/backups/*": "allow",
      "external_directory:/ssl/*": "ask", "external_directory:/backup/*": "ask",
      "external_directory:/tmp/*": "allow",
      "external_directory:/data/pi-agent/skills/*": "allow",
      "external_directory:/data/pi-agent/AGENTS.md": "allow"
    }
    # Outside-the-workdir paths that must never be reachable, even if someone approves a prompt.
    + ([(if $restrict then protected_paths else [] end)[], control_files[]]
       | map(select(startswith("/"))) | unique
       | map({key: ("external_directory:" + .), value: "deny"}) | from_entries))
  }' > "$POLICY.tmp" && mv "$POLICY.tmp" "$POLICY"
POLICY_OVERRIDE="$CONFIG_DIR/pi-permissions.override.json"
if [ -f "$POLICY_OVERRIDE" ]; then
  if jq -e . "$POLICY_OVERRIDE" > /dev/null 2>&1; then
    jq -s '.[0] * .[1]' "$POLICY" "$POLICY_OVERRIDE" > "$POLICY.tmp" && mv "$POLICY.tmp" "$POLICY"
    log "Merged $POLICY_OVERRIDE into the permission policy"
  else
    err "$POLICY_OVERRIDE is not valid JSON; ignoring it"
  fi
fi
log "Permission policy written (restrict_sensitive_files=$RESTRICT)"

# The extension's own switches (enabled / yoloMode) are rewritten every start, outside the agent's data dir.
mkdir -p /opt/pps
echo '{"enabled": true, "yoloMode": false}' > /opt/pps/config.json
export PI_PERMISSION_SYSTEM_CONFIG_PATH=/opt/pps/config.json

# The enforcing extensions must always be installed, even for an older persistent settings.json.
if [ -f "$SEED_DIR/settings.json" ]; then
  jq -s '.[0] * {packages: ((((.[0].packages // []) | map(select((startswith("npm:pi-permission-system") or startswith("npm:pi-mcp-adapter") or startswith("npm:@juicesharp/rpiv-web-tools")) | not))) + (.[1].packages // [])) | unique)}' "$SETTINGS" "$SEED_DIR/settings.json" \
    > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"
fi

# --- MCP (pi-mcp-adapter reads ~/.config/mcp/mcp.json) ---------------------
# /root is ephemeral, so the Supervisor token is never persisted or backed up.
MCP_JSON=/root/.config/mcp/mcp.json
if [ "$ENABLE_MCP" = "true" ]; then
  jq -n --arg tok "${SUPERVISOR_TOKEN:-}" '{mcpServers:{homeassistant:{
    command:"hass-mcp",
    env:{HA_URL:"http://supervisor/core", HA_TOKEN:$tok}}}}' > "$MCP_JSON"
  chmod 600 "$MCP_JSON"
  log "MCP: Home Assistant (hass-mcp) configured"
else
  echo '{"mcpServers":{}}' > "$MCP_JSON"
  log "MCP disabled"
fi

# --- Web search (rpiv-web-tools): provider from the option, key via builtin_api_keys (e.g. BRAVE_SEARCH_API_KEY) ----
WEB_PROVIDER=$(opt web_search_provider)
if [ -n "$WEB_PROVIDER" ]; then export WEB_SEARCH_PROVIDER="$WEB_PROVIDER"; log "Web search provider: $WEB_PROVIDER"; fi

# --- Terminal ----------------------------------------------------------------
if [ "$THEME" = "dark" ]; then
  COLORS='background=#1e1e2e,foreground=#cdd6f4,cursor=#f5e0dc'
else
  COLORS='background=#eff1f5,foreground=#4c4f69,cursor=#dc8a78'
fi
if [ "$SESSION_PERSIST" = "true" ]; then SHELL_CMD=(tmux new-session -A -s pi); else SHELL_CMD=(bash --login); fi

log "Pi $(pi --version 2>/dev/null || echo '(version check failed)'); agent dir: $AGENT_DIR"
[ -d "$WORKDIR" ] || { warn "working_directory $WORKDIR missing; using /"; WORKDIR=/; }
cd "$WORKDIR" || true

nginx -t -c /etc/nginx/pi-agent.conf >/dev/null 2>&1 || { err "nginx config is invalid"; exit 1; }
# nginx runs in the foreground inside a restart loop, so a crash does not silently break ingress.
( while true; do nginx -c /etc/nginx/pi-agent.conf; warn "nginx exited; restarting"; sleep 1; done ) &
exec ttyd --interface 127.0.0.1 --port 7682 --writable --ping-interval 30 --max-clients 5 \
  -t fontSize="$FONT_SIZE" \
  -t fontFamily=Monaco,Consolas,monospace \
  -t scrollback=20000 \
  -t "theme=$COLORS" \
  "${SHELL_CMD[@]}"
