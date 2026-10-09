"""Tests for render_config.py. Run: uv run --with pytest pytest pi-agent/tests"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1] / "rootfs/usr/local/lib/pi-agent"
sys.path.insert(0, str(LIB))
import render_config as rc  # noqa: E402


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if isinstance(text, str) else json.dumps(text))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake /data, /config, /root, seed and defaults tree; module globals point at it."""
    seed, defaults = tmp_path / "seed", tmp_path / "defaults"
    for pkg, ver in (
        ("pi-permission-system", "0.8.0"),
        ("pi-mcp-adapter", "5.1.0"),
        ("@juicesharp/rpiv-web-tools", "2.12.0"),
    ):
        write(seed / "npm/node_modules" / pkg / "package.json", {"version": ver})
    write(
        seed / "settings.json",
        {
            "packages": [
                "npm:pi-permission-system@0.8.0",
                "npm:pi-mcp-adapter@5.1.0",
                "npm:@juicesharp/rpiv-web-tools@2.12.0",
            ]
        },
    )
    write(defaults / "AGENTS.md", "DEFAULT AGENTS")
    write(defaults / "skills/home-assistant-config/SKILL.md", "SKILL")
    paths = dict(
        OPTIONS=tmp_path / "options.json",
        DATA_DIR=tmp_path / "data",
        CONFIG_DIR=tmp_path / "config",
        SEED_DIR=seed,
        DEFAULTS_DIR=defaults,
        ROOT_HOME=tmp_path / "root",
        PPS_DIR=tmp_path / "pps",
    )
    for k, v in paths.items():
        monkeypatch.setattr(rc, k, v)
    (tmp_path / "config").mkdir()
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    for var in rc.WEB_KEY_VAR.values():
        monkeypatch.delenv(var, raising=False)
    # No test may touch the network: provider discovery is stubbed unless a test overrides it.
    monkeypatch.setattr(rc, "discover_models", lambda url, key: ([], "000", "offline"))
    return tmp_path


def run_main(env, opts, capsys):
    write(env / "options.json", opts)
    rc.main()
    out = capsys.readouterr()
    exports = {}
    for line in out.out.splitlines():
        name, _, value = line.removeprefix("export ").partition("=")
        exports[name] = subprocess.run(["bash", "-c", f"printf %s {value}"], capture_output=True, text=True).stdout
    return exports, out.err


# --- helpers -----------------------------------------------------------------------------------


def test_deep_merge_objects_recurse_everything_else_replaces():
    base = {"a": {"x": 1, "y": 2}, "l": [1, 2], "s": "old"}
    merged = rc.deep_merge(base, {"a": {"y": 3, "z": 4}, "l": [9], "s": {"now": "obj"}})
    assert merged == {"a": {"x": 1, "y": 3, "z": 4}, "l": [9], "s": {"now": "obj"}}
    assert base["a"] == {"x": 1, "y": 2}  # input untouched


def test_merge_override_ignores_missing_and_invalid(env, capsys):
    data = {"k": 1}
    assert rc.merge_override(data, env / "nope.json", "x") == data
    write(env / "bad.json", "[1, 2]")
    assert rc.merge_override(data, env / "bad.json", "x") == data
    assert "not a valid JSON object" in capsys.readouterr().err
    write(env / "ok.json", {"k": 2, "n": 3})
    assert rc.merge_override(data, env / "ok.json", "x") == {"k": 2, "n": 3}


def test_write_json_is_atomic_and_sets_mode(tmp_path):
    p = tmp_path / "sub/f.json"
    rc.write_json(p, {"a": 1}, mode=0o600)
    assert json.loads(p.read_text()) == {"a": 1}
    assert (p.stat().st_mode & 0o777) == 0o600
    assert not list(tmp_path.rglob("*.tmp"))


def test_copy_no_clobber_keeps_existing_files(tmp_path):
    write(tmp_path / "src/a.txt", "new")
    write(tmp_path / "src/b.txt", "new")
    write(tmp_path / "dst/a.txt", "mine")
    rc.copy_no_clobber(tmp_path / "src", tmp_path / "dst")
    assert (tmp_path / "dst/a.txt").read_text() == "mine"
    assert (tmp_path / "dst/b.txt").read_text() == "new"


