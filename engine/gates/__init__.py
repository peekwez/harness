"""C6 — Gates: deterministic checks bound to engine events.

Each gate declares preferred/fallback events (T1 portability: post-only
frameworks run pre_change gates at post_change in degraded revert-and-retry
mode). Every blocking finding cites a rule_ref — enforced by the engine.

The pack is G1, G3, G5, G6 and G8 plus whatever the repo lists under
`gates.extra` (ADR-002 / D-007) — see `engine/gates/extra.py`. G2, G4 and
G7 were removed in 0.10; their ids stay reserved so old override records
keep their meaning.
"""
from __future__ import annotations

from pathlib import Path

from .. import (DEFAULT_EXEMPT_PATHS, HarnessError, get_slice,
                load_boundaries, load_decisions)
from ..registry import load_registry
from .extra import ExtraGate, cited_rules, load_extra_gates, run_gate


def exempt_paths(config) -> tuple:
    """The `gates.exempt_paths` prefixes in force (spec 5.6).

    Args:
        config: Loaded engine config, or None.

    Returns:
        The configured prefixes, or `DEFAULT_EXEMPT_PATHS` when the key is
        absent.

    Raises:
        HarnessError: The key is present but is not a list of non-empty
            strings. A gate must never guess which files are exempt.
    """
    raw = ((config or {}).get("gates") or {}).get("exempt_paths")
    if raw is None:
        return DEFAULT_EXEMPT_PATHS
    if (isinstance(raw, str) or not isinstance(raw, (list, tuple))
            or not all(isinstance(p, str) and p.strip() for p in raw)):
        raise HarnessError(
            "gates.exempt_paths must be a list of path prefixes, for "
            "example [\"docs/\", \"tests/\"]. Fix .harness/config.yaml.")
    return tuple(raw)


def exempt(rel: str, config) -> bool:
    """True when a repo-relative path starts with an exempt prefix."""
    return str(rel).replace("\\", "/").startswith(exempt_paths(config))


class GateContext:
    """Lazy substrate access shared by all gates in one event dispatch."""

    def __init__(self, root, event: dict, config: dict, sidecar):
        self.root = Path(root)
        self.event = event["event"]
        self.session_id = event["session_id"]
        self.work_unit_id = event.get("work_unit_id")
        self.payload = event["payload"]
        self.config = config
        self.sidecar = sidecar
        self._registry = None
        self._slice = None
        self._decisions = None
        self._boundaries = None
        self._cited = None

    @property
    def registry(self):
        if self._registry is None:
            self._registry = load_registry(self.root)
        return self._registry

    @property
    def slice(self):
        if self._slice is None and self.work_unit_id:
            self._slice = get_slice(self.root, self.work_unit_id)
        return self._slice

    @property
    def decisions(self):
        if self._decisions is None:
            self._decisions = load_decisions(self.root)
        return self._decisions

    @property
    def boundaries(self):
        if self._boundaries is None:
            self._boundaries = load_boundaries(self.root)
        return self._boundaries

    @property
    def cited(self) -> set:
        """Non-goal ids and rule refs that a `gates.extra` gate cites."""
        if self._cited is None:
            extra, _errors = load_extra_gates(
                self.root, self.config, reserved_ids=reserved_gate_ids())
            self._cited = cited_rules(extra)
        return self._cited

    def touched_files(self) -> list:
        return [f["path"] for f in self.payload.get("files", [])]

    def rel(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            try:
                return str(p.resolve().relative_to(self.root.resolve()))
            except ValueError:
                return str(p)
        return str(p)


RETIRED_GATE_IDS = frozenset({"G2", "G4", "G7"})


def builtin_gates() -> list:
    """The gates that ship with the engine, in id order."""
    from . import g1_manifest, g3_scope, g5_conformance, g6_drift, g8_coverage
    return [g1_manifest, g3_scope, g5_conformance, g6_drift, g8_coverage]


def reserved_gate_ids() -> set:
    """Ids a repo-local gate may not take: the builtins and the retired ids."""
    return {g.GATE["id"] for g in builtin_gates()} | set(RETIRED_GATE_IDS)


def all_gates(root=None, config=None) -> list:
    """Builtin gates plus every repo-local `gates.extra` gate.

    Entries that fail to load are dropped here — they are findings, not
    gates. Callers that must REPORT them (`run_gates`, `harness verify`)
    call `engine.gates.extra.load_extra_gates` directly.

    Args:
        root: Repo root; relative `gates.extra` paths resolve against it.
        config: Loaded engine config. Absent, only the builtin pack is
            returned (pre-0.8 behaviour).

    Returns:
        The gate objects, builtins first, extras in config order.
    """
    gates = builtin_gates()
    extra, _errors = load_extra_gates(
        root, config, reserved_ids=reserved_gate_ids())
    return gates + extra


def select_gates(gates: list, event: str, degraded: bool = False) -> list:
    """Filter a gate list to those bound to `event` (T1 fallback aware)."""
    picked = []
    for g in gates:
        if event in g.GATE["preferred"]:
            picked.append(g)
        elif degraded and event in g.GATE.get("fallback", ()):
            picked.append(g)
    return picked


def gates_for_event(event: str, degraded: bool = False, root=None,
                    config=None) -> list:
    """The gate pack for one event.

    Args:
        event: One of the five engine events.
        degraded: Host has no pre-change interception (T1).
        root: Repo root, for repo-local gates.
        config: Loaded engine config, for repo-local gates.

    Returns:
        The gates bound to that event.
    """
    return select_gates(all_gates(root, config), event, degraded)


def run_gates(root, event: dict, config: dict, sidecar) -> list:
    """Dispatch one event to its gate pack and collect the findings.

    Repo-local gate load failures are prepended as blocking findings so a
    broken `gates.extra` entry can never be a silent skip (D-007).
    """
    degraded = bool(config.get("gates", {}).get("degraded_mode", False))
    ctx = GateContext(root, event, config, sidecar)
    builtins = builtin_gates()
    extra, findings = load_extra_gates(
        root, config, reserved_ids=reserved_gate_ids())
    findings = list(findings)
    ctx._cited = cited_rules(extra)
    for gate in select_gates(builtins + extra, event["event"], degraded):
        if isinstance(gate, ExtraGate):
            findings.extend(run_gate(gate, ctx))
        else:
            findings.extend(gate.check(ctx))
    return findings
