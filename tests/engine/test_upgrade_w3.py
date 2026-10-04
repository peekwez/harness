"""W3 upgrade steps (spec section 12, steps 3, 6 and 13)."""
import re
import shlex
import shutil

import pytest

from conftest import git
from engine import HarnessError, append_jsonl
from engine import shared_memory as sm
from engine import upgrade_w3

W3_IDS = ["w3.retire-durable-memory", "w3.memory-git-lines",
          "w3.shared-memory-index", "w3.claude-md-import"]
JOURNAL = ".close-abc.json"


def _row(rid, kind, content, attempt=None):
    return {"id": rid, "scope": "durable", "slice_id": "slice-001",
            "commit": None, "kind": kind, "content": content,
            "attempt": attempt, "edges": []}


def _write_rows(toy):
    mem = toy / ".harness" / "memory"
    (mem / "session").mkdir(parents=True)
    durable = mem / "durable.jsonl"
    append_jsonl(durable, _row("mem-a1", "attempt", "tried sqlite advisory locks",
                               {"approach": "advisory locks",
                                "outcome": "abandoned",
                                "why": "worktrees partition state"}))
    append_jsonl(durable, _row("mem-j1", "adjudication",
                               "F-1: retry wrappers aren't exempt"))
    append_jsonl(durable, _row("mem-s1", "observation",
                               "slice slice-001: 3 working-memory entries, "
                               "2 promoted (1 attempts)"))
    (mem / "session" / JOURNAL).write_text('{"pending": 1}')


def _legacy_memory(toy, commit=True):
    _write_rows(toy)
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text() + ".harness/memory/durable.jsonl merge=union\n")
    gi = toy / ".gitignore"
    gi.write_text(gi.read_text() + ".harness/memory/session/\n")
    if commit:
        git(toy, "add", "-A")
        git(toy, "commit", "-qm", "legacy memory")


def _legacy_tree(root):
    trees = sorted((root / upgrade_w3.LEGACY_DIR).iterdir())
    assert len(trees) == 1
    assert re.fullmatch(r"\d{8}T\d{6}Z", trees[0].name)
    return trees[0]


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def test_w3_steps_are_registered_in_order():
    from engine import upgrade_010
    ids = [s.id for s in upgrade_010.STEPS if s.id.startswith("w3.")]
    assert ids == W3_IDS
    by_id = {s.id: s for s in upgrade_010.STEPS}
    assert by_id["w3.retire-durable-memory"].destructive is True
    assert all(not by_id[i].destructive for i in W3_IDS[1:])


# ------------------------------------------------- w3.retire-durable-memory
def test_retire_exports_rows_never_promotes_then_deletes(toy):
    _legacy_memory(toy)
    assert upgrade_w3.describe_retire(toy)
    asked = []

    def ask(question):
        asked.append(question)
        return True

    report = upgrade_w3.apply_retire(toy, ask)
    assert len(asked) == 1
    assert upgrade_w3.LEGACY_DIR in asked[0]
    assert "git history" not in asked[0]
    assert not (toy / ".harness" / "memory").exists()
    legacy = _legacy_tree(toy)
    assert (legacy / "durable.jsonl").exists()        # nothing is deleted
    assert any(line.startswith("moved .harness/memory/ to "
                               f"{upgrade_w3.LEGACY_DIR}/") for line in report)
    assert sm.index_entries(toy) == []          # upgrade never promotes
    assert not (toy / sm.INDEX_REL).exists()
    export = (toy / upgrade_w3.EXPORT_REL).read_text()
    assert "mem-a1" in export and "mem-j1" in export
    assert "mem-s1" not in export               # observation rows are noise
    assert "harness memory promote --text" in export
    assert "Why: worktrees partition state." in export
    assert upgrade_w3.describe_retire(toy) == []
    assert upgrade_w3.advise_retire(toy)[0].startswith(
        f"check: review {upgrade_w3.EXPORT_REL}")
    assert ".harness/memory/" not in git(toy, "ls-files").stdout


def test_export_commands_are_shell_quoted_and_round_trip(toy):
    _legacy_memory(toy)
    upgrade_w3.apply_retire(toy, lambda question: True)
    export = (toy / upgrade_w3.EXPORT_REL).read_text()
    commands = [line for line in export.splitlines()
                if line.startswith("harness memory promote --text ")]
    assert len(commands) == 2
    texts = [shlex.split(c)[4] for c in commands]
    assert texts[1] == "F-1: retry wrappers aren't exempt"
    assert texts[0].startswith("tried sqlite advisory locks Approach:")


def test_retire_moves_an_interrupted_close_journal_to_the_cache(toy):
    _legacy_memory(toy)
    upgrade_w3.apply_retire(toy, lambda question: True)
    moved = toy / ".harness" / "cache" / "close-abc.json"
    assert moved.read_text() == '{"pending": 1}'


