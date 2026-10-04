"""W5 (spec 6.4 checks 3-5, section 14): close checks red and coverage."""
import json

from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine import get_slice, load_config, save_slice, write_jsonl
from engine.events import handle_event
from engine.verification import close_checks, slice_metrics

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")
TEST_BODY = ("def test_orders():\n    import orders\n"
             "    assert orders.create_order('x')\n")
RED = {"slice": "slice-042", "red": True, "green_at_start": False,
       "exit_code": 1}
GREEN = {"slice": "slice-042", "red": False, "green_at_start": True,
         "exit_code": 0}


def _setup(tmp_path, verifies=(), record=None, link=None,
           statements=("V-orders-1",)):
    toy = build_toy_repo(tmp_path / "toy", legacy_verification=False)
    write_jsonl(toy / ".harness" / "verify.jsonl", [
        {"id": s, "feature": "orders", "statement": f"statement {s}",
         "source": "explore/VERIFY.md"} for s in statements])
    sl = get_slice(toy, "slice-042")
    sl["verifies"] = list(verifies)
    save_slice(toy, sl)
    if record is not None:
        path = toy / ".harness" / "verification" / "slice-042.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record))
    if link is not None:
        (toy / "tests" / "slices" / "042_orders.py").write_text(
            link + "\n" + TEST_BODY)
    return toy


def _check(toy):
    return close_checks(toy, get_slice(toy, "slice-042"), load_config(toy))


def _codes(findings, severity="block"):
    return [f["code"] for f in findings if f["severity"] == severity]


# ------------------------------------------------------------- check 3
def test_missing_red_record_blocks(tmp_path):
    findings, report = _check(_setup(tmp_path))
    assert _codes(findings) == ["RED_RECORD_MISSING"]
    assert findings[0]["rule_ref"] == "verify:red-record"
    assert report["red_before_green"] is False


def test_red_record_passes_and_feeds_metrics(tmp_path):
    findings, report = _check(_setup(tmp_path, record=RED))
    assert _codes(findings) == []
    assert slice_metrics(report) == {"red_before_green": True,
                                     "green_at_start": False}


def test_runner_error_record_blocks(tmp_path):
    record = {"slice": "slice-042", "red": False, "green_at_start": False,
              "exit_code": None, "runner_error": "pytest exit 5"}
    findings, _ = _check(_setup(tmp_path, record=record))
    assert _codes(findings) == ["RED_RECORD_MISSING"]
    assert "pytest exit 5" in findings[0]["message"]


def test_corrupt_record_blocks_with_the_repair_text(tmp_path):
    toy = _setup(tmp_path)
    path = toy / ".harness" / "verification" / "slice-042.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    findings, report = _check(toy)
    assert _codes(findings) == ["RED_RECORD_MISSING"]
    assert "Repair or delete" in findings[0]["message"]
    assert report["red_before_green"] is False


def test_runner_error_is_not_green_at_start(tmp_path):
    record = {"slice": "slice-042", "red": False, "green_at_start": False,
              "exit_code": None, "runner_error": "boom"}
    _, report = _check(_setup(tmp_path, record=record))
    assert report["green_at_start"] is False


def test_green_at_start_blocks_until_an_override_with_reason(tmp_path):
    toy = _setup(tmp_path, record=GREEN)
    findings, _ = _check(toy)
    assert _codes(findings) == ["GREEN_AT_START"]
    assert "verification:green-at-start" in json.dumps(findings[0])
    proc = run_cli("gates", "override", "--slice", "slice-042", "--target",
                   "verification:green-at-start", "--rule-ref",
                   "verify:red-record", "--justification",
                   "pure refactor: behaviour must not change", root=toy)
    assert proc.returncode == 0, proc.stderr
    findings, report = _check(toy)
    assert _codes(findings) == []
    assert report["green_at_start"] is True
    assert report["green_at_start_override"] is True
    assert slice_metrics(report) == {"red_before_green": False,
                                     "green_at_start": True}


def test_runner_none_skips_check_three(tmp_path):
    import yaml
    toy = _setup(tmp_path)
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["gates"]["acceptance_runner"] = "none"
    cfg_path.write_text(yaml.safe_dump(cfg))
    findings, report = _check(toy)
    assert _codes(findings) == []
    assert report["red_record"].startswith("skipped")


# ------------------------------------------------------------- checks 4, 5
def test_statement_without_a_test_blocks(tmp_path):
    findings, _ = _check(_setup(tmp_path, verifies=["V-orders-1"],
                                record=RED))
    assert _codes(findings) == ["STATEMENT_UNTESTED"]
    assert "V-orders-1" in findings[0]["message"]
    assert findings[0]["rule_ref"] == "verify:statement-coverage"


def test_linked_test_without_kills_blocks(tmp_path):
    findings, _ = _check(_setup(tmp_path, verifies=["V-orders-1"], record=RED,
                                link="# verifies: V-orders-1"))
    assert _codes(findings) == ["KILLS_MISSING"]
    assert "tests/slices/042_orders.py:1" in findings[0]["message"]


