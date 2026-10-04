"""Spec 5.6: `gates.exempt_paths` replaces SUBSTRATE_PREFIXES and the G5
tuple. G3, G5, the permit layer and the close ceremony all read it."""
import json

import pytest
import yaml

from conftest import make_event, run_cli
from engine import HarnessError, read_jsonl, write_jsonl
from engine.events import handle_event
from engine.gates import exempt, exempt_paths

SPEC_DEFAULT = (".harness/", "adr/", ".github/", "tests/", "docs/",
                ".claude/", "explore/")


def _codes(verdict):
    return {f["code"] for f in verdict["findings"]}


def test_default_exempt_paths_match_the_spec():
    assert exempt_paths({}) == SPEC_DEFAULT
    assert exempt_paths(None) == SPEC_DEFAULT
    assert exempt("explore/toy.py", {})
    assert exempt("docs/notes.md", None)
    assert not exempt("contracts/api.yaml", {})
    assert not exempt("src/app.py", {})


def test_default_config_carries_the_default_list():
    from engine import DEFAULT_CONFIG
    assert tuple(DEFAULT_CONFIG["gates"]["exempt_paths"]) == SPEC_DEFAULT


def test_config_replaces_the_default_list():
    cfg = {"gates": {"exempt_paths": ["generated/"]}}
    assert exempt("generated/client.py", cfg)
    assert not exempt("docs/notes.md", cfg)


@pytest.mark.parametrize("bad", ["docs/", [""], [1], {"docs/": True}])
def test_malformed_exempt_paths_fail_loud(bad):
    with pytest.raises(HarnessError, match="gates.exempt_paths"):
        exempt("x.py", {"gates": {"exempt_paths": bad}})


def test_g3_raises_no_scope_finding_under_explore(toy):
    v = handle_event(make_event("pre_change", session="ex3",
                                files=["explore/toy.py"]), toy)
    assert "UNDECLARED_FILE" not in _codes(v)


def test_g3_reads_a_configured_prefix(toy):
    cfg_path = toy / ".harness" / "config.yaml"
    doc = yaml.safe_load(cfg_path.read_text())
    doc["gates"]["exempt_paths"] = ["generated/"]
    cfg_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    v = handle_event(make_event("pre_change", session="ex3c",
                                files=["generated/client.py"]), toy)
    assert "UNDECLARED_FILE" not in _codes(v)
    v2 = handle_event(make_event("pre_change", session="ex3c",
                                 files=["docs/notes.md"]), toy)
    assert "UNDECLARED_FILE" in _codes(v2), "the list replaces the default"


def test_g5_skips_exempt_paths(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["declares_dep"] = ["config"]          # telemetry is undeclared
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    (toy / "explore").mkdir()
    (toy / "explore" / "toy.py").write_text(
        "import telemetry\n\n\ndef f():\n"
        "    return telemetry.emit_span('x', {})\n")
    handle_event(make_event("post_change", session="ex5",
                            files=["explore/toy.py"]), toy)
    v = handle_event(make_event("unit_complete", session="ex5"), toy)
    hits = [f for f in v["findings"]
            if f["code"] in ("UNDECLARED_USE", "DUPLICATE_CANDIDATE")
            and "explore/toy.py" in f["message"]]
    assert hits == []


def test_permit_auto_approves_exempt_paths(toy):
    out = json.loads(run_cli("permit", "--paths", "explore/toy.py",
                             "--slice", "slice-042", root=toy).stdout)
    assert out["allow"] is True
    out = json.loads(run_cli("permit", "--paths", "rogue.py",
                             "--slice", "slice-042", root=toy).stdout)
    assert out["allow"] is False


def test_hardcoded_prefixes_are_gone():
    import engine.gates.g3_scope as g3
    assert not hasattr(g3, "SUBSTRATE_PREFIXES")


def test_entry_without_slash_matches_a_whole_segment():
    cfg = {"gates": {"exempt_paths": ["docs"]}}
    assert exempt("docs/notes.md", cfg)
    assert exempt("docs", cfg)
    assert not exempt("docsite/index.html", cfg)
    assert not exempt("docs.md", cfg)


def test_entry_with_slash_keeps_prefix_semantics():
    cfg = {"gates": {"exempt_paths": ["docs/"]}}
    assert exempt("docs/notes.md", cfg)
    assert not exempt("docsite/index.html", cfg)


def test_leading_dot_slash_is_ignored():
    cfg = {"gates": {"exempt_paths": ["./docs/", "./generated"]}}
    assert exempt("docs/notes.md", cfg)
    assert exempt("./docs/notes.md", cfg)
    assert exempt("generated/client.py", cfg)
    assert exempt("./tests/test_x.py", {})
