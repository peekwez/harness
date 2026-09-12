"""Safe project migrations and explicit Claude/Codex plugin upgrades."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from engine import (ENGINE_VERSION, SCHEMA_VERSION, HarnessError, load_config,
                    sha256_file)
from engine.cli.common import _install_merge_drivers, _print
from engine.cli.init import (_vendor_engine, _write_autonomy_settings,
                             _write_workflow)
from engine.plugin_install import (entry_id, installed_entries,
                                   plugin_commands, prove_engine,
                                   select_plugin)


PROJECT_PLAN = [
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


def _require_substrate(root: Path) -> None:
    if not (root / ".harness").is_dir():
        raise HarnessError(
            f"{root / '.harness'} does not exist — nothing to upgrade; run "
            "`harness init` to scaffold a substrate first")


def _schema_version(root: Path) -> int:
    from engine.migrate import current_version
    try:
        return current_version(root)
    except (OSError, ValueError) as exc:
        raise HarnessError(
            f"{root / '.harness' / 'schema_version'} is invalid: {exc}") from exc


def _clean_registry_entries(root: Path) -> tuple[list[str], list[str], list[str]]:
    """Snapshot which BUILT entries were clean before upgrade writes.

    Registry hashes are provenance.  A later forced extraction must not turn
    an unrelated, pre-existing source edit into an approved registry update.
    """
    from engine.registry import load_registry

    clean, dirty, warnings = [], [], []
    for entry in load_registry(root):
        if entry.get("status") != "built":
            continue
        entry_id = entry["id"]
        source = entry.get("source")
        recorded = entry.get("source_hash")
        path = root / source if source else None
        if (path is not None and path.is_file() and recorded
                and sha256_file(path) == recorded):
            clean.append(entry_id)
            continue
        dirty.append(entry_id)
        warnings.append(
            f"registry {entry_id}: source differs from its recorded hash "
            "(or is missing); derivation was not refreshed or ratified")
    return clean, dirty, warnings


def _refresh_claude_settings(root: Path, config: dict) -> dict:
    report = {}
    for local, key in ((False, "settings"), (True, "settings_local")):
        name = "settings.local.json" if local else "settings.json"
        path = root / ".claude" / name
        if not path.exists():
            report[key] = {"path": str(path.relative_to(root)),
                           "action": "missing"}
        elif "harness autonomy profile" not in path.read_text():
            report[key] = {"path": str(path.relative_to(root)),
                           "action": "kept",
                           "note": "not a Harness-owned profile"}
        else:
            _write_autonomy_settings(root, quiet=True, local=local,
                                     config=config)
            report[key] = {"path": str(path.relative_to(root)),
                           "action": "refreshed"}
    return report


def _is_harness_adapter_command(command: object) -> bool:
    if not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) != 2:
        return False
    interpreter = Path(words[0]).name.casefold()
    script = words[1].replace("\\", "/")
    return (interpreter in ("python", "python3")
            and script.endswith("/adapters/codex/adapter.py")
            and "harness" in script.casefold())


def _refresh_codex_hooks(root: Path, *, dry_run: bool = False) -> dict:
    """Point only recognizable Harness commands at the vendored adapter."""
    path = root / ".codex" / "hooks.json"
    report = {
        "path": str(path.relative_to(root)),
        "retrust_required": True,
        "note": ("Codex must install/trust this project's hooks after the "
                 "upgrade; installing the plugin alone does not enable "
                 "project enforcement."),
    }
    if not path.exists():
        report["action"] = "missing"
        return report
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        report.update(action="kept", warning=f"could not read hooks: {exc}")
        return report

    changed = 0
    adapter_path = (root / ".harness" / "engine" / "adapters" / "codex" /
                    "adapter.py")
    adapter_command = f'python3 "{adapter_path}"'

    def visit(value):
        nonlocal changed
        if isinstance(value, dict):
            if (value.get("type") == "command"
                    and _is_harness_adapter_command(value.get("command"))
                    and value["command"] != adapter_command):
                value["command"] = adapter_command
                changed += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if changed and not dry_run:
        path.write_text(json.dumps(payload, indent=2) + "\n")
    report["action"] = ("would_refresh" if dry_run else "refreshed") \
        if changed else "unchanged"
    report["commands"] = changed
    return report


def upgrade_project(root, *, dry_run: bool = False) -> dict:
    """Upgrade one substrate without rewriting authored project state."""
    root = Path(root).resolve()
    _require_substrate(root)
    from engine.migrate import MIGRATIONS, migrate
    from engine.overrides import repair_legacy_overrides

    # Even a dry run performs the schema preflight, but nothing that writes.
    version = _schema_version(root)
    if dry_run:
        if version > SCHEMA_VERSION:
            raise HarnessError(
                f"substrate schema {version} is newer than engine "
                f"{SCHEMA_VERSION}; upgrade the plugin")
        missing = [v for v in range(version, SCHEMA_VERSION)
                   if v not in MIGRATIONS]
        if missing:
            raise HarnessError(
                f"no migration path from schema {missing[0]} to "
                f"{SCHEMA_VERSION} (fail closed)")
        return {"dry_run": True, "plan": PROJECT_PLAN,
                "schema": {"from": version, "to": SCHEMA_VERSION,
                           "would_apply": list(
                               range(version + 1, SCHEMA_VERSION + 1))},
                "engine_version": ENGINE_VERSION,
                "legacy_overrides": repair_legacy_overrides(root, dry_run=True),
                "codex_adapter": _refresh_codex_hooks(root, dry_run=True)}

    # Migration is deliberately the first write.  New code must never read
    # old substrate rows as though they already had the current schema.
    schema = migrate(root)
    config = load_config(root)
    clean, dirty, warnings = _clean_registry_entries(root)

    _install_merge_drivers(root)
    vendored = _vendor_engine(root)
    workflow = _write_workflow(root)
    claude = _refresh_claude_settings(root, config)
    codex = _refresh_codex_hooks(root)
    if workflow.get("note"):
        warnings.append(workflow["note"])
    warnings.extend(v["note"] for v in claude.values()
                    if v.get("action") == "kept" and v.get("note"))
    if codex.get("warning"):
        warnings.append(codex["warning"])
    if codex.get("action") in ("missing", "kept"):
        warnings.append(codex["note"])

    from engine.graph import repair_legacy_provenance
    legacy_overrides = repair_legacy_overrides(root)
    graph = repair_legacy_provenance(root)
    from engine.extractor.engine import extract_all
    shadows = extract_all(root, config, force=True)
    warnings.extend(f["message"] for f in shadows.get("findings", []))

    from engine.registry import refresh_built
    refreshed = []
    for entry_id in clean:
        refresh_built(root, entry_id)
        refreshed.append(entry_id)

    from engine.schema import validate_substrate
    problems = validate_substrate(root, config=config)
    if problems:
        raise HarnessError("upgraded substrate failed validation: "
                           + "; ".join(problems))
    return {
        "schema": schema,
        "vendored_engine": vendored,
        "workflow": workflow,
        "claude": claude,
        "codex_adapter": codex,
        "graph": graph,
        "legacy_overrides": legacy_overrides,
        "shadows": shadows,
        "registry": {"refreshed": refreshed, "skipped_dirty": dirty},
        "schema_validation": {"problems": [], "passed": True},
        "warnings": warnings,
        "engine_version": ENGINE_VERSION,
    }


def _run_command(command):
    return subprocess.run(command, capture_output=True, text=True)


def _run_host_command(command):
    """Run an interactive host mutation without contaminating JSON stdout."""
    return subprocess.run(command, stdin=None, stdout=sys.stderr,
                          stderr=sys.stderr, text=True)


def _run_checked(command):
    try:
        proc = _run_command(command)
    except OSError as exc:
        raise HarnessError(
            f"cannot run {' '.join(command)}: {exc}") from exc
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or "no diagnostic").strip()
        raise HarnessError(f"command failed ({' '.join(command)}): {detail}")
    return proc


def _run_host_checked(command):
    try:
        proc = _run_host_command(command)
    except OSError as exc:
        raise HarnessError(
            f"cannot run {' '.join(command)}: {exc}") from exc
    if proc.returncode:
        raise HarnessError(
            f"host command failed with exit {proc.returncode} "
            f"({' '.join(command)})")
    return proc


def _command_json(command):
    proc = _run_checked(command)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HarnessError(
            f"command returned invalid JSON ({' '.join(command)}): {exc}") from exc


def upgrade_installed_plugin(root, host: str, *, plugin_id=None,
                             scope=None, dry_run: bool = False) -> dict:
    """Update one installed Harness plugin, then delegate project upgrade."""
    root = Path(root).resolve()
    _require_substrate(root)
    # Parse the project's schema marker before any host command can update an
    # installation.  Compatibility is decided by the newly installed engine,
    # so an older/newer numeric version is intentionally delegated to it.
    _schema_version(root)
    if host not in ("claude", "codex"):
        raise HarnessError("--host must be claude or codex")
    list_command = [host, "plugin", "list", "--json"]
    before = select_plugin(
        host, installed_entries(host, _command_json(list_command)), plugin_id,
        scope)
    selected_id = entry_id(host, before)
    commands = plugin_commands(host, before)

    if dry_run:
        _plugin_root, binary = prove_engine(host, before)
        delegate = [sys.executable, str(binary), "--root", str(root),
                    "upgrade"]
        return {
            "dry_run": True,
            "host": host,
            "plugin": {"id": selected_id,
                       "from_version": before.get("version"),
                       "scope": before.get("scope") if host == "claude" else None},
            "commands": commands + [delegate],
            "delegate_note": (
                "The displayed engine path is the current installation; a "
                "real upgrade re-lists the plugin and delegates through the "
                "newly installed path."),
            "restart_required": True,
            "restart_note": "Restart the host or open a new thread after upgrade.",
        }

    for command in commands:
        # Claude's update command has no JSON mode.  Codex does, but its
        # output is not needed here; the authoritative result is the fresh
        # plugin listing below.
        _run_host_checked(command)
    after = select_plugin(
        host, installed_entries(host, _command_json(list_command)), selected_id,
        before.get("scope") if host == "claude" else None)
    from engine.plugin_install import prevent_downgrade
    prevent_downgrade(after.get("version"), ENGINE_VERSION, "project upgrade engine")
    plugin_root, binary = prove_engine(host, after)
    delegate = [sys.executable, str(binary), "--root", str(root), "upgrade"]
    project = _command_json(delegate)
    plugin_version = after.get("version")
    engine_version = project.get("engine_version")
    versions_match = (
        isinstance(plugin_version, str) and isinstance(engine_version, str)
        and (plugin_version == engine_version
             or plugin_version.startswith(engine_version + "-")
             or plugin_version.startswith(engine_version + "+")))
    version_check = {"plugin": plugin_version, "engine": engine_version,
                     "matches": versions_match}
    if not versions_match:
        version_check["warning"] = (
            "delegated engine version does not match the refreshed plugin "
            "manifest version")
    return {
        "host": host,
        "plugin": {"id": selected_id,
                   "from_version": before.get("version"),
                   "to_version": after.get("version"),
                   "scope": after.get("scope") if host == "claude" else None,
                   "marketplace_source": after.get("marketplaceSource"),
                   "install_path": str(plugin_root)},
        "commands": commands + [delegate],
        "project": project,
        "engine_version": engine_version,
        "version_check": version_check,
        "restart_required": True,
        "restart_note": "Restart the host or open a new thread to load the upgraded plugin.",
        "enforcement_note": (
            "Plugin installation alone does not enable Codex project hooks; "
            "install/trust the project's .codex/hooks.json after reviewing it."
            if host == "codex" else None),
    }


def cmd_upgrade(args):
    root = (Path(args.root).resolve() if getattr(args, "root", None)
            else Path.cwd().resolve())
    plugin = getattr(args, "plugin", False)
    host = getattr(args, "host", None)
    if plugin:
        if not host:
            raise HarnessError("--plugin requires --host claude|codex")
        report = upgrade_installed_plugin(
            root, host, plugin_id=getattr(args, "plugin_id", None),
            scope=getattr(args, "scope", None),
            dry_run=getattr(args, "dry_run", False))
    else:
        if host or getattr(args, "plugin_id", None) or getattr(args, "scope", None):
            raise HarnessError("--host, --plugin-id and --scope require --plugin")
        report = upgrade_project(root, dry_run=getattr(args, "dry_run", False))
    _print(report)
    return 0
