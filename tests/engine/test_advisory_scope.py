"""D-0.10-01: G3 scope and G5 advise; close reconciles uses, not files."""
import json

from conftest import (PLUGIN_ROOT, build_toy_repo, git, loaded_context,
                      make_event, run_cli)
from engine import read_jsonl, write_jsonl
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def test_undeclared_file_is_advisory_even_in_block_mode(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", g3_mode="block")
    v = handle_event(make_event("pre_change", session="g3b",
                                files=["rogue.py"]), toy)
    hits = [f for f in v["findings"] if f["code"] == "UNDECLARED_FILE"]
    assert hits and all(f["severity"] == "advisory" for f in hits)
    assert v["verdict"] == "allow_with_findings"


def test_undeclared_use_is_advisory(toy):
    loaded_context(toy, session="g5a")
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["declares_dep"] = ["config"]          # telemetry is undeclared
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    (toy / "orders.py").write_text(
        "import telemetry\n\ndef create_order(sku):\n"
        "    return telemetry.emit_span('create_order', {})\n")
    handle_event(make_event("post_change", session="g5a",
                            files=["orders.py"]), toy)
    v = handle_event(make_event("unit_complete", session="g5a"), toy)
    hits = [f for f in v["findings"] if f["code"] == "UNDECLARED_USE"]
    assert hits and all(f["severity"] == "advisory" for f in hits)
    assert v["verdict"] != "block"


def test_g5_override_mode_is_gone():
    from engine import DEFAULT_CONFIG
    assert "g5_override" not in DEFAULT_CONFIG["gates"]
    assert "g5_override" not in (PLUGIN_ROOT / "templates"
                                 / "harness.yaml").read_text()


def test_close_lists_undeclared_files_without_blocking(toy):
    session = "scope-adv"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    (toy / "rogue.py").write_text("x = 1\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py", "rogue.py"]), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "orders and rogue")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] is True
    assert out["scope_advisory"] == ["rogue.py"]
