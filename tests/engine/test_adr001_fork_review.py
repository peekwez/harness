"""ADR-001: independent (forked) LLM review is mandatory before closing a
slice that resolves any security-marked decision row; engine-only review
suffices everywhere else."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine import read_jsonl
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")

SECURITY_ROW = {"id": "D-777", "domain": "telemetry", "security": True,
                "question": "May spans carry auth tokens?",
                "answer": "Never; redact before emit.",
                "adr_ref": None, "origin": "phase0",
                "created": "2026-07-18T00:00:00+00:00"}


def _ready_to_close(toy, session):
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042")


def test_security_slice_blocks_close_until_fork_review_pass(toy):
    with (toy / ".harness" / "decisions.jsonl").open("a") as fh:
        fh.write(json.dumps(SECURITY_ROW) + "\n")
    session = "sec"
    _ready_to_close(toy, session)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["rule_ref"] == "adr:001"
    assert "D-777" in out["reason"], "the triggering row must be named"
    assert "--record-fork" in out["reason"], "the fix must be named"

    # a recorded BLOCK verdict does not unlock the close
    run_cli("review", "--record-fork", "block", "--slice", "slice-042",
            "--notes", "seed leaks into span attrs", root=toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1

    # the LATEST verdict wins: pass after fixes closes
    proc = run_cli("review", "--record-fork", "pass", "--slice", "slice-042",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["fork_review"] == "pass"


def test_non_security_slice_closes_engine_only(toy):
    """No security rows resolve for the slice: the deterministic stack is
    the whole contract — no fork ceremony demanded."""
    session = "plain"
    _ready_to_close(toy, session)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_record_fork_requires_slice(toy):
    proc = run_cli("review", "--record-fork", "pass", root=toy)
    assert proc.returncode == 2
    assert "--slice" in proc.stderr


def test_compile_carries_the_security_flag(toy):
    (toy / "adr" / "010-span-hygiene.md").write_text(
        '---\nid: "010"\nstatus: accepted\ndomains: [telemetry]\n'
        'supersedes: []\ndecision_table_rows:\n'
        '  - id: D-900\n    domain: telemetry\n    security: true\n'
        '    question: "Tokens in spans?"\n    answer: "Never."\n'
        'abstractions: []\napi_surface: []\n---\n\n# ADR-010\n\n## Status\n\n'
        'Accepted.\n\n## Context\n\nx\n\n## Decision\n\nx\n\n'
        '## Consequences\n\nx\n\n## Considered Alternatives\n\nx\n\n'
        '## Implementation\n\nx\n')
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "decisions.jsonl")}
    assert rows["D-900"].get("security") is True, \
        "the compiler must carry the security flag or ADR-marked rows never enforce"
