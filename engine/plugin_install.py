"""Validate host plugin listings and locate installed engine copies."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from engine import HarnessError


def prevent_downgrade(candidate, current, label="engine"):
    def key(value):
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?", str(value))
        return tuple(int(n or 0) for n in match.groups()) if match else None
    new, old = key(candidate), key(current)
    if new is not None and old is not None and new < old:
        raise HarnessError(f"refusing to downgrade {label} from {current} to {candidate}; "
                           "install or publish a current Harness release first")


def installed_entries(host: str, payload) -> list[dict]:
    if host == "claude":
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("installed", "plugins"):
                if isinstance(payload.get(key), list):
                    return payload[key]
    elif host == "codex" and isinstance(payload, dict):
        if isinstance(payload.get("installed"), list):
            return payload["installed"]
    raise HarnessError(f"{host} plugin list returned an unsupported JSON shape")


def entry_id(host: str, entry: dict) -> str | None:
    return entry.get("id" if host == "claude" else "pluginId")


def _is_harness(host: str, entry: dict) -> bool:
    plugin_id = str(entry_id(host, entry) or "")
    return (plugin_id.split("@", 1)[0].casefold() == "harness"
            or str(entry.get("name", "")).casefold() == "harness")


def select_plugin(host: str, entries: list[dict], plugin_id=None,
                  scope=None) -> dict:
    if scope and host != "claude":
        raise HarnessError("--scope is supported only with --host claude")
    if plugin_id:
        matches = [e for e in entries if entry_id(host, e) == plugin_id]
        if not matches:
            raise HarnessError(
                f"Harness plugin {plugin_id!r} is not installed for {host}")
        if any(not _is_harness(host, entry) for entry in matches):
            raise HarnessError(f"{plugin_id!r} is not a Harness plugin")
    else:
        matches = [e for e in entries if _is_harness(host, e)]
    if scope:
        matches = [e for e in matches if e.get("scope") == scope]
    if not matches:
        raise HarnessError(
            f"no installed Harness plugin found for {host}"
            + (f" with scope {scope!r}" if scope else "")
            + "; install it first or select the correct --plugin-id/--scope")
    if len(matches) > 1:
        ids = ", ".join(
            f"{entry_id(host, e)} (scope {e.get('scope')})"
            if host == "claude" else str(entry_id(host, e))
            for e in matches)
        raise HarnessError(
            f"multiple Harness plugins are installed for {host}: {ids}; "
            "choose one with --plugin-id"
            + (" and --scope" if host == "claude" else ""))
    return matches[0]


def _listed_path(host: str, entry: dict) -> Path | None:
    source = entry.get("source")
    raw = (entry.get("installPath") if host == "claude" else
           source.get("path") if isinstance(source, dict) else None)
    return Path(raw).expanduser() if isinstance(raw, str) and raw else None


def _engine_files(root: Path | None) -> tuple[Path, Path] | None:
    if root is None:
        return None
    binary = root / "bin" / "harness"
    init_py = root / "engine" / "__init__.py"
    if binary.is_file() and init_py.is_file():
        return root.resolve(), binary.resolve()
    return None


def _manifest_matches(root: Path, entry: dict) -> bool:
    manifest = root / ".codex-plugin" / "plugin.json"
    try:
        payload = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    plugin_id = str(entry.get("pluginId") or "")
    expected_name = plugin_id.split("@", 1)[0]
    return (payload.get("name") == expected_name
            and payload.get("version") == entry.get("version"))


def _codex_cache_root() -> Path:
    configured = os.environ.get("CODEX_HOME")
    codex_home = Path(configured).expanduser() if configured else Path.home() / ".codex"
    return codex_home / "plugins" / "cache"


def _prove_codex_engine(entry: dict) -> tuple[Path, Path]:
    plugin_id = str(entry.get("pluginId") or "")
    name = plugin_id.split("@", 1)[0]
    marketplace = entry.get("marketplaceName")
    version = entry.get("version")
    if not name or not marketplace or not isinstance(version, str) or not version:
        raise HarnessError(
            f"cannot prove the installed engine for {plugin_id!r}: Codex "
            "did not report plugin identity, marketplace, and version")

    base = _codex_cache_root() / str(marketplace) / name
    cached = []
    if base.is_dir():
        for candidate in base.iterdir():
            files = (_engine_files(candidate) if candidate.is_dir()
                     and _manifest_matches(candidate, entry) else None)
            if files:
                cached.append(files)
    if len(cached) == 1:
        return cached[0]
    if len(cached) > 1:
        roots = ", ".join(str(pair[0]) for pair in cached)
        raise HarnessError(
            f"cannot prove the installed engine for {plugin_id!r}: multiple "
            f"cached copies match version {version}: {roots}")

    source_root = _listed_path("codex", entry)
    if source_root and _manifest_matches(source_root, entry):
        files = _engine_files(source_root)
        if files:
            return files
    raise HarnessError(
        f"cannot prove the installed engine for {plugin_id!r} version "
        f"{version}: `codex plugin list --json` exposes no installed path and "
        "no unique matching copy exists in the Codex plugin cache")


def prove_engine(host: str, entry: dict) -> tuple[Path, Path]:
    if host == "codex":
        return _prove_codex_engine(entry)
    files = _engine_files(_listed_path(host, entry))
    if files is None:
        raise HarnessError(
            f"cannot prove the installed engine path for "
            f"{entry_id(host, entry)!r}; plugin list must expose a valid "
            "install path containing bin/harness and engine/__init__.py")
    return files


def plugin_commands(host: str, entry: dict) -> list[list[str]]:
    plugin_id = entry_id(host, entry)
    if not isinstance(plugin_id, str) or not plugin_id:
        raise HarnessError(f"{host} Harness plugin entry has no usable plugin id")
    if host == "claude":
        scope = entry.get("scope")
        if not scope:
            raise HarnessError(
                f"Claude plugin {plugin_id!r} has no scope; cannot update safely")
        return [["claude", "plugin", "update", plugin_id,
                 "--scope", str(scope)]]
    marketplace = entry.get("marketplaceName")
    if not marketplace or "@" not in plugin_id:
        raise HarnessError(
            f"Codex plugin {plugin_id!r} has no marketplace identity; "
            "cannot update it without touching unrelated sources")
    marketplace_source = entry.get("marketplaceSource")
    source_type = (marketplace_source.get("sourceType")
                   if isinstance(marketplace_source, dict) else None)
    add = ["codex", "plugin", "add", plugin_id, "--json"]
    if source_type == "local":
        # A local marketplace is the user's checkout. Reinstall from it, but
        # never pull or otherwise mutate that unrelated source tree.
        return [add]
    if source_type in ("git", "github"):
        return [["codex", "plugin", "marketplace", "upgrade",
                 str(marketplace), "--json"], add]
    raise HarnessError(
        f"Codex plugin {plugin_id!r} has unsupported marketplace source "
        f"type {source_type!r}; refusing to update an unproven source")
