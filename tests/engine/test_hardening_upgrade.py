"""Upgrade lifecycle: safe local refresh and explicit host plugin updates."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import build_toy_repo, run_cli
from engine import HarnessError, read_jsonl


def _completed(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _plugin_tree(tmp_path, name="harness-plugin", version=None):
    root = tmp_path / name
    (root / "bin").mkdir(parents=True)
    (root / "engine").mkdir()
    (root / "bin" / "harness").write_text("#!/usr/bin/env python3\n")
    (root / "engine" / "__init__.py").write_text("")
    if version is not None:
        (root / ".codex-plugin").mkdir()
        (root / ".codex-plugin" / "plugin.json").write_text(json.dumps({
            "name": "harness", "version": version,
        }))
    return root


def test_local_upgrade_preserves_authored_state_and_does_not_ratify_dirty_source(
        tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    authored = [root / ".harness" / name for name in
                ("config.yaml", "backlog.jsonl", "decisions.jsonl")]
    before = {path: path.read_bytes() for path in authored}
    custom = root / "CUSTOM.txt"
    custom.write_text("user owned\n")
    registry_before = read_jsonl(root / ".harness" / "registry.jsonl")
    telemetry_before = next(r for r in registry_before if r["id"] == "telemetry")
    (root / "telemetry.py").write_text(
        (root / "telemetry.py").read_text() + "\ndef dirty_change():\n    pass\n")

    proc = run_cli("upgrade", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert custom.read_text() == "user owned\n"
    assert {path: path.read_bytes() for path in authored} == before
    telemetry_after = next(r for r in read_jsonl(
        root / ".harness" / "registry.jsonl") if r["id"] == "telemetry")
    assert telemetry_after["source_hash"] == telemetry_before["source_hash"]
    assert telemetry_after["signature_digest"] == telemetry_before["signature_digest"]
    assert out["registry"]["refreshed"] == []
    assert out["registry"]["skipped_dirty"] == ["telemetry"]
    assert "telemetry" in "\n".join(out["warnings"])


def test_local_upgrade_dry_run_reports_plan_without_writes(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    tracked = [root / ".harness" / "schema_version",
               root / ".harness" / "registry.jsonl",
               root / ".harness" / "config.yaml"]
    before = {path: path.read_bytes() for path in tracked}

    proc = run_cli("upgrade", "--dry-run", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["dry_run"] is True
    assert out["plan"] == [
        "migrate substrate schema",
        "install merge drivers",
        "refresh vendored engine",
        "refresh harness-generated workflow",
        "refresh harness-owned Claude settings",
        "refresh Harness-owned Codex hook commands",
        "canonicalize legacy G5 dependency overrides",
        "repair legacy graph provenance",
        "force-regenerate shadows",
        "refresh clean registry derivations",
        "validate substrate schema",
    ]
    assert {path: path.read_bytes() for path in tracked} == before


def test_claude_plugin_upgrade_uses_scope_and_delegates_to_new_engine(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    old_path = _plugin_tree(tmp_path, "old")
    new_path = _plugin_tree(tmp_path, "new")
    before = [{"id": "harness@team", "version": "1.0", "scope": "user",
               "installPath": str(old_path)}]
    after = [{"id": "harness@team", "version": "2.0", "scope": "user",
              "installPath": str(new_path)}]
    calls = []

    def run(command):
        calls.append(command)
        if command == ["claude", "plugin", "list", "--json"]:
            payload = before if calls.count(command) == 1 else after
            return _completed(json.dumps(payload))
        if command[:3] == ["claude", "plugin", "update"]:
            return _completed()
        if command[0] == upgrade.sys.executable:
            return _completed(json.dumps({"engine_version": "2.0"}))
        raise AssertionError(command)

    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(
        project, "claude", plugin_id="harness@team")
    assert calls[1] == ["claude", "plugin", "update", "harness@team",
                        "--scope", "user"]
    assert "--yes" not in calls[1]
    assert calls[-1] == [upgrade.sys.executable,
                         str(new_path / "bin" / "harness"),
                         "--root", str(project.resolve()), "upgrade"]
    assert report["plugin"]["from_version"] == "1.0"
    assert report["plugin"]["to_version"] == "2.0"
    assert report["project"]["engine_version"] == "2.0"
    assert report["restart_required"] is True


def test_codex_plugin_upgrade_updates_only_selected_marketplace(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    plugin_path = _plugin_tree(tmp_path, version="1.2")
    entry = {"pluginId": "harness@acme-tools", "name": "harness",
             "marketplaceName": "acme-tools", "version": "1.2",
             "source": {"source": "git", "path": str(plugin_path)},
             "marketplaceSource": {"sourceType": "git",
                                   "source": "https://example.invalid/acme"}}
    listing = {"installed": [entry, {
        "pluginId": "other@other-market", "name": "other",
        "marketplaceName": "other-market", "version": "9",
        "source": {"path": str(tmp_path / "other")}}], "available": []}
    calls = []

    def run(command):
        calls.append(command)
        if command == ["codex", "plugin", "list", "--json"]:
            return _completed(json.dumps(listing))
        if command[:3] in (["codex", "plugin", "marketplace"],
                           ["codex", "plugin", "add"]):
            return _completed("{}")
        if command[0] == upgrade.sys.executable:
            return _completed(json.dumps({"engine_version": "1.2"}))
        raise AssertionError(command)

    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(project, "codex")
    assert ["codex", "plugin", "marketplace", "upgrade", "acme-tools",
            "--json"] in calls
    assert ["codex", "plugin", "add", "harness@acme-tools", "--json"] in calls
    assert not any("other-market" in command for command in calls)
    assert report["plugin"]["id"] == "harness@acme-tools"
    assert report["version_check"]["matches"] is True


def test_plugin_upgrade_dry_run_lists_exact_commands_without_mutation(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    plugin_path = _plugin_tree(tmp_path)
    listing = [{"id": "harness@team", "version": "1", "scope": "project",
                "installPath": str(plugin_path)}]
    calls = []

    def run(command):
        calls.append(command)
        assert command == ["claude", "plugin", "list", "--json"]
        return _completed(json.dumps(listing))

    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(project, "claude", dry_run=True)
    assert calls == [["claude", "plugin", "list", "--json"]]
    assert report["commands"] == [
        ["claude", "plugin", "update", "harness@team", "--scope", "project"],
        [upgrade.sys.executable, str(plugin_path / "bin" / "harness"),
         "--root", str(project.resolve()), "upgrade"],
    ]
    assert report["dry_run"] is True
    assert "current installation" in report["delegate_note"]


def test_plugin_selection_rejects_ambiguity_and_unproven_install_path(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    ambiguous = [
        {"id": "harness@one", "scope": "user", "installPath": "/missing/one"},
        {"id": "harness@two", "scope": "project", "installPath": "/missing/two"},
    ]
    monkeypatch.setattr(
        upgrade, "_run_command",
        lambda command: _completed(json.dumps(ambiguous)))
    with pytest.raises(HarnessError, match="multiple Harness plugins"):
        upgrade.upgrade_installed_plugin(project, "claude")

    missing = [{"id": "harness@one", "version": "2", "scope": "user",
                "installPath": "/missing/one"}]
    responses = iter([_completed(json.dumps(missing)), _completed(),
                      _completed(json.dumps(missing))])
    response = lambda command: next(responses)
    monkeypatch.setattr(upgrade, "_run_command", response)
    monkeypatch.setattr(upgrade, "_run_host_command", response)
    with pytest.raises(HarnessError, match="cannot prove the installed engine"):
        upgrade.upgrade_installed_plugin(
            project, "claude", plugin_id="harness@one")


def test_claude_duplicate_id_requires_scope(tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    user_path = _plugin_tree(tmp_path, "user")
    project_path = _plugin_tree(tmp_path, "project-plugin")
    entries = [
        {"id": "harness@team", "version": "1", "scope": "user",
         "installPath": str(user_path)},
        {"id": "harness@team", "version": "1", "scope": "project",
         "installPath": str(project_path)},
    ]
    monkeypatch.setattr(
        upgrade, "_run_command",
        lambda command: _completed(json.dumps(entries)))
    with pytest.raises(HarnessError, match="and --scope"):
        upgrade.upgrade_installed_plugin(
            project, "claude", plugin_id="harness@team", dry_run=True)

    calls = []

    def run(command):
        calls.append(command)
        return _completed(json.dumps(entries))

    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(
        project, "claude", plugin_id="harness@team", scope="project",
        dry_run=True)
    assert report["commands"][0] == [
        "claude", "plugin", "update", "harness@team", "--scope", "project"]
    assert str(project_path / "bin" / "harness") in report["commands"][1]


def test_codex_discovers_manifest_verified_installed_cache(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    source = tmp_path / "marketplace-source"
    source.mkdir()
    codex_home = tmp_path / "codex-home"
    installed = _plugin_tree(
        codex_home / "plugins" / "cache" / "acme" / "harness",
        "2.0", version="2.0")
    entry = {"pluginId": "harness@acme", "name": "harness",
             "marketplaceName": "acme", "version": "2.0",
             "source": {"source": "local", "path": str(source)},
             "marketplaceSource": {"sourceType": "local",
                                   "source": str(source)}}
    listing = {"installed": [entry], "available": []}
    calls = []

    def run(command):
        calls.append(command)
        if command == ["codex", "plugin", "list", "--json"]:
            return _completed(json.dumps(listing))
        if command[0] == upgrade.sys.executable:
            return _completed(json.dumps({"engine_version": "2.0"}))
        return _completed("{}")

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(project, "codex")
    assert not any("marketplace" in command[2:] for command in calls)
    assert ["codex", "plugin", "add", "harness@acme", "--json"] in calls
    assert calls[-1][1] == str(installed / "bin" / "harness")
    assert report["plugin"]["install_path"] == str(installed.resolve())


def test_codex_rejects_source_path_without_matching_manifest(
        tmp_path, monkeypatch):
    from engine.plugin_install import prove_engine

    source = _plugin_tree(tmp_path, "marketplace-source")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "empty-codex-home"))
    entry = {"pluginId": "harness@acme", "name": "harness",
             "marketplaceName": "acme", "version": "2.0",
             "source": {"source": "local", "path": str(source)},
             "marketplaceSource": {"sourceType": "local",
                                   "source": str(source)}}
    with pytest.raises(HarnessError, match="no unique matching copy"):
        prove_engine("codex", entry)


def test_plugin_upgrade_reports_engine_manifest_version_discrepancy(
        tmp_path, monkeypatch):
    from engine.cli import upgrade

    project = build_toy_repo(tmp_path / "project")
    plugin_path = _plugin_tree(tmp_path, "claude")
    listing = [{"id": "harness@team", "version": "2.0", "scope": "user",
                "installPath": str(plugin_path)}]

    def run(command):
        if command == ["claude", "plugin", "list", "--json"]:
            return _completed(json.dumps(listing))
        if command[:3] == ["claude", "plugin", "update"]:
            return _completed("updated")
        return _completed(json.dumps({"engine_version": "1.9"}))

    monkeypatch.setattr(upgrade, "_run_command", run)
    monkeypatch.setattr(upgrade, "_run_host_command", run)
    report = upgrade.upgrade_installed_plugin(project, "claude")
    assert report["version_check"] == {
        "plugin": "2.0", "engine": "1.9", "matches": False,
        "warning": ("delegated engine version does not match the refreshed "
                    "plugin manifest version"),
    }


def test_mutating_host_runner_inherits_stdin_and_forwards_output_to_stderr(
        monkeypatch):
    from engine.cli import upgrade

    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, kwargs=kwargs)
        return _completed()

    monkeypatch.setattr(upgrade.subprocess, "run", run)
    upgrade._run_host_checked(["claude", "plugin", "update", "harness"])
    assert seen["kwargs"] == {
        "stdin": None,
        "stdout": upgrade.sys.stderr,
        "stderr": upgrade.sys.stderr,
        "text": True,
    }
    assert "capture_output" not in seen["kwargs"]


def test_mutating_host_runner_wraps_os_errors_with_command(monkeypatch):
    from engine.cli import upgrade

    def fail(command):
        raise OSError("not executable")

    monkeypatch.setattr(upgrade, "_run_host_command", fail)
    with pytest.raises(HarnessError, match="codex plugin add harness@team"):
        upgrade._run_host_checked(
            ["codex", "plugin", "add", "harness@team"])


def test_local_upgrade_repoints_only_harness_codex_hooks_to_vendored_adapter(
        tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    hooks = root / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(json.dumps({
        "user": {"theme": "dark"},
        "hooks": {
            "SessionStart": [{"hooks": [
                {"type": "command", "command":
                 'python3 "${HARNESS_DIR}/adapters/codex/adapter.py"'},
                {"type": "command", "command": "python3 user_hook.py"},
            ]}],
        },
    }))

    proc = run_cli("upgrade", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    updated = json.loads(hooks.read_text())
    commands = [h["command"] for h in
                updated["hooks"]["SessionStart"][0]["hooks"]]
    assert commands == [
        f'python3 "{root / ".harness/engine/adapters/codex/adapter.py"}"',
        "python3 user_hook.py",
    ]
    assert updated["user"] == {"theme": "dark"}
    assert out["codex_adapter"]["action"] == "refreshed"
    assert out["codex_adapter"]["retrust_required"] is True
    assert "alone does not enable" in out["codex_adapter"]["note"]


def test_local_upgrade_preserves_unrecognized_codex_hooks(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    hooks = root / ".codex" / "hooks.json"
    hooks.parent.mkdir()
    original = {"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python3 custom/adapter.py"},
        {"type": "command", "command":
         "python3 custom.py # harness adapters/codex/adapter.py"},
    ]}]}}
    hooks.write_text(json.dumps(original))

    proc = run_cli("upgrade", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(hooks.read_text()) == original
    assert json.loads(proc.stdout)["codex_adapter"]["action"] == "unchanged"
def test_upgrade_never_replaces_newer_vendored_engine(tmp_path):
    project = build_toy_repo(tmp_path / "project")
    assert run_cli("upgrade", root=project).returncode == 0
    version = project / ".harness/engine/VERSION"
    version.write_text("999.0.0\n")
    binary = project / ".harness/engine/bin/harness"
    before = binary.read_bytes()
    proc = run_cli("upgrade", root=project)
    assert proc.returncode != 0 and "downgrade" in proc.stderr
    assert version.read_text() == "999.0.0\n" and binary.read_bytes() == before


def test_outdated_marketplace_cannot_delegate_an_older_engine(tmp_path, monkeypatch):
    from engine.cli import upgrade
    project = build_toy_repo(tmp_path / "project")
    entry = {"id": "harness@team", "scope": "user", "version": "0.0.1"}
    monkeypatch.setattr(upgrade, "_command_json", lambda _cmd: [entry])
    monkeypatch.setattr(upgrade, "_run_host_checked", lambda _cmd: _completed())
    with pytest.raises(HarnessError, match="downgrade"):
        upgrade.upgrade_installed_plugin(project, "claude")