def test_copy_overwrite_replaces_files_and_symlinks(tmp_path):
    """Regression: shutil.copytree crashed on existing symlinks during an upgrade."""
    (tmp_path / "src/bin").mkdir(parents=True)
    write(tmp_path / "src/real.js", "v2")
    os.symlink("real.js", tmp_path / "src/bin/tool")
    (tmp_path / "dst/bin").mkdir(parents=True)
    write(tmp_path / "dst/real.js", "v1")
    os.symlink("old-target", tmp_path / "dst/bin/tool")
    rc.copy_overwrite(tmp_path / "src", tmp_path / "dst")
    assert (tmp_path / "dst/real.js").read_text() == "v2"
    assert os.readlink(tmp_path / "dst/bin/tool") == "real.js"


def test_copies_never_follow_destination_directory_symlinks(tmp_path):
    """A symlinked directory in the destination must not let seed files land outside it."""
    write(tmp_path / "src/skills/a.txt", "seed")
    outside = tmp_path / "outside"
    outside.mkdir()
    for copy in (rc.copy_no_clobber, rc.copy_overwrite):
        dst = tmp_path / f"dst-{copy.__name__}"
        dst.mkdir()
        os.symlink(outside, dst / "skills")
        copy(tmp_path / "src", dst)
        assert list(outside.iterdir()) == []


# --- seeding -----------------------------------------------------------------------------------


def test_seed_first_run_installs_everything(env):
    agent = env / "data/pi-agent"
    rc.seed_agent_dir(agent)
    assert (agent / "npm/node_modules/pi-permission-system").is_dir()
    assert (agent / "AGENTS.md").read_text() == "DEFAULT AGENTS"
    assert (agent / "skills/home-assistant-config/SKILL.md").read_text() == "SKILL"


def test_seed_never_overwrites_user_files(env):
    agent = env / "data/pi-agent"
    write(agent / "AGENTS.md", "MINE")
    write(agent / "skills/home-assistant-config/SKILL.md", "MY SKILL")
    rc.seed_agent_dir(agent)
    assert (agent / "AGENTS.md").read_text() == "MINE"
    assert (agent / "skills/home-assistant-config/SKILL.md").read_text() == "MY SKILL"


def test_seed_updates_stale_extension(env):
    agent = env / "data/pi-agent"
    rc.seed_agent_dir(agent)
    write(agent / "npm/node_modules/pi-permission-system/package.json", {"version": "0.1.0"})
    rc.seed_agent_dir(agent)
    assert rc.package_version(agent, "pi-permission-system") == "0.8.0"


def test_seed_fails_closed_without_permission_extension(env, tmp_path):
    (env / "seed/npm/node_modules/pi-permission-system/package.json").unlink()
    with pytest.raises(rc.Fatal):
        rc.seed_agent_dir(env / "data/pi-agent")


# --- providers ---------------------------------------------------------------------------------


def provider(**kw):
    return {"name": "aki", "base_url": "https://x.example/v1/", "api_key": "k", **kw}


def test_build_models_uses_listed_models_and_dedupes_in_order():
    out = rc.build_models(
        {"custom_providers": [provider(models=["b", "a", "b", "", None])]},
        discover=lambda *a: pytest.fail("must not discover"),
    )
    assert [m["id"] for m in out["providers"]["aki"]["models"]] == ["b", "a"]


def test_build_models_never_embeds_the_api_key():
    out = rc.build_models({"custom_providers": [provider(api_key="s3cret", models=["m"])]})
    text = json.dumps(out)
    assert "s3cret" not in text
    assert ".custom_providers[0].api_key" in out["providers"]["aki"]["apiKey"]


def test_build_models_discovers_when_no_models_given():
    out = rc.build_models({"custom_providers": [provider()]}, discover=lambda url, key: (["x", "y"], "200", ""))
    assert [m["id"] for m in out["providers"]["aki"]["models"]] == ["x", "y"]


def test_build_models_zero_models_logs_error(capsys):
    out = rc.build_models({"custom_providers": [provider()]}, discover=lambda *a: ([], "401", "nope"))
    assert out["providers"]["aki"]["models"] == []
    err = capsys.readouterr().err
    assert "HTTP 401" in err and "No models available" in err


