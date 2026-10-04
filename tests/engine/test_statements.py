"""W5 (spec 6.1, 6.2): statements and the test links that prove them."""
import pytest
from conftest import build_toy_repo
from engine import HarnessError, write_jsonl
from engine.statements import (STATEMENT_ID, expand_suite, is_test_path,
                               linked_test_files, load_statements,
                               parse_id_list, parse_statements,
                               scan_test_links, statement_key,
                               unowned_statements)

FENCE = "`" * 3


def test_statement_id_pattern_is_the_spec_pattern():
    assert STATEMENT_ID.pattern == r"V-[a-z0-9-]+-[0-9]+"


def test_parse_reads_plain_list_heading_and_bold_lines():
    text = "\n".join([
        "# Verify",
        "V-orders-1: an order has one row",
        "- V-orders-2: a rollback leaves no event row",
        "### V-order-sync-3: sync retries twice",
        "**V-orders-4:** totals use cents",
        "1. `V-orders-5`: refunds keep the order id",
    ])
    rows = parse_statements(text, "explore/VERIFY.md")
    assert [r["id"] for r in rows] == ["V-orders-1", "V-orders-2",
                                      "V-order-sync-3", "V-orders-4",
                                      "V-orders-5"]
    assert rows[1] == {"id": "V-orders-2", "feature": "orders",
                       "statement": "a rollback leaves no event row",
                       "source": "explore/VERIFY.md"}
    assert rows[2]["feature"] == "order-sync"
    assert rows[3]["statement"] == "totals use cents"
    assert rows[4]["statement"] == "refunds keep the order id"


def test_parse_skips_fenced_code_and_prose():
    text = "\n".join([FENCE + "text", "V-orders-9: example only", FENCE,
                      "V-shaped: a prose line, not a statement",
                      "V-orders-1: real"])
    assert [r["id"] for r in parse_statements(text, "d.md")] == ["V-orders-1"]


def test_parse_rejects_a_malformed_id_naming_the_line():
    with pytest.raises(HarnessError) as exc:
        parse_statements("ok line\nV-Orders-3: capital letters", "d.md")
    assert "d.md:2" in str(exc.value)
    assert "V-Orders-3" in str(exc.value)


def test_parse_rejects_a_duplicate_id_naming_both_lines():
    with pytest.raises(HarnessError) as exc:
        parse_statements("V-orders-1: a\nV-orders-1: b", "d.md")
    assert "d.md:2" in str(exc.value) and "line 1" in str(exc.value)


def test_parse_rejects_an_empty_statement():
    with pytest.raises(HarnessError) as exc:
        parse_statements("V-orders-1:", "d.md")
    assert "d.md:1" in str(exc.value)


def test_statement_key_sorts_numbers_as_numbers():
    ids = ["V-orders-10", "V-orders-2", "V-billing-1"]
    assert sorted(ids, key=statement_key) == ["V-billing-1", "V-orders-2",
                                              "V-orders-10"]


def test_parse_id_list_splits_commas_and_spaces_and_dedupes():
    assert parse_id_list(["V-a-1,V-a-2", "V-a-2", "V-b-3"]) == [
        "V-a-1", "V-a-2", "V-b-3"]


def test_parse_id_list_rejects_a_malformed_id():
    with pytest.raises(HarnessError) as exc:
        parse_id_list(["orders-1"])
    assert "orders-1" in str(exc.value)


@pytest.mark.parametrize("rel,expected", [
    ("tests/slices/042_orders.py", True), ("pkg/tests/x.py", True),
    ("test_x.py", True), ("x_test.go", True), ("web/a.test.ts", True),
    ("web/a.spec.tsx", True), ("conftest.py", True),
    ("src/__tests__/a.js", True), ("orders.py", False),
    ("src/testing_utils.py", False), ("docs/tests.md", False),
])
def test_is_test_path(rel, expected):
    assert is_test_path(rel) is expected


