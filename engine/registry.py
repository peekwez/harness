"""C3 — Registry: reusable abstractions with lifecycle planned -> built.

CRUD over registry.jsonl; status transitions only via engine; manifest
validation is the md-file-bug killer: every path listed in an entry's
manifest must exist — mismatch is a hard failure naming the entry and paths.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import HarnessError, harness_dir, read_jsonl, sha256_file, write_jsonl
from .events import make_finding

REGISTRY_KINDS = {"logging", "telemetry", "config", "errors", "util",
                  "component", "other"}
STATUSES = {"planned", "built"}


class RegistryError(HarnessError):
    pass


def registry_kinds(config=None) -> set:
    """The registry `kind` enum in force for this repo.

    `registry.kinds_extra` widens the builtin enum so a consumer repo can
    name its own abstraction kinds (`package`, `protocol`, ...) without the
    compiler coercing them to `other` (ADR-002 / D-007).

    Args:
        config: Loaded engine config, or None for the builtin enum only.

    Returns:
        Every accepted `kind` string.

    Raises:
        RegistryError: `kinds_extra` is not a list of strings — silently
            stringifying a typo would widen the enum with garbage.
    """
    extra = ((config or {}).get("registry") or {}).get("kinds_extra") or []
    if isinstance(extra, str):
        extra = [extra]
    if not isinstance(extra, (list, tuple)):
        raise RegistryError(
            f"registry.kinds_extra must be a list of strings, got "
            f"{type(extra).__name__}")
    bad = [k for k in extra if not isinstance(k, str) or not k.strip()]
    if bad:
        raise RegistryError(
            f"registry.kinds_extra must be a list of non-empty strings; "
            f"got {bad!r}")
    return set(REGISTRY_KINDS) | set(extra)


def registry_path(root) -> Path:
    return harness_dir(root) / "registry.jsonl"


def load_registry(root) -> list:
    path = registry_path(root)
    if not path.exists():
        raise RegistryError(f"{path} missing — substrate incomplete (fail closed)")
    entries = read_jsonl(path)
    seen = set()
    for e in entries:
        if not e.get("id"):
            raise RegistryError(f"registry entry without id: {e}")
        if e["id"] in seen:
            raise RegistryError(f"duplicate registry id {e['id']!r}")
        seen.add(e["id"])
        if e.get("status") not in STATUSES:
            raise RegistryError(f"registry {e['id']}: invalid status {e.get('status')!r}")
    return entries


def save_registry(root, entries: list) -> None:
    write_jsonl(registry_path(root), entries)


def get_entry(root, entry_id: str) -> dict:
    for e in load_registry(root):
        if e["id"] == entry_id:
            return e
    raise RegistryError(f"registry entry {entry_id!r} not found (fail closed)")


def entry_for_source(entries: list, rel_path: str):
    for e in entries:
        if e.get("source") == rel_path:
            return e
    return None


def validate_manifests(root, entries=None, base=None, pending=None) -> list:
    """Every path in every entry's manifest must exist. Findings name the
    entry ID and each missing path. `base` overrides the tree checked
    (CI validates the built/installed artifact, not just the source tree).

    `pending`: paths an open slice is about to create. A PLANNED entry's
    missing manifest path that is pending work is the normal pre-build state
    (advisory), not the md-file-bug; built entries never get that grace."""
    base = Path(base or root)
    pending = set(pending or ())
    findings = []
    for e in (entries if entries is not None else load_registry(root)):
        missing = [m for m in e.get("manifest", []) if not (base / m).exists()]
        if not missing:
            continue
        unexcused = [m for m in missing
                     if not (e.get("status") == "planned" and m in pending)]
        if unexcused:
            findings.append(make_finding(
                "MANIFEST_INCOMPLETE", "gate:G1",
                f"registry entry {e['id']!r}: {len(unexcused)} manifest paths "
                f"are missing: {', '.join(unexcused[:3])}.",
                severity="block", key=e["id"] + "|" + ",".join(unexcused),
                fix="Create the missing files, or remove them from the "
                    "manifest of the entry."))
        else:
            findings.append(make_finding(
                "MANIFEST_INCOMPLETE", "gate:G1",
                f"registry entry {e['id']!r}: manifest paths "
                f"{', '.join(missing[:3])} are not built yet. Close marks "
                f"them built.",
                severity="advisory", key=e["id"] + "|pending"))
    return findings


def _tokenize_sig(sig: str) -> set:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sig)
    out = set()
    for w in words:
        for part in re.split(r"_+", w):
            out.update(p.lower() for p in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+", part) if p)
    return out


def signature_digest(shadow: dict) -> str:
    """Normalized digest of the exported surface, used by G5 similarity."""
    sigs = sorted(s["signature"] for s in shadow.get("symbols", [])
                  if s.get("visibility") == "public")
    return json.dumps(sigs, sort_keys=True)


def digest_tokens(digest: str) -> set:
    try:
        sigs = json.loads(digest) if digest else []
    except json.JSONDecodeError:
        sigs = [digest]
    toks = set()
    for s in sigs:
        toks |= _tokenize_sig(s)
    return toks


def similarity(tokens_a: set, tokens_b: set) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _shadow_of(root, entry, config=None, **kw):
    """The entry's shadow through the cache, or None (no source / out of scope)."""
    if not entry.get("source"):
        return None
    from . import load_config
    from .extractor.engine import shadow_for
    return shadow_for(root, Path(root) / entry["source"],
                      config if config is not None else load_config(root), **kw)


