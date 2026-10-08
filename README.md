# Vinkels Home Assistant Add-ons

## Add-ons

| Add-on | Description |
|---|---|
| [Pi Agent](pi-agent/) | [Pi](https://pi.dev) coding agent in the HA sidebar, with any token-based model (Mistral, AKI.IO, any OpenAI-compatible provider) |

## Credits

Huge thanks to **[Robson Felix](https://github.com/robsonfelix)**. The structure of
these add-ons (ingress web terminal via ttyd, tmux persistence, hass-mcp wiring, the
Home Assistant path/log guidance for the agent) is adapted from his
[Claude Code add-on](https://github.com/robsonfelix/robsonfelix-hass-addons/tree/main/claudecode),
which is MIT licensed. The agent work is his. If you use Claude, go use his add-on.

The safety design (validate-before-commit config writes, rollback, per-file backups, protected
secrets, asking before writes) is inspired by
**[magnusoverli's OpenCode add-on](https://github.com/magnusoverli/opencode)** for Home Assistant
(Unlicense). We took the ideas, not the code. If you want a fuller-featured agent add-on, use his.

Built on [Pi](https://pi.dev), [pi-mcp-adapter](https://pi.dev/packages/pi-mcp-adapter),
[pi-permission-system](https://github.com/MasuRii/pi-permission-system) (MIT), [hass-mcp](https://pypi.org/project/hass-mcp/)
and [ttyd](https://github.com/tsl0922/ttyd).