def _write(root, files):
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def test_scan_finds_links_in_any_comment_syntax(tmp_path):
    files = {
        "tests/test_a.py": ("# verifies: V-orders-1  kills: commit before "
                            "rollback check\ndef test_a(): pass\n"),
        "web/a.test.ts": "// verifies: V-orders-2, V-orders-3 kills: total uses floats\n",
        "db/check_test.sql": "-- verifies: V-orders-4  kills: missing index\n",
        "web/b.spec.css": "/* verifies: V-orders-5 kills: wrong colour */\n",
        "web/page.test.html": "<!-- verifies: V-orders-6 kills: no title -->\n",
    }
    _write(tmp_path, files)
    links = scan_test_links(tmp_path, list(files))
    assert links["V-orders-1"] == [{"path": "tests/test_a.py", "line": 1,
                                    "kills": "commit before rollback check"}]
    assert links["V-orders-2"][0]["kills"] == "total uses floats"
    assert links["V-orders-3"][0]["path"] == "web/a.test.ts"
    assert links["V-orders-4"][0]["kills"] == "missing index"
    assert links["V-orders-5"][0]["kills"] == "wrong colour"
    assert links["V-orders-6"][0]["kills"] == "no title"


def test_kills_may_sit_on_the_next_line_and_may_be_missing(tmp_path):
    _write(tmp_path, {"t_test.go": (
        "// verifies: V-pay-1\n// kills: double charge on retry\n"
        "func TestX(t *testing.T) {}\n// verifies: V-pay-2\n"
        "func TestY(t *testing.T) {}\n")})
    links = scan_test_links(tmp_path, ["t_test.go"])
    assert links["V-pay-1"][0]["kills"] == "double charge on retry"
    assert links["V-pay-2"] == [{"path": "t_test.go", "line": 4,
                                 "kills": None}]


def test_a_string_literal_is_not_a_link(tmp_path):
    _write(tmp_path, {"tests/test_s.py":
                      'X = "# verifies: V-pay-3 kills: y"\n'})
    assert scan_test_links(tmp_path, ["tests/test_s.py"]) == {}


def test_scan_reports_mistyped_ids_as_keys(tmp_path):
    _write(tmp_path, {"tests/test_t.py": "# verifies: V-Orders-3 kills: x\n"})
    assert "V-Orders-3" in scan_test_links(tmp_path, ["tests/test_t.py"])


def test_scan_skips_binary_and_missing_files(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "blob_test.bin").write_bytes(
        b"\0# verifies: V-a-1 kills: x\n")
    assert scan_test_links(tmp_path, ["tests/blob_test.bin",
                                      "tests/gone_test.py"]) == {}


def test_expand_suite_expands_globs_and_directories(tmp_path):
    _write(tmp_path, {"tests/slices/a.py": "", "tests/slices/b.py": "",
                      "tests/other/c.py": ""})
    assert expand_suite(tmp_path, ["tests/slices"]) == [
        "tests/slices/a.py", "tests/slices/b.py"]
    assert expand_suite(tmp_path, ["tests/*/c.py", "tests/missing.py"]) == [
        "tests/other/c.py"]


def test_linked_test_files_lists_tests_and_acceptance_but_not_source(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    files = linked_test_files(toy)
    assert "tests/slices/042_orders.py" in files
    assert "telemetry.py" not in files
    assert not any(f.startswith(".harness/") for f in files)


def test_load_and_unowned_statements(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    assert load_statements(toy) == []
    write_jsonl(toy / ".harness" / "verify.jsonl", [
        {"id": i, "feature": "orders", "statement": "s",
         "source": "explore/VERIFY.md"}
        for i in ("V-orders-1", "V-orders-2", "V-orders-10")])
    rows = [{"id": "s1", "verifies": ["V-orders-2"]}, {"id": "s2"}]
    assert unowned_statements(toy, rows) == ["V-orders-1", "V-orders-10"]
