"""Safe project migrations and explicit Claude/Codex plugin upgrades."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

from engine import (ENGINE_VERSION, SCHEMA_VERSION, HarnessError, sha256_file)
from engine.cli.common import PLUGIN_ROOT, _install_merge_drivers, _print
from engine.cli.init import (VENDOR_DIR, _vendor_engine, _write_autonomy_settings,
                             _write_workflow)
from engine.plugin_install import (entry_id, installed_entries,
                                   plugin_commands, prove_engine,
                                   select_plugin)
from engine.upgrade_report import dry_run_report, make_ask, step_warnings


PROJECT_PLAN = [
    "migrate substrate schema",
    "canonicalize legacy G5 dependency overrides",
    "repair legacy graph provenance",
    "run the 0.10 upgrade steps",
    "install merge drivers",
    "refresh vendored engine",
    "refresh harness-generated workflow",
    "refresh Harness-owned Codex hook commands",
    "refresh harness-owned Claude settings",
    "refresh clean registry derivations",
    "validate substrate schema",
    "run doctor and verify",
    "propose one commit",
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


def _vendor(root: Path) -> dict:
    """The plugin repo runs its own engine; a vendored copy would be a
    second, stale engine inside `.harness/`."""
    if root.resolve() == PLUGIN_ROOT.resolve():
        return {"path": str(VENDOR_DIR), "version": ENGINE_VERSION,
                "action": "self-hosted", "from": None}
    return _vendor_engine(root)


def _refresh_registry(root: Path, clean: list, warnings: list) -> list:
    from engine.registry import RegistryError, refresh_built
    refreshed = []
    for name in clean:
        try:
            refresh_built(root, name)
        except RegistryError as exc:
            # the steps already ran: name the entry, never abort here
            warnings.append(
                f"registry {name}: not refreshed ({exc}). To keep it, "
                f"add its source to shadows.include in .harness/config.yaml")
            continue
        refreshed.append(name)
    return refreshed


def upgrade_project(root, *, dry_run: bool = False, ask=None,
                    yes: bool = False) -> dict:
    """Bring one substrate to the current schema and report what changed.

    Order: schema stamp; the 0.8 and 0.9 repairs, which read old shapes; the
    0.10 steps; the harness-owned files; the registry refresh, on 0.10 rows
    only; schema validation; doctor and verify. Upgrade never commits. The
    report proposes one commit. `ask` wins over `yes`.
    """
    root = Path(root).resolve()
    _require_substrate(root)
    version = _schema_version(root)
    if dry_run:
        return dry_run_report(root, version, PROJECT_PLAN,
                              _refresh_codex_hooks(root, dry_run=True))

    from engine import upgrade_010
    from engine import upgrade_report as rep
    from engine.graph import repair_legacy_provenance
    from engine.migrate import migrate
    from engine.overrides import repair_legacy_overrides
    from engine.schema import validate_substrate

    ask = ask or make_ask(yes)
    before = rep.snapshot(root)
    staged_before = rep.staged_paths(root)
    dirty_before = rep.dirty_paths(root)

    # Migration is deliberately the first write.  New code must never read
    # old substrate rows as though they already had the current schema.
    schema = migrate(root)
    # Which BUILT rows were clean before any upgrade write.
    clean, dirty, warnings = _clean_registry_entries(root)
    # From here on a stage that raises becomes a failure row, never a crash.
    failures: list = []

    def stage(name, func, default=None):
        return rep.run_stage(failures, name, func, default)

    legacy_overrides = stage("repair legacy overrides",
                             lambda: repair_legacy_overrides(root), {})
    graph = stage("repair legacy graph provenance",
                  lambda: repair_legacy_provenance(root), {})
    steps = upgrade_010.run(root, ask, dry_run=False)
    failures.extend(rep.reported_step_errors(steps))

    stage("install merge drivers", lambda: _install_merge_drivers(root))
    vendored = stage("refresh vendored engine", lambda: _vendor(root), {})
    workflow = stage("refresh workflow", lambda: _write_workflow(root), {})
    codex = stage("refresh Codex hooks", lambda: _refresh_codex_hooks(root), {})
    config = rep.load_config_or_fail(root, failures)
    claude = {} if config is None else stage(
        "refresh Claude settings", lambda: _refresh_claude_settings(root, config), {})
    warnings.extend(step_warnings(steps, workflow, claude, codex))
    # After any failure the registry may still hold 0.9 rows: a rerun refreshes.
    refreshed = [] if failures else stage(
        "refresh registry", lambda: _refresh_registry(root, clean, warnings), [])

    problems = stage("validate substrate",
                     lambda: validate_substrate(root, config=config or {}), [])
    failures.extend({"check": "schema", "code": "SCHEMA_INVALID", "text": p,
                     "fix": "correct the named row, then run: harness upgrade --yes"}
                    for p in problems)
    checks = rep.final_checks(root)
    failures.extend(checks["doctor"]["failures"] + checks["verify"]["failures"])
    files = stage("list changed files",
                  lambda: rep.changed_files(before, rep.snapshot(root)),
                  {"added": [], "modified": [], "removed": []})
    pending = rep.pending_ids(root, upgrade_010.STEPS)
    advice = stage("collect advice", lambda: upgrade_010.advice(root), [])
    commit = None
    if not failures and not pending:
        commit = stage("propose commit", lambda: rep.commit_proposal(root, files))
    failures = rep.attribute(failures, steps)
    status = rep.upgrade_status(schema_from=schema["from"], current=SCHEMA_VERSION,
                                files=files, steps=steps, pending=pending,
                                failures=failures)
    return {
        "status": status,
        "schema": schema,
        "engine_version": ENGINE_VERSION,
        "vendored_engine": vendored,
        "workflow": workflow,
        "claude": claude,
        "codex_adapter": codex,
        "graph": graph,
        "legacy_overrides": legacy_overrides,
        "registry": {"refreshed": refreshed, "skipped_dirty": dirty},
        "schema_validation": {"problems": problems, "passed": not problems},
        "steps": steps,
        "advice": advice,
        "files": files,
        "checks": checks,
        "failures": failures,
        "human_checks": rep.human_checks(
            steps, pending=pending, staged_before=staged_before,
            dirty_before=dirty_before, files=files, checks=checks,
            is_repo=(root / ".git").exists(), advice=advice),
        "commit": commit if status == "upgraded" else None,
        "warnings": warnings,
    }


def _run_command(command):
    """Run a non-interactive command and capture its output. The child gets
    no stdin: a delegated `harness upgrade` must not wait on a [y/N] prompt
    that captured stderr hides. It reports `needs confirmation` instead."""
    return subprocess.run(command, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True)


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
                             scope=None, dry_run: bool = False,
                             yes: bool = False) -> dict:
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
        if yes:
            delegate.append("--yes")
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
    if yes:
        delegate.append("--yes")
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
            dry_run=getattr(args, "dry_run", False),
            yes=getattr(args, "yes", False))
    else:
        if host or getattr(args, "plugin_id", None) or getattr(args, "scope", None):
            raise HarnessError("--host, --plugin-id and --scope require --plugin")
        report = upgrade_project(root, dry_run=getattr(args, "dry_run", False),
                                 ask=make_ask(getattr(args, "yes", False)))
    _print(report)
    return 0
