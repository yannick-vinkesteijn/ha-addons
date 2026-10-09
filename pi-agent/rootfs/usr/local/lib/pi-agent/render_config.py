#!/usr/bin/env python3
"""Render Pi Agent's configuration from the add-on options (/data/options.json).

Called by run.sh on every start. Writes the generated files and prints `export NAME=value`
lines on stdout for run.sh to eval; all log output goes to stderr.

Ownership model:
  - models.json, pi-permissions.jsonc, MCP config, defaults in settings.json -> regenerated each start
  - AGENTS.md, skills, packages the user installed                          -> seeded once, never overwritten
  - /config/models.override.json, /config/pi-permissions.override.json
      -> optional, deep-merged over the generated files

Structure adapted from Robson Felix's Claude Code add-on (MIT).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict

# Anything json.loads can return. Pi's config files are free-form, so we do not model them further.
Json = Any


class BuiltinKey(TypedDict):
    """One `builtin_api_keys` entry: a key for a provider Pi already knows (e.g. MISTRAL_API_KEY)."""

    env_var: str
    api_key: str


class CustomProvider(TypedDict):
    """One `custom_providers` entry: any OpenAI-compatible endpoint."""

    name: str
    base_url: str
    api_key: str
    models: NotRequired[list[str | None]]


# Result of probing <base_url>/models: (model ids, HTTP status as text or "000", start of the body).
Discovery = tuple[list[str], str, str]
Discoverer = Callable[[str, str], Discovery]

# Paths come from environment variables so tests (and dev/run-local.sh) can point at a scratch tree.
OPTIONS = Path(os.environ.get("OPTIONS_FILE", "/data/options.json"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
SEED_DIR = Path(os.environ.get("PI_SEED_DIR", "/opt/pi-seed"))
DEFAULTS_DIR = Path(os.environ.get("DEFAULTS_DIR", "/opt/defaults"))
ROOT_HOME = Path(os.environ.get("ROOT_HOME", "/root"))
PPS_DIR = Path(os.environ.get("PPS_DIR", "/opt/pps"))

# Extensions bundled in the image; re-synced from the seed when their version changes.
PINNED_PACKAGES = ["pi-permission-system", "pi-mcp-adapter", "@juicesharp/rpiv-web-tools"]

# Environment variable holding each web-search provider's API key.
WEB_KEY_VAR = {
    "brave": "BRAVE_SEARCH_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "serper": "SERPER_API_KEY",
    "exa": "EXA_API_KEY",
    "youcom": "YOUCOM_API_KEY",
    "jina": "JINA_API_KEY",
    "firecrawl": "FIRECRAWL_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}

# Never readable by the agent when restrict_sensitive_files is on, and never writable at all.
PROTECTED_PATHS = [
    "*secrets.yaml*",
    "/homeassistant/.storage/*",
    "/homeassistant/.cloud/*",
    "/homeassistant/.git/*",
    "/ssl/*",
    "/backup/*",
    "*.key",
    "*.pem",
    "/data/options.json",
    "/data/pi-agent/auth.json",
    "/root/.config/mcp/*",
    "/proc/*/environ",
    "/addon_configs/*/secrets*",
    "*.env",
    "*credentials*",
]


class Fatal(Exception):
    """Configuration problem that must stop the add-on (fail closed)."""


def log(level: str, msg: str) -> None:
    """Log lines go to stderr: stdout is reserved for the `export` lines run.sh evals."""
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


def info(msg: str) -> None:
    log("INFO", msg)


def warn(msg: str) -> None:
    log("WARN", msg)


def err(msg: str) -> None:
    log("ERROR", msg)


# --- small helpers -----------------------------------------------------------------------------


def read_json(path: str | Path, default: Json = None) -> Json:
    """Parsed JSON, or `default` if the file is missing or not valid JSON."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path: str | Path, data: Json, mode: int | None = None) -> None:
    """Write via a temp file + rename so a crash never leaves a half-written config behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def deep_merge(base: Json, extra: Json) -> Json:
    """Recursive object merge; anything that is not an object in `extra` replaces the value."""
    if isinstance(base, dict) and isinstance(extra, dict):
        out = dict(base)
        for k, v in extra.items():
            out[k] = deep_merge(base[k], v) if k in base else v
        return out
    return extra


def merge_override(data: dict[str, Json], path: str | Path, what: str) -> dict[str, Json]:
    """Merge the user's optional override file over generated config. A broken file is ignored, not fatal."""
    path = Path(path)
    if not path.is_file():
        return data
    extra = read_json(path)
    if not isinstance(extra, dict):
        err(f"{path} is not a valid JSON object; ignoring it")
        return data
    info(f"Merged {path} into the {what}")
    merged: dict[str, Json] = deep_merge(data, extra)
    return merged


