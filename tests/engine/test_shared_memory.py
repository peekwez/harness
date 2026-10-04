"""Shared memory (D-0.10-02): promote, index, personal-memory lookup."""
import json
import os
import re
import subprocess

import pytest

from engine import HarnessError
from engine import shared_memory as sm

SHARED = ".claude/memory/shared"


def _personal(tmp_path, name="testing.md", body=None):
    path = tmp_path / "personal" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else (
        "---\nname: Run tests with uv\n"
        "description: Use uv run pytest, never bare pytest\n"
        "type: feedback\n---\n\nAlways run `uv run pytest`.\n"))
    return path


@pytest.mark.parametrize("rel", [
    ".claude/memory/shared",
    ".claude/memory/shared/MEMORY.md",
    "./.claude/memory/shared/x.md",
    "docs/../.claude/memory/shared/x.md",
    ".Claude/Memory/Shared/X.md",
    ".worktrees/slice-1/.claude/memory/shared/x.md",
    ".claude\\memory\\shared\\x.md",
])
def test_in_shared_dir_matches_every_spelling(rel):
    assert sm.in_shared_dir(rel)


@pytest.mark.parametrize("rel", [
    ".claude/memory/notes.md",
    ".claude/memory/shared-old/x.md",
    ".claude/settings.json",
    "/elsewhere/.claude/memory/shared/x.md",
])
def test_in_shared_dir_rejects_other_paths(rel):
    assert not sm.in_shared_dir(rel)


def test_slugify():
    assert sm.slugify("Run tests with UV!") == "run-tests-with-uv"
    assert sm.slugify("ünïcode only ☃") == "n-code-only"
    assert sm.slugify("☃") == "fact"
    long = sm.slugify("word " * 40)
    assert len(long) <= sm.MAX_SLUG and not long.endswith("-")


def test_index_line_truncates_title_and_summary():
    line = sm.index_line("T" * 300, "s" * 50, "S" * 300)
    assert len(line) <= sm.MAX_INDEX_LINE
    assert line.startswith("- [T")
    assert "](" + "s" * 50 + ".md)" in line


def test_index_line_strips_brackets_and_newlines_from_title():
    line = sm.index_line("a [b]\nc", "abc", "sum")
    assert line == "- [a (b) c](abc.md) — sum"


def test_promote_file_copies_fact_with_front_matter(toy, tmp_path):
    out = sm.promote(toy, source=_personal(tmp_path))
    assert out["promoted"] is True
    assert out["path"] == f"{SHARED}/run-tests-with-uv.md"
    meta, body = sm.split_front_matter((toy / out["path"]).read_text())
    assert meta["promoted_by"] == "t <t@t>"
    assert re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", meta["promoted_at"])
    assert meta["type"] == "feedback"
    assert body.strip() == "Always run `uv run pytest`."
    expected = ("- [Run tests with uv](run-tests-with-uv.md) — "
                "Use uv run pytest, never bare pytest")
    assert sm.index_entries(toy) == [expected]
    assert out["index_line"] == expected and out["entries"] == 1


def test_promote_text_names_the_fact_from_its_words(toy):
    out = sm.promote(toy, text="Deploys happen on Tuesdays only.")
    assert out["path"] == f"{SHARED}/deploys-happen-on-tuesdays-only.md"
    assert sm.index_entries(toy)[0].endswith("— Deploys happen on Tuesdays only.")


def test_promote_twice_is_a_no_op(toy, tmp_path):
    src = _personal(tmp_path)
    sm.promote(toy, source=src)
    again = sm.promote(toy, source=src)
    assert again["promoted"] is False and again["reason"] == "already shared"
    assert len(sm.index_entries(toy)) == 1


def test_promote_refuses_a_different_fact_with_the_same_name(toy):
    sm.promote(toy, text="Deploys happen on Tuesdays.", name="deploys")
    with pytest.raises(HarnessError, match="--name"):
        sm.promote(toy, text="Deploys happen on Fridays.", name="deploys")


def test_promote_refuses_an_index_file(toy, tmp_path):
    src = _personal(tmp_path, name="MEMORY.md", body="- [a](a.md)\n")
    with pytest.raises(HarnessError, match="index"):
        sm.promote(toy, source=src)


def test_promote_refuses_empty_and_double_input(toy, tmp_path):
    with pytest.raises(HarnessError, match="empty"):
        sm.promote(toy, text="   ")
    with pytest.raises(HarnessError, match="one fact"):
        sm.promote(toy)
    with pytest.raises(HarnessError, match="one fact"):
        sm.promote(toy, source=_personal(tmp_path), text="x")


