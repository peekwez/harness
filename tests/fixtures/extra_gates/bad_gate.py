"""Fixture: a repo-local gate that explodes on import (fail-closed path).

Loading this entry must produce exactly one blocking EXTRA_GATE_LOAD_ERROR
finding while the builtin gate pack keeps running.
"""
from __future__ import annotations

GATE = {"id": "K9", "rule_ref": "adr:002", "preferred": ["pre_change"],
        "fallback": []}

raise RuntimeError("bad_gate: deliberate import failure")


def run(ctx) -> list:
    """Never reached — the module raises above."""
    return []