def public_symbols(root, entry, config=None, **kw) -> list | None:
    """Public symbol signatures from an entry's shadow, or None if no shadow."""
    shadow = _shadow_of(root, entry, config, **kw)
    if shadow is None:
        return None
    return sorted(f"{s['kind']} {s['signature']}" for s in shadow.get("symbols", [])
                  if s.get("visibility") == "public")


def refresh_built(root, entry_id: str) -> dict:
    """Re-derive a BUILT entry's source_hash/signature_digest from its shadow
    after a slice legitimately modified the source (G6-acknowledged drift).
    Without this, verify reports HASH_MISMATCH forever."""
    entries = load_registry(root)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise RegistryError(f"registry entry {entry_id!r} not found")
    if entry.get("status") != "built" or not entry.get("source"):
        return entry
    src = Path(root) / entry["source"]
    if not src.exists():
        raise RegistryError(
            f"cannot refresh {entry_id!r}: source {entry['source']} is missing")
    shadow = _shadow_of(root, entry)
    if shadow is None:
        raise RegistryError(
            f"cannot refresh {entry_id!r}: {entry['source']} is outside shadow "
            f"scope. Add it to shadows.include in .harness/config.yaml")
    entry["source_hash"] = sha256_file(src)
    entry["signature_digest"] = signature_digest(shadow)
    entry["module_id"] = shadow.get("module_id")
    entry.pop("shadow", None)
    save_registry(root, entries)
    return entry


def flip_status(root, entry_id: str) -> dict:
    """planned -> built. Rejected unless the source exists inside shadow
    scope (status flips are derived at close-slice)."""
    entries = load_registry(root)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise RegistryError(f"registry entry {entry_id!r} not found")
    if entry.get("status") == "built":
        return entry
    source = entry.get("source")
    if not source or not (Path(root) / source).exists():
        raise RegistryError(
            f"cannot flip {entry_id!r} to built: source {source!r} missing")
    shadow = _shadow_of(root, entry)
    if shadow is None:
        raise RegistryError(
            f"cannot flip {entry_id!r} to built: {source} is outside shadow "
            f"scope. Add it to shadows.include in .harness/config.yaml")
    entry["status"] = "built"
    entry["source_hash"] = sha256_file(Path(root) / source)
    entry["module_id"] = shadow.get("module_id")
    entry["signature_digest"] = signature_digest(shadow)
    entry.pop("shadow", None)
    save_registry(root, entries)
    return entry