def _under_symlinked_dir(dst: Path, target: Path) -> bool:
    """True if a directory between `dst` (exclusive) and `target` is a symlink in the destination tree.
    Copying through it would write outside `dst`, so such entries are skipped."""
    ancestors = [q for q in target.relative_to(dst).parents if q != Path(".")]
    return any((dst / q).is_symlink() for q in ancestors)


def copy_no_clobber(src: str | Path, dst: str | Path) -> None:
    """Like `cp -an`: copy what is missing, never overwrite."""
    src, dst = Path(src), Path(dst)
    for p in sorted(src.rglob("*")):
        target = dst / p.relative_to(src)
        if (target.is_symlink() and p.is_dir() and not p.is_symlink()) or _under_symlinked_dir(dst, target):
            continue
        if p.is_dir() and not p.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists() and not target.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            if p.is_symlink():
                os.symlink(os.readlink(p), target)
            else:
                shutil.copy2(p, target)


def copy_overwrite(src: str | Path, dst: str | Path) -> None:
    """Like `cp -a`: copy everything, replacing same-named files and symlinks (shutil.copytree cannot)."""
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.rglob("*")):
        target = dst / p.relative_to(src)
        if (target.is_symlink() and p.is_dir() and not p.is_symlink()) or _under_symlinked_dir(dst, target):
            continue
        if p.is_dir() and not p.is_symlink():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.is_file():
            target.unlink()
        if p.is_symlink():
            os.symlink(os.readlink(p), target)
        else:
            shutil.copy2(p, target)


def package_version(root: str | Path, pkg: str) -> str | None:
    """Installed version of an npm package under <root>/npm, or None if absent."""
    data = read_json(Path(root) / "npm" / "node_modules" / pkg / "package.json", {})
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


# --- seeding -----------------------------------------------------------------------------------


