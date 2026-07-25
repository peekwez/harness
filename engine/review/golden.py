"""Golden-set replay: past diffs + adjudicated verdicts re-run whenever
rubrics, exemplars, or models change. Any changed verdict fails —
reviewer changes get reviewed.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import HarnessError


class ReplayModel:
    """Replays stored model outputs keyed by (rubric question, sample)."""

    def __init__(self, stored: dict):
        self.stored = stored

    def __call__(self, question: str, context: dict) -> dict:
        outs = self.stored.get(question)
        if outs is None:
            # Fail loud: a reworded rubric must break replay, not vacuously pass.
            raise HarnessError(
                f"golden pair has no stored model output for rubric question "
                f"{question[:80]!r} — rubrics changed; re-adjudicate the golden set")
        if isinstance(outs, list):
            i = context.get("sample", 0)
            return outs[min(i, len(outs) - 1)]
        return outs


def replay(root, golden_dir, config) -> dict:
    """Re-run stored diff+verdict pairs; any changed verdict fails."""
    from .layer0 import assemble
    from .rubrics import run_review

    golden_dir = Path(golden_dir)
    pairs = sorted(golden_dir.glob("*.json"))
    if not pairs:
        raise HarnessError(f"no golden pairs in {golden_dir} (fail closed)")
    results = []
    for p in pairs:
        fixture = json.loads(p.read_text())
        expected = fixture["verdict"]
        model = ReplayModel(fixture.get("model_outputs", {}))
        facts = fixture.get("facts")
        if facts is None:
            facts = assemble(root, fixture.get("diff", ""), fixture["slice"], config)
        # Replay is a regression check: it must never mutate the substrate.
        got = run_review(root, facts, config, model=model, record_parks=False)
        results.append({
            "pair": p.name,
            "expected": expected,
            "got": got["verdict"],
            "stable": got["verdict"] == expected,
        })
    failed = [r for r in results if not r["stable"]]
    return {"passed": not failed, "pairs": len(results), "failed": failed,
            "results": results}