def test_build_models_indexes_apikey_per_provider():
    out = rc.build_models({"custom_providers": [provider(models=["m"]), provider(name="b", models=["m"])]})
    assert ".custom_providers[1].api_key" in out["providers"]["b"]["apiKey"]


def test_discover_models_parses_and_survives_garbage(monkeypatch):
    class Resp:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(rc._OPENER, "open", lambda *a, **k: Resp(b'{"data":[{"id":"a"},{"id":null},{}, "x"]}'))
    assert rc.discover_models("https://h/v1", "k")[0] == ["a"]
    monkeypatch.setattr(rc._OPENER, "open", lambda *a, **k: Resp(b"<html>"))
    assert rc.discover_models("https://h/v1", "k")[0] == []

    def boom(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(rc._OPENER, "open", boom)
    ids, code, body = rc.discover_models("https://h/v1", "k")
    assert (ids, code) == ([], "000") and "refused" in body


def test_discover_models_does_not_leak_the_key_on_redirect():
    """Regression: urllib forwards Authorization across redirects; the old curl call never followed them."""
    import http.server
    import threading

    seen: list[str | None] = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"stolen"}]}')

        def log_message(self, format, *args): ...

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/v1/models")
            self.end_headers()

        def log_message(self, format, *args): ...

    redirector = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    servers = (target, redirector)
    for srv in servers:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ids, code, _ = rc.discover_models(f"http://127.0.0.1:{redirector.server_port}/v1", "SECRETKEY")
    finally:
        for srv in servers:
            srv.shutdown()
            srv.server_close()
    assert ids == [] and code == "302"
    assert seen == []  # the redirect target never received a request


# --- policy ------------------------------------------------------------------------------------


def test_policy_restricted_denies_secret_reads_and_all_writes():
    p = rc.build_policy(True, Path("/data/pi-agent"))
    assert p["tools"]["read:*secrets.yaml*"] == "deny"
    assert p["tools"]["grep:/homeassistant/.storage/*"] == "deny"
    assert p["tools"]["write:*secrets.yaml*"] == "deny"
    assert p["tools"]["write:/data/pi-agent/pi-permissions.jsonc"] == "deny"
    assert p["tools"]["write"] == "ask" and p["tools"]["web_fetch"] == "ask" and p["tools"]["web_search"] == "allow"
    assert p["bash"]["sudo *"] == "deny" and p["bash"]["*secrets.yaml*"] == "deny"


def test_policy_unrestricted_still_blocks_writes_and_control_files():
    p = rc.build_policy(False, Path("/data/pi-agent"))
    assert "read:*secrets.yaml*" not in p["tools"]
    assert "*secrets.yaml*" not in p["bash"]
    assert p["tools"]["write:*secrets.yaml*"] == "deny"
    assert p["special"]["external_directory:/data/pi-agent/pi-permissions.jsonc"] == "deny"


def test_policy_denies_come_after_broad_allows():
    """Last matching rule wins, so a deny must never precede the broad rule it should override."""
    p = rc.build_policy(True, Path("/data/pi-agent"))
    keys = list(p["tools"])
    assert keys.index("read") < keys.index("read:*secrets.yaml*")
    assert next(iter(p["bash"])) == "*"
    assert list(p["special"]).index("external_directory:/homeassistant/*") < list(p["special"]).index(
        "external_directory:/homeassistant/.storage/*"
    )


def test_policy_addon_configs_ask_but_ha_config_free():
    sp = rc.build_policy(True, Path("/data/pi-agent"))["special"]
    assert sp["external_directory:/addon_configs/*"] == "ask"
    assert sp["external_directory:/homeassistant/*"] == "allow"
    # the secrets deny must still come after the broad ask
    assert list(sp).index("external_directory:/addon_configs/*") < list(sp).index(
        "external_directory:/data/options.json"
    )


def test_policy_hass_mcp_reads_allowed_writes_ask():
    m = rc.build_policy(True, Path("/x"))["mcp"]
    assert m["*"] == "ask" and m["homeassistant:get_*"] == "allow"


# --- settings ----------------------------------------------------------------------------------