def test_linked_test_with_kills_passes(tmp_path):
    findings, report = _check(_setup(
        tmp_path, verifies=["V-orders-1"], record=RED,
        link="# verifies: V-orders-1  kills: create_order returns None"))
    assert _codes(findings) == []
    assert report["statements"]["V-orders-1"] == [
        {"path": "tests/slices/042_orders.py", "line": 1,
         "kills": "create_order returns None"}]


def test_a_link_outside_every_acceptance_suite_does_not_count(tmp_path):
    toy = _setup(tmp_path, verifies=["V-orders-1"], record=RED)
    (toy / "tests" / "test_elsewhere.py").write_text(
        "# verifies: V-orders-1  kills: x\ndef test_x(): pass\n")
    (toy / "docs").mkdir(exist_ok=True)
    (toy / "docs" / "notes.md").write_text(
        "<!-- verifies: V-orders-1 kills: x -->\n")
    findings, _ = _check(toy)
    assert _codes(findings) == ["STATEMENT_UNTESTED"]


def test_a_link_in_a_closed_slice_suite_counts(tmp_path):
    toy = _setup(tmp_path, verifies=["V-orders-1"], record=RED)
    (toy / "tests" / "slices" / "041_base.py").write_text(
        "# verifies: V-orders-1  kills: base row missing\n"
        "def test_base(): pass\n")
    rows = json.loads(json.dumps(get_slice(toy, "slice-042")))
    rows.update({"id": "slice-041", "status": "closed",
                 "acceptance": ["tests/slices/041_base.py"], "verifies": []})
    save_slice(toy, rows)
    findings, _ = _check(toy)
    assert _codes(findings) == []


def test_unknown_statement_in_verifies_blocks(tmp_path):
    findings, _ = _check(_setup(tmp_path, verifies=["V-orders-7"],
                                record=RED))
    assert _codes(findings) == ["UNKNOWN_STATEMENT"]


def test_unknown_link_id_in_the_slice_suite_is_advisory(tmp_path):
    findings, report = _check(_setup(
        tmp_path, record=RED, link="# verifies: V-orders-9  kills: x"))
    assert _codes(findings) == []
    assert _codes(findings, "advisory") == ["UNKNOWN_TEST_LINK"]
    assert report["unknown_test_links"][0]["id"] == "V-orders-9"


def test_legacy_slices_skip_checks_three_to_five(tmp_path):
    toy = _setup(tmp_path, verifies=["V-orders-1"])
    sl = get_slice(toy, "slice-042")
    sl["legacy_verification"] = True
    save_slice(toy, sl)
    findings, report = _check(toy)
    assert findings == []
    assert report["legacy"] is True


# ------------------------------------------------------------- CLI (spec 14)
def _work_and_commit(toy, session="vc", orders_first=False):
    if orders_first:
        (toy / "orders.py").write_text(GOOD_ORDERS)
        git(toy, "add", "-A")
        git(toy, "commit", "-qm", "orders before the slice")
    proc = run_cli("start", "--slice", "slice-042", "--session", session,
                   "--no-worktree", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work", "--allow-empty")
    return session


def _close(toy, session):
    return run_cli("close-slice", "--slice", "slice-042", "--session",
                   session, "--commit", "HEAD", root=toy)


def _last_metrics(toy):
    lines = (toy / ".harness" / "slice-metrics.jsonl").read_text().splitlines()
    return json.loads(lines[-1])


def test_a_green_suite_at_start_cannot_close_without_override(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", legacy_verification=False)
    session = _work_and_commit(toy, orders_first=True)
    proc = _close(toy, session)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "GREEN_AT_START" in proc.stdout
    assert run_cli("gates", "override", "--slice", "slice-042", "--target",
                   "verification:green-at-start", "--rule-ref",
                   "verify:red-record", "--justification",
                   "pure refactor slice", root=toy).returncode == 0
    proc = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] is True
    assert out["verification"]["green_at_start"] is True
    metrics = _last_metrics(toy)
    assert metrics["green_at_start"] is True
    assert metrics["red_before_green"] is False


def test_a_statement_with_no_test_blocks_close(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", legacy_verification=False)
    write_jsonl(toy / ".harness" / "verify.jsonl", [
        {"id": "V-orders-1", "feature": "orders",
         "statement": "an order has one row", "source": "explore/VERIFY.md"}])
    sl = get_slice(toy, "slice-042")
    sl["verifies"] = ["V-orders-1"]
    save_slice(toy, sl)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "statements")
    session = _work_and_commit(toy)
    proc = _close(toy, session)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "STATEMENT_UNTESTED" in proc.stdout

    test = toy / "tests" / "slices" / "042_orders.py"
    test.write_text("# verifies: V-orders-1  kills: create_order returns "
                    "None\n" + test.read_text())
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "link the test")
    proc = _close(toy, session)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["verification"]["red_before_green"] is True
    assert _last_metrics(toy)["red_before_green"] is True