def test_promote_refuses_a_missing_file(toy, tmp_path):
    with pytest.raises(HarnessError, match="not found"):
        sm.promote(toy, source=tmp_path / "nope.md")


def test_promote_without_git_identity_fails_and_writes_nothing(toy, monkeypatch):
    subprocess.run(["git", "-C", str(toy), "config", "--unset", "user.name"],
                   check=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    with pytest.raises(HarnessError, match="user.name"):
        sm.promote(toy, text="Deploys happen on Tuesdays.")
    assert not (toy / SHARED).exists()


def test_long_fact_keeps_a_short_valid_index_line(toy):
    out = sm.promote(toy, text=("word " * 200).strip())
    assert len(out["index_line"]) <= sm.MAX_INDEX_LINE
    assert re.match(r"- \[[^\]]+\]\([a-z0-9-]+\.md\)", out["index_line"])


def test_personal_memory_dir_defaults_to_claude_projects_slug(
        toy, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(toy.resolve()))
    assert sm.personal_memory_dir(toy) == (
        tmp_path / "home" / ".claude" / "projects" / slug / "memory")


def test_personal_memory_dir_is_shared_by_worktrees(toy, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(toy), "worktree", "add", "-q", str(wt)],
                   check=True)
    assert sm.personal_memory_dir(wt) == sm.personal_memory_dir(toy)


def test_auto_memory_directory_setting_wins(toy, tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryDirectory": str(tmp_path / "user-mem")}))
    assert sm.personal_memory_dir(toy) == tmp_path / "user-mem"
    (toy / ".claude").mkdir(exist_ok=True)
    # project settings may not redirect personal memory
    (toy / ".claude" / "settings.json").write_text(
        json.dumps({"autoMemoryDirectory": str(tmp_path / "evil")}))
    assert sm.personal_memory_dir(toy) == tmp_path / "user-mem"
    (toy / ".claude" / "settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": "~/local-mem"}))
    assert sm.personal_memory_dir(toy) == home / "local-mem"


def test_relative_auto_memory_directory_is_ignored(toy, tmp_path, monkeypatch):
    # Claude Code does not support relative paths; do not guess a base.
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    (toy / ".claude").mkdir(exist_ok=True)
    (toy / ".claude" / "settings.local.json").write_text(
        json.dumps({"autoMemoryDirectory": "rel/mem"}))
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(toy.resolve()))
    assert sm.personal_memory_dir(toy) == (
        home / ".claude" / "projects" / slug / "memory")


def test_changed_since_filters_by_mtime_and_skips_the_index(tmp_path):
    d = tmp_path / "mem"
    d.mkdir()
    for name, mtime in (("old.md", 1000), ("new.md", 3000),
                        ("MEMORY.md", 3000), ("notes.txt", 3000)):
        (d / name).write_text("x")
        os.utime(d / name, (mtime, mtime))
    assert sm.changed_since(d, 2000) == [str(d / "new.md")]
    assert sm.changed_since(tmp_path / "missing", 0) == []


def test_claude_md_states(tmp_path):
    assert sm.claude_md_state(tmp_path) == "missing"
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# CLAUDE.md\n\nThis repo is harness-enforced.\n\n@AGENTS.md\n")
    assert sm.claude_md_state(tmp_path) == "marked"
    assert sm.add_claude_import(tmp_path) is True
    assert sm.claude_md_state(tmp_path) == "current"
    assert claude.read_text().count(sm.CLAUDE_IMPORT) == 1
    assert claude.read_text().endswith("@AGENTS.md\n" + sm.CLAUDE_IMPORT + "\n")
    assert sm.add_claude_import(tmp_path) is False
    claude.write_text("# my own notes\n")
    assert sm.claude_md_state(tmp_path) == "unmarked"
    assert sm.add_claude_import(tmp_path) is False
    assert claude.read_text() == "# my own notes\n"


def test_ensure_index_is_idempotent(toy):
    assert sm.ensure_index(toy) is True
    first = (toy / sm.INDEX_REL).read_text()
    assert first.startswith("# Shared memory")
    assert sm.ensure_index(toy) is False
    assert (toy / sm.INDEX_REL).read_text() == first
    assert sm.index_entries(toy) == []


def test_promote_never_overwrites_the_index_by_name(toy, tmp_path):
    sm.ensure_index(toy)
    before = (toy / sm.INDEX_REL).read_text()
    with pytest.raises(HarnessError, match="--name"):
        sm.promote(toy, text="Memory")
    with pytest.raises(HarnessError, match="--name"):
        sm.promote(toy, text="Deploys on Tuesdays.", name="memory")
    src = _personal(tmp_path, name="memory.md", body="Some fact.\n")
    with pytest.raises(HarnessError, match="--name"):
        sm.promote(toy, source=src)
    assert (toy / sm.INDEX_REL).read_text() == before


