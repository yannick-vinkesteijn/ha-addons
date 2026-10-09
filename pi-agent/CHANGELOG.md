# Changelog

## 0.1.2
- Home Assistant now pulls the prebuilt multi-arch image from ghcr.io instead of building it on your device (much faster install and update).

## 0.1.1
- Reading other add-ons' configs (`/addon_configs`) now asks first, like writing does; they often contain credentials.
- Python tests (pytest), ruff and ty config (`pyproject.toml`), pre-commit hooks, and a CI job that runs them.
- Startup configuration moved from a ~230-line bash script to `render_config.py` (Python); `run.sh` now only starts the services. Generated files are unchanged, except that models keep the order you list them in.
- Install `fd` in the image (Pi no longer downloads it into /data at runtime).
- tmux: enable extended keys with the csi-u format (modified Enter, no more warning).
- Pi's built-in MCP is switched off up front, so the first start has no "extension conflict" warning.
- The terminal opens with a short setup status: what is configured, and what to add if no provider is set or a provider has no models.
- Model discovery now logs the HTTP status and response when it fails; a provider with no models is reported as an error with the fix.

## 0.1.0
- Initial version: Pi in an ingress web terminal; any provider via built-in API keys or custom OpenAI-compatible endpoints; hass-mcp via pi-mcp-adapter.
- Permission policy (pi-permission-system), `ha-safe-write` / `ha-reload` / `ha-restore`, nginx in front of ttyd.
