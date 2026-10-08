---
name: home-assistant-config
description: Safely edit Home Assistant YAML configuration (automations, scripts, scenes, configuration.yaml). Use whenever a change to files under /homeassistant is needed.
---

# Editing Home Assistant configuration

Always go through `ha-safe-write` and `ha-reload`. They are cheap, deterministic and always do the same checks.

## Steps
1. **Read** the current file and understand what is already there. Never read `secrets.yaml`, `.storage/` or `.cloud/`.
2. **Draft** the full new file content (these tools replace the whole file, so include everything that should stay).
3. **Save** with validation:
   `ha-safe-write /homeassistant/<file> < draft` (use a heredoc or a temp file)
   - Exit 0: saved and HA Core's config check passed. A backup is kept under `/data/backups/<timestamp>/`.
   - Exit 1: HA's check failed; the previous version was restored. Read the errors, fix the draft, retry.
   - Exit 2: refused (outside `/homeassistant`, protected file, empty, invalid YAML, or a large shrink). Do not bypass with other tools. `--allow-shrink` only if the user asked for a big deletion.
4. **Apply** only after the user agrees: `ha-reload automation` (or `script`, `scene`, `template`, `core`). A full restart is a separate, explicit user decision.
5. **Verify** it loaded: check the entity state or `ha core logs 2>&1 | tail -50`.
6. **Report** three separate facts: saved, reloaded, load verified. Never say "done" after step 3 alone.

## Undo
- `ha-restore list` shows saved copies (each holds the file as it was *before* that change).
- `ha-restore apply <timestamp> [file]` puts it back, validated and itself backed up.
- These are per-file copies, not Home Assistant backups. Offer to have the user make a full HA backup before large changes.

## Rules
- One change at a time; reload and verify before the next.
- Use `!secret name` references; never inline a secret value.
- If `ha-safe-write` is unavailable or refuses, tell the user instead of writing around it.
