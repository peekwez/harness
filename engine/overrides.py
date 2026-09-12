"""Compatibility for justified registry exceptions using legacy deps: IDs."""
from __future__ import annotations

import json
from pathlib import Path

from . import sha256_text


DEP_MANIFESTS = ("requirements.txt", "requirements-dev.txt",
                 "pyproject.toml", "setup.py", "setup.cfg", "package.json",
                 "Cargo.toml", "go.mod")


def canonical_target(root, target, rule_ref, justification, registry_ids=None):
    """Resolve only unambiguous, justified G5 legacy registry targets.

    deps: also names actual dependency manifests. Paths, known manifest
    names, existing files, unknown IDs and other gates retain that spelling.
    A matching registry ID alone must never convert a manifest exception.
    """
    if (rule_ref != "gate:G5" or not isinstance(justification, str)
            or not justification.strip() or not isinstance(target, str)
            or not target.startswith("deps:")):
        return target
    name = target[len("deps:"):]
    if (not name or "/" in name or "\\" in name or ":" in name
            or name in {".", ".."}
            or name.casefold() in {p.casefold() for p in DEP_MANIFESTS}
            or (Path(root) / name).is_file()):
        return target
    if registry_ids is None:
        from .registry import load_registry
        registry_ids = {entry["id"] for entry in load_registry(root)}
    return f"registry:{name}" if name in registry_ids else target


def repair_legacy_overrides(root, *, dry_run=False):
    """Append canonical aliases once, retaining every original approval."""
    from .graph import append_edge, load_edges
    from .registry import load_registry

    edges = load_edges(root)
    registry_ids = {entry["id"] for entry in load_registry(root)}
    seen = {e.get("meta", {}).get("legacy_override", {}).get("source_hash")
            for e in edges if e.get("type") == "override"}
    planned, slices = [], set()
    for edge in edges:
        if (edge.get("type") != "override"
                or not edge.get("from", "").startswith("slice:")):
            continue
        meta = edge.get("meta", {})
        target = canonical_target(root, edge["to"], meta.get("rule_ref"),
                                  meta.get("justification"), registry_ids)
        if target == edge["to"]:
            continue
        source_hash = sha256_text(json.dumps(edge, sort_keys=True))
        if source_hash in seen:
            continue
        seen.add(source_hash)
        planned.append((edge, target, source_hash))
        slices.add(edge["from"].split(":", 1)[1])

    if not dry_run:
        for edge, target, source_hash in planned:
            meta = dict(edge.get("meta", {}))
            meta["legacy_override"] = {"target": edge["to"],
                                       "ts": edge.get("ts"),
                                       "source_hash": source_hash}
            append_edge(root, "override", edge["from"], target,
                        commit=edge.get("commit"), meta=meta)
    return {"edges_added": 0 if dry_run else len(planned),
            "would_add": len(planned) if dry_run else 0,
            "slices": sorted(slices)}