def test_retire_keeps_a_newer_journal_already_in_the_cache(toy):
    _legacy_memory(toy)
    cache = toy / ".harness" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "close-abc.json").write_text('{"pending": 2}')
    upgrade_w3.apply_retire(toy, lambda question: True)
    assert (cache / "close-abc.json").read_text() == '{"pending": 2}'
    kept = _legacy_tree(toy) / "session" / JOURNAL
    assert kept.read_text() == '{"pending": 1}'        # both journals kept


def test_retire_decline_asks_first_and_changes_nothing(toy):
    _legacy_memory(toy)
    before = _snapshot(toy)
    report = upgrade_w3.apply_retire(toy, lambda question: False)
    assert report == ["skipped: needs confirmation"]
    assert _snapshot(toy) == before
    assert not (toy / upgrade_w3.EXPORT_REL).exists()
    assert upgrade_w3.describe_retire(toy)
    assert upgrade_w3.advise_retire(toy) == []


def test_retire_deletes_untracked_memory_after_export(toy):
    _legacy_memory(toy, commit=False)
    assert ".harness/memory/" not in git(toy, "ls-files").stdout
    upgrade_w3.apply_retire(toy, lambda question: True)
    assert not (toy / ".harness" / "memory").exists()
    assert (_legacy_tree(toy) / "durable.jsonl").exists()
    assert "mem-a1" in (toy / upgrade_w3.EXPORT_REL).read_text()
    assert (toy / ".harness" / "cache" / "close-abc.json").exists()


def test_retire_works_in_a_root_without_git(toy):
    shutil.rmtree(toy / ".git")
    _write_rows(toy)
    upgrade_w3.apply_retire(toy, lambda question: True)
    assert not (toy / ".harness" / "memory").exists()
    assert (_legacy_tree(toy) / "durable.jsonl").exists()
    assert (toy / upgrade_w3.EXPORT_REL).exists()
    assert upgrade_w3.describe_retire(toy) == []


def test_retire_stops_before_deleting_when_git_rm_fails(toy):
    _legacy_memory(toy)
    (toy / ".git" / "index.lock").write_text("")      # git rm fails
    with pytest.raises(HarnessError) as err:
        upgrade_w3.apply_retire(toy, lambda question: True)
    assert "git rm" in str(err.value)
    assert "harness upgrade" in str(err.value)
    assert (toy / ".harness" / "memory" / "durable.jsonl").exists()
    assert ".harness/memory/durable.jsonl" in git(toy, "ls-files").stdout
    (toy / ".git" / "index.lock").unlink()
    upgrade_w3.apply_retire(toy, lambda question: True)
    assert upgrade_w3.describe_retire(toy) == []


def test_retire_is_a_no_op_without_harness_memory(toy):
    assert upgrade_w3.describe_retire(toy) == []
    assert upgrade_w3.apply_retire(toy, lambda question: True) == []


def test_retire_without_offered_rows_writes_no_export(toy):
    (toy / ".harness" / "memory" / "session").mkdir(parents=True)
    upgrade_w3.apply_retire(toy, lambda question: True)
    assert not (toy / ".harness" / "memory").exists()
    assert not (toy / upgrade_w3.EXPORT_REL).exists()
    assert upgrade_w3.advise_retire(toy) == []


# ------------------------------------------------------ w3.memory-git-lines
def test_git_lines_removed_after_memory_is_gone(toy):
    _legacy_memory(toy)
    lines = upgrade_w3.describe_git_lines(toy)
    assert any(".gitattributes" in line for line in lines)
    assert not any(".gitignore" in line for line in lines)
    upgrade_w3.apply_retire(toy, lambda question: True)
    upgrade_w3.apply_git_lines(toy, lambda question: True)
    assert ".harness/memory" not in (toy / ".gitattributes").read_text()
    assert ".harness/memory" not in (toy / ".gitignore").read_text()
    assert ".harness/cache/" in (toy / ".gitignore").read_text()
    assert upgrade_w3.describe_git_lines(toy) == []


def test_git_lines_match_equivalent_spellings(toy):
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text()
                  + "/.harness/memory/durable.jsonl\tmerge=union  \n")
    gi = toy / ".gitignore"
    gi.write_text(gi.read_text() + "  .harness/memory/session\n")
    assert len(upgrade_w3.describe_git_lines(toy)) == 2
    upgrade_w3.apply_git_lines(toy, lambda question: True)
    assert ".harness/memory" not in ga.read_text()
    assert ".harness/memory" not in gi.read_text()
    assert upgrade_w3.describe_git_lines(toy) == []


def test_git_lines_keep_unrelated_memory_lines(toy):
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text()
                  + ".harness/memory/durable.jsonl merge=union -diff\n")
    assert upgrade_w3.describe_git_lines(toy) == []


