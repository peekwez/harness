"""Spec 5.5: `harness explore --freeze` checks, then signs DECISIONS.md."""
import hashlib
import json

from conftest import git, run_cli
from explore_samples import DECISIONS, OPEN, VERIFY

from engine.explore import (check_statements, freeze_state, front_matter,
                            parse_open)


def _write(toy, decisions=DECISIONS, verify=VERIFY, open_=OPEN):
    assert run_cli("explore", root=toy).returncode == 0
    (toy / "explore" / "DECISIONS.md").write_text(decisions)
    (toy / "explore" / "VERIFY.md").write_text(verify)
    (toy / "explore" / "OPEN.md").write_text(open_)


def _freeze(toy):
    proc = run_cli("explore", "--freeze", root=toy)
    return proc.returncode, json.loads(proc.stdout)


def test_freeze_writes_identity_and_commit(toy):
    _write(toy)
    code, out = _freeze(toy)
    assert code == 0, out
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    assert out["frozen"] is True
    assert out["frozen_by"] == "t <t@t>"
    assert out["frozen_at_commit"] == head
    assert (out["cards"], out["chosen"], out["parked"],
            out["statements"]) == (2, 1, 1, 2)
    data, body = front_matter((toy / "explore" / "DECISIONS.md").read_text())
    digest = hashlib.sha256(DECISIONS.encode("utf-8")).hexdigest()
    assert data == {"frozen_by": "t <t@t>", "frozen_at_commit": head,
                    "frozen_digest": digest}
    assert body == DECISIONS
    assert freeze_state(toy) == {"frozen_by": "t <t@t>",
                                 "frozen_at_commit": head}


def test_freeze_twice_keeps_one_front_matter(toy):
    _write(toy)
    _freeze(toy)
    code, out = _freeze(toy)
    assert code == 0, out
    text = (toy / "explore" / "DECISIONS.md").read_text()
    assert text.count("frozen_by:") == 1


def test_fresh_scaffold_does_not_freeze(toy):
    run_cli("explore", root=toy)
    code, out = _freeze(toy)
    assert code == 1
    assert out["frozen"] is False
    assert any("no decision cards" in p for p in out["problems"])
    assert any("no statements" in p for p in out["problems"])
    assert freeze_state(toy) is None


def test_nothing_is_written_when_a_check_fails(toy):
    broken = DECISIONS.replace("**Chosen:** A", "**Chosen:** C")
    _write(toy, decisions=broken)
    code, out = _freeze(toy)
    assert code == 1
    assert any("'Chosen' is 'C'" in p for p in out["problems"])
    assert (toy / "explore" / "DECISIONS.md").read_text() == broken


def test_a_parked_card_needs_owner_and_trigger(toy):
    _write(toy, open_="# Open questions\n")
    code, out = _freeze(toy)
    assert code == 1
    assert any("D-E2 is parked" in p for p in out["problems"])


def test_missing_files_are_named(toy):
    code, out = _freeze(toy)
    assert code == 1
    assert out["problems"] == [
        "explore/DECISIONS.md is missing. Run: harness explore",
        "explore/VERIFY.md is missing. Run: harness explore",
        "explore/OPEN.md is missing. Run: harness explore"]


def test_statement_ids_are_unique_and_well_formed():
    statements, problems = check_statements(VERIFY)
    assert problems == []
    assert [s["id"] for s in statements] == ["V-orders-1", "V-orders-2"]
    _, problems = check_statements("- V-orders-1: a.\n- V-orders-1: b.\n")
    assert any("V-orders-1 is also on line 1" in p for p in problems)
    _, problems = check_statements("- V-Orders-1: a.\n")
    assert any("'V-Orders-1'" in p for p in problems)
    _, problems = check_statements("- V-orders-3:\n")
    assert any("has no text" in p for p in problems)


def test_statements_are_read_as_compile_reads_them():
    heading = "# Verify\n### V-orders-3: A refund restores stock.\n"
    statements, problems = check_statements(heading)
    assert problems == []
    assert [s["id"] for s in statements] == ["V-orders-3"]
    statements, problems = check_statements("1. V-orders-4: Numbered.\n")
    assert problems == [] and len(statements) == 1


def test_skipped_statement_lines_are_problems():
    _, problems = check_statements(
        "- V-orders-1: ok.\n- [ ] V-orders-2: in a checkbox.\n")
    assert any("explore/VERIFY.md:2: statement line skipped" in p
               for p in problems)


def test_fenced_statements_are_not_read():
    _, problems = check_statements(
        "# Verify\n```\n- V-orders-1: example.\n```\n")
    assert any("no statements" in p for p in problems)


def test_commented_statements_are_read_like_compile_reads_them():
    statements, problems = check_statements(
        "# Verify\n<!--\n- V-orders-1: example.\n-->\n")
    assert problems == [] and len(statements) == 1


def test_parse_open():
    assert parse_open(OPEN) == {"D-E2": {
        "question": "Which queue do we use?", "owner": "kwesi",
        "trigger": "more than 1,000 jobs a minute"}}


def test_freeze_without_git_identity_fails(toy):
    _write(toy)
    git(toy, "config", "--unset", "user.name")
    # a global user.name on the test machine must not hide the failure
    proc = run_cli("explore", "--freeze", root=toy,
                   env={"GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_CONFIG_NOSYSTEM": "1"})
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert any("git user.name is not set" in p for p in out["problems"])


def test_freeze_refuses_a_row_over_150_words(toy):
    long = " ".join(["word"] * 160)
    _write(toy, decisions=DECISIONS.replace(
        "- Solves: One file holds all orders. No server runs.",
        f"- Solves: {long}."))
    code, out = _freeze(toy)
    assert code == 1
    assert out["frozen"] is False
    assert any("D-E1" in p and "limit is 150" in p for p in out["problems"])
    assert freeze_state(toy) is None
