"""C6 — Gates: deterministic checks bound to engine events.

Each gate declares preferred/fallback events (T1 portability: post-only
frameworks run pre_change gates at post_change in degraded revert-and-retry
mode). Every blocking finding cites a rule_ref — enforced by the engine.
"""
from __future__ import annotations

from pathlib import Path

from .. import get_slice, load_boundaries, load_decisions
from ..registry import load_registry


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
        self._context_loaded = None

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
    def context_loaded(self) -> set:
        if self._context_loaded is None:
            self._context_loaded = (self.sidecar.context_get(self.session_id) |
                                    set(self.payload.get("context_loaded", [])))
        return self._context_loaded

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


def all_gates():
    from . import (g1_manifest, g2_context, g3_scope, g4_freshness,
                   g5_conformance, g6_drift, g7_derivation, g8_coverage)
    return [g1_manifest, g2_context, g3_scope, g4_freshness,
            g5_conformance, g6_drift, g7_derivation, g8_coverage]


def gates_for_event(event: str, degraded: bool = False):
    picked = []
    for g in all_gates():
        if event in g.GATE["preferred"]:
            picked.append(g)
        elif degraded and event in g.GATE.get("fallback", ()):
            picked.append(g)
    return picked


def run_gates(root, event: dict, config: dict, sidecar) -> list:
    degraded = bool(config.get("gates", {}).get("degraded_mode", False))
    ctx = GateContext(root, event, config, sidecar)
    findings = []
    for gate in gates_for_event(event["event"], degraded):
        findings.extend(gate.check(ctx))
    return findings
