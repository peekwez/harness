"""The spec-review findings (R1–R8): agent-side review findings become
substrate, adjudication is reachable, G2 certifies only what was emitted,
G7 scales, substrate writes are atomic, docs stay true, metrics are honest."""
import json
import subprocess
import sys

from conftest import PLUGIN_ROOT, run_cli
from engine import read_jsonl


# ---------------------------------------------------------------- R1/R2
def test_reviewer_records_findings_and_parks_into_the_queue(toy):
    """Layers 1-3 run in the reviewer agent, so its verdict must land in
    substrate — otherwise the adjudication loop has no producer at all."""
    proc = run_cli("review", "--slice", "slice-042", "--record-finding",
                   "--code", "R-decisions", "--rule-ref", "decision:D-041",
                   "--message", "span name is free-form, violates D-041",
                   "--severity", "block", "--fix", "Name the span.", root=toy)
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
# ---------------------------------------------------------------- R4




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
    glossary = (PLUGIN_ROOT / "docs" / "internal" / "SPEC.md").read_text()
    refs = set()
    for p in (PLUGIN_ROOT / "skills").rglob("*.md"):
        refs |= set(re.findall(r"§[\d.]+|\bC[1-9]\b|\bT[1-3]\b|\bM[1-9]\b",
                               p.read_text()))
    missing = sorted(r for r in refs if r not in glossary)
    assert not missing, f"docs/internal/SPEC.md does not define: {missing}"
