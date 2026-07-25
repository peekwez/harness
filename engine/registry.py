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
                f"registry entry {e['id']!r}: manifest paths missing: {unexcused}",
                severity="block", key=e["id"] + "|" + ",".join(unexcused)))
        else:
            findings.append(make_finding(
                "MANIFEST_INCOMPLETE", "gate:G1",
                f"registry entry {e['id']!r}: manifest paths {missing} not yet "
                f"built (declared by the active slice — will flip at close)",
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


def public_symbols(root, entry) -> list | None:
    """Public symbol signatures from an entry's shadow, or None if no shadow."""
    if not entry.get("shadow"):
        return None
    sp = Path(root) / entry["shadow"]
    if not sp.exists():
        return None
    shadow = json.loads(sp.read_text())
    return sorted(f"{s['kind']} {s['signature']}" for s in shadow.get("symbols", [])
                  if s.get("visibility") == "public")


def refresh_built(root, entry_id: str) -> dict:
    """Re-derive a BUILT entry's source_hash/signature_digest from its (fresh)
    shadow after a slice legitimately modified the source (G6-acknowledged
    drift). Without this, verify reports HASH_MISMATCH forever."""
    entries = load_registry(root)
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        raise RegistryError(f"registry entry {entry_id!r} not found")
    if entry.get("status") != "built" or not entry.get("source"):
        return entry
    src = Path(root) / entry["source"]
    sp = Path(root) / (entry.get("shadow") or "")
    if not src.exists() or not entry.get("shadow") or not sp.exists():
        raise RegistryError(
            f"cannot refresh {entry_id!r}: source or shadow missing (fail closed)")
    shadow = json.loads(sp.read_text())
    current = sha256_file(src)
    if shadow.get("source_hash") != current:
        raise RegistryError(
            f"cannot refresh {entry_id!r}: shadow is stale — run `harness extract`")
    entry["source_hash"] = current
    entry["signature_digest"] = signature_digest(shadow)
    entry["module_id"] = shadow.get("module_id")
    save_registry(root, entries)
    return entry


def flip_status(root, entry_id: str) -> dict:
    """planned -> built. Rejected unless the shadow exists and its hash
    matches current source (status flips are derived at close-slice)."""
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
    shadow_rel = entry.get("shadow")
    if not shadow_rel:
        # derive the canonical shadow location for this source
        from .extractor.engine import shadow_path_for
        derived = shadow_path_for(root, Path(root) / source)
        shadow_rel = str(derived.relative_to(Path(root).resolve()))
        entry["shadow"] = shadow_rel
    if not (Path(root) / shadow_rel).exists():
        raise RegistryError(
            f"cannot flip {entry_id!r} to built: shadow {shadow_rel!r} missing "
            f"(run `harness extract`)")
    shadow = json.loads((Path(root) / shadow_rel).read_text())
    current = sha256_file(Path(root) / source)
    if shadow.get("source_hash") != current:
        raise RegistryError(
            f"cannot flip {entry_id!r} to built: shadow is stale "
            f"(shadow hash {shadow.get('source_hash')} != source {current})")
    entry["status"] = "built"
    entry["source_hash"] = current
    entry["module_id"] = shadow.get("module_id")
    entry["signature_digest"] = signature_digest(shadow)
    save_registry(root, entries)
    return entry
