"""Regression tests for field report round 4 (X1–X5, W3 ruling,
improvements 1/2/5): CI template, CLI ergonomics, close auto-extraction."""
import json

from conftest import PLUGIN_ROOT, git, loaded_context, make_event, run_cli
from engine import read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


# ---------------------------------------------------------------- X5
def test_ci_template_does_not_assume_a_vendored_engine():
    """Consumer repos have no ./bin/harness — the scaffolded workflow must
    fetch the engine (or use a vendored one) and fail with a NAMED fix when
    it can't, not crash on the first push."""
    wf = (PLUGIN_ROOT / "templates" / "ci-verify.yml").read_text()
    assert "harness-repo" in wf, "engine source must be configurable"
    assert "git clone" in wf, "the engine must be fetched when not vendored"
    assert "HARNESS_REPO" in wf, "repo variable fallback for pull_request runs"
    assert "vendor" in wf.lower() or "-x ./bin/harness" in wf, \
        "self-hosted/vendored repos must keep working"
    # the bare invocation that broke every consumer must be gone
    assert "\n            ./bin/harness verify" not in wf


# ---------------------------------------------------------------- X1
def test_review_diff_with_missing_file_errors_cleanly(toy):
    proc = run_cli("review", "--slice", "slice-042",
                   "--diff", "does-not-exist.patch", root=toy)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "does-not-exist.patch" in proc.stderr
    assert "stdin" in proc.stderr, "the fix (pipe the diff) must be named"


# ---------------------------------------------------------------- X3 + improvement 1
def test_resolve_accepts_session_and_registers_context(toy):
    proc = run_cli("resolve", "--slice", "slice-042", "--session", "x3",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sc = Sidecar(toy)
    try:
        assert sc.context_get("x3"), \
            "resolve knows the context set — it must register it (G2)"
    finally:
        sc.close()


def test_bind_registers_resolved_context_for_the_session(toy):
    """Improvement 1: after `harness slice`, an edit under that session must
    pass G2 without a separate pre_context ceremony."""
    proc = run_cli("slice", "--slice", "slice-042", "--session", "imp1",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    v = handle_event(make_event("pre_change", session="imp1",
                                files=["orders.py"]), toy)
    assert v["verdict"] == "allow", v["findings"]


# ---------------------------------------------------------------- improvement 2
def test_session_defaults_to_claude_session_id_env(toy):
    proc = run_cli("slice", "--slice", "slice-042", root=toy,
                   env={"CLAUDE_SESSION_ID": "env-uuid-1"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["session"] == "env-uuid-1"
    sc = Sidecar(toy)
    try:
        assert sc.state_get("env-uuid-1", "active_slice") == "slice-042"
    finally:
        sc.close()


# ---------------------------------------------------------------- X2
def test_g7_mismatch_names_a_fix_that_cannot_noop(toy):
    """`extract --all` can legitimately report 'cached' in edge states; the
    finding must name `extract --force <path>` — guaranteed effective."""
    from engine import load_config
    from engine.gates.g7_derivation import derivation_findings
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    shadow = json.loads(sp.read_text())
    shadow["symbols"] = []
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n")
    f = [f for f in derivation_findings(toy, load_config(toy))
         if f["code"] == "DERIVATION_MISMATCH"]
    assert f and "--force" in f[0]["message"]


# ---------------------------------------------------------------- W3 ruling
def test_close_auto_extracts_missing_shadows_for_touched_files(toy):
    """The documented contract: derived artifacts are the ENGINE's job.
    Close extracts missing shadows for touched files itself and reports
    them; G7 still blocks anything stale or hand-edited."""
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["predicted_files"] = ["orders.py", "newcli.py"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    session = "heal"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    (toy / "newcli.py").write_text("def main() -> int:\n    return 0\n")
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 heal")
    # close under a DIFFERENT session: the ceremony's session-scoped
    # regeneration can't cover these — the auto-extract contract must
    proc = run_cli("close-slice", "--slice", "slice-042",
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert set(out.get("shadows_extracted", [])) >= {"newcli.py"}, out
    assert (toy / ".harness" / "shadows" / "newcli.py.json").exists()
    # and the auto-extracted shadows ride in the substrate commit
    dirty = git(toy, "status", "--porcelain", "--", ".harness").stdout.strip()
    assert not dirty


# ---------------------------------------------------------------- improvement 5
def test_resolve_advertises_the_acceptance_interpreter(toy):
    proc = run_cli("resolve", "--slice", "slice-042", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out.get("acceptance_python"), \
        "builders should not need the venv path plumbed by hand"