# --------------------------------------------------- w3.shared-memory-index
def test_index_step_creates_the_shared_index_once(toy):
    assert upgrade_w3.describe_index(toy) == [f"create {sm.INDEX_REL}"]
    upgrade_w3.apply_index(toy, lambda question: True)
    assert (toy / sm.INDEX_REL).read_text() == sm.INDEX_HEADER
    assert upgrade_w3.describe_index(toy) == []
    assert upgrade_w3.apply_index(toy, lambda question: True) == []


G10_GATE = '''GATE = {"id": "G10", "rule_ref": "adr:007",
        "preferred": ["unit_complete"]}


def run(ctx):
    return []
'''


def test_consumer_gate_named_g10_gets_advice(toy):
    import yaml
    gates_dir = toy / ".harness" / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    (gates_dir / "mine.py").write_text(G10_GATE)
    cfg = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg.read_text()) or {}
    doc.setdefault("gates", {})["extra"] = [".harness/gates/mine.py"]
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False))
    advice = upgrade_w3.advise_index(toy)
    assert len(advice) == 1
    assert advice[0].startswith("check: ")
    assert ".harness/gates/mine.py" in advice[0] and "G10" in advice[0]
    assert len(advice[0].split()) <= 30


def test_no_g10_advice_without_a_clash(toy):
    assert upgrade_w3.advise_index(toy) == []


# ------------------------------------------------------ w3.claude-md-import
def test_claude_md_import_added_only_to_marked_files(toy):
    (toy / "CLAUDE.md").write_text(
        "# CLAUDE.md\n\nThis repo is harness-enforced.\n\n@AGENTS.md\n")
    assert upgrade_w3.describe_claude(toy) == [
        f"add {sm.CLAUDE_IMPORT} to CLAUDE.md"]
    upgrade_w3.apply_claude(toy, lambda question: True)
    assert sm.claude_md_state(toy) == "current"
    assert upgrade_w3.describe_claude(toy) == []
    assert upgrade_w3.advise_claude(toy) == []


def test_unmarked_claude_md_is_advice_not_pending(toy):
    (toy / "CLAUDE.md").write_text("# team notes\n")
    assert upgrade_w3.describe_claude(toy) == []      # second run stays clean
    assert upgrade_w3.apply_claude(toy, lambda question: True) == []
    assert (toy / "CLAUDE.md").read_text() == "# team notes\n"
    advice = upgrade_w3.advise_claude(toy)
    assert len(advice) == 1 and sm.CLAUDE_IMPORT in advice[0]
    assert advice[0].startswith("check: ")


def test_missing_claude_md_is_advice_and_never_created(toy):
    (toy / "CLAUDE.md").unlink(missing_ok=True)
    assert upgrade_w3.describe_claude(toy) == []
    assert upgrade_w3.apply_claude(toy, lambda question: True) == []
    assert not (toy / "CLAUDE.md").exists()
    advice = upgrade_w3.advise_claude(toy)
    assert len(advice) == 1 and sm.CLAUDE_IMPORT in advice[0]


# ------------------------------------------------------------ whole plan
def test_plan_lists_w3_changes_then_nothing_after_apply(toy):
    from engine import upgrade_010
    _legacy_memory(toy)
    (toy / "CLAUDE.md").write_text("This repo is harness-enforced.\n")
    pending = {p["id"] for p in upgrade_010.plan(toy)}
    assert set(W3_IDS) <= pending
    for step in [s for s in upgrade_010.STEPS if s.id.startswith("w3.")]:
        step.apply(toy, lambda question: True)
    assert not {p["id"] for p in upgrade_010.plan(toy)} & set(W3_IDS)


def test_run_with_declines_reports_skip_and_keeps_memory(toy):
    from engine import upgrade_010
    _legacy_memory(toy)
    results = {r["id"]: r for r in
               upgrade_010.run(toy, lambda question: False, dry_run=False)}
    assert results["w3.retire-durable-memory"]["report"] == [
        upgrade_010.SKIPPED]
    assert (toy / ".harness" / "memory" / "durable.jsonl").exists()
    assert ".harness/memory/session/" in (toy / ".gitignore").read_text()


# ------------------------------------------------------------ fix round 1
def test_retire_exports_session_rows_and_promoted_reasoning(toy):
    _legacy_memory(toy)
    session = toy / ".harness" / "memory" / "session" / "slice-007.jsonl"
    append_jsonl(session, _row("mem-w1", "attempt", "",
                               {"approach": "inline cache", "outcome": "abandoned",
                                "why": "stale reads"}))
    reasoning = _row("mem-r1", "reasoning", "keep ids stable")
    reasoning["promote"] = True
    append_jsonl(session, reasoning)
    append_jsonl(session, _row("mem-r2", "reasoning", "scratch thought"))
    append_jsonl(session, _row("mem-a1", "attempt", "duplicate id"))
    upgrade_w3.apply_retire(toy, lambda question: True)
    export = (toy / upgrade_w3.EXPORT_REL).read_text()
    assert "mem-w1" in export and "Approach: inline cache." in export
    assert "mem-r1" in export and "mem-r2" not in export
    assert "duplicate id" not in export
    assert (_legacy_tree(toy) / "session" / "slice-007.jsonl").exists()