def test_promote_refuses_a_symlink_in_the_shared_folder(toy, tmp_path):
    outside = tmp_path / "outside.md"
    shared = toy / SHARED
    shared.mkdir(parents=True)
    (shared / "evil.md").symlink_to(outside)
    with pytest.raises(HarnessError, match="link"):
        sm.promote(toy, text="x", name="evil")
    assert not outside.exists()


def test_promote_refuses_a_symlinked_shared_folder(toy, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (toy / ".claude" / "memory").mkdir(parents=True, exist_ok=True)
    (toy / SHARED).symlink_to(elsewhere)
    with pytest.raises(HarnessError, match="link"):
        sm.promote(toy, text="Deploys on Tuesdays.")
    assert list(elsewhere.iterdir()) == []


def test_promote_leaves_no_temp_files(toy):
    sm.promote(toy, text="Deploys happen on Tuesdays.")
    assert sorted(p.name for p in (toy / SHARED).iterdir()) == [
        "MEMORY.md", "deploys-happen-on-tuesdays.md"]


def test_split_front_matter_edge_cases():
    meta, body = sm.split_front_matter("---\r\nname: a\r\n---\r\n\r\nBody\r\n")
    assert meta == {"name": "a"} and body.strip() == "Body"
    assert sm.split_front_matter("---\n---\nBody\n") == ({}, "Body\n")
    # a closing line must be exactly ---
    text = "---\nname: a\n----\nBody\n"
    assert sm.split_front_matter(text) == ({}, text)
    text = "---\nname: a\n---x\nBody\n"
    assert sm.split_front_matter(text) == ({}, text)


def test_promote_refuses_a_non_utf8_file(toy, tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(HarnessError, match="UTF-8"):
        sm.promote(toy, source=bad)


def test_claude_md_marker_is_line_anchored(tmp_path):
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("We are not harness-enforced.\n")
    assert sm.claude_md_state(tmp_path) == "unmarked"
    claude.write_text("# CLAUDE.md\n\nThis repo is harness-enforced. "
                      "The working agreement is in AGENTS.md.\n")
    assert sm.claude_md_state(tmp_path) == "marked"


def test_index_line_truncates_multibyte_text():
    line = sm.index_line("é" * 300, "slug", "日本語" * 100)
    assert len(line) <= sm.MAX_INDEX_LINE
    assert line.startswith("- [é") and "](slug.md)" in line


def _index_with(toy, n):
    sm.ensure_index(toy)
    lines = "".join(f"- [f{i}](f{i}.md) — fact {i}\n" for i in range(n))
    index = toy / sm.INDEX_REL
    index.write_text(index.read_text() + lines)


def test_doctor_warns_above_forty_shared_entries(toy):
    from conftest import run_cli
    _index_with(toy, 41)
    out = json.loads(run_cli("doctor", "--substrate", root=toy).stdout)
    assert out["shared_memory"]["entries"] == 41
    assert out["shared_memory"]["limit"] == 40
    assert any("41 entries" in w for w in out["shared_memory"]["warnings"])
    # advisory: warnings never change substrate health
    assert out["substrate_healthy"] is True


def test_doctor_is_quiet_at_forty_entries(toy):
    _index_with(toy, 40)
    assert sm.shared_memory_health(toy)["warnings"] == []


def test_doctor_warns_when_shared_memory_is_git_ignored(toy):
    sm.ensure_index(toy)
    gi = toy / ".gitignore"
    gi.write_text((gi.read_text() if gi.exists() else "") + ".claude/\n")
    warnings = sm.shared_memory_health(toy)["warnings"]
    assert any("gitignored" in w for w in warnings)


def test_doctor_names_a_missing_index(toy):
    warnings = sm.shared_memory_health(toy)["warnings"]
    assert any("harness upgrade" in w for w in warnings)


def test_doctor_warns_for_a_harness_root_inside_a_repo_subdirectory(tmp_path):
    sub = tmp_path / "mono" / "sub"
    sub.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(tmp_path / "mono")], check=True)
    (tmp_path / "mono" / ".gitignore").write_text(".claude/\n")
    sm.ensure_index(sub)
    assert any("gitignored" in w
               for w in sm.shared_memory_health(sub)["warnings"])


def test_doctor_does_not_crash_without_git(toy, monkeypatch):
    sm.ensure_index(toy)
    monkeypatch.setenv("PATH", "/nonexistent")
    assert sm.shared_memory_health(toy)["warnings"] == []
