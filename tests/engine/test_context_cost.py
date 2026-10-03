"""Always-on context cost (spec §7.5): per source, chars and tokens."""
import json

from conftest import make_event, run_cli
from engine.context_cost import always_on_cost, listing_chars
from engine.events import handle_event

SOURCES = {"skills", "agents", "agents_md", "shared_memory", "last_injection"}


def test_status_reports_always_on_cost_per_source(toy):
    (toy / "AGENTS.md").write_text("x" * 400)
    v = handle_event(make_event("pre_context", session="cost"), toy)
    out = json.loads(run_cli("status", root=toy).stdout)
    cost = out["always_on"]
    assert set(cost["sources"]) == SOURCES
    assert cost["sources"]["agents_md"] == {"chars": 400, "tokens": 100}
    assert cost["sources"]["shared_memory"] == {"chars": 0, "tokens": 0}
    assert cost["sources"]["skills"]["chars"] > 0
    assert cost["sources"]["agents"]["chars"] > 0
    assert cost["sources"]["last_injection"]["chars"] == \
        len("\n\n".join(v["injections"]))
    assert cost["total"]["chars"] == sum(
        s["chars"] for s in cost["sources"].values())


def test_listing_chars_counts_name_and_description_only(tmp_path):
    skill = tmp_path / "skills" / "a"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: a\ndescription: Does b.\n---\nbody text is not listed\n")
    assert listing_chars(tmp_path / "skills", "*/SKILL.md") == len("a: Does b.")


def test_shared_memory_index_is_counted(toy):
    index = toy / ".claude" / "memory" / "shared" / "MEMORY.md"
    index.parent.mkdir(parents=True)
    index.write_text("- a fact\n")
    assert always_on_cost(toy)["sources"]["shared_memory"]["chars"] == 9