def test_export_merges_by_row_id_and_never_drops_rows(toy):
    _legacy_memory(toy)
    upgrade_w3.apply_retire(toy, lambda question: True)
    export = toy / upgrade_w3.EXPORT_REL
    export.write_text(export.read_text() + "\nmy review note\n")
    mem = toy / ".harness" / "memory"
    append_jsonl(mem / "durable.jsonl", _row("mem-z1", "adjudication", "zed"))
    append_jsonl(mem / "durable.jsonl", _row("mem-a1", "attempt", "changed"))
    report = upgrade_w3.apply_retire(toy, lambda question: True)
    text = export.read_text()
    assert "mem-a1" in text and "mem-j1" in text and "mem-z1" in text
    assert "my review note" in text
    assert "changed" not in text
    assert text.count("harness-export-row: mem-a1 ") == 1
    assert f"exported 1 new rows to {upgrade_w3.EXPORT_REL}" in report
    assert len(list((toy / upgrade_w3.LEGACY_DIR).iterdir())) == 2


def test_export_fence_is_longer_than_backticks_in_content(toy):
    (toy / ".harness" / "memory").mkdir(parents=True)
    append_jsonl(toy / ".harness" / "memory" / "durable.jsonl",
                 _row("mem-f1", "adjudication", "use ```` fences and `x`"))
    upgrade_w3.apply_retire(toy, lambda question: True)
    lines = (toy / upgrade_w3.EXPORT_REL).read_text().splitlines()
    assert "`````bash" in lines
    i = lines.index("`````bash")
    assert lines[i + 2] == "`````"
    assert shlex.split(lines[i + 1])[4] == "use ```` fences and `x`"


def _bad_memory(toy, data: bytes):
    mem = toy / ".harness" / "memory"
    (mem / "session").mkdir(parents=True)
    append_jsonl(mem / "durable.jsonl", _row("mem-a1", "attempt", "ok"))
    (mem / "session" / "slice-009.jsonl").write_bytes(data)


def test_bad_json_line_is_pending_and_apply_raises_before_changes(toy):
    _bad_memory(toy, b'{"kind": "attempt"}\nnot json\n')
    lines = upgrade_w3.describe_retire(toy)
    assert len(lines) == 1
    msg = lines[0]
    assert ".harness/memory/session/slice-009.jsonl line 2" in msg
    assert str(toy) not in msg
    assert msg.endswith("then run: harness upgrade")
    assert len(msg.split()) <= 25
    before = _snapshot(toy)
    asked = []
    with pytest.raises(HarnessError) as err:
        upgrade_w3.apply_retire(toy, lambda q: asked.append(q) or True)
    assert str(err.value) == msg
    assert asked == [] and _snapshot(toy) == before


def test_bad_utf8_is_a_harness_error_not_a_crash(toy):
    from engine import upgrade_010
    _bad_memory(toy, b'{"content": "\xff\xfe"}\n')
    msg = upgrade_w3.describe_retire(toy)[0]
    assert "slice-009.jsonl is not valid UTF-8" in msg
    assert len(msg.split()) <= 25
    ids = {p["id"] for p in upgrade_010.plan(toy)}     # dry run still works
    assert "w3.retire-durable-memory" in ids
    with pytest.raises(HarnessError):
        upgrade_w3.apply_retire(toy, lambda question: True)
    assert (toy / ".harness" / "memory" / "durable.jsonl").exists()


def test_git_lines_keep_utf8_text(toy):
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text(encoding="utf-8") + "# café\n"
                  ".harness/memory/durable.jsonl merge=union\n",
                  encoding="utf-8")
    upgrade_w3.apply_git_lines(toy, lambda question: True)
    assert "# café" in ga.read_text(encoding="utf-8")


def test_gate_exiting_at_import_gets_no_advice_and_others_still_do(toy):
    import yaml
    gates_dir = toy / ".harness" / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    (gates_dir / "boom.py").write_text("import sys\nsys.exit(3)\n")
    (gates_dir / "mine.py").write_text(G10_GATE)
    cfg = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg.read_text()) or {}
    doc.setdefault("gates", {})["extra"] = [".harness/gates/boom.py",
                                            ".harness/gates/mine.py"]
    cfg.write_text(yaml.safe_dump(doc, sort_keys=False))
    advice = upgrade_w3.advise_index(toy)
    assert len(advice) == 1 and ".harness/gates/mine.py" in advice[0]
