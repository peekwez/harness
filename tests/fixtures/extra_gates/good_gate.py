"""Fixture: a well-formed repo-local gate (the `gates.extra` contract, D-007).

Mirrors the shape kente ships as K1: any touched path that would capture the
`kente` PEP 420 namespace is a blocking finding citing ADR-002.
"""
from __future__ import annotations

GATE = {"id": "K1", "rule_ref": "adr:002",
        "preferred": ["pre_change", "unit_complete"],
        "fallback": ["post_change"]}

NAMESPACE_FILE = "src/kente/__init__.py"


def run(ctx) -> list:
    """Block any touched path that captures the `kente` namespace.

    Args:
        ctx: The engine's GateContext for this event.

    Returns:
        One blocking finding per offending path.
    """
    from engine.events import make_finding

    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if rel == NAMESPACE_FILE:
            findings.append(make_finding(
                "NAMESPACE_CAPTURE", GATE["rule_ref"],
                f"{rel} captures the kente namespace package",
                severity="block", key=rel))
    return findings
