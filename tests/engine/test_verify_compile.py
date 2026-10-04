"""W5 (spec 6.1, 6.2): compile writes verify.jsonl and reports unknown links."""
import json

from conftest import run_cli
from engine import read_jsonl
from engine.schema import validate_rows


def _compile(toy, *args):
    proc = run_cli("compile", *args, root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def _verify_md(toy, body):
    (toy / "explore").mkdir(exist_ok=True)
    (toy / "explore" / "VERIFY.md").write_text(body)


def test_compile_writes_verify_jsonl_from_explore_verify_md(toy):
    _verify_md(toy, "# Verify\n\nV-orders-2: rollback leaves no event row\n"
                    "V-orders-1: an order has one row\n")
    report = _compile(toy)
    rows = read_jsonl(toy / ".harness" / "verify.jsonl")
    assert [r["id"] for r in rows] == ["V-orders-1", "V-orders-2"]
    assert rows[0] == {"id": "V-orders-1", "feature": "orders",
                       "statement": "an order has one row",
                       "source": "explore/VERIFY.md"}
    assert report["statements_source"] == "explore/VERIFY.md"
    assert report["statements"] == ["V-orders-1", "V-orders-2"]


def test_without_explore_the_working_doc_matrix_is_the_source(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("# Architecture\n\n## Verification matrix\n\n"
                   "### V-orders-1: an order has one row\n"
                   "Initial state: empty store.\n")
    report = _compile(toy, "--doc", "docs/architecture.md")
    rows = read_jsonl(toy / ".harness" / "verify.jsonl")
    assert rows == [{"id": "V-orders-1", "feature": "orders",
                     "statement": "an order has one row",
                     "source": "docs/architecture.md"}]
    assert report["statements_source"] == "docs/architecture.md"


def test_explore_verify_md_wins_over_the_working_doc(toy):
    _verify_md(toy, "V-orders-1: from explore\n")
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("V-orders-7: from the doc\n")
    _compile(toy, "--doc", "docs/architecture.md")
    assert [r["id"] for r in read_jsonl(toy / ".harness" / "verify.jsonl")] \
        == ["V-orders-1"]


def test_a_repo_without_statements_gets_no_verify_jsonl(toy):
    report = _compile(toy)
    assert not (toy / ".harness" / "verify.jsonl").exists()
    assert report["statements"] == [] and report["statements_source"] is None


def test_compile_reports_unknown_test_link_ids(toy):
    _verify_md(toy, "V-orders-1: an order has one row\n")
    test = toy / "tests" / "slices" / "042_orders.py"
    test.write_text("# verifies: V-orders-9  kills: x\n" + test.read_text())
    report = _compile(toy)
    assert report["unknown_test_links"] == [
        {"id": "V-orders-9", "path": "tests/slices/042_orders.py",
         "line": 1, "kills": "x"}]
    assert any("UNKNOWN_TEST_LINK" in w and "V-orders-9" in w
               for w in report["warnings"])


def test_compile_fails_loud_on_a_malformed_statement_id(toy):
    _verify_md(toy, "V-Orders-1: capital letters\n")
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 1
    assert "explore/VERIFY.md:1" in proc.stderr
    assert not (toy / ".harness" / "verify.jsonl").exists()


def test_schema_rejects_bad_statement_rows():
    problems = validate_rows("verify.jsonl", [
        {"id": "V-Orders-1", "feature": "orders", "statement": "x",
         "source": "explore/VERIFY.md"},
        {"id": "V-orders-2", "feature": "orders", "source": "s"}])
    assert any("V-Orders-1" in p for p in problems)
    assert any("'statement'" in p for p in problems)


def _slice_row(**extra):
    row = {"id": "s1", "status": "planned", "declares_dep": [],
           "acceptance": ["tests/a.py"], "predicted_files": []}
    row.update(extra)
    return row


def test_schema_checks_verifies_and_legacy_verification():
    problems = validate_rows("backlog.jsonl", [_slice_row(
        verifies=["V-orders-1", "orders-2"], legacy_verification="yes")])
    assert any("orders-2" in p for p in problems)
    assert any("legacy_verification" in p for p in problems)
    assert validate_rows("backlog.jsonl", [_slice_row(
        verifies=["V-orders-1"], legacy_verification=True)]) == []


def test_schema_checks_metrics_bool_fields():
    row = {"id": "s1", "closed_at": "t", "red_before_green": "yes"}
    problems = validate_rows("slice-metrics.jsonl", [row])
    assert any("red_before_green" in p for p in problems)
    row = {"id": "s1", "closed_at": "t", "red_before_green": True,
           "green_at_start": False}
    assert validate_rows("slice-metrics.jsonl", [row]) == []


def test_catalog_has_unknown_test_link():
    from engine.findings import CATALOG
    assert "UNKNOWN_TEST_LINK" in CATALOG


def test_compile_warns_when_the_default_doc_has_uncompiled_statements(toy):
    doc = toy / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("# Architecture\n\nV-orders-1: an order has one row\n")
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert "V-" in proc.stderr and "--doc docs/architecture.md" in proc.stderr
    assert not (toy / ".harness" / "verify.jsonl").exists()
    _verify_md(toy, "V-orders-1: x\n")
    assert "--doc" not in run_cli("compile", root=toy).stderr
    (toy / "explore" / "VERIFY.md").unlink()
    assert "--doc" not in run_cli("compile", "--doc", "docs/architecture.md",
                                  root=toy).stderr


def test_backlog_add_fix_names_both_statement_sources(toy):
    proc = run_cli("backlog", "add", "--id", "slice-050", "--acceptance",
                   "tests/slices/050_x.py", "--verifies", "V-orders-1",
                   root=toy)
    assert proc.returncode == 1
    assert "--doc" in proc.stderr