def test_update_settings_keeps_user_keys_and_replaces_stale_pins(env):
    s = env / "settings.json"
    write(
        s,
        {
            "theme": "mine",
            "extensions": ["x"],
            "defaultProvider": "old",
            "packages": ["npm:pi-permission-system@0.1.0", "npm:user-pkg@1.0.0"],
        },
    )
    rc.update_settings(s, "mistral", "")
    data = json.loads(s.read_text())
    assert data["theme"] == "mine"
    assert data["defaultProvider"] == "mistral" and "defaultModel" not in data
    assert data["extensions"] == ["-builtin:mcp", "x"]
    assert "npm:pi-permission-system@0.8.0" in data["packages"]
    assert "npm:pi-permission-system@0.1.0" not in data["packages"]
    assert "npm:user-pkg@1.0.0" in data["packages"]


def test_update_settings_tolerates_non_string_entries(env):
    s = env / "settings.json"
    write(s, {"extensions": ["x", {"odd": 1}], "packages": [{"source": "npm:mine"}, "npm:pi-mcp-adapter@1.0.0"]})
    rc.update_settings(s, "", "")
    data = json.loads(s.read_text())
    assert data["extensions"] == ["-builtin:mcp", "x"]
    assert {"source": "npm:mine"} in data["packages"]
    assert "npm:pi-mcp-adapter@5.1.0" in data["packages"] and "npm:pi-mcp-adapter@1.0.0" not in data["packages"]


def test_update_settings_recovers_from_corrupt_file(env):
    s = env / "settings.json"
    write(s, "{not json")
    rc.update_settings(s, "", "")
    assert "-builtin:mcp" in json.loads(s.read_text())["extensions"]


# --- MOTD --------------------------------------------------------------------------------------


def test_motd_nothing_configured_explains_what_to_do():
    text, problems = rc.build_motd({}, {"providers": {}}, "", "", True, lambda v: False, "brave")
    assert problems and "No model provider is set up yet" in text and "builtin_api_keys" in text


def test_motd_all_good_and_web_key_hint():
    opts = {"builtin_api_keys": [{"env_var": "MISTRAL_API_KEY", "api_key": "k"}]}
    text, problems = rc.build_motd(opts, {"providers": {}}, "mistral", "m", True, lambda v: False, "brave")
    assert not problems and "key for MISTRAL_API_KEY" in text and "BRAVE_SEARCH_API_KEY" in text
    text, _ = rc.build_motd(opts, {"providers": {}}, "", "", False, lambda v: True, "brave")
    assert "[ok] web search" in text and "Home Assistant tools are off" in text


def test_motd_ignores_incomplete_builtin_entries():
    opts = {"builtin_api_keys": [{"env_var": "A_API_KEY", "api_key": ""}, {"env_var": "", "api_key": "k"}]}
    text, problems = rc.build_motd(opts, {"providers": {}}, "", "", True, lambda v: False, "brave")
    assert problems and "[ok] key for" not in text and "No model provider is set up yet" in text


def test_main_incomplete_builtin_entry_reports_no_provider(env, capsys):
    _, err = run_main(env, {"builtin_api_keys": [{"env_var": "A_API_KEY", "api_key": ""}]}, capsys)
    assert "No provider configured" in err
    assert "[ok] key for" not in (env / "root/.pi-agent-motd").read_text()


def test_motd_flags_provider_without_models():
    opts = {"custom_providers": [{"name": "aki"}]}
    text, problems = rc.build_motd(
        opts, {"providers": {"aki": {"models": []}}}, "", "", True, lambda v: False, "searxng"
    )
    assert problems and "provider aki has no models" in text
    assert "[ok] web search: searxng" in text  # providers without a key never nag


# --- main() end to end -------------------------------------------------------------------------


def test_main_nothing_configured_still_starts_and_explains(env, capsys):
    exports, err = run_main(env, {}, capsys)
    assert exports["PI_UI_WORKDIR"] == "/homeassistant" and exports["PI_UI_THEME"] == "dark"
    assert exports["PI_UI_SESSION_PERSIST"] == "true"
    assert "No provider configured" in err
    assert "No model provider is set up yet" in (env / "root/.pi-agent-motd").read_text()
    assert json.loads((env / "pps/config.json").read_text()) == {"enabled": True, "yoloMode": False}


def test_main_exports_survive_shell_eval_with_hostile_values(env, capsys):
    key = "a\\b $(touch /tmp/pwned) 'q' \"d\" `x`"
    exports, _ = run_main(env, {"builtin_api_keys": [{"env_var": "MISTRAL_API_KEY", "api_key": key}]}, capsys)
    assert exports["MISTRAL_API_KEY"] == key


