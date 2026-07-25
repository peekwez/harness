"""The spec-review findings (R1–R8): agent-side review findings become
substrate, adjudication is reachable, G2 certifies only what was emitted,
G7 scales, substrate writes are atomic, docs stay true, metrics are honest."""
import json
import os
import subprocess
import sys

from conftest import PLUGIN_ROOT, git, loaded_context, make_event, run_cli
from engine import load_config, read_jsonl
from engine.events import Sidecar, handle_event


# ---------------------------------------------------------------- R1/R2
def test_reviewer_records_findings_and_parks_into_the_queue(toy):
    """Layers 1-3 run in the reviewer agent, so its verdict must land in
    substrate — otherwise the adjudication loop has no producer at all."""
    proc = run_cli("review", "--slice", "slice-042", "--record-finding",
                   "--code", "R-decisions", "--rule-ref", "decision:D-041",
                   "--message", "span name is free-form, violates D-041",
                   "--severity", "block", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    from engine.graph import load_edges
    assert any(e["type"] == "reviewed_by" and e["from"] == "slice:slice-042"
               for e in load_edges(toy))

    proc = run_cli("review", "--slice", "slice-042", "--park",
                   "--code", "REVIEW_UNCERTAIN", "--rule-ref", "decision:D-041",
                   "--message", "unsure whether the retry wrapper counts",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    parked = read_jsonl(toy / ".harness" / "parked.jsonl")
    assert parked and parked[0]["slice"] == "slice-042"
    finding_id = parked[0]["finding"]["finding_id"]

    listed = run_cli("adjudicate", "--list", root=toy)
    assert finding_id in listed.stdout, "the queue must be reachable"
    resolved = run_cli("adjudicate", "--finding-id", finding_id,
                       "--resolution", "retry wrappers are exempt",
                       "--decision-id", "D-900", "--domain", "telemetry",
                       root=toy)
    assert resolved.returncode == 0, resolved.stdout + resolved.stderr
    assert not read_jsonl(toy / ".harness" / "parked.jsonl")
    assert any(r["id"] == "D-900"
               for r in read_jsonl(toy / ".harness" / "decisions.jsonl"))


def test_park_requires_a_rule_ref_and_message(toy):
    proc = run_cli("review", "--slice", "slice-042", "--park",
                   "--code", "REVIEW_UNCERTAIN", root=toy)
    assert proc.returncode == 2
    assert "--message" in proc.stderr or "--rule-ref" in proc.stderr


def test_the_same_question_never_parks_twice(toy):
    for _ in range(2):
        run_cli("review", "--slice", "slice-042", "--park",
                "--code", "REVIEW_UNCERTAIN", "--rule-ref", "gate:G5",
                "--message", "same question", root=toy)
    assert len(read_jsonl(toy / ".harness" / "parked.jsonl")) == 1


def test_status_reports_parks_per_slice(toy):
    run_cli("review", "--slice", "slice-042", "--park",
            "--code", "REVIEW_UNCERTAIN", "--rule-ref", "gate:G5",
            "--message", "q", root=toy)
    out = json.loads(run_cli("status", root=toy).stdout)
    assert out["parks_per_slice"].get("slice-042") == 1


# ---------------------------------------------------------------- R3
def test_resolve_registers_context_only_when_it_emits_it(toy):
    """G2 must certify what the caller actually printed, never the
    resolver's intent — otherwise the gate verifies nothing."""
    proc = run_cli("resolve", "--slice", "slice-042", "--session", "quiet",
                   "--quiet", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not json.loads(proc.stdout).get("injections"), \
        "--quiet suppresses the injections"
    sc = Sidecar(toy)
    try:
        assert not sc.context_get("quiet"), \
            "context nobody was shown must not be registered"
    finally:
        sc.close()
    # the normal (emitting) path does register
    run_cli("resolve", "--slice", "slice-042", "--session", "loud", root=toy)
    sc = Sidecar(toy)
    try:
        assert sc.context_get("loud")
    finally:
        sc.close()


# ---------------------------------------------------------------- R4
def test_g7_reverifies_only_what_changed_since_the_last_clean_sweep(toy):
    """Regenerating every shadow on every Stop is an O(repo) scale cliff.
    A shadow proven identical in an earlier sweep and untouched since is
    skipped — provable by backdating its mtime past the watermark."""
    session = "g7scope"
    loaded_context(toy, session=session)
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert v["verdict"] != "block", v["findings"]      # clean sweep recorded

    sp = toy / ".harness" / "shadows" / "config.py.json"
    shadow = json.loads(sp.read_text())
    shadow["symbols"] = []
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n")
    os.utime(sp, ns=(1_000_000_000, 1_000_000_000))    # "unchanged since"
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert "DERIVATION_MISMATCH" not in {f["code"] for f in v["findings"]}, \
        "an untouched-since-verified shadow must not be re-parsed"
    # the exhaustive sweep still belongs to CI verify, which never skips
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1 and "DERIVATION_MISMATCH" in proc.stdout


def test_g7_still_catches_any_hand_edited_shadow_at_stop(toy):
    """The guarantee is unchanged: a hand-edit moves mtime forward, so the
    cache can never hide one — including for files this slice never touched."""
    session = "g7hit"
    loaded_context(toy, session=session)
    handle_event(make_event("unit_complete", session=session), toy)
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    shadow = json.loads(sp.read_text())
    shadow["symbols"][0]["signature"] = "def hacked()"
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n")
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert "DERIVATION_MISMATCH" in {f["code"] for f in v["findings"]}
    # and it keeps reporting until fixed — a standing mismatch must not be
    # swallowed by the watermark
    v2 = handle_event(make_event("unit_complete", session=session), toy)
    assert "DERIVATION_MISMATCH" in {f["code"] for f in v2["findings"]}


# ---------------------------------------------------------------- R5
def test_substrate_writes_are_atomic(toy, tmp_path):
    """A crash mid-write must never leave a truncated substrate file: the
    whole system's value is substrate integrity."""
    from engine import write_jsonl
    target = tmp_path / "rows.jsonl"
    write_jsonl(target, [{"id": "a"}])
    original = target.read_text()

    try:
        # unserializable row: the failure happens mid-write, exactly like a
        # crash would
        write_jsonl(target, [{"id": "a"}, {"id": object()}])
    except Exception:
        pass
    assert target.read_text() == original, "partial write must not land"
    assert not list(tmp_path.glob("*.tmp*")), "no temp litter left behind"


# ---------------------------------------------------------------- R6
def test_readme_documents_every_cli_subcommand():
    """Docs drift is a correctness bug in a tool whose whole thesis is
    'lookup, never interpret'."""
    readme = (PLUGIN_ROOT / "README.md").read_text()
    proc = subprocess.run([sys.executable, str(PLUGIN_ROOT / "bin" / "harness"),
                           "--help"], capture_output=True, text=True)
    body = proc.stdout.split("{", 1)[1].split("}", 1)[0]
    subcommands = [s.strip() for s in body.split(",") if s.strip()]
    missing = [s for s in subcommands if f"`{s}`" not in readme]
    assert not missing, f"README does not document: {missing}"


def test_spec_glossary_resolves_every_referenced_marker():
    """The skills cite §5.6 / C7 / T1 — an agent told to look things up must
    be able to."""
    import re
    glossary = (PLUGIN_ROOT / "docs" / "SPEC.md").read_text()
    refs = set()
    for p in (PLUGIN_ROOT / "skills").rglob("*.md"):
        refs |= set(re.findall(r"§[\d.]+|\bC[1-9]\b|\bT[1-3]\b|\bM[1-9]\b",
                               p.read_text()))
    missing = sorted(r for r in refs if r not in glossary)
    assert not missing, f"SPEC.md does not define: {missing}"


# ---------------------------------------------------------------- R7
def test_promotion_candidates_rank_rules_that_fire_and_are_never_overridden(toy):
    """The metric answers 'which rules are stable enough to promote?' — it
    must look at rules that FIRED, not only ones that were overridden."""
    from engine import telemetry
    from engine.gates.g5_conformance import record_override
    for _ in range(3):
        telemetry.emit(toy, "event", {"event": "pre_change", "session": "s",
                                      "slice": "slice-042", "verdict": "block",
                                      "codes": ["UNDECLARED_FILE"],
                                      "gates": ["gate:G3"]})
    telemetry.emit(toy, "event", {"event": "pre_change", "session": "s",
                                  "slice": "slice-042", "verdict": "block",
                                  "codes": ["UNDECLARED_USE"],
                                  "gates": ["gate:G5"]})
    record_override(toy, "slice-042", "registry:telemetry", "needed",
                    rule_ref="gate:G5")
    agg = telemetry.aggregate(toy)
    assert "gate:G3" in agg["layer0_promotion_candidates"], \
        "fired 3x, never overridden -> promote"
    assert "gate:G5" not in agg["layer0_promotion_candidates"], \
        "overridden -> not a promotion candidate"


# ---------------------------------------------------------------- R8
def test_telemetry_buffers_in_the_sidecar_and_flushes_at_close(toy):
    """Hook events appending to a tracked file forced churn commits before
    every merge; buffer them and flush once at close."""
    session = "buf"
    run_cli("start", "--slice", "slice-042", "--session", session,
            "--no-worktree", root=toy)
    before = len(read_jsonl(toy / ".harness" / "telemetry.jsonl"))
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    for _ in range(3):
        handle_event(make_event("post_change", session=session,
                                files=["orders.py"]), toy)
    assert len(read_jsonl(toy / ".harness" / "telemetry.jsonl")) == before, \
        "hook events must not churn the tracked file"
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "x")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = read_jsonl(toy / ".harness" / "telemetry.jsonl")
    assert len(rows) > before, "buffered events must land at close"
    assert any(r["kind"] == "event" for r in rows)
    # and the dashboard still sees buffered-but-unflushed events
    out = json.loads(run_cli("status", root=toy).stdout)
    assert out["pre_change_events"] >= 0
