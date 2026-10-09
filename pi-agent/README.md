# Pi Agent for Home Assistant

The [Pi](https://pi.dev) coding agent in a Home Assistant sidebar terminal. Use any token-based model (Mistral, AKI.IO,
any OpenAI-compatible endpoint) to read, explain and fix your HA config. Home Assistant tools via hass-mcp.

## Quick start
1. Add this repository to the add-on store: `https://github.com/yannick-vinkesteijn/ha-addons`, then install **Pi Agent**.
2. In **Configuration**, add a provider (below), then start the add-on.
3. Open **Pi Agent** in the sidebar and type `pi`. The terminal shows what is configured and what is missing.

## Providers
```yaml
# A provider Pi already knows (Mistral, OpenAI, Groq, OpenRouter, ...): its API key variable
builtin_api_keys:
  - env_var: MISTRAL_API_KEY
    api_key: "..."

# Anything OpenAI-compatible. Leave models empty to fetch the list from <base_url>/models.
custom_providers:
  - name: aki
    base_url: https://aki.io/openai/v1
    api_key: "..."
    models: []

default_provider: aki      # optional
default_model: ""          # optional
```
`models.json` and the default provider/model are regenerated on every start; keys are never written into it.
`AGENTS.md`, skills and installed packages are seeded once and are yours to edit (`/data/pi-agent`).
Extra provider settings can go in `/config/models.override.json` (merged over the generated file).

## Safety: it asks first
An agent with access can destroy things: delete files, break your config, or send data to your model provider. So:
- **Reads** inside the mapped folders are free. **Writes, edits and shell commands ask first.**
- **Protected:** `secrets.yaml`, `.storage/`, `.cloud/`, `.git/`, `ssl/`, `/backup`, key files and the add-on options can't be read or written
  (`restrict_sensitive_files`, on by default). The policy and extension files are never writable.
- **Config edits** go through `ha-safe-write` (backup, HA config check, rollback), then `ha-reload`. Undo with `ha-restore`.
  These are per-file copies in `/data/backups`, **not HA backups**; make a real one before big changes.
- Reading other add-ons' configs (`/addon_configs`) asks first. No `full_access`, Docker or manager role; ingress only.

It's a speed bump, not a sandbox: bash rules match the command text so tricks get around them, `grep`/`find` on a directory
can still read protected files inside it, and symlinks aren't resolved.

## Web search
Set `web_search_provider` (e.g. `brave`) and add its key as a `builtin_api_keys` entry (`BRAVE_SEARCH_API_KEY`).
Searching is allowed; **fetching a URL always asks**, so read the full URL before approving.

## Tips
- Copying text: Pi captures the mouse, so hold **Shift** (**Option** on macOS) while you drag to select, then copy with Ctrl/Cmd+C.
- Try it locally: `./dev/run-local.sh --mock-ha` (Docker; state in `~/pi-test`).

## Credits
Inspired by [Robson Felix's Claude Code add-on](https://github.com/robsonfelix/robsonfelix-hass-addons/tree/main/claudecode) (MIT),
which I use myself; a few pieces are adapted from it (see `LICENSE`). I also looked at
[magnusoverli's OpenCode add-on](https://github.com/magnusoverli/opencode) (Unlicense); its approach to validated config writes
shaped this one (ideas only). Uses [pi-permission-system](https://github.com/MasuRii/pi-permission-system) (MIT).
