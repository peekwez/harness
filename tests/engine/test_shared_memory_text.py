"""Skill and agent text for shared memory (D-0.10-02)."""
from conftest import PLUGIN_ROOT


def _read(rel):
    return (PLUGIN_ROOT / rel).read_text()


def test_close_slice_offers_personal_memory_for_promotion():
    text = _read("skills/close-slice/SKILL.md")
    assert "memory changed --slice $1" in text
    assert "Promote any to shared?" in text
    assert "memory promote" in text
    assert "autoMemoryDirectory" in text and "~/.claude/projects/" in text
    assert "memory compaction" not in text and "durable" not in text


def test_reviewer_agent_no_longer_bars_a_removed_path():
    text = _read("agents/reviewer.md")
    assert "disallowed-paths" not in text and ".harness/memory" not in text
    assert "personal memory" in text


def test_review_skill_describes_edge_only_adjudication():
    text = _read("skills/review/adjudicate.md")
    assert "suggest" in text and "harness memory promote" in text


def test_close_slice_offers_promotion_before_the_close_commit():
    """Promoted facts must ride the slice commit (final fix I1)."""
    text = _read("skills/close-slice/SKILL.md")
    offer = text.index("Promote any to shared?")
    commit = text.index("git add -A -- . ':(exclude).harness' && git commit")
    close = text.index("close-slice --slice $1 --commit HEAD")
    assert offer < commit < close
    assert "dir_exists" in text