def seed_agent_dir(agent_dir: Path) -> None:
    """Make /data/pi-agent ready: copy the image's seed in, sync pinned extensions, add default AGENTS.md/skills."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    if SEED_DIR.is_dir():
        copy_no_clobber(SEED_DIR, agent_dir)

    # Extensions are copied once, then re-synced only when the image ships a different version.
    # (Never overwrite on every start: the user may have installed packages of their own.)
    need_sync = False
    for pkg in PINNED_PACKAGES:
        seed_version = package_version(SEED_DIR, pkg)
        if seed_version is None:
            err(f"{pkg} missing from the image ({SEED_DIR}/npm/node_modules/{pkg})")
            if pkg == "pi-permission-system":
                raise Fatal("the permission extension is missing from the image")
            continue
        if seed_version != package_version(agent_dir, pkg):
            need_sync = True
            info(f"{pkg} will be updated to {seed_version}")
    if need_sync:
        try:
            copy_overwrite(SEED_DIR / "npm", agent_dir / "npm")
        except OSError as e:
            raise Fatal(f"could not update the bundled extensions: {e}") from e
    # Fail closed: without the permission extension the safety model does not exist.
    if not (agent_dir / "npm/node_modules/pi-permission-system").is_dir():
        raise Fatal("permission extension is not installed; refusing to start without it")

    # User-owned files: seeded once, never overwritten.
    if not (agent_dir / "AGENTS.md").exists():
        shutil.copy2(DEFAULTS_DIR / "AGENTS.md", agent_dir / "AGENTS.md")
    (agent_dir / "skills").mkdir(exist_ok=True)
    if (DEFAULTS_DIR / "skills").is_dir():
        copy_no_clobber(DEFAULTS_DIR / "skills", agent_dir / "skills")


# --- providers ---------------------------------------------------------------------------------


def discover_models(base_url: str, api_key: str) -> Discovery:
    """Ask <base_url>/models. Returns (ids, code, start of the response body)."""
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    code, body = "000", ""  # "000" = no HTTP response at all
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            code, body = str(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, body = str(e.code), e.read().decode("utf-8", "replace")
    except Exception as e:  # connection refused, DNS, timeout, bad URL ...
        body = str(e)
    ids = []
    if code == "200":
        with contextlib.suppress(ValueError, AttributeError):  # not JSON, or not the shape we expect
            ids = [m["id"] for m in json.loads(body).get("data", []) if isinstance(m, dict) and m.get("id")]
    return ids, code, " ".join(body.split())[:200]


def build_models(opts: dict[str, Json], discover: Discoverer = discover_models) -> dict[str, Json]:
    """models.json content from custom_providers. API keys are never written into it:
    Pi resolves them at use time by running the `!jq ...` command against the options file."""
    providers: dict[str, Json] = {}
    for i, c in enumerate(opts.get("custom_providers") or []):
        name, base_url = c["name"], c["base_url"]
        ids = [m for m in (c.get("models") or []) if m]  # skip null/empty entries from the options form
        if not ids:  # no models listed: ask the endpoint
            ids, code, body = discover(base_url, c["api_key"])
            if not ids:
                warn(f"{name}: could not list models from {base_url.rstrip('/')}/models (HTTP {code}): {body}")
        ids = list(dict.fromkeys(ids))  # drop duplicates, keep the order given
        providers[name] = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "apiKey": f"!jq -r '.custom_providers[{i}].api_key' {OPTIONS}",
            # Generic OpenAI-compatible servers reject several OpenAI-only request fields.
            "compat": {
                "supportsDeveloperRole": False,
                "supportsReasoningEffort": False,
                "supportsUsageInStreaming": False,
                "maxTokensField": "max_tokens",
            },
            "models": [{"id": m} for m in ids],
        }
        info(f"Custom provider: {name} ({len(ids)} models)")
        if not ids:
            err(
                f"{name} has no models, so Pi will say 'No models available'. Add a model id under "
                "custom_providers -> models in the add-on options (copy it from the provider's dashboard), "
                "then restart."
            )
    return {"providers": providers}


# --- permission policy -------------------------------------------------------------------------


def build_policy(restrict: bool, agent_dir: Path) -> dict[str, Json]:
    """pi-permission-system policy. The LAST matching rule wins, so broad rules come first and
    denies come last (dict insertion order is preserved in the JSON file).
    Reads are free inside the mapped folders; writes, edits and bash ask first. Bash patterns match
    the whole command string, so denies there are a speed bump, not a sandbox."""
    agent = str(agent_dir)
    # Files that control or could disable enforcement: never writable by the agent.
    control_files = [
        f"{agent}/pi-permissions.jsonc",
        f"{agent}/settings.json",
        f"{agent}/models.json",
        f"{agent}/extensions/*",
        f"{agent}/npm/*",
        "/opt/pps/*",
        "/config/*override*",
        "*/.pi/*",
        "/data/options.json",
    ]
    never_writable = PROTECTED_PATHS + control_files + ["/opt/*", "/usr/*", "/etc/*", "/root/.bash*", "/root/.profile"]

    tools: dict[str, str] = {
        "read": "allow",
        "grep": "allow",
        "find": "allow",
        "ls": "allow",
        "write": "ask",
        "edit": "ask",
        # Searching is allowed; fetching always asks (a URL can carry data out or point at internal hosts).
        "web_search": "allow",
        "web_fetch": "ask",
    }
    if restrict:  # path-scoped denies come after the broad "allow" so they win
        for p in PROTECTED_PATHS:
            for tool in ("read", "grep", "find"):
                tools[f"{tool}:{p}"] = "deny"
    for p in never_writable:
        for tool in ("write", "edit"):
            tools[f"{tool}:{p}"] = "deny"

    bash: dict[str, str] = {
        "*": "ask",
        "sudo *": "deny",
        "rm -rf /*": "deny",
        "rm -rf /": "deny",
        "*pi-permissions.jsonc*": "deny",
        "*.pi/*": "deny",
    }
    if restrict:
        bash.update(
            {
                "*secrets.yaml*": "deny",
                "*/.storage/*": "deny",
                "*/.cloud/*": "deny",
                "*/data/options.json*": "deny",
                "*/proc/*/environ*": "deny",
            }
        )

    special: dict[str, str] = {"doom_loop": "deny", "external_directory": "ask"}
    for d in ("/homeassistant", "/config", "/share", "/media", "/data/backups"):
        special[f"external_directory:{d}/*"] = "allow"
    # Other add-ons' configs often hold credentials: reading them asks first.
    special["external_directory:/addon_configs/*"] = "ask"
    special["external_directory:/ssl/*"] = "ask"
    special["external_directory:/backup/*"] = "ask"
    special["external_directory:/tmp/*"] = "allow"
    special["external_directory:/data/pi-agent/skills/*"] = "allow"
    special["external_directory:/data/pi-agent/AGENTS.md"] = "allow"
    # Paths outside the working directory that must stay unreachable even if someone approves a prompt.
    for p in sorted({p for p in (PROTECTED_PATHS if restrict else []) + control_files if p.startswith("/")}):
        special[f"external_directory:{p}"] = "deny"

    return {
        "defaultPolicy": {"tools": "ask", "bash": "ask", "mcp": "ask", "skills": "allow", "special": "ask"},
        "tools": tools,
        "bash": bash,
        "mcp": {
            "*": "ask",
            "homeassistant:get_*": "allow",
            "homeassistant:list_*": "allow",
            "homeassistant:search_*": "allow",
            "homeassistant:domain_summary*": "allow",
        },
        "skills": {"*": "allow"},
        "special": special,
    }


# --- settings.json -----------------------------------------------------------------------------


def update_settings(path: str | Path, provider: str, model: str) -> None:
    """Merge our defaults into Pi's settings.json and keep everything else Pi wrote."""
    settings = read_json(path, None)
    if not isinstance(settings, dict):
        if Path(path).exists():
            warn(f"{path} was not valid JSON; starting a fresh one")
        settings = {}
    for key, value in (("defaultProvider", provider), ("defaultModel", model)):
        if value:
            settings[key] = value
        else:
            settings.pop(key, None)
    # pi-mcp-adapter replaces Pi's built-in MCP; switch the built-in off up front so Pi does not warn.
    settings["extensions"] = sorted(set(settings.get("extensions") or []) | {"-builtin:mcp"})
    # The bundled extensions must always be installed at the pinned versions, even for an old settings.json.
    # Packages: keep the user's own, but replace any stale pin of ours with the version in the image.
    seed = read_json(SEED_DIR / "settings.json", {})
    if seed.get("packages"):
        pinned_prefixes = tuple(f"npm:{p}" for p in PINNED_PACKAGES)
        kept = [p for p in settings.get("packages") or [] if not p.startswith(pinned_prefixes)]
        settings["packages"] = sorted(set(kept) | set(seed["packages"]))
    write_json(path, settings)


