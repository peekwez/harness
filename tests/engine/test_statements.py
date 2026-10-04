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


# ---- fix round 1 ----------------------------------------------------------
from engine.statements import compile_statements, skipped_statement_lines


@pytest.mark.parametrize("pattern", ["/etc/hosts", "/etc/*", "../*",
                                     "../outside.py"])
def test_expand_suite_ignores_paths_outside_the_root(tmp_path, pattern):
    root = tmp_path / "repo"
    _write(root, {"tests/a.py": ""})
    (tmp_path / "outside.py").write_text("")
    # `../*` reaches the repo directory itself; its files are still in root.
    assert set(expand_suite(root, [pattern])) <= {"tests/a.py"}
    assert expand_suite(root, [pattern, "tests/a.py"]) == ["tests/a.py"]


def test_expand_suite_skips_a_symlink_that_leaves_the_root(tmp_path):
    root = tmp_path / "repo"
    _write(root, {"tests/a.py": ""})
    (tmp_path / "secret.py").write_text("")
    (root / "tests" / "link.py").symlink_to(tmp_path / "secret.py")
    assert expand_suite(root, ["tests"]) == ["tests/a.py"]


@pytest.mark.parametrize("body", [
    'x = "a # verifies: V-pay-3 kills: y"\n',
    "const x = 'a // verifies: V-pay-3 kills: y';\n",
    'const x = "say \\" # verifies: V-pay-3 kills: y";\n',
])
def test_a_marker_inside_a_quoted_string_is_not_a_link(tmp_path, body):
    _write(tmp_path, {"tests/test_q.py": body})
    assert scan_test_links(tmp_path, ["tests/test_q.py"]) == {}


def test_a_trailing_comment_after_a_string_is_a_link(tmp_path):
    _write(tmp_path, {"tests/test_q.py":
                      'x = "a"  # verifies: V-pay-3 kills: y\n'})
    assert scan_test_links(tmp_path, ["tests/test_q.py"])["V-pay-3"][0][
        "kills"] == "y"


def test_scan_skips_outside_root_and_dedupes_symlinks(tmp_path):
    root = tmp_path / "repo"
    _write(root, {"tests/test_a.py": "# verifies: V-a-1 kills: x\n"})
    (root / "tests" / "test_b.py").symlink_to(root / "tests" / "test_a.py")
    (tmp_path / "out_test.py").write_text("# verifies: V-a-2 kills: x\n")
    links = scan_test_links(root, ["tests/test_a.py", "tests/test_b.py",
                                   "../out_test.py"])
    assert list(links) == ["V-a-1"] and len(links["V-a-1"]) == 1


def test_skipped_statement_forms_are_reported_not_fatal():
    text = "\n".join(["- [ ] V-a-1: checkbox", "> V-a-2: quote",
                      "| V-a-3 | table |", "see V-a-4: mid line",
                      "V-a-5: fine", FENCE, "V-a-6: fenced", FENCE])
    warns = skipped_statement_lines(text, "d.md")
    assert [w.split(":")[1] for w in warns] == ["1", "2", "3", "4"]
    assert all(len(w.split(": ", 2)[2].split()) <= 25 for w in warns)
    assert [r["id"] for r in parse_statements(text, "d.md")] == ["V-a-5"]


def _verify_bytes(root):
    return (root / ".harness" / "verify.jsonl").read_bytes()


def test_compile_writes_sorted_statements_and_is_idempotent(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"explore/VERIFY.md":
                 "V-orders-10: b\nV-orders-2: a\n"})
    out = compile_statements(toy)
    assert out["source"] == "explore/VERIFY.md"
    assert out["statements"] == ["V-orders-2", "V-orders-10"]
    assert [r["id"] for r in load_statements(toy)] == ["V-orders-2",
                                                       "V-orders-10"]
    first = _verify_bytes(toy)
    compile_statements(toy)
    assert _verify_bytes(toy) == first


