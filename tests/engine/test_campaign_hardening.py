"""Unattended-mode hardening: cumulative regression ratchet, attempt caps
with auto-park, Layer-0 secret scan, dependency governance, contract lint."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _ready(toy, session="camp", orders=GOOD_ORDERS):
    run_cli("start", "--slice", "slice-042", "--session", session,
            "--no-worktree", root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(orders)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    return session


def _close(toy, session):
    return run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)


# ---------------------------------------------------------------- A: ratchet
def test_close_runs_the_full_accumulated_acceptance_suite(toy):
    """A slice must not close green while breaking an EARLIER slice's
    acceptance tests — the ratchet is cumulative or it is not a ratchet."""
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows.append({"id": "slice-041", "spec": "spec-007", "title": "earlier",
                 "status": "closed", "declares_dep": [],
                 "acceptance": ["tests/slices/041_telemetry.py"],
                 "predicted_files": [], "depends_on": [], "worktree": None})
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    (toy / "tests" / "slices" / "041_telemetry.py").write_text(
        "import telemetry\n\ndef test_emit():\n"
        "    assert telemetry.emit_span('x', {})['name'] == 'x'\n")
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-041 history")
    for sid in ("slice-041",):
        run_cli("graph", "note", "--slice", sid, "--commit",
                git(toy, "rev-parse", "HEAD").stdout.strip(), root=toy)
    session = _ready(toy)
    # regress slice-041: break telemetry while slice-042's own tests stay green
    (toy / "telemetry.py").write_text(
        "__all__ = ['emit_span']\n\n\ndef emit_span(name, attrs):\n"
        "    return {'title': name, 'attrs': attrs}\n")
    run_cli("extract", str(toy / "telemetry.py"), root=toy)
    run_cli("gates", "ack-drift", "--slice", "slice-042", "--module",
            "telemetry", root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "regressive change")
    proc = _close(toy, "camp")
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert "041" in out["reason"] or "regression" in out["reason"].lower()


def test_merge_slice_rolls_back_when_the_merged_suite_is_red(toy):
    """Two slices can each be green alone and red together — the merged
    tree is what ships, so the merged tree is what must pass."""
    wt = toy / ".worktrees" / "slice-042"
    git(toy, "worktree", "add", str(wt), "-b", "slice/slice-042")
    run_cli("slice", "--slice", "slice-042", "--session", "m", root=wt)
    (wt / "orders.py").write_text(GOOD_ORDERS)
    run_cli("extract", str(wt / "orders.py"), root=wt)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "slice work")
    assert run_cli("close-slice", "--slice", "slice-042", "--session", "m",
                   "--commit", "HEAD", root=wt).returncode == 0
    # meanwhile main moved: telemetry got an incompatible signature, making
    # the combination red even though each side was green alone
    (toy / "telemetry.py").write_text(
        '"""Telemetry module."""\n\n__all__ = ["emit_span"]\n\n\n'
        "def emit_span(name, attrs, level):\n"
        '    """Emit a span."""\n'
        "    return {'name': name, 'attrs': attrs}\n")
    run_cli("extract", str(toy / "telemetry.py"), root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "main moved incompatibly")
    main_head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy,
                   env={"CLAUDE_SESSION_ID": ""})
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["merged"] is False and "rolled_back" in out
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == main_head, \
        "a red merged suite must roll the merge back"


# ---------------------------------------------------------------- B: parking
def test_repeated_close_failures_auto_park_the_slice(toy):
    session = _ready(toy, orders="def create_order(s):\n    raise ValueError\n")
    for i in range(3):
        proc = _close(toy, session)
        assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out.get("parked") is True, out
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-042"]["status"] == "parked"
    assert rows["slice-042"]["parked_reason"]
    # a parked slice blocks its dependents like any non-closed one
    # and refuses further closes until a human unparks it
    proc = _close(toy, session)
    assert proc.returncode == 1
    assert "parked" in json.loads(proc.stdout)["reason"].lower()


def test_explicit_bind_unparks(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "parked"
    rows[0]["parked_reason"] = "3 close failures"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    proc = run_cli("slice", "--slice", "slice-042", "--session", "human",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    assert rows[0]["status"] == "in_progress"
    assert "parked_reason" not in rows[0]


# ---------------------------------------------------------------- C: secrets
SECRETY = ('import telemetry\n\nAWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n\n\n'
           "def create_order(sku: str) -> dict:\n"
           "    telemetry.emit_span('create_order', {'sku': sku})\n"
           "    return {'sku': sku}\n")


def test_a_secret_in_the_diff_blocks_the_close(toy):
    session = _ready(toy, orders=SECRETY)
    proc = _close(toy, session)
    assert proc.returncode == 1, proc.stdout
    blob = json.dumps(json.loads(proc.stdout))
    assert "SECRET_IN_DIFF" in blob
    assert "AKIA" not in blob, "the finding must not repeat the secret"


def test_a_recorded_override_clears_a_secret_false_positive(toy):
    session = _ready(toy, orders=SECRETY)
    assert _close(toy, session).returncode == 1
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", "secret:orders.py", "--rule-ref", "review:layer0",
            "--justification", "documented AWS example key, not a credential",
            root=toy)
    proc = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------- D: deps
def test_new_dependencies_require_a_recorded_override(toy):
    session = _ready(toy)
    (toy / "requirements.txt").write_text("requests==2.32.0\n")
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["predicted_files"] = ["orders.py", "requirements.txt"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    handle_event(make_event("post_change", session=session,
                            files=["requirements.txt"]), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "add requests")
    proc = _close(toy, session)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert "requirements.txt" in out["reason"] and "requests" in out["reason"]
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", "deps:requirements.txt", "--rule-ref", "gate:G5",
            "--justification", "requests approved in ADR-007 discussion",
            root=toy)
    proc = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------- E: contracts
def test_verify_lints_contracts(toy):
    (toy / "contracts" / "api.yaml").write_text("openapi: 3.0.3\n[broken")
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    assert "CONTRACT_INVALID" in proc.stdout
    (toy / "contracts" / "api.yaml").write_text("info: {title: x}\n")
    proc = run_cli("verify", root=toy)
    assert "CONTRACT_INVALID" in proc.stdout, "missing openapi/paths keys"
