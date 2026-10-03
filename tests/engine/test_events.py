"""C1 acceptance: golden in/out for all five events; malformed -> exit 2;
verdict merging property; warm pre_change < 150 ms."""
import itertools
import json
import time

import pytest

from conftest import loaded_context, make_event, run_cli
from engine.events import (EVENTS, EventError, VerdictError, handle_event,
                           make_finding, merge_verdicts, validate_event,
                           verdict_for)

GOLDEN = {
    # event -> (needs_phase1_first, files, expected_verdict, expected_codes ⊆)
    "session_start": (False, [], "allow", set()),
    "pre_context": (False, [], "allow", set()),
    "pre_change": (True, ["orders.py"], "allow", set()),
    "post_change": (True, ["orders.py"], "allow_with_findings", set()),
    "unit_complete": (True, [], "allow", set()),
}


def test_golden_round_trip_all_five_events(toy):
    for event in EVENTS:
        phase1, files, expected, codes = GOLDEN[event]
        session = f"golden-{event}"
        if phase1:
            loaded_context(toy, session=session)
        if event == "post_change":
            # post_change follows the write of a declared file
            (toy / "orders.py").write_text(
                "def create_order(sku):\n    return {'sku': sku}\n")
        v = handle_event(make_event(event, session=session, files=files), toy)
        assert v["verdict"] in ("allow", "allow_with_findings"), \
            f"{event}: {v['findings']}"
        for f in v["findings"]:
            assert f["rule_ref"], f
        # round-trip: verdict is valid JSON and schema-complete
        parsed = json.loads(json.dumps(v))
        assert set(parsed) == {"verdict", "findings", "injections"}


def test_golden_fixture_files(toy, plugin_root):
    fixtures = sorted((plugin_root / "tests" / "fixtures" / "events").glob("*.json"))
    assert len(fixtures) == 5
    for fx in fixtures:
        pair = json.loads(fx.read_text())
        session = f"fx-{fx.stem}"
        if pair.get("phase1_first"):
            loaded_context(toy, session=session)
        evt = pair["event"]
        evt["session_id"] = session
        v = handle_event(evt, toy)
        assert v["verdict"] == pair["expect"]["verdict"], (fx.name, v["findings"])
        got_codes = {f["code"] for f in v["findings"]}
        assert set(pair["expect"]["codes_subset"]) <= got_codes or \
            not pair["expect"]["codes_subset"]


def test_malformed_input_exit_2(toy):
    for bad in ("not json", '{"event": "bogus"}', '{"event": "pre_change"}'):
        proc = run_cli("event", root=toy, stdin=bad)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert "error" in json.loads(proc.stdout)


def test_validate_event_rejects():
    with pytest.raises(EventError):
        validate_event({"event": "nope", "session_id": "s"})
    with pytest.raises(EventError):
        validate_event({"event": "pre_change"})
    with pytest.raises(EventError):
        validate_event({"event": "pre_change", "session_id": "s",
                        "payload": {"files": [42]}})


def test_verdict_merging_property():
    """Most restrictive wins, for every combination up to length 3."""
    rank = {"allow": 0, "allow_with_findings": 1, "block": 2}
    def mk(v):
        findings = []
        if v != "allow":
            findings = [make_finding("UNDECLARED_FILE", "gate:G3", "m",
                                     severity="block" if v == "block" else "gate")]
        return {"verdict": v, "findings": findings, "injections": []}
    for combo in itertools.chain.from_iterable(
            itertools.product(rank, repeat=n) for n in (1, 2, 3)):
        merged = merge_verdicts([mk(v) for v in combo])
        assert merged["verdict"] == max(combo, key=lambda v: rank[v])
        assert len(merged["findings"]) == sum(1 for v in combo if v != "allow")


def test_blocking_finding_without_rule_ref_rejected():
    f = make_finding("UNDECLARED_USE", "gate:G5", "m", severity="block")
    f["rule_ref"] = ""
    with pytest.raises(VerdictError):
        verdict_for([f])




def test_phase1_reinjection_deduped_per_session(toy):
    """SessionStart re-runs on resume (same session_id) and pre_context fires
    every prompt: once the manifest is loaded, injections must not repeat."""
    first = handle_event(make_event("session_start", session="dedupe"), toy)
    assert first["injections"]
    resumed = handle_event(make_event("session_start", session="dedupe"), toy)
    assert resumed["injections"] == []
    prompt = handle_event(make_event("pre_context", session="dedupe"), toy)
    assert prompt["injections"] == []
    # a different session still gets its own Phase-1 injection
    other = handle_event(make_event("session_start", session="dedupe-2"), toy)
    assert other["injections"]