def test_compile_with_no_source_and_no_file_creates_nothing(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    out = compile_statements(toy)
    assert out == {"source": None, "statements": [], "unknown_links": [],
                   "warnings": []}
    assert not (toy / ".harness" / "verify.jsonl").exists()


def test_compile_with_no_source_keeps_an_existing_file(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    write_jsonl(toy / ".harness" / "verify.jsonl", [
        {"id": "V-a-1", "feature": "a", "statement": "s", "source": "x"}])
    before = _verify_bytes(toy)
    assert compile_statements(toy)["statements"] == ["V-a-1"]
    assert _verify_bytes(toy) == before


def test_compile_falls_back_to_the_working_document(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    doc = toy / "docs" / "plan.md"
    _write(toy, {"docs/plan.md": "# Plan\nV-a-1: first\n"})
    out = compile_statements(toy, doc)
    assert out["source"] == "docs/plan.md"
    assert load_statements(toy)[0]["source"] == "docs/plan.md"


def test_compile_ignores_a_working_document_without_statements(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"docs/plan.md": "# Plan\nno statements\n"})
    out = compile_statements(toy, toy / "docs" / "plan.md")
    assert out["source"] is None
    assert not (toy / ".harness" / "verify.jsonl").exists()


def test_compile_warns_about_unknown_test_links(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"explore/VERIFY.md": "V-a-1: first\n",
                 "tests/test_l.py": ("# verifies: V-a-1 kills: x\n"
                                     "# verifies: V-a-9 kills: y\n")})
    out = compile_statements(toy)
    assert [u["id"] for u in out["unknown_links"]] == ["V-a-9"]
    assert out["unknown_links"][0]["line"] == 2
    assert len(out["warnings"]) == 1
    assert out["warnings"][0].startswith("UNKNOWN_TEST_LINK: tests/test_l.py:2")


def test_compile_empty_source_does_not_wipe_existing_statements(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"explore/VERIFY.md": "V-a-1: first\n"})
    compile_statements(toy)
    before = _verify_bytes(toy)
    _write(toy, {"explore/VERIFY.md": "# nothing here yet\n"})
    out = compile_statements(toy)
    assert _verify_bytes(toy) == before
    assert out["source"] is None and out["statements"] == ["V-a-1"]
    assert any("no statements found" in w for w in out["warnings"])


def test_compile_surfaces_skipped_statement_lines(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"explore/VERIFY.md": "V-a-1: ok\n- [ ] V-a-2: lost\n"})
    out = compile_statements(toy)
    assert any("explore/VERIFY.md:2" in w for w in out["warnings"])


# ---- final-fix wave -------------------------------------------------------
def test_compile_keeps_rows_from_other_sources(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"docs/a.md": "V-a-1: first\nV-a-2: second\n",
                 "docs/b.md": "V-b-1: bee\n"})
    compile_statements(toy, toy / "docs" / "a.md")
    compile_statements(toy, toy / "docs" / "b.md")
    assert [r["id"] for r in load_statements(toy)] == ["V-a-1", "V-a-2",
                                                       "V-b-1"]
    first = _verify_bytes(toy)
    compile_statements(toy, toy / "docs" / "b.md")
    assert _verify_bytes(toy) == first
    _write(toy, {"docs/a.md": "V-a-1: changed\n"})
    compile_statements(toy, toy / "docs" / "a.md")
    rows = {r["id"]: r for r in load_statements(toy)}
    assert sorted(rows) == ["V-a-1", "V-b-1"]
    assert rows["V-a-1"]["statement"] == "changed"


def test_compile_duplicate_id_across_sources_fails_and_writes_nothing(
        tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    _write(toy, {"docs/a.md": "V-a-1: first\n", "docs/b.md": "V-a-1: dup\n"})
    compile_statements(toy, toy / "docs" / "a.md")
    before = _verify_bytes(toy)
    with pytest.raises(HarnessError, match="V-a-1"):
        compile_statements(toy, toy / "docs" / "b.md")
    assert _verify_bytes(toy) == before