# --- setup status shown when the terminal opens ------------------------------------------------


def build_motd(
    opts: dict[str, Json],
    models: dict[str, Json],
    provider: str,
    model: str,
    enable_mcp: bool,
    key_is_set: Callable[[str], bool],
    web_provider: str,
) -> tuple[str, bool]:
    """Text for the terminal banner. Returns (text, whether anything needs the user's attention)."""
    lines: list[str] = ["", "  Pi Agent for Home Assistant", ""]
    problems = False
    builtin = usable_builtin_keys(opts)
    custom: list[CustomProvider] = opts.get("custom_providers") or []
    if not builtin and not custom:
        problems = True
        lines += [
            "  [!] No model provider is set up yet, so Pi has nothing to talk to.",
            "      Open this add-on's Configuration tab and add one of:",
            "        - builtin_api_keys: a key for a provider Pi knows (e.g. MISTRAL_API_KEY, OPENAI_API_KEY)",
            "        - custom_providers: any OpenAI-compatible endpoint (name, base_url, api_key, models)",
            "      Then restart the add-on. (Or run /login inside Pi to sign in interactively.)",
        ]
    else:
        lines += [f"  [ok] key for {b['env_var']}" for b in builtin]
        for c in custom:
            n = len(models["providers"].get(c["name"], {}).get("models", []))
            if n:
                lines.append(f"  [ok] provider {c['name']} ({n} models)")
            else:
                problems = True
                lines += [
                    f"  [!] provider {c['name']} has no models. Add a model id under custom_providers -> models",
                    "      (copy it from the provider's dashboard) and restart the add-on.",
                ]
    if provider:
        lines.append(f"  default provider: {provider}" + (f", model {model}" if model else ""))
    var = WEB_KEY_VAR.get(web_provider)  # None for key-less providers such as searxng
    if var is None or key_is_set(var):
        lines.append(f"  [ok] web search: {web_provider} (fetching a URL always asks first)")
    else:
        lines.append(f"  [ ] web search: needs a key. Add {var} under builtin_api_keys (optional).")
    lines.append(
        "  [ok] Home Assistant tools (hass-mcp)" if enable_mcp else "  [ ] Home Assistant tools are off (enable_mcp)"
    )
    lines += [
        "",
        "  Type  pi  to start."
        if not problems
        else "  Fix the items marked [!] above, then restart. You can still type  pi  to look around.",
        "",
    ]
    return "\n".join(lines) + "\n", problems


# --- main --------------------------------------------------------------------------------------


def usable_builtin_keys(opts: dict[str, Json]) -> list[BuiltinKey]:
    """`builtin_api_keys` entries that have both a name and a key (the options form allows empty ones)."""
    return [e for e in opts.get("builtin_api_keys") or [] if e.get("env_var") and e.get("api_key")]