def test_main_rejects_bad_env_var_names(env, capsys):
    with pytest.raises(rc.Fatal):
        run_main(env, {"builtin_api_keys": [{"env_var": "X; rm -rf /", "api_key": "k"}]}, capsys)


def test_main_skips_incomplete_builtin_entries(env, capsys):
    exports, _ = run_main(
        env, {"builtin_api_keys": [{"env_var": "A_API_KEY", "api_key": ""}, {"env_var": "", "api_key": "k"}]}, capsys
    )
    assert "A_API_KEY" not in exports


def test_main_mcp_token_file_private_and_removed_when_disabled(env, capsys):
    run_main(env, {"enable_mcp": True}, capsys)
    mcp = env / "root/.config/mcp/mcp.json"
    assert (mcp.stat().st_mode & 0o777) == 0o600
    assert json.loads(mcp.read_text())["mcpServers"]["homeassistant"]["env"]["HA_TOKEN"] == "sup-token"
    run_main(env, {"enable_mcp": False}, capsys)
    assert json.loads(mcp.read_text()) == {"mcpServers": {}}
    assert "sup-token" not in mcp.read_text()


def test_main_api_key_not_written_to_models_json(env, capsys):
    run_main(env, {"custom_providers": [provider(api_key="TOPSECRET", models=["m"])]}, capsys)
    assert "TOPSECRET" not in (env / "data/pi-agent/models.json").read_text()


def test_main_override_files_merge_into_generated_config(env, capsys):
    write(env / "config/models.override.json", {"providers": {"aki": {"models": [{"id": "extra"}]}}})
    write(env / "config/pi-permissions.override.json", {"tools": {"web_fetch": "allow"}})
    run_main(env, {"custom_providers": [provider(models=["m"])]}, capsys)
    agent = env / "data/pi-agent"
    assert json.loads((agent / "models.json").read_text())["providers"]["aki"]["models"] == [{"id": "extra"}]
    assert json.loads((agent / "pi-permissions.jsonc").read_text())["tools"]["web_fetch"] == "allow"


def test_main_restart_is_idempotent_and_keeps_user_settings(env, capsys):
    opts = {"default_provider": "aki", "default_model": "m", "custom_providers": [provider(models=["m"])]}
    run_main(env, opts, capsys)
    agent = env / "data/pi-agent"
    s = json.loads((agent / "settings.json").read_text())
    s["lastChangelogVersion"] = "9"
    (agent / "settings.json").write_text(json.dumps(s))
    first = (agent / "pi-permissions.jsonc").read_text()
    run_main(env, opts, capsys)
    assert (agent / "pi-permissions.jsonc").read_text() == first
    after = json.loads((agent / "settings.json").read_text())
    assert after["lastChangelogVersion"] == "9" and after["defaultProvider"] == "aki" and after["defaultModel"] == "m"
    assert len(after["packages"]) == len(set(after["packages"]))


def test_main_web_provider_export(env, capsys):
    exports, _ = run_main(env, {"web_search_provider": "tavily"}, capsys)
    assert exports["WEB_SEARCH_PROVIDER"] == "tavily"
    exports, _ = run_main(env, {}, capsys)
    assert "WEB_SEARCH_PROVIDER" not in exports


def test_main_override_breaking_providers_is_fatal(env, capsys):
    write(env / "config/models.override.json", {"providers": None})
    with pytest.raises(rc.Fatal):
        run_main(env, {}, capsys)


def test_write_json_secret_file_is_never_world_readable(tmp_path):
    old = os.umask(0)  # worst case: nothing masked
    try:
        rc.write_json(tmp_path / "s.json", {"t": 1}, mode=0o600)
    finally:
        os.umask(old)
    assert (tmp_path / "s.json").stat().st_mode & 0o777 == 0o600


def test_main_unreadable_options_is_fatal(env):
    with pytest.raises(rc.Fatal):
        rc.main()  # options.json does not exist


def test_cli_exit_code_is_1_on_fatal(tmp_path):
    r = subprocess.run(
        [sys.executable, str(LIB / "render_config.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "OPTIONS_FILE": str(tmp_path / "missing.json")},
    )
    assert r.returncode == 1 and "[ERROR]" in r.stderr and r.stdout == ""
