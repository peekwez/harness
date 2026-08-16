"""Repo-local gates listed under `gates.extra` (ADR-002, decision row D-007).

A consumer repo teaches the engine its own invariants by listing gate modules
in `.harness/config.yaml`:

```yaml
gates:
  extra: [".harness/gates/namespace.py", "kente_gates.dag:GATE"]
```

Each entry exposes the same contract as the builtin pack — a `GATE` dict with
`id` / `preferred` (+ optional `fallback`) and a `run(ctx)` returning findings.

Two things fail **closed and loud**, never as a silent skip, and neither stops
the builtin gates from running:

* `EXTRA_GATE_LOAD_ERROR` — the entry could not be imported or its declaration
  is malformed. Path entries are **repo-relative and contained**: the resolved
  path must stay under the repo root, so `../` traversal, absolute paths and
  escaping symlinks are rejected before any code executes.
* `EXTRA_GATE_RUN_ERROR` — the gate raised, returned a non-list, or produced a
  finding the engine's own `validate_finding` rejects (a blocking finding with
  no `rule_ref` is the case that matters: D-003/D-007 hold for repo-local
  gates exactly as for G1-G8).
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import sys
import traceback
from pathlib import Path

from ..events import EVENTS, VerdictError, make_finding, validate_finding

LOAD_ERROR_CODE = "EXTRA_GATE_LOAD_ERROR"
RUN_ERROR_CODE = "EXTRA_GATE_RUN_ERROR"
RULE_REF = "adr:002"
_MESSAGE_LIMIT = 600
_UNCONTAINED = "must be repo-relative and inside the repo"


class ExtraGate:
    """Module-like adapter presenting a repo-local gate as a builtin gate.

    Builtin gates are modules carrying `GATE` and `check(ctx)`. Repo-local
    gates may name their declaration with the `module:ATTR` entry form and
    expose `run(ctx)` (the D-007 contract) instead of `check`; this wrapper
    normalises both so every caller can treat gates uniformly.

    Attributes:
        entry: The `gates.extra` entry string this gate was loaded from.
        module: The imported module object.
        GATE: The gate declaration dict (id / preferred / fallback / rule_ref).
    """

    def __init__(self, entry: str, module, gate: dict, fn):
        self.entry = entry
        self.module = module
        self.GATE = gate
        self._fn = fn

    def check(self, ctx) -> list:
        """Run the gate against one event.

        Args:
            ctx: The engine's GateContext for the event being dispatched.

        Returns:
            The findings the gate produced.
        """
        return self._fn(ctx)

    def __repr__(self) -> str:
        return f"<ExtraGate {self.GATE.get('id')!r} from {self.entry!r}>"


def extra_entries(config) -> list:
    """The raw `gates.extra` list from a loaded engine config.

    Args:
        config: Loaded engine config, or None.

    Returns:
        The configured entries (a lone string is treated as a one-item list).

    Raises:
        TypeError: The key is present but is neither a string nor a sequence.
    """
    raw = ((config or {}).get("gates") or {}).get("extra") or []
    if isinstance(raw, str):
        return [raw]
    if not isinstance(raw, (list, tuple)):
        raise TypeError(
            f"gates.extra must be a list of entry strings, got "
            f"{type(raw).__name__}")
    return list(raw)


def load_extra_gates(root, config, reserved_ids=None) -> tuple:
    """Load every gate listed under `gates.extra`.

    Args:
        root: Repo root; a relative path entry resolves against it.
        config: Loaded engine config (`engine.load_config`).
        reserved_ids: Gate ids already taken — the builtin pack — so a
            repo-local gate cannot shadow G1-G8.

    Returns:
        A `(gates, findings)` pair: the successfully loaded gates in config
        order, and one blocking `EXTRA_GATE_LOAD_ERROR` finding per entry
        that failed to load or failed validation.
    """
    try:
        entries = extra_entries(config)
    except TypeError as exc:
        return [], [_load_error("gates.extra", exc)]
    if not entries:
        return [], []

    taken = set(reserved_ids or ())
    gates, findings = [], []
    for entry in entries:
        gate, problem = _load_one(root, entry, taken)
        if problem is not None:
            findings.append(problem)
            continue
        taken.add(gate.GATE["id"])
        gates.append(gate)
    return gates, findings


def run_gate(gate: ExtraGate, ctx) -> list:
    """Run one repo-local gate, converting any misbehaviour into a finding.

    A third-party gate must never take the engine down with it, and must not
    smuggle a malformed finding into a verdict. An exception, a non-list
    return, or a finding the engine's own `validate_finding` rejects is
    reported as a blocking `EXTRA_GATE_RUN_ERROR` naming the entry, so the
    event still yields a verdict and the failure is visible.

    Args:
        gate: The loaded gate.
        ctx: The engine's GateContext for the event being dispatched.

    Returns:
        The gate's validated findings, or a single blocking run-error finding.
    """
    try:
        findings = gate.check(ctx)
    except Exception as exc:  # noqa: BLE001 - third-party code, fail loud
        return [_run_error(gate.entry, exc)]
    if not isinstance(findings, list):
        return [_run_error(gate.entry, TypeError(
            f"run(ctx) returned {type(findings).__name__}, "
            f"expected a list of findings"))]
    for finding in findings:
        problem = _finding_problem(finding)
        if problem is not None:
            return [_run_error(gate.entry, problem)]
    return findings


def _finding_problem(finding):
    """The reason a gate's finding is unusable, or None if it is valid.

    Args:
        finding: One item from a gate's return value.

    Returns:
        An exception describing the problem, or None.
    """
    if not isinstance(finding, dict):
        return TypeError(
            f"finding must be an object, got {type(finding).__name__}")
    try:
        validate_finding(finding)
    except VerdictError as exc:
        return exc
    return None


def verify_extra_findings(root, config, slices) -> list:
    """Repo-local gate findings for `harness verify` (the CI entry point).

    Load errors are always reported. Loaded gates then run once per **closed**
    slice against a synthetic `unit_complete` event whose `payload.files` is
    that slice's `predicted_files` union `acceptance` (existing files only),
    so repo invariants are enforced on landed work even when the edits came
    from a tool the hooks never saw.

    A gate that declares only `pre_change` therefore does not run in CI —
    there is no edit to intercept. Give a gate `unit_complete` in `preferred`
    (or in `fallback` with `gates.degraded_mode`) to have it checked here.

    Args:
        root: Repo root.
        config: Loaded engine config.
        slices: Backlog rows; only rows with `status: closed` are checked.

    Returns:
        Load errors plus every finding the selected gates produced.
    """
    from . import GateContext, builtin_gates

    gates, findings = load_extra_gates(
        root, config, reserved_ids={g.GATE["id"] for g in builtin_gates()})
    findings = list(findings)
    if not gates:
        return findings

    degraded = bool((config.get("gates") or {}).get("degraded_mode", False))
    picked = [g for g in gates
              if "unit_complete" in g.GATE["preferred"]
              or (degraded and "unit_complete" in (g.GATE.get("fallback") or ()))]
    if not picked:
        return findings

    root = Path(root)
    sidecar = _NullSidecar()
    for sl in slices:
        if sl.get("status") != "closed":
            continue
        paths = _slice_files(root, sl)
        event = {
            "event": "unit_complete",
            "session_id": f"verify:{sl['id']}",
            "work_unit_id": sl["id"],
            "payload": {"files": [{"path": p, "proposed_content_hash": None}
                                  for p in paths],
                        "context_loaded": [], "diff": None, "prompt": None},
        }
        ctx = GateContext(root, event, config, sidecar)
        for gate in picked:
            findings.extend(run_gate(gate, ctx))
    return findings


# ----------------------------------------------------------------- internals
class _NullSidecar:
    """Read-only stand-in for the sidecar.

    `harness verify` runs in CI with no session state and must not create the
    gitignored SQLite file as a side effect of a read-only check.
    """

    def context_get(self, session_id) -> set:
        """No session ever loaded context in a CI verifier."""
        return set()


def _slice_files(root: Path, sl: dict) -> list:
    """Existing repo-relative files a closed slice declared.

    Declared paths are substrate rows, so they can be absolute or contain
    `../` — `engine.events.rel_in_root` screens both out before any glob,
    because `Path.glob` on an absolute pattern raises on 3.12 and an escaping
    path has no business reaching a repo-local gate.

    Args:
        root: Repo root.
        sl: A backlog row.

    Returns:
        Sorted relative paths from `predicted_files` + `acceptance` that
        exist on disk; glob patterns in `acceptance` are expanded.
    """
    from ..events import rel_in_root

    declared = list(sl.get("predicted_files") or []) + \
        list(sl.get("acceptance") or [])
    out = set()
    for item in declared:
        if not isinstance(item, str) or not rel_in_root(root, item):
            continue
        if "*" in item:
            out.update(str(p.relative_to(root)) for p in root.glob(item)
                       if p.is_file())
        elif (root / item).exists():
            out.add(item)
    return sorted(out)


def _load_one(root, entry, taken: set) -> tuple:
    """Import and validate one `gates.extra` entry.

    Args:
        root: Repo root, or None when only module entries are resolvable.
        entry: The config entry string.
        taken: Gate ids already claimed.

    Returns:
        `(ExtraGate, None)` on success, `(None, finding)` on any failure.
    """
    try:
        module, attr = _import_entry(root, entry)
        gate = getattr(module, attr)
        _validate_gate(gate, taken)
        fn = getattr(module, "run", None) or getattr(module, "check", None)
        if not callable(fn):
            raise TypeError(
                f"module {module.__name__!r} defines no callable run(ctx) "
                f"(or check(ctx))")
        return ExtraGate(entry, module, gate, fn), None
    except Exception as exc:  # noqa: BLE001 - third-party code, fail loud
        return None, _load_error(entry, exc)


def _import_entry(root, entry):
    """Resolve an entry to `(module, gate_attr_name)`.

    A `.py` path (or anything containing a path separator) is loaded from
    file and must be repo-relative and contained; anything else is a dotted
    module name. Either form may name the declaration attribute with a
    trailing `:ATTR` (default `GATE`).

    Args:
        root: Repo root for path entries, or None.
        entry: The config entry string.

    Returns:
        The imported module and the attribute holding its GATE dict.

    Raises:
        TypeError: The entry is not a non-empty string.
        ValueError: A path entry is absolute or escapes the repo.
        FileNotFoundError: A path entry does not exist.
        ImportError: The module could not be imported.
    """
    if not isinstance(entry, str) or not entry.strip():
        raise TypeError(
            f"gates.extra entry must be a non-empty string, got {entry!r}")
    spec, _sep, attr = entry.partition(":")
    attr = attr or "GATE"
    if spec.endswith(".py") or "/" in spec or os.sep in spec:
        return _import_path(root, spec), attr
    return importlib.import_module(spec), attr


def _import_path(root, spec: str):
    """Load a gate module from a contained, repo-relative `.py` path.

    Containment is the security boundary: a `gates.extra` entry names code
    the engine will EXECUTE, so the resolved path must stay under the repo
    root. Absolute paths are rejected outright, and resolution happens before
    the containment check so `../` traversal and escaping symlinks are caught
    before the module is executed.

    Args:
        root: Repo root.
        spec: The path portion of the config entry.

    Returns:
        The executed module.

    Raises:
        ImportError: No root was supplied, or the module could not be loaded.
        ValueError: The entry is absolute or resolves outside the repo.
        FileNotFoundError: The path does not exist.
    """
    if root is None:
        raise ImportError(
            f"gates.extra path {spec!r} needs a repo root; pass root= to "
            f"all_gates()/gates_for_event()")
    if Path(spec).is_absolute():
        raise ValueError(f"path entries {_UNCONTAINED}; {spec!r} is absolute")
    base = Path(root).resolve()
    path = (base / spec).resolve()
    if path != base and base not in path.parents:
        raise ValueError(
            f"path entries {_UNCONTAINED}; {spec!r} resolves to {path}, "
            f"outside {base}")
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    name = "harness_extra_gate_" + hashlib.sha1(
        str(path.resolve()).encode()).hexdigest()[:12]
    ispec = importlib.util.spec_from_file_location(name, path)
    if ispec is None or ispec.loader is None:
        raise ImportError(f"cannot load a Python module from {path}")
    module = importlib.util.module_from_spec(ispec)
    sys.modules[name] = module
    try:
        ispec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _validate_gate(gate, taken: set) -> None:
    """Reject a declaration the dispatcher could not honour.

    Args:
        gate: The candidate GATE dict.
        taken: Gate ids already claimed by builtin or earlier extra gates.

    Raises:
        TypeError: Wrong shape for the dict or one of its fields.
        ValueError: Missing required field, unknown event, or duplicate id.
    """
    if not isinstance(gate, dict):
        raise TypeError(f"GATE must be a dict, got {type(gate).__name__}")
    for field in ("id", "preferred"):
        if not gate.get(field):
            raise ValueError(f"GATE is missing required field {field!r}")
    if not isinstance(gate["id"], str):
        raise TypeError(
            f"GATE['id'] must be a string, got {type(gate['id']).__name__}")
    if gate["id"] in taken:
        raise ValueError(
            f"GATE['id'] {gate['id']!r} is already taken by another gate")
    for field in ("preferred", "fallback"):
        value = gate.get(field) or ()
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            raise TypeError(f"GATE[{field!r}] must be a list of event names")
        unknown = [e for e in value if e not in EVENTS]
        if unknown:
            raise ValueError(
                f"GATE[{field!r}] names unknown events {unknown}; "
                f"expected {list(EVENTS)}")


def _load_error(entry, exc: BaseException) -> dict:
    """Build the blocking finding for an entry that could not be loaded."""
    message = (f"gates.extra entry {entry!r} failed to load: "
               f"{type(exc).__name__}: {exc}")
    return make_finding(LOAD_ERROR_CODE, RULE_REF, message[:_MESSAGE_LIMIT],
                        severity="block", key=f"extra|{entry}")


def _run_error(entry, exc: BaseException) -> dict:
    """Build the blocking finding for a gate that misbehaved while running."""
    frame = _last_frame(exc)
    where = f" at {frame}" if frame else ""
    message = (f"gates.extra entry {entry!r} failed while running{where}: "
               f"{type(exc).__name__}: {exc}")
    return make_finding(RUN_ERROR_CODE, RULE_REF, message[:_MESSAGE_LIMIT],
                        severity="block", key=f"extra-run|{entry}")


def _last_frame(exc: BaseException):
    """`file:line` of the deepest traceback frame, or None if there is none."""
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None
    return f"{frames[-1].filename}:{frames[-1].lineno}"
