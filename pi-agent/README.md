# Pi Agent for Home Assistant

Runs the [Pi](https://pi.dev) coding agent in a Home Assistant sidebar terminal, with any token-based model and
Home Assistant access through hass-mcp. Providers are configured the way Pi does it: built-in providers by API key,
everything else as a custom OpenAI-compatible provider.

## Setup
1. Install the add-on, open **Configuration**, add a provider (see below).
2. Start it, open **Pi Agent** in the sidebar, type `pi`.

## Providers
Add them in **Configuration**. Nothing is special-cased.

**Built-in Pi providers** (Mistral, OpenAI, Groq, OpenRouter, ...): add an entry under *Other built-in providers*.
```yaml
builtin_api_keys:
  - env_var: MISTRAL_API_KEY
    api_key: "..."
```

**Anything OpenAI-compatible** (AKI.IO, Scaleway, a self-hosted vLLM, ...): add an entry under *Custom providers*.
If `models` is left empty, the model list is fetched from `<base_url>/models`.
```yaml
custom_providers:
  - name: aki
    base_url: https://aki.io/v1
    api_key: "..."
    models: []
```

## How configuration works
| What | Behaviour |
|---|---|
| `models.json`, default provider/model, MCP config | Regenerated from the add-on options on **every start** |
| `AGENTS.md`, `skills/`, installed Pi packages | Seeded **once**, then yours to edit (`/data/pi-agent`, not overwritten) |
| `/config/models.override.json` (add-on config dir) | Optional; merged over the generated `models.json` (e.g. add a third provider) |

API keys are not written into `models.json`: built-in keys come from the environment, custom provider keys are resolved by Pi from the options file at use time.

## Web search
The agent has `web_search` and `web_fetch` (the [rpiv-web-tools](https://pi.dev/packages/@juicesharp/rpiv-web-tools) package).
Pick a provider with *Web search provider* and add its key under *Other built-in providers*, for example:
```yaml
web_search_provider: brave
builtin_api_keys:
  - env_var: BRAVE_SEARCH_API_KEY
    api_key: "..."
```
- **Searching is allowed; fetching a URL always asks.** A URL can carry data out, and fetching can reach internal hosts, so you approve each one. Read the full URL in the prompt before approving.
- The package refuses literal private IPs (`192.168.x.x`, `127.0.0.1`) but **not** hostnames that resolve to private addresses or redirects to them. Treat the prompt as the real protection.
- For Home Assistant's own state and logs use the `homeassistant` MCP tools (authenticated). For a LAN device the agent can use `curl` through bash, which also asks.
- SearXNG/Ollama need a base URL (`SEARXNG_URL`, `OLLAMA_HOST`); not exposed as an option yet.

## Safety model
Pi itself has no approval prompts, so this add-on adds the `pi-permission-system` extension with a generated policy
(`/data/pi-agent/pi-permissions.jsonc`, rewritten on every start):

- **Reads** inside the mapped folders are free. **Writes, edits and shell commands ask first.** If the terminal has no UI to ask, they are blocked.
- **Protected files** (`restrict_sensitive_files`, on by default): `secrets.yaml`, `.storage/`, `.cloud/`, `.git/`, `ssl/`, `/backup`, key files, `/data/options.json`.
  The agent cannot read them with the read tool and cannot write them at all.
- **Self-protection:** the policy, `settings.json`, `models.json`, extensions, `.pi/` folders and `*override*` files in `/config` are not writable by the agent.
  The extension's own on/off switch is rewritten at start, and the add-on refuses to start if the extension is missing.
- **Config edits** should go through `ha-safe-write` (backup, HA Core config check, rollback), then `ha-reload`. Undo with `ha-restore`.
  These are per-file copies in `/data/backups`, **not Home Assistant backups**. Make a real HA backup before large changes.
- **No `full_access`, Docker, UART or manager role.** The terminal is only reachable through HA ingress (nginx allows the Supervisor only).

Limits you should know about. This is a speed bump, not a sandbox:
- Bash rules match the whole command string, so a deny on `secrets.yaml` is easy to get around with a shell trick.
- `grep` and `find` on a **directory** are not blocked by path rules, so they can still read protected files inside it.
- The policy does not resolve symlinks: a link to a protected file can be read.
- `/addon_configs` (other add-ons' configs) is mounted read-write. Reads and writes both ask first, and anything the agent reads is sent to your model provider.
- Back up before letting it loose on `configuration.yaml`.

## Local testing
```bash
./dev/run-local.sh --mock-ha     # builds the image, runs it on http://localhost:7681, fake HA API included
./dev/run-local.sh --detach      # background; --stop to stop
```
State is kept in `~/pi-test` (override with `PI_TEST_DIR`); put your API keys in `~/pi-test/data/options.json`.
Without real Home Assistant, hass-mcp is unavailable and `--mock-ha` only fakes the config check and reload calls.

## Credits
Based on, and with thanks to, **[Robson Felix](https://github.com/robsonfelix)** and his
[Claude Code add-on](https://github.com/robsonfelix/robsonfelix-hass-addons/tree/main/claudecode) (MIT).
The safe-write / backup / protected-files design is inspired by
**[magnusoverli's OpenCode add-on](https://github.com/magnusoverli/opencode)** (Unlicense); ideas only, no code copied.
Uses [pi-permission-system](https://github.com/MasuRii/pi-permission-system) (MIT) for the permission policy.
