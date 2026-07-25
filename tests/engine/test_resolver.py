"""C5 acceptance: determinism; budget never exceeded; superseded guidance
absent; degradation order (docstrings before modules)."""
import json

import pytest

from engine import load_config, token_estimate
from engine.resolver import resolve


def test_same_slice_same_substrate_byte_identical(toy):
    config = load_config(toy)
    a = json.dumps(resolve(toy, "slice-042", config), sort_keys=True)
    b = json.dumps(resolve(toy, "slice-042", config), sort_keys=True)
    assert a == b


def test_budget_never_exceeded(toy):
    config = load_config(toy)
    for budget in (10, 40, 80, 150, 300, 800, 8000):
        config["resolver"]["budget_tokens"] = budget
        out = resolve(toy, "slice-042", config)
        actual = sum(token_estimate(b) for b in out["injections"])
        assert actual <= budget, f"budget {budget}: emitted {actual}"
        assert out["token_estimate"] <= budget


def test_superseded_guidance_absent_surviving_present(toy):
    """telemetry is built and supersedes adr/007#s2; #s3 survives (it is not
    signature-expressible)."""
    config = load_config(toy)
    out = resolve(toy, "slice-042", config)
    joined = "\n".join(out["injections"])
    assert "SUPERSEDABLE-GUIDANCE-MARKER" not in joined
    assert "SURVIVING-GUIDANCE-MARKER" in joined
    assert any("shadow:telemetry" == c for c in out["context_loaded"])


def test_planned_entry_uses_guidance_not_shadow(toy):
    config = load_config(toy)
    out = resolve(toy, "slice-042", config)
    joined = "\n".join(out["injections"])
    # config is planned: its guidance section s1 appears; no config shadow block
    assert "Telemetry section one" in joined
    assert "=== shadow:config" not in joined


def test_decision_rows_for_touched_domains(toy):
    config = load_config(toy)
    out = resolve(toy, "slice-042", config)
    joined = "\n".join(out["injections"])
    assert "D-041" in joined and "snake_case verb_noun" in joined
    assert "decision:D-041" in out["context_loaded"]


def test_durable_memories_ranked_below_shadows(toy):
    from engine import append_jsonl
    append_jsonl(toy / ".harness" / "memory" / "durable.jsonl", {
        "id": "mem-aaa", "scope": "durable", "slice_id": "slice-000",
        "commit": None, "kind": "reasoning",
        "content": "DURABLE-MEMORY-MARKER: spans must nest",
        "attempt": None,
        "edges": [{"type": "remembers", "to": "module:telemetry"}]})
    config = load_config(toy)
    out = resolve(toy, "slice-042", config)
    joined = out["injections"]
    mem_idx = next(i for i, b in enumerate(joined) if "DURABLE-MEMORY-MARKER" in b)
    shadow_idx = next(i for i, b in enumerate(joined) if "shadow:telemetry" in b)
    assert shadow_idx < mem_idx
    assert "memory:mem-aaa" in out["context_loaded"]


def test_degradation_drops_docstrings_before_modules(toy):
    config = load_config(toy)
    full = resolve(toy, "slice-042", config)
    shadow_block_full = next(b for b in full["injections"]
                             if "shadow:telemetry" in b)
    assert "# Emit a span" in shadow_block_full  # docstring present at full budget

    # shrink budget until the shadow degrades but survives
    for budget in range(full["token_estimate"] - 1, 10, -3):
        config["resolver"]["budget_tokens"] = budget
        out = resolve(toy, "slice-042", config)
        blocks = [b for b in out["injections"] if "shadow:telemetry" in b]
        if blocks and "# Emit a span" not in blocks[0]:
            return  # degraded (no docstring) before being dropped entirely
        if not blocks:
            pytest.fail("module dropped before docstring degradation was tried")
    pytest.fail("never hit the degradation window")


def test_missing_guidance_file_fails_loud(toy):
    from engine import SubstrateMissing
    (toy / "adr" / "007-telemetry.md").unlink()
    with pytest.raises(SubstrateMissing, match="guidance_ref"):
        resolve(toy, "slice-042", load_config(toy))


def test_missing_built_shadow_fails_loud(toy):
    from engine import SubstrateMissing
    (toy / ".harness" / "shadows" / "telemetry.py.json").unlink()
    with pytest.raises(SubstrateMissing, match="shadow"):
        resolve(toy, "slice-042", load_config(toy))


def test_missing_declared_dep_fails_loud(toy):
    from engine import read_jsonl, write_jsonl, SubstrateMissing
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["declares_dep"].append("ghost")
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    with pytest.raises(SubstrateMissing, match="ghost"):
        resolve(toy, "slice-042", load_config(toy))