@pytest.mark.parametrize("changed", ["decision", "slice"])
def test_phase1_resends_only_the_changed_block(toy, changed):
    from engine import read_jsonl, write_jsonl
    event = make_event("pre_context", session="updated-content")
    first = handle_event(event, toy)
    assert len(first["injections"]) == 4
    if changed == "decision":
        path = toy / ".harness" / "decisions.jsonl"
        rows = read_jsonl(path)
        rows[0]["answer"] = "Always include a trace correlation identifier."
        header = "=== decisions in scope ==="
    else:
        path = toy / ".harness" / "backlog.jsonl"
        rows = read_jsonl(path)
        rows[0]["predicted_files"].append("orders_cli.py")
        header = "=== slice slice-042 ==="
    write_jsonl(path, rows)
    updated = handle_event(event, toy)
    assert [t.splitlines()[0] for t in updated["injections"]] == [header]
    assert handle_event(event, toy)["injections"] == []


def test_fifteen_prompt_session_injects_once_then_only_deltas(toy):
    from engine import read_jsonl, write_jsonl
    run_cli("slice", "--slice", "slice-042", "--session", "fifteen", root=toy)
    sizes = []
    for i in range(15):
        if i == 7:
            path = toy / ".harness" / "decisions.jsonl"
            rows = read_jsonl(path)
            rows[0]["answer"] = "Use verb_noun span names."
            write_jsonl(path, rows)
        v = handle_event(make_event("pre_context", session="fifteen",
                                    prompt=f"prompt {i}"), toy)
        sizes.append(len(v["injections"]))
    assert sizes[0] == 4      # decisions, non-goals, slice, modules
    assert sizes[7] == 1      # only the changed decisions block
    assert sum(sizes) == 5


def test_last_injection_size_is_recorded(toy):
    from engine.events import Sidecar
    v = handle_event(make_event("pre_context", session="size"), toy)
    sc = Sidecar(toy)
    try:
        assert sc.state_get("__context__", "last_injection_chars") == \
            len("\n\n".join(v["injections"]))
    finally:
        sc.close()


def test_over_cap_injection_adds_an_advisory_finding(toy):
    from conftest import oversize_slice
    oversize_slice(toy)
    v = handle_event(make_event("pre_context", session="cap"), toy)
    hits = [f for f in v["findings"] if f["code"] == "CONTEXT_OVER_CAP"]
    assert hits and hits[0]["severity"] == "advisory"
    assert v["verdict"] == "allow_with_findings"
    assert len("\n\n".join(v["injections"])) <= 9000


def test_rebinding_mid_session_sends_only_the_changed_blocks(toy):
    from engine import read_jsonl, write_jsonl
    path = toy / ".harness" / "backlog.jsonl"
    rows = read_jsonl(path)
    rows.append({"id": "slice-043", "spec": "spec-007", "title": "span export",
                 "status": "planned", "declares_dep": ["telemetry"],
                 "acceptance": ["tests/slices/042_orders.py"],
                 "predicted_files": ["spans.py"], "depends_on": [],
                 "worktree": None})
    write_jsonl(path, rows)
    run_cli("slice", "--slice", "slice-042", "--session", "rebind", root=toy)
    first = handle_event(make_event("pre_context", session="rebind",
                                    slice_id=None), toy)
    assert len(first["injections"]) == 4
    run_cli("slice", "--slice", "slice-043", "--session", "rebind", root=toy)
    second = handle_event(make_event("pre_context", session="rebind",
                                     slice_id=None), toy)
    assert [t.splitlines()[0] for t in second["injections"]] == [
        "=== slice slice-043 ===",
        "=== modules (full context: harness resolve --module <id>) ==="]


def test_warm_pre_change_under_150ms(toy):
    loaded_context(toy, session="warm")
    evt = make_event("pre_change", session="warm", files=["orders.py"])
    handle_event(evt, toy)  # warm caches
    t0 = time.perf_counter()
    v = handle_event(evt, toy)
    elapsed = time.perf_counter() - t0
    assert v["verdict"] == "allow", v["findings"]
    assert elapsed < 0.150, f"warm pre_change took {elapsed*1000:.0f} ms"


def test_resolve_reset_makes_the_next_prompt_inject_again(toy):
    event = make_event("pre_context", session="compact")
    assert handle_event(event, toy)["injections"]
    assert handle_event(event, toy)["injections"] == []
    proc = run_cli("resolve", "--reset", "--session", "compact", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout) == {"reset": True, "session": "compact",
                                       "cleared": 1}
    assert len(handle_event(event, toy)["injections"]) == 4
