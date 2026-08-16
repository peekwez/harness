"""C1 — Event contract & engine shell.

EnforcementEvent (stdin JSON) -> gate dispatch -> EnforcementVerdict (stdout JSON).
Exit 0: verdict carries semantics. Nonzero exit = engine error only.
Session-scoped state (context_loaded per session_id) lives in the sidecar.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from . import (HarnessError, harness_dir, now_iso, token_estimate)

EVENTS = ("session_start", "pre_context", "pre_change", "post_change", "unit_complete")
SEVERITIES = ("gate", "block", "advisory")
_VERDICT_RANK = {"allow": 0, "allow_with_findings": 1, "block": 2}

FINDING_CODES = {
    "MANIFEST_INCOMPLETE", "SCHEMA_MISMATCH", "CONTEXT_NOT_LOADED",
    "MISSING_SHADOW", "UNDECLARED_FILE", "NON_GOAL_VIOLATION", "STALE_SHADOW",
    "UNDECLARED_USE", "DUPLICATE_CANDIDATE", "INTERFACE_DRIFT",
    "DERIVATION_MISMATCH", "UNSHADOWED_FILE", "UNKNOWN_LANGUAGE",
    "NO_ACTIVE_WORK_UNIT", "HASH_MISMATCH", "ORPHANED_NOTE", "MISSING_DEPENDENCY",
    "UNRECONCILED_SLICE", "MISSING_RULE_REF", "REVIEW_UNCERTAIN",
    "COMPACTION_REACHED",
}


class EventError(HarnessError):
    """Malformed EnforcementEvent — exit 2 with error JSON."""


class VerdictError(HarnessError):
    """Engine produced an invalid verdict — a bug, fail loud."""


# ---------------------------------------------------------------- findings
def make_finding(code, rule_ref, message, severity="advisory", layer=0,
                 inject=None, precedents=None, key=None) -> dict:
    fid = "F-" + hashlib.sha1(
        f"{code}|{rule_ref}|{key or message}".encode()).hexdigest()[:10]
    return {
        "finding_id": fid,
        "layer": layer,
        "severity": severity,
        "code": code,
        "rule_ref": rule_ref,
        "message": message,
        "inject": list(inject or []),
        "precedents": list(precedents or []),
    }


def validate_finding(f: dict) -> None:
    for req in ("finding_id", "layer", "severity", "code", "rule_ref", "message"):
        if req not in f:
            raise VerdictError(f"finding missing field {req!r}: {f}")
    if f["severity"] not in SEVERITIES:
        raise VerdictError(f"invalid severity {f['severity']!r}")
    if f["severity"] == "block" and not f.get("rule_ref"):
        # Blocking without a rule reference is a bug — rejected by the engine itself.
        raise VerdictError(
            f"blocking finding {f.get('finding_id')} ({f.get('code')}) has no rule_ref")


def verdict_for(findings: list, injections=None) -> dict:
    v = "allow"
    for f in findings:
        validate_finding(f)
        if f["severity"] == "block":
            v = "block"
        elif v == "allow":
            v = "allow_with_findings"
    return {"verdict": v, "findings": findings, "injections": list(injections or [])}


def merge_verdicts(verdicts: list) -> dict:
    """Most restrictive wins: block > allow_with_findings > allow."""
    if not verdicts:
        return {"verdict": "allow", "findings": [], "injections": []}
    out = {"verdict": "allow", "findings": [], "injections": []}
    for v in verdicts:
        if v["verdict"] not in _VERDICT_RANK:
            raise VerdictError(f"invalid verdict {v['verdict']!r}")
        if _VERDICT_RANK[v["verdict"]] > _VERDICT_RANK[out["verdict"]]:
            out["verdict"] = v["verdict"]
        out["findings"].extend(v.get("findings", []))
        out["injections"].extend(v.get("injections", []))
    for f in out["findings"]:
        validate_finding(f)
    return out


# ---------------------------------------------------------------- event
def validate_event(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise EventError("event must be a JSON object")
    ev = raw.get("event")
    if ev not in EVENTS:
        raise EventError(f"unknown event {ev!r}; expected one of {list(EVENTS)}")
    if not raw.get("session_id") or not isinstance(raw["session_id"], str):
        raise EventError("session_id (string) is required")
    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        raise EventError("payload must be an object")
    files = payload.get("files") or []
    if not isinstance(files, list):
        raise EventError("payload.files must be a list")
    norm_files = []
    for f in files:
        if isinstance(f, str):
            norm_files.append({"path": f, "proposed_content_hash": None})
        elif isinstance(f, dict) and isinstance(f.get("path"), str):
            norm_files.append({"path": f["path"],
                               "proposed_content_hash": f.get("proposed_content_hash")})
        else:
            raise EventError(f"invalid file entry: {f!r}")
    ctx = payload.get("context_loaded") or []
    if not isinstance(ctx, list) or not all(isinstance(c, str) for c in ctx):
        raise EventError("payload.context_loaded must be a list of strings")
    return {
        "event": ev,
        "session_id": raw["session_id"],
        "work_unit_id": raw.get("work_unit_id"),
        "payload": {
            "files": norm_files,
            "context_loaded": ctx,
            "diff": payload.get("diff"),
            "prompt": payload.get("prompt"),
        },
    }


# ---------------------------------------------------------------- sidecar
class Sidecar:
    """Gitignored SQLite: session context_loaded state, slice symbol snapshots,
    touched-file tracking, extractor cache metadata. Fully rebuildable."""

    def __init__(self, root):
        self.path = harness_dir(root) / "sidecar.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=10)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # WAL-unsupported filesystem: default journal is correct, slower
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS session_context(
            session_id TEXT, item TEXT, ts TEXT,
            UNIQUE(session_id, item));
        CREATE TABLE IF NOT EXISTS session_state(
            session_id TEXT, key TEXT, value TEXT,
            UNIQUE(session_id, key));
        CREATE TABLE IF NOT EXISTS slice_snapshot(
            slice_id TEXT, module_id TEXT, symbols TEXT,
            UNIQUE(slice_id, module_id));
        CREATE TABLE IF NOT EXISTS touched(
            session_id TEXT, slice_id TEXT, path TEXT,
            UNIQUE(session_id, slice_id, path));
        CREATE TABLE IF NOT EXISTS telemetry_buffer(
            id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def context_add(self, session_id, items):
        ts = now_iso()
        self.db.executemany(
            "INSERT OR IGNORE INTO session_context(session_id, item, ts) VALUES(?,?,?)",
            [(session_id, i, ts) for i in items])
        self.db.commit()

    def context_get(self, session_id) -> set:
        cur = self.db.execute(
            "SELECT item FROM session_context WHERE session_id=?", (session_id,))
        return {r[0] for r in cur.fetchall()}

    def state_set(self, session_id, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO session_state(session_id, key, value) VALUES(?,?,?)",
            (session_id, key, json.dumps(value)))
        self.db.commit()

    def state_get(self, session_id, key, default=None):
        cur = self.db.execute(
            "SELECT value FROM session_state WHERE session_id=? AND key=?",
            (session_id, key))
        row = cur.fetchone()
        return json.loads(row[0]) if row else default

    def release_slice(self, slice_id=None) -> int:
        """Clear active-slice bindings — for one slice (on close) or all
        (`harness slice --release`). Returns rows cleared."""
        if slice_id is None:
            cur = self.db.execute(
                "DELETE FROM session_state WHERE key='active_slice'")
        else:
            cur = self.db.execute(
                "DELETE FROM session_state WHERE key='active_slice' AND value=?",
                (json.dumps(slice_id),))
        self.db.commit()
        return cur.rowcount

    def telemetry_buffer(self, row: dict) -> None:
        """Hook-frequency telemetry parks here (gitignored) instead of
        churning the tracked file on every event (review R8)."""
        self.db.execute("INSERT INTO telemetry_buffer(row) VALUES(?)",
                        (json.dumps(row, sort_keys=True),))
        self.db.commit()

    def telemetry_peek(self) -> list:
        return [json.loads(r[0]) for r in
                self.db.execute("SELECT row FROM telemetry_buffer ORDER BY id")]

    def telemetry_drain(self) -> list:
        rows = self.telemetry_peek()
        self.db.execute("DELETE FROM telemetry_buffer")
        self.db.commit()
        return rows

    def release_snapshots(self, slice_id) -> int:
        """Drop a slice's G6 baselines at close — stale baselines cause
        phantom drift when the id is later rebound (S6)."""
        cur = self.db.execute(
            "DELETE FROM slice_snapshot WHERE slice_id=?", (slice_id,))
        self.db.commit()
        return cur.rowcount

    def snapshot_set(self, slice_id, module_id, symbols):
        self.db.execute(
            "INSERT OR IGNORE INTO slice_snapshot(slice_id, module_id, symbols) VALUES(?,?,?)",
            (slice_id, module_id, json.dumps(symbols, sort_keys=True)))
        self.db.commit()

    def snapshot_get(self, slice_id) -> dict:
        cur = self.db.execute(
            "SELECT module_id, symbols FROM slice_snapshot WHERE slice_id=?", (slice_id,))
        return {m: json.loads(s) for m, s in cur.fetchall()}

    def touch(self, session_id, slice_id, paths):
        self.db.executemany(
            "INSERT OR IGNORE INTO touched(session_id, slice_id, path) VALUES(?,?,?)",
            [(session_id, slice_id or "", p) for p in paths])
        self.db.commit()

    def touched_paths(self, slice_id=None, session_id=None) -> set:
        q, args = "SELECT path FROM touched WHERE 1=1", []
        if slice_id is not None:
            q += " AND slice_id=?"; args.append(slice_id)
        if session_id is not None:
            q += " AND session_id=?"; args.append(session_id)
        return {r[0] for r in self.db.execute(q, args).fetchall()}


# ---------------------------------------------------------------- handler
def handle_event(raw: dict, root) -> dict:
    """Dispatch an EnforcementEvent to the gate pack for that event; merge
    verdicts; Phase-1 events additionally run the resolver and inject."""
    from . import check_schema_version, load_config
    from .gates import run_gates
    from . import telemetry

    evt = validate_event(raw)
    _normalize_file_paths(root, evt)
    check_schema_version(root)
    config = load_config(root)
    sidecar = Sidecar(root)
    try:
        session, event = evt["session_id"], evt["event"]
        # Binding resolution: explicit event field > this session's binding >
        # the repo-default binding ("__default__", set by `harness slice`).
        # The default exists because the id in hook events is the host's real
        # session UUID, which humans can't know in advance (field report #18).
        slice_id = (evt["work_unit_id"]
                    or sidecar.state_get(session, "active_slice")
                    or sidecar.state_get("__default__", "active_slice"))
        evt["work_unit_id"] = slice_id

        # Remember the live host session: builder shells often lack
        # $CLAUDE_SESSION_ID, so CLI commands fall back to this to JOIN the
        # session the hooks are gating instead of a parallel "cli" one (Y2).
        if session not in ("cli", "__default__"):
            sidecar.state_set("__hooks__", "last_session_id", session)

        # Persist context_loaded additions per session_id (spec C1).
        if evt["payload"]["context_loaded"]:
            sidecar.context_add(session, evt["payload"]["context_loaded"])

        injections, resolved_manifest = [], []
        if event in ("session_start", "pre_context") and slice_id:
            # Phase 1 — inject early; ~90% of context loading happens here.
            from .resolver import resolve
            res = resolve(root, slice_id, config)
            resolved_manifest = res["context_loaded"]
            already = sidecar.context_get(session)
            # Dedupe for BOTH Phase-1 events: SessionStart re-runs on resume
            # (same session_id) and UserPromptSubmit fires every prompt — if
            # the session already carries the full manifest, re-injecting only
            # bloats the transcript. Substrate changes alter the manifest and
            # re-trigger injection naturally.
            if resolved_manifest and set(resolved_manifest) <= already:
                injections = []
            else:
                injections = res["injections"]
            sidecar.context_add(session, resolved_manifest)
            _snapshot_slice_baseline(root, sidecar, slice_id)

        if event == "post_change":
            # the tool already ran: these files were really touched.
            # Paths still absolute after normalization — or escaping the
            # root via `../` traversal — are outside the repo: G8 enumerates
            # them; recording them would poison unit_complete regeneration
            # (field report #19, S5).
            paths = [f["path"] for f in evt["payload"]["files"]
                     if rel_in_root(root, f["path"])]
            if paths:
                sidecar.touch(session, slice_id, paths)

        if event == "unit_complete":
            _regenerate_touched(root, sidecar, session, slice_id, config)

        findings = run_gates(root, evt, config, sidecar)
        verdict = merge_verdicts([verdict_for(findings, injections)])

        if event == "pre_change" and verdict["verdict"] != "block":
            # record the touch only when the edit is allowed to proceed —
            # a denied edit never happened, and phantom touches would demand
            # G3 reconciliation at close-slice for files no one changed
            paths = [f["path"] for f in evt["payload"]["files"]
                     if rel_in_root(root, f["path"])]
            if paths:
                sidecar.touch(session, slice_id, paths)
            # NOTE: whether the HOST should prompt is a separate question
            # from the enforcement verdict, and stays out of this schema —
            # adapters ask `harness permit` (engine/permits.py). The verdict
            # contract is the portability boundary; it does not grow fields.

        telemetry.emit(root, "event", {
            "event": event, "session": session, "slice": slice_id,
            "verdict": verdict["verdict"],
            "codes": sorted({f["code"] for f in verdict["findings"]}),
            "gates": sorted({f["rule_ref"] for f in verdict["findings"]
                             if f["rule_ref"].startswith("gate:")}),
        })
        return verdict
    finally:
        sidecar.close()


def rel_in_root(root, rel) -> bool:
    """True if rel is a RELATIVE path that stays inside root. Absolute paths
    and `../` traversal both fail — a traversal path recorded as touched
    poisons every later unit_complete with a crash (S5)."""
    p = Path(rel)
    if p.is_absolute():
        return False
    root = Path(root).resolve()
    try:
        (root / p).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_file_paths(root, evt):
    """Root-relative paths at ingress: node IDs in edges.jsonl and git notes
    must be stable logical IDs (§5.7), never machine-specific absolutes."""
    root = Path(root).resolve()
    for f in evt["payload"]["files"]:
        p = Path(f["path"])
        if p.is_absolute():
            try:
                f["path"] = str(p.resolve().relative_to(root))
            except ValueError:
                pass  # outside the repo: left as-is, gates will flag it


def _snapshot_slice_baseline(root, sidecar, slice_id):
    """G6 baseline: public symbols per module at slice start (first Phase 1).
    The source_hash rides along so G6 can tell real drift (source changed)
    from extractor format skew (symbols changed, bytes did not) — W8."""
    from .registry import load_registry, public_symbols
    for entry in load_registry(root):
        if entry.get("status") == "built" and entry.get("shadow"):
            syms = public_symbols(root, entry)
            if syms is None:
                continue
            src_hash = None
            try:
                src_hash = json.loads(
                    (Path(root) / entry["shadow"]).read_text()).get("source_hash")
            except (OSError, json.JSONDecodeError):
                pass
            sidecar.snapshot_set(slice_id, entry["id"],
                                 {"symbols": syms, "source_hash": src_hash})


def _regenerate_touched(root, sidecar, session, slice_id, config):
    """Stop hook duties: regenerate shadows for touched files, append
    touches + uses edges (feeding G5 and the close-slice reconciliation)."""
    from .extractor.engine import RegistryIndex, extract_path
    from .graph import append_edge, load_edges
    from .registry import load_registry
    touched = sidecar.touched_paths(session_id=session)
    if not touched:
        return
    registry = load_registry(root)
    index = RegistryIndex(registry)
    existing = {(e["type"], e["from"], e["to"]) for e in load_edges(root)}

    def add_once(etype, frm, to):
        if (etype, frm, to) not in existing:
            append_edge(root, etype, frm, to)
            existing.add((etype, frm, to))

    for rel in sorted(touched):
        if not rel_in_root(root, rel):
            continue  # legacy poison rows (absolute OR traversal): skip, never crash
        p = Path(root) / rel
        if not p.exists():
            continue
        shadow, _f = extract_path(root, p, config)
        if shadow is None or not slice_id:
            continue
        add_once("touches", f"slice:{slice_id}", f"file:{rel}")
        own = next((e for e in registry if e.get("source") == rel), None)
        for imp in shadow.get("imports", []):
            target = index.match(imp)
            if target is not None and (own is None or own["id"] != target["id"]):
                add_once("uses", f"slice:{slice_id}", f"module:{target['id']}")


# ---------------------------------------------------------------- CLI shim
def run_stdin(root, stdin_text: str) -> tuple:
    """Returns (exit_code, stdout_json_str). Malformed input -> exit 2."""
    try:
        raw = json.loads(stdin_text)
    except json.JSONDecodeError as exc:
        return 2, json.dumps({"error": f"invalid JSON on stdin: {exc}"})
    try:
        verdict = handle_event(raw, root)
    except EventError as exc:
        return 2, json.dumps({"error": str(exc)})
    return 0, json.dumps(verdict, sort_keys=True)
