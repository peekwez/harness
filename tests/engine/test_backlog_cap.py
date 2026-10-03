"""Plan-time context cap (D-0.10-06): backlog warns when a slice's cited
context does not fit MAX_INJECTION_CHARS."""
import json

from conftest import build_toy_repo, run_cli
from engine import read_jsonl


def test_backlog_output_carries_the_context_size(toy):
    out = json.loads(run_cli("backlog", "--no-split", root=toy).stdout)
    ctx = out["context"]["slice-042"]
    assert set(ctx) == {"chars", "demand_chars", "cut", "tokens"}
    assert ctx["cut"] == [] and out["warnings"] == [] and out["cap"] == 9000
    row = read_jsonl(toy / ".harness" / "backlog.jsonl")[0]
    assert row["context_cost_estimate"] == ctx["tokens"]


def test_backlog_warns_when_a_slice_does_not_fit_the_cap(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", oversized=True)
    out = json.loads(run_cli("backlog", "--no-split", root=toy).stdout)
    assert out["context"]["slice-042"]["cut"] == ["modules", "slice"]
    hits = [w for w in out["warnings"] if w["code"] == "CONTEXT_OVER_CAP"]
    assert hits and "slice-042" in hits[0]["message"]
    assert hits[0]["severity"] == "advisory"


def test_backlog_add_estimates_the_new_row(toy):
    proc = run_cli("backlog", "add", "--id", "slice-050", "--declares",
                   "telemetry", "--acceptance", "tests/slices/050_x.py",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["context_cost_estimate"] > 0