def opt(opts: dict[str, Json], key: str, default: Json = "") -> Json:
    """Option value, treating a missing key and an explicit null the same (HA may send either)."""
    value = opts.get(key)
    return default if value is None else value


def main() -> None:
    """Render everything and print the exports. Raises Fatal for problems that must stop the add-on."""
    opts = read_json(OPTIONS)
    if not isinstance(opts, dict):
        raise Fatal(f"cannot read {OPTIONS}")

    provider = str(opt(opts, "default_provider"))
    model = str(opt(opts, "default_model"))
    enable_mcp = bool(opt(opts, "enable_mcp", True))
    restrict = bool(opt(opts, "restrict_sensitive_files", True))
    web_provider = str(opt(opts, "web_search_provider"))

    agent_dir = DATA_DIR / "pi-agent"
    exports: dict[str, str] = {"PI_CODING_AGENT_DIR": str(agent_dir)}

    seed_agent_dir(agent_dir)

    # Keys for Pi's built-in providers, e.g. MISTRAL_API_KEY (see Pi's providers.md).
    builtin = usable_builtin_keys(opts)
    for entry in builtin:
        name, key = entry["env_var"], entry["api_key"]
        # The name ends up in a shell `export` line, so it must be a plain identifier.
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise Fatal(f"invalid environment variable name: {name!r}")
        exports[name] = key
        info(f"Built-in provider key set: {name}")

    # models.json: regenerated every start; the user can layer /config/models.override.json on top.
    models = merge_override(build_models(opts), CONFIG_DIR / "models.override.json", "models.json")
    write_json(agent_dir / "models.json", models)

    if provider and provider not in models["providers"] and not builtin:
        warn(f"default_provider '{provider}' is neither a custom provider nor backed by a builtin_api_keys entry")
    if not opts.get("custom_providers") and not builtin:
        err("No provider configured. Add an entry under builtin_api_keys or custom_providers and restart.")

    # settings.json: only our defaults are touched; everything else Pi wrote stays.
    update_settings(agent_dir / "settings.json", provider, model)

    policy = merge_override(
        build_policy(restrict, agent_dir), CONFIG_DIR / "pi-permissions.override.json", "permission policy"
    )
    write_json(agent_dir / "pi-permissions.jsonc", policy)
    info(f"Permission policy written (restrict_sensitive_files={str(restrict).lower()})")

    # The extension's own switches are rewritten every start, outside the agent's data dir.
    write_json(PPS_DIR / "config.json", {"enabled": True, "yoloMode": False})
    exports["PI_PERMISSION_SYSTEM_CONFIG_PATH"] = str(PPS_DIR / "config.json")

    # MCP (pi-mcp-adapter reads ~/.config/mcp/mcp.json). /root is ephemeral, so the Supervisor token
    # is never persisted or backed up.
    mcp_path = ROOT_HOME / ".config/mcp/mcp.json"
    if enable_mcp:
        write_json(
            mcp_path,
            {
                "mcpServers": {
                    "homeassistant": {
                        "command": "hass-mcp",
                        "env": {"HA_URL": "http://supervisor/core", "HA_TOKEN": os.environ.get("SUPERVISOR_TOKEN", "")},
                    }
                }
            },
            mode=0o600,
        )
        info("MCP: Home Assistant (hass-mcp) configured")
    else:
        write_json(mcp_path, {"mcpServers": {}})
        info("MCP disabled")

    if web_provider:
        exports["WEB_SEARCH_PROVIDER"] = web_provider
        info(f"Web search provider: {web_provider}")

    motd, problems = build_motd(
        opts,
        models,
        provider,
        model,
        enable_mcp,
        lambda var: bool(exports.get(var) or os.environ.get(var)),
        web_provider or "brave",
    )
    (ROOT_HOME / ".pi-agent-motd").write_text(motd)
    if problems:
        warn(f"Setup incomplete; the terminal shows what to do (see {ROOT_HOME}/.pi-agent-motd)")

    # Values run.sh needs for the terminal.
    exports["PI_UI_FONT_SIZE"] = str(opt(opts, "terminal_font_size", 14))
    exports["PI_UI_THEME"] = str(opt(opts, "terminal_theme", "dark"))
    exports["PI_UI_SESSION_PERSIST"] = str(bool(opt(opts, "session_persistence", True))).lower()
    exports["PI_UI_WORKDIR"] = str(opt(opts, "working_directory", "/homeassistant"))

    # Values are shell-quoted: API keys may contain quotes, $ or backslashes.
    for name, value in exports.items():
        print(f"export {name}={shlex.quote(value)}")


if __name__ == "__main__":
    try:
        main()
    except Fatal as e:
        err(str(e))
        sys.exit(1)
