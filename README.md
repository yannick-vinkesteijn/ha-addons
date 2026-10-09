# Vinkels Home Assistant Add-ons

## Add-ons

| Add-on | Description |
|---|---|
| [Pi Agent](pi-agent/) | [Pi](https://pi.dev) coding agent in the HA sidebar, with any token-based model (Mistral, AKI.IO, any OpenAI-compatible provider) |

## Credits

Inspired by [Robson Felix's Claude Code add-on](https://github.com/robsonfelix/robsonfelix-hass-addons/tree/main/claudecode)
(MIT), which I use myself. I built this because I use [Pi](https://pi.dev) as my daily driver for open
models, and wanted the same thing for it. A few pieces are adapted from his add-on (the ttyd/tmux ingress
setup and the Home Assistant path guidance for the agent); see `LICENSE`.

The safety design (validated config writes, rollback, backups, protected secrets, asking before writes)
is inspired by [magnusoverli's OpenCode add-on](https://github.com/magnusoverli/opencode) (Unlicense);
ideas only, no code.

Built on [Pi](https://pi.dev), [pi-mcp-adapter](https://pi.dev/packages/pi-mcp-adapter),
[pi-permission-system](https://github.com/MasuRii/pi-permission-system) (MIT), [hass-mcp](https://pypi.org/project/hass-mcp/)
and [ttyd](https://github.com/tsl0922/ttyd).
