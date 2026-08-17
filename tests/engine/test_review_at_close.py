"""Review is part of the close ceremony, not prompt discipline: the
deterministic stack runs over the slice's own diff, blocks on blocking
findings, and lands its verdict in substrate."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.events import handle_event
from engine.graph import load_edges

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _work_and_commit(toy, session="rc"):
    run_cli("start", "--slice", "slice-042", "--session", session,
            "--no-worktree", root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    return session


def test_close_runs_the_review_stack_and_records_its_verdict(toy):
    session = _work_and_commit(toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["review"]["verdict"] in ("allow", "allow_with_findings")
    assert out["review"]["ran"] is True
    edge = next(e for e in load_edges(toy)
                if e["type"] == "reviewed_by"
                and e["from"] == "slice:slice-042"
                and e.get("meta", {}).get("kind") == "close")
    assert edge["meta"]["verdict"] == out["review"]["verdict"]


def test_a_blocking_review_finding_blocks_the_close(toy):
    """The deterministic rubrics are real gates now, not a report."""
    session = _work_and_commit(toy)
    from engine.graph import append_edge
    append_edge(toy, "uses", "slice:slice-042", "module:ghost")  # R-uses fails
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert not out["closed"]
    assert "ghost" in json.dumps(out)


def test_agent_recorded_findings_are_surfaced_at_close(toy):
    """A reviewer agent's own blocking finding must stop the close too —
    otherwise recording it changes nothing."""
    session = _work_and_commit(toy)
    run_cli("review", "--slice", "slice-042", "--record-finding",
            "--code", "R-decisions", "--rule-ref", "decision:D-041",
            "--message", "span name is free-form", "--severity", "block",
            root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert "D-041" in json.dumps(out) or "free-form" in json.dumps(out)


def test_an_unadjudicated_park_blocks_the_close(toy):
    """Parking is the reviewer saying 'a human must rule on this' — closing
    over it would make parking meaningless."""
    session = _work_and_commit(toy)
    run_cli("review", "--slice", "slice-042", "--park", "--code",
            "REVIEW_UNCERTAIN", "--rule-ref", "gate:G5",
            "--message", "unsure about the retry wrapper", root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    assert "adjudicat" in json.loads(proc.stdout)["reason"].lower()

    # adjudicating it unblocks the close
    parked = read_jsonl(toy / ".harness" / "parked.jsonl")
    run_cli("adjudicate", "--finding-id", parked[0]["finding"]["finding_id"],
            "--resolution", "wrappers are exempt", root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_review_at_close_can_be_disabled_by_config(toy):
    import yaml
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("review", {})["run_at_close"] = False
    cfg_path.write_text(yaml.safe_dump(cfg))
    session = _work_and_commit(toy)
    # a finding the reviewer agent recorded as blocking would normally stop
    # the close; with the stack disabled it does not run at all
    run_cli("review", "--slice", "slice-042", "--record-finding",
            "--code", "R-decisions", "--rule-ref", "decision:D-041",
            "--message", "would block", "--severity", "block", root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["review"]["ran"] is False


def test_a_recorded_g5_override_satisfies_r_uses(toy):
    """`g5_override: recorded_justification` is a first-class resolution: an
    undeclared use with a recorded override passes the close's own
    uses ⊆ declares check, so the Layer-1 R-uses rubric must read the same
    override-aware set (`unresolved`), not `undeclared` — otherwise the
    override clears the gate and the review blocks the close anyway."""
    session = _work_and_commit(toy)
    from engine.graph import append_edge
    append_edge(toy, "uses", "slice:slice-042", "module:ghost")
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", "module:ghost", "--rule-ref", "gate:G5",
            "--justification", "ghost is referenced only by a red test stub",
            root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] is True
    assert not [f for f in out["review"].get("findings", [])
                if f["code"] == "R-uses"], out["review"]
