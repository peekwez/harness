"""`harness verify`, `doctor` and `event` — the read-only check surface.

`verify` is the CI verifier (runs with no plugin at all); `doctor` is the
engine/substrate preflight; `event` is the stdin EnforcementEvent bridge.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine import HarnessError, harness_dir, load_backlog, load_config
from engine.cli.common import _dep_status, _print, _root


# ------------------------------------------------------------------ event
def cmd_event(args):
    from engine.events import run_stdin
    root = _root(args)
    code, out = run_stdin(root, sys.stdin.read())
    print(out)
    return code


def cmd_doctor(args):
    """Engine preflight: run this (or init runs it for you) before blaming
    the gates. Missing extraction deps degrade shadows; missing pyyaml is
    fatal for the engine itself. `--substrate` adds a repo health pass."""
    import platform
    deps = _dep_status()
    missing = sorted(k for k, v in deps.items() if v == "MISSING")
    report = {"python": platform.python_version(), "deps": deps,
              "healthy": not missing,
              "fix": f"pip install {' '.join(missing)}" if missing else None}
    if args.substrate:
        report.update(_substrate_health(_root(args), fix=args.fix))
        report["healthy"] = report["healthy"] and report["substrate_healthy"]
    _print(report)
    return 0 if report["healthy"] else 1


def _substrate_health(root, fix=False) -> dict:
    """Everything that rots quietly: schema drift, bindings pointing at
    closed slices, worktrees for slices nobody is building, findings parked
    and never adjudicated, telemetry never flushed, closed slices with no
    provenance note."""
    import subprocess
    from engine import read_jsonl, telemetry
    from engine.events import Sidecar
    from engine.schema import validate_substrate

    problems = {"schema": validate_substrate(root)}
    backlog = {s["id"]: s for s in load_backlog(root)}

    sidecar = Sidecar(root)
    try:
        cur = sidecar.db.execute(
            "SELECT session_id, value FROM session_state WHERE key='active_slice'")
        bindings = [(s, json.loads(v)) for s, v in cur.fetchall()]
        stale_bindings = [{"session": s, "slice": sid} for s, sid in bindings
                          if backlog.get(sid, {}).get("status") == "closed"]
        buffered = len(sidecar.telemetry_peek())
    finally:
        sidecar.close()

    stale_worktrees = []
    wt_dir = root / ".worktrees"
    if wt_dir.is_dir():
        for child in sorted(p for p in wt_dir.iterdir() if p.is_dir()):
            row = backlog.get(child.name)
            if row is None or row.get("status") == "closed":
                stale_worktrees.append({
                    "path": str(child), "slice": child.name,
                    "reason": "no such slice" if row is None else "slice closed",
                    "remove_with": f"git worktree remove --force {child}"})

    parked = read_jsonl(harness_dir(root) / "parked.jsonl")
    missing_notes = []
    if (root / ".git").exists():
        from engine.graph import read_notes
        noted = {p.get("slice_id") for n in read_notes(root) for p in n["payloads"]}
        missing_notes = [sid for sid, s in backlog.items()
                         if s.get("status") == "closed" and sid not in noted]

    fixed = {"bindings_released": 0, "telemetry_flushed": 0}
    if fix:
        sidecar = Sidecar(root)
        try:
            for b in stale_bindings:
                sidecar.db.execute(
                    "DELETE FROM session_state WHERE session_id=? AND key='active_slice'",
                    (b["session"],))
                fixed["bindings_released"] += 1
            sidecar.db.commit()
        finally:
            sidecar.close()
        fixed["telemetry_flushed"] = telemetry.flush(root)
        stale_bindings, buffered = [], 0

    healthy = not (problems["schema"] or stale_bindings or stale_worktrees
                   or parked or missing_notes)
    return {
        "substrate_healthy": healthy,
        "schema_problems": problems["schema"],
        "stale_bindings": stale_bindings,
        "stale_worktrees": stale_worktrees,      # never auto-removed: destructive
        "parked_findings": len(parked),
        "unflushed_telemetry": buffered,
        "missing_notes": missing_notes,
        "fixed": fixed if fix else None,
        "next": ("harness adjudicate --list" if parked else
                 "harness graph note --slice <id> --commit <sha>"
                 if missing_notes else None),
    }


# ------------------------------------------------------------------ verify
def cmd_verify(args):
    """C9 — CI verifier: runs with no plugin. Named finding codes."""
    root = _root(args)
    config = load_config(root)
    findings = []

    # schema_version check
    from engine import check_schema_version, SchemaError
    try:
        check_schema_version(root)
    except SchemaError as exc:
        from engine.events import make_finding
        findings.append(make_finding("SCHEMA_MISMATCH", "gate:G1", str(exc),
                                     severity="block", key="schema"))

    # substrate row schemas (§5.5/§5.6): a malformed row must fail here,
    # naming file/row/field, not three ceremonies later
    from engine.events import make_finding
    from engine.schema import validate_substrate
    for problem in validate_substrate(root):
        findings.append(make_finding("SCHEMA_INVALID", "gate:G1", problem,
                                     severity="block", key=problem[:80]))

    # shadow regeneration match (G7)
    from engine.gates.g7_derivation import derivation_findings
    findings.extend(derivation_findings(root, config))

    # manifest completeness against the built artifact. Files an OPEN slice
    # predicts are pending work, not the md-file-bug.
    from engine.registry import load_registry, validate_manifests
    base = Path(args.built_artifact).resolve() if args.built_artifact else root
    pending = set()
    try:
        for s in load_backlog(root):
            if s.get("status") != "closed":
                pending.update(s.get("predicted_files", []))
                pending.update(s.get("acceptance", []))
    except HarnessError:
        pass  # backlog problems are reported by the reconciliation block below
    try:
        registry = load_registry(root)
        findings.extend(validate_manifests(root, registry, base=base,
                                           pending=pending))
    except HarnessError as exc:
        from engine.events import make_finding
        findings.append(make_finding("MANIFEST_INCOMPLETE", "gate:G1", str(exc),
                                     severity="block", key="registry"))
        registry = []

    # hash validation + derived-artifact existence for built entries
    from engine import sha256_file
    from engine.events import make_finding
    for e in registry:
        if e.get("status") != "built":
            continue
        if e.get("source") and e.get("source_hash"):
            src = root / e["source"]
            if src.exists() and sha256_file(src) != e["source_hash"]:
                findings.append(make_finding(
                    "HASH_MISMATCH", "gate:G4",
                    f"registry {e['id']!r}: source_hash stale for {e['source']}",
                    severity="block", key=e["id"]))
        # a built entry's shadow is a required derived artifact — its absence
        # is the md-file-bug class, never a silent pass
        if not e.get("shadow") or not (root / e["shadow"]).exists():
            findings.append(make_finding(
                "MISSING_SHADOW", "gate:G7",
                f"registry {e['id']!r} is built but its shadow "
                f"{e.get('shadow')!r} does not exist; run `harness extract --all`",
                severity="block", key=e["id"] + "|shadow"))
        for ref in e.get("guidance_refs", []):
            if not (root / ref.split("#")[0]).exists():
                findings.append(make_finding(
                    "MANIFEST_INCOMPLETE", "gate:G1",
                    f"registry {e['id']!r}: guidance_ref {ref!r} missing",
                    severity="block", key=e["id"] + "|" + ref))

    # contract lint: contracts/ is scaffolded as the FE/BE seam — an
    # unparseable or shapeless contract silently disables that seam
    contracts = root / "contracts"
    if contracts.is_dir():
        import yaml as _yaml
        for c in sorted(contracts.glob("*.y*ml")):
            rel = str(c.relative_to(root))
            try:
                doc = _yaml.safe_load(c.read_text())
            except _yaml.YAMLError as exc:
                findings.append(make_finding(
                    "CONTRACT_INVALID", "gate:G1",
                    f"{rel}: unparseable YAML: {exc}"[:300],
                    severity="block", key=rel))
                continue
            if not isinstance(doc, dict) or "openapi" not in doc \
                    or "paths" not in doc:
                findings.append(make_finding(
                    "CONTRACT_INVALID", "gate:G1",
                    f"{rel}: not an OpenAPI document (needs `openapi` and "
                    f"`paths` keys) — fix it or delete the contract",
                    severity="block", key=rel))

    # orphaned-notes detection (git failures are loud; only a non-repo skips).
    # A squash/rebase merge rewrites the sha a note was written on, so an
    # unreachable note is only a hole when the derived notes log cannot
    # resolve the slice either (ADR-002 / D-010).
    from engine.cli.landing import landing_config
    from engine.graph import (orphaned_notes, read_notes, reachable_source_keys,
                              reachable_trees, resolve_note)
    resolved_via, trees, cache = {}, {}, {}
    is_repo = (root / ".git").exists()
    landing = landing_config(config)
    base, remote = landing["base"], landing["remote"]
    if is_repo:
        trees = reachable_trees(root, base, remote=remote)

    def _source_keys():
        # one `git ls-tree` per commit: computed once, and only for a repo
        # that actually has a note to resolve
        if "keys" not in cache:
            cache["keys"] = reachable_source_keys(root, base, remote=remote)
        return cache["keys"]

    def _resolves(slice_id):
        if not (is_repo and slice_id):
            return False
        hit = resolve_note(root, slice_id, trees, _source_keys)
        if hit:
            resolved_via[slice_id] = hit["resolved_via"]
        return bool(hit)

    if is_repo:
        for n in orphaned_notes(root):
            slices = [p.get("slice_id") for p in n["payloads"]]
            if slices and all(_resolves(sid) for sid in slices):
                continue
            findings.append(make_finding(
                "ORPHANED_NOTE", "gate:G1",
                f"git note on unreachable commit {n['commit']} with no "
                f"tree-hash match in .harness/notes.jsonl "
                f"(payload: {json.dumps(n['payload'])[:120]}); repair with "
                f"`harness graph note --repoint <slice-id> <sha>`",
                severity="block", key=n["commit"]))

    # uses/declares reconciliation for all closed slices. A missing backlog is
    # legal pre-Phase-0; a CORRUPT one must fail loud (md-file-bug class).
    from engine import SubstrateMissing
    from engine.graph import uses_vs_declares
    try:
        backlog = load_backlog(root)
    except SubstrateMissing:
        backlog = []
    except HarnessError as exc:
        backlog = []
        findings.append(make_finding(
            "SCHEMA_MISMATCH", "gate:G1",
            f"backlog.jsonl unreadable: {exc}", severity="block", key="backlog"))
    # provenance completeness: every CLOSED slice must carry a note naming
    # it. The orphan check above catches notes whose commit went away; this
    # catches the inverse — a slice closed with no note at all, which used
    # to pass verify silently.
    noted = set()
    if (root / ".git").exists():
        noted = {p.get("slice_id") for n in read_notes(root)
                 for p in n["payloads"]}

    # repo-local gates (ADR-002 / D-007): a `gates.extra` entry that fails to
    # load is a blocking finding here too, and every CLOSED slice is replayed
    # through a synthetic unit_complete event so repo invariants are enforced
    # on landed work — including diffs no hook ever saw. Gates that declare
    # only pre_change do not run in CI: there is no edit to intercept.
    from engine.gates.extra import verify_extra_findings
    findings.extend(verify_extra_findings(root, config, backlog))

    for s in backlog:
        if s.get("status") != "closed":
            continue
        if (root / ".git").exists() and s["id"] not in noted \
                and not _resolves(s["id"]):
            findings.append(make_finding(
                "MISSING_PROVENANCE_NOTE", "gate:G1",
                f"closed slice {s['id']} has no provenance note and no "
                f"tree-hash key in .harness/notes.jsonl; provenance must "
                f"travel with the repo — repair with `harness graph note "
                f"--slice {s['id']} --commit <sha>`",
                severity="block", key=s["id"] + "|note"))
        if s.get("landed_via") == "pending":
            # closed, but the push or the PR command did not go through: not
            # a block (the work IS closed and committed), and not silence
            # either — the branch is not on the forge yet
            findings.append(make_finding(
                "LANDING_PENDING", "adr:002",
                f"slice {s['id']} closed but its landing did not complete: "
                f"{str(s.get('landing_error', ''))[:200]} — re-land with "
                f"`harness land --slice {s['id']}` from the slice's worktree",
                severity="advisory", key=s["id"] + "|landing"))
        ud = uses_vs_declares(root, s["id"])
        und = ud["unresolved"]
        if und:
            findings.append(make_finding(
                "UNRECONCILED_SLICE", "gate:G5",
                f"closed slice {s['id']}: undeclared uses {und}",
                severity="block", key=s["id"]))

    passed = not any(f["severity"] == "block" for f in findings)
    report = {"passed": passed, "findings": findings}
    if resolved_via:
        # how a landed slice's provenance was recovered: `tree_hash` (a
        # reachable commit carries the recorded tree) or `notes_row` (the
        # committed notes log names the slice)
        report["resolved_via"] = resolved_via
    _print(report)
    return 0 if passed else 1
