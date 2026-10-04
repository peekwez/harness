"""W5 (spec 6.1): backlog add --verifies and statements no slice owns."""
import json

from conftest import run_cli
from engine import get_slice, load_backlog, save_slice, write_jsonl


def _statements(toy, *ids):
    write_jsonl(toy / ".harness" / "verify.jsonl", [
        {"id": i, "feature": i[2:].rpartition("-")[0], "statement": "s",
         "source": "explore/VERIFY.md"} for i in ids])


def _add(toy, *extra):
    return run_cli("backlog", "add", "--id", "slice-050", "--acceptance",
                   "tests/slices/050_x.py", *extra, root=toy)


def test_backlog_add_stores_comma_separated_verifies(toy):
    _statements(toy, "V-orders-1", "V-orders-2")
    proc = _add(toy, "--verifies", "V-orders-1,V-orders-2")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == ["V-orders-1",
                                                       "V-orders-2"]


def test_backlog_add_accepts_space_separated_verifies(toy):
    _statements(toy, "V-orders-1", "V-orders-2")
    proc = _add(toy, "--verifies", "V-orders-1", "V-orders-2")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == ["V-orders-1",
                                                       "V-orders-2"]


def test_backlog_add_always_writes_verifies(toy):
    proc = _add(toy)
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == []


def test_backlog_add_refuses_an_unknown_statement(toy):
    _statements(toy, "V-orders-1")
    proc = _add(toy, "--verifies", "V-orders-9")
    assert proc.returncode == 1
    assert "V-orders-9" in proc.stderr
    assert "slice-050" not in {r["id"] for r in load_backlog(toy)}


def test_backlog_add_needs_compiled_statements(toy):
    proc = _add(toy, "--verifies", "V-orders-1")
    assert proc.returncode == 1
    assert "harness compile" in proc.stderr


def test_backlog_add_refuses_a_malformed_id(toy):
    _statements(toy, "V-orders-1")
    proc = _add(toy, "--verifies", "orders-1")
    assert proc.returncode == 1
    assert "orders-1" in proc.stderr


def test_backlog_reports_statements_no_slice_owns(toy):
    _statements(toy, "V-orders-1", "V-orders-2")
    sl = get_slice(toy, "slice-042")
    sl["verifies"] = ["V-orders-1"]
    save_slice(toy, sl)
    proc = run_cli("backlog", "--no-split", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["unowned_statements"] == ["V-orders-2"]


def test_backlog_add_accumulates_a_repeated_flag(toy):
    _statements(toy, "V-orders-1", "V-orders-2")
    proc = _add(toy, "--verifies", "V-orders-1", "--verifies", "V-orders-2")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == ["V-orders-1",
                                                       "V-orders-2"]


def test_backlog_add_drops_duplicate_ids(toy):
    _statements(toy, "V-orders-1")
    proc = _add(toy, "--verifies", "V-orders-1,V-orders-1")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == ["V-orders-1"]


def test_backlog_add_tolerates_spaces_and_trailing_comma(toy):
    _statements(toy, "V-orders-1", "V-orders-2")
    proc = _add(toy, "--verifies", "V-orders-1, V-orders-2,")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == ["V-orders-1",
                                                       "V-orders-2"]


def test_backlog_add_accepts_mixed_comma_and_space(toy):
    _statements(toy, "V-orders-1", "V-orders-2", "V-orders-3")
    proc = _add(toy, "--verifies", "V-orders-1,V-orders-2", "V-orders-3")
    assert proc.returncode == 0, proc.stderr
    assert get_slice(toy, "slice-050")["verifies"] == [
        "V-orders-1", "V-orders-2", "V-orders-3"]


def test_unknown_ids_message_is_plain_and_capped(toy):
    _statements(toy, "V-orders-1")
    proc = _add(toy, "--verifies",
                "V-a-1,V-a-2,V-a-3,V-a-4,V-a-5")
    assert proc.returncode == 1
    assert "[" not in proc.stderr
    assert "V-a-1, V-a-2, V-a-3 and 2 more" in proc.stderr
