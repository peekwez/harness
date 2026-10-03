"""W2 upgrade steps: each converges, and describe() is [] after apply()."""
import json
import sqlite3

import pytest
import yaml

from conftest import cite_non_goals, git
from engine import HarnessError, read_jsonl, write_jsonl
from engine import upgrade_010, upgrade_w2

YES = lambda _question: True   # noqa: E731
NO = lambda _question: False   # noqa: E731

W2_IDS = ["w2.slice-metrics", "w2.telemetry", "w2.config",
          "w2.skill-names", "w2.contracts"]
DEFAULT_EXEMPT = [".harness/", "adr/", ".github/", "tests/", "docs/",
                  ".claude/", "explore/"]
AGENTS_MARKER = "<!-- harness:agents-md 0.10 -->"
LEGACY_AGENTS_LINE = "# AGENTS.md — this repo is harness-enforced"

OLD_CONFIG = """\
# harness per-repo engine config (authored — edit freely, then commit)
schema: 1
gates:
  g3_mode: allow_with_findings      # keep this comment
  g5_override: recorded_justification
  g5_similarity_threshold: 0.6
review:
  fork_for_security_rows: true
ensemble:
  trigger_confidence_below: 0.7
  samples: 3
languages:
  python: true
telemetry:
  compaction_is_defect: false
"""


def _step(step_id):
    from engine.upgrade_010 import STEPS
    return next(s for s in STEPS if s.id == step_id)


def _legacy_telemetry(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    rows.append({**rows[0], "id": "slice-open", "status": "in_progress"})
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    write_jsonl(toy / ".harness" / "telemetry.archive.jsonl", [
        {"id": "e1", "ts": "2026-09-01T00:00:00+00:00", "kind": "event",
         "meta": {"slice": "slice-042", "gates": ["gate:G3"]}}])
    (toy / ".harness" / "telemetry.jsonl").write_text(
        json.dumps({"id": "e2", "ts": "2026-09-02T00:00:00+00:00",
                    "kind": "slice_closed", "meta": {"slice": "slice-042"}})
        + "\n{torn\n"
        + json.dumps({"id": "e3", "ts": "2026-09-03T00:00:00+00:00",
                      "kind": "event",
                      "meta": {"slice": "slice-open", "gates": ["gate:G5"]}})
        + "\n")
    (toy / ".harness" / "telemetry.quarantine.jsonl").write_text("{}\n")
    con = sqlite3.connect(str(toy / ".harness" / "sidecar.db"))
    con.execute("CREATE TABLE IF NOT EXISTS telemetry_buffer("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT)")
    con.execute("INSERT INTO telemetry_buffer(row) VALUES(?)", (json.dumps(
        {"id": "e4", "ts": "2026-09-01T12:00:00+00:00",
         "kind": "COMPACTION_REACHED", "meta": {"slice": "slice-042"}}),))
    con.commit()
    con.close()


def _no_non_goals(toy):
    write_jsonl(toy / ".harness" / "boundaries.jsonl", [])


def _advice(step_id, root):
    step = _step(step_id)
    return step.advise(root) if step.advise else []


def test_w2_steps_are_registered_in_order():
    from engine.upgrade_010 import STEPS
    ids = [s.id for s in STEPS if s.id.startswith("w2.")]
    assert ids == W2_IDS
    assert [s.id for s in STEPS].index("w2.slice-metrics") > \
        [s.id for s in STEPS].index("w1.drop-resolver-config")
    assert _step("w2.telemetry").destructive is True
    assert all(not _step(i).destructive for i in W2_IDS if i != "w2.telemetry")


def test_toy_repo_is_already_on_the_w2_shape(toy):
    cite_non_goals(toy, "adr:007")
    for step_id in W2_IDS:
        assert _step(step_id).describe(toy) == [], step_id
        assert _advice(step_id, toy) == [], step_id


# ------------------------------------------------------- w2.slice-metrics
def test_metrics_step_rewrites_gitattributes(toy):
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text().replace(
        ".harness/slice-metrics.jsonl merge=harness-substrate\n",
        ".harness/telemetry.jsonl merge=union\n"))
    (toy / ".harness" / "slice-metrics.jsonl").unlink()
    step = _step("w2.slice-metrics")
    assert len(step.describe(toy)) == 3
    step.apply(toy, NO)
    text = ga.read_text()
    assert ".harness/telemetry.jsonl merge=union" not in text
    assert ".harness/slice-metrics.jsonl merge=harness-substrate" in text
    assert ".harness/edges.jsonl merge=union" in text
    assert (toy / ".harness" / "slice-metrics.jsonl").exists()
    assert step.describe(toy) == []


def test_metrics_step_ignores_rule_spacing(toy):
    ga = toy / ".gitattributes"
    ga.write_text(ga.read_text().replace(
        ".harness/slice-metrics.jsonl merge=harness-substrate",
        ".harness/slice-metrics.jsonl  merge=harness-substrate"))
    assert _step("w2.slice-metrics").describe(toy) == []
    ga.write_text(ga.read_text() + ".harness/telemetry.jsonl   merge=union\n")
    step = _step("w2.slice-metrics")
    assert len(step.describe(toy)) == 1
    step.apply(toy, NO)
    assert "telemetry.jsonl" not in ga.read_text()
    assert ga.read_text().count("slice-metrics.jsonl") == 1


def test_metrics_step_keeps_existing_summary_rows(toy):
    write_jsonl(toy / ".harness" / "slice-metrics.jsonl", [{"id": "s-1"}])
    (toy / ".gitattributes").write_text("")
    _step("w2.slice-metrics").apply(toy, NO)
    assert read_jsonl(toy / ".harness" / "slice-metrics.jsonl") == [{"id": "s-1"}]


# ---------------------------------------------------------- w2.telemetry
def test_telemetry_step_needs_confirmation(toy):
    _legacy_telemetry(toy)
    step = _step("w2.telemetry")
    before = (toy / ".harness" / "telemetry.jsonl").read_bytes()
    assert step.apply(toy, NO) == ["skipped: needs confirmation"]
    assert (toy / ".harness" / "telemetry.jsonl").read_bytes() == before
    assert (toy / ".harness" / "telemetry.archive.jsonl").exists()
    assert read_jsonl(toy / ".harness" / "slice-metrics.jsonl") == []
    assert step.describe(toy)


def test_telemetry_step_declined_through_run_reports_a_skip(toy):
    _legacy_telemetry(toy)
    rows = upgrade_010.run(toy, NO, dry_run=False)
    row = next(r for r in rows if r["id"] == "w2.telemetry")
    assert row["report"] == ["skipped: needs confirmation"]
    assert (toy / ".harness" / "telemetry.jsonl").exists()


def test_telemetry_step_converts_then_deletes(toy):
    _legacy_telemetry(toy)
    step = _step("w2.telemetry")
    assert len(step.describe(toy)) == 4
    report = step.apply(toy, YES)
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "slice-metrics.jsonl")}
    row = rows["slice-042"]
    assert row["gates_fired"] == {"gate:G3": 1}
    assert row["compactions"] == 1
    assert row["closed_at"] == "2026-09-02T00:00:00+00:00"
    assert row["source"] == "upgrade"
    assert "slice-open" not in rows
    events = read_jsonl(toy / ".harness" / "cache" / "events.jsonl")
    assert any(e["meta"].get("slice") == "slice-open" for e in events)
    assert not any(e["meta"].get("slice") == "slice-042" for e in events)
    for name in ("telemetry.jsonl", "telemetry.archive.jsonl",
                 "telemetry.quarantine.jsonl"):
        assert not (toy / ".harness" / name).exists(), name
        # untracked by git: moved to the cache, not deleted
        assert (toy / ".harness" / "cache" / "legacy-telemetry" / name).exists()
    assert not any("git history keeps" in line for line in report)
    con = sqlite3.connect(str(toy / ".harness" / "sidecar.db"))
    assert con.execute("SELECT name FROM sqlite_master WHERE "
                       "name='telemetry_buffer'").fetchone() is None
    con.close()
    assert any("skipped 1 unreadable" in line for line in report)
    assert step.describe(toy) == []


def _write_telemetry(toy, *rows, raw=""):
    (toy / ".harness" / "telemetry.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows) + raw)


def _close_042(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)


def test_telemetry_step_describes_quarantine_as_delete(toy):
    (toy / ".harness" / "telemetry.quarantine.jsonl").write_text("{}\n")
    assert _step("w2.telemetry").describe(toy) == [
        "delete .harness/telemetry.quarantine.jsonl"]


def test_telemetry_step_deletes_tracked_files(toy):
    _close_042(toy)
    _write_telemetry(toy, {"ts": "t", "kind": "event",
                           "meta": {"slice": "slice-042", "gates": ["g"]}})
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "0.9 telemetry")
    report = _step("w2.telemetry").apply(toy, YES)
    assert not (toy / ".harness" / "telemetry.jsonl").exists()
    assert not (toy / ".harness" / "cache" / "legacy-telemetry").exists()
    assert "deleted .harness/telemetry.jsonl; git history keeps it" in report


def test_telemetry_step_counts_odd_rows_as_unreadable(toy):
    _close_042(toy)
    _write_telemetry(
        toy,
        {"id": "a", "kind": "event", "meta": "oops"},
        {"id": "b", "kind": "event", "meta": {"slice": ["x"]}},
        {"id": "c", "kind": "event",
         "meta": {"slice": "slice-042", "gates": "gate:G3"}},
        {"id": "d", "kind": "event",
         "meta": {"slice": "slice-042", "gates": {"gate:G5": 1}}},
        ["not", "a", "row"])
    report = _step("w2.telemetry").apply(toy, YES)
    row = read_jsonl(toy / ".harness" / "slice-metrics.jsonl")[0]
    assert row["id"] == "slice-042"
    assert row["gates_fired"] == {"gate:G3": 1}
    assert "skipped 3 unreadable telemetry lines" in report
    assert _step("w2.telemetry").describe(toy) == []


def test_telemetry_step_counts_unreadable_buffer_rows(toy):
    con = sqlite3.connect(str(toy / ".harness" / "sidecar.db"))
    con.execute("CREATE TABLE telemetry_buffer("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT)")
    con.executemany("INSERT INTO telemetry_buffer(row) VALUES(?)",
                    [("{torn",), (None,), (json.dumps({"kind": "event"}),)])
    con.commit()
    con.close()
    report = _step("w2.telemetry").apply(toy, YES)
    assert "skipped 2 unreadable telemetry lines" in report
    assert "dropped the sidecar telemetry_buffer table" in report


def test_telemetry_step_refuses_a_malformed_backlog(toy):
    _write_telemetry(toy, {"id": "a", "ts": "t", "kind": "slice_closed",
                           "meta": {"slice": "slice-042"}})
    _legacy_buffer = sqlite3.connect(str(toy / ".harness" / "sidecar.db"))
    _legacy_buffer.execute("CREATE TABLE telemetry_buffer("
                           "id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT)")
    _legacy_buffer.commit()
    _legacy_buffer.close()
    (toy / ".harness" / "backlog.jsonl").write_text("{bad\n")
    with pytest.raises(HarnessError, match="backlog.jsonl is not valid"):
        _step("w2.telemetry").apply(toy, YES)
    assert (toy / ".harness" / "telemetry.jsonl").exists()
    assert read_jsonl(toy / ".harness" / "slice-metrics.jsonl") == []
    assert not (toy / ".harness" / "cache" / "events.jsonl").exists()
    assert upgrade_w2._has_buffer(toy)


def test_telemetry_step_without_a_backlog_uses_close_events(toy):
    (toy / ".harness" / "backlog.jsonl").unlink()
    _write_telemetry(toy, {"id": "a", "ts": "2026-09-02T00:00:00+00:00",
                           "kind": "slice_closed",
                           "meta": {"slice": "slice-042"}})
    report = _step("w2.telemetry").apply(toy, YES)
    assert [r["id"] for r in read_jsonl(
        toy / ".harness" / "slice-metrics.jsonl")] == ["slice-042"]
    assert any("found no .harness/backlog.jsonl" in line for line in report)


def test_telemetry_step_treats_a_close_event_as_closed(toy):
    _write_telemetry(
        toy,
        {"ts": "2026-09-01T00:00:00+00:00", "kind": "event",
         "meta": {"slice": "slice-gone", "gates": ["gate:G3"]}},
        {"ts": "2026-09-02T00:00:00+00:00", "kind": "slice_closed",
         "meta": {"slice": "slice-gone"}})
    _step("w2.telemetry").apply(toy, YES)
    rows = read_jsonl(toy / ".harness" / "slice-metrics.jsonl")
    assert [r["id"] for r in rows] == ["slice-gone"]
    assert rows[0]["closed_at"] == "2026-09-02T00:00:00+00:00"
    assert not (toy / ".harness" / "cache" / "events.jsonl").exists()


def test_telemetry_step_deletes_nothing_when_the_sidecar_is_locked(
        toy, monkeypatch):
    _legacy_telemetry(toy)
    monkeypatch.setattr(upgrade_w2, "SIDECAR_TIMEOUT", 0.05)
    holder = sqlite3.connect(str(toy / ".harness" / "sidecar.db"),
                             isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(HarnessError, match="Nothing was deleted"):
            _step("w2.telemetry").apply(toy, YES)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    for name in ("telemetry.jsonl", "telemetry.archive.jsonl",
                 "telemetry.quarantine.jsonl"):
        assert (toy / ".harness" / name).exists(), name
    assert upgrade_w2._has_buffer(toy)


def test_telemetry_step_keeps_a_close_written_summary(toy):
    _legacy_telemetry(toy)
    write_jsonl(toy / ".harness" / "slice-metrics.jsonl", [
        {"id": "slice-042", "closed_at": "2026-09-05T00:00:00+00:00",
         "source": "close", "gates_fired": {}}])
    _step("w2.telemetry").apply(toy, YES)
    row = read_jsonl(toy / ".harness" / "slice-metrics.jsonl")[0]
    assert row["source"] == "close" and row["gates_fired"] == {}


def test_telemetry_step_ignores_a_sidecar_without_the_buffer(toy):
    con = sqlite3.connect(str(toy / ".harness" / "sidecar.db"))
    con.execute("CREATE TABLE IF NOT EXISTS other(x)")
    con.commit()
    con.close()
    assert _step("w2.telemetry").describe(toy) == []


# ------------------------------------------------------------- w2.config
def test_config_step_keeps_comments_and_is_idempotent(toy):
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text(OLD_CONFIG)
    step = _step("w2.config")
    assert len(step.describe(toy)) == 5
    report = step.apply(toy, NO)
    assert not any("without comments" in line for line in report)
    text = cfg.read_text()
    assert text.startswith("# harness per-repo engine config")
    assert "g3_mode: allow_with_findings      # keep this comment" in text
    doc = yaml.safe_load(text)
    assert "ensemble" not in doc and "telemetry" not in doc
    assert doc["review"] == {"fork_for_security_rows": True, "ensemble": False}
    assert doc["gates"] == {"g3_mode": "allow_with_findings",
                            "g5_similarity_threshold": 0.6,
                            "exempt_paths": DEFAULT_EXEMPT}
    assert doc["languages"] == {"python": True} and doc["schema"] == 1
    assert step.describe(toy) == []
    before = cfg.read_bytes()
    step.apply(toy, NO)
    assert cfg.read_bytes() == before


def test_config_step_keeps_other_telemetry_keys(toy):
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text("schema: 1\ntelemetry:\n  compaction_is_defect: true\n"
                   "  other: 1   # mine\nreview:\n  ensemble: true\n"
                   "gates:\n  exempt_paths: []\n")
    step = _step("w2.config")
    assert step.describe(toy) == [
        "remove telemetry.compaction_is_defect from .harness/config.yaml"]
    step.apply(toy, NO)
    text = cfg.read_text()
    assert "other: 1   # mine" in text
    assert yaml.safe_load(text) == {"schema": 1, "telemetry": {"other": 1},
                                    "review": {"ensemble": True},
                                    "gates": {"exempt_paths": []}}
    assert step.describe(toy) == []


def test_config_step_drops_block_mode_and_advises(toy):
    cfg = toy / ".harness" / "config.yaml"
    _no_non_goals(toy)
    cfg.write_text("schema: 1\ngates:\n  g3_mode: block\n"
                   "  exempt_paths: [docs/]\nreview:\n  ensemble: false\n")
    step = _step("w2.config")
    advice = _advice("w2.config", toy)
    assert advice == ["check: G3 scope is advisory in 0.10. To block a path, "
                      "cite its non-goal from a gates.extra gate."]
    report = step.apply(toy, NO)
    assert any("advisory in 0.10" in line for line in report)
    assert yaml.safe_load(cfg.read_text())["gates"] == {"exempt_paths": ["docs/"]}
    assert step.describe(toy) == []


def test_config_step_keeps_radius_mode(toy):
    _no_non_goals(toy)
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text("schema: 1\ngates:\n  g3_mode: radius\n")
    _step("w2.config").apply(toy, NO)
    assert yaml.safe_load(cfg.read_text())["gates"]["g3_mode"] == "radius"
    assert _advice("w2.config", toy) == []


def test_config_step_adds_contracts_prefix_when_contracts_exist(toy):
    (toy / ".harness" / "config.yaml").write_text(OLD_CONFIG)
    (toy / "contracts").mkdir()
    _step("w2.config").apply(toy, NO)
    doc = yaml.safe_load((toy / ".harness" / "config.yaml").read_text())
    assert doc["gates"]["exempt_paths"] == DEFAULT_EXEMPT + ["contracts/"]


def test_config_step_reports_the_added_contracts_prefix(toy):
    """I2 (spec 12 step 4): the report says contracts/ is no longer checked."""
    (toy / ".harness" / "config.yaml").write_text(OLD_CONFIG)
    (toy / "contracts").mkdir()
    step = _step("w2.config")
    assert ("add gates.exempt_paths to .harness/config.yaml, including "
            "contracts/ (harness no longer checks it)") in step.describe(toy)
    assert ("added gates.exempt_paths to .harness/config.yaml, including "
            "contracts/ (harness no longer checks it)") in step.apply(toy, NO)


def test_config_step_does_not_mention_contracts_without_the_folder(toy):
    (toy / ".harness" / "config.yaml").write_text(OLD_CONFIG)
    assert "add gates.exempt_paths to .harness/config.yaml" in \
        _step("w2.config").describe(toy)


UNCITED_ADVICE = ("check: 1 non-goals no longer block. Cite them from a "
                  "gates.extra gate to keep them blocking.")


def test_config_advice_counts_uncited_non_goals(toy):
    """R7: non-goals that blocked in 0.9 turn advisory unless a gate cites
    them."""
    assert _advice("w2.config", toy) == [UNCITED_ADVICE]


def test_config_advice_skips_cited_and_pathless_non_goals(toy):
    write_jsonl(toy / ".harness" / "boundaries.jsonl", [
        {"id": "B-legacy", "source_adr": "007", "rule_ref": "adr:007",
         "text": "legacy", "patterns": ["legacy/**"]},
        {"id": "B-prose", "source_adr": "008", "rule_ref": "adr:008",
         "text": "no paths", "patterns": []}])
    cite_non_goals(toy, "B-legacy")
    assert _advice("w2.config", toy) == []


def test_config_advice_ignores_a_gate_that_fails_to_load(toy):
    cite_non_goals(toy, "adr:007")
    (toy / ".harness" / "gates" / "toy_cites.py").write_text(
        "raise ImportError('deliberate')\n")
    assert _advice("w2.config", toy) == [UNCITED_ADVICE]


def test_config_step_adds_missing_parents(toy):
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text("schema: 1  # top\n")
    step = _step("w2.config")
    step.apply(toy, NO)
    text = cfg.read_text()
    assert "# top" in text
    assert yaml.safe_load(text) == {
        "schema": 1, "review": {"ensemble": False},
        "gates": {"exempt_paths": DEFAULT_EXEMPT}}
    assert step.describe(toy) == []


def test_config_step_falls_back_for_flow_style(toy):
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text("schema: 1\nreview: {fork_for_security_rows: true}\n"
                   "gates: {g3_mode: radius, g5_override: advisory}\n"
                   "ensemble: {samples: 3}\n")
    report = _step("w2.config").apply(toy, NO)
    doc = yaml.safe_load(cfg.read_text())
    assert doc["review"] == {"fork_for_security_rows": True, "ensemble": False}
    assert doc["gates"] == {"g3_mode": "radius", "exempt_paths": DEFAULT_EXEMPT}
    assert "ensemble" not in doc
    assert any("without comments" in line for line in report)
    assert _step("w2.config").describe(toy) == []


def test_config_step_skips_a_missing_config(toy):
    (toy / ".harness" / "config.yaml").unlink()
    step = _step("w2.config")
    assert step.describe(toy) == []
    assert step.apply(toy, NO) == []
    assert _advice("w2.config", toy) == []
    assert not (toy / ".harness" / "config.yaml").exists()


def test_config_step_fails_loud_on_invalid_yaml(toy):
    (toy / ".harness" / "config.yaml").write_text("gates: [\n")
    with pytest.raises(HarnessError, match="not valid YAML"):
        _step("w2.config").describe(toy)


# --------------------------------------------------------- w2.skill-names
def test_skill_names_step_rewrites_marked_files_only(toy):
    (toy / "AGENTS.md").write_text(
        f"{LEGACY_AGENTS_LINE}\n\nRun /harness:status, then "
        "/harness:review-rubrics and /harness:review. Park: "
        "/harness:adjudicate.\n")
    (toy / "docs").mkdir()
    (toy / "docs" / "notes.md").write_text("/harness:status\n")
    step = _step("w2.skill-names")
    assert step.describe(toy) == [
        "AGENTS.md: harness:adjudicate -> harness:harness",
        "AGENTS.md: harness:review-rubrics -> harness:review",
        "AGENTS.md: harness:status -> harness:harness"]
    step.apply(toy, NO)
    assert (toy / "AGENTS.md").read_text() == (
        f"{LEGACY_AGENTS_LINE}\n\nRun /harness:harness, then "
        "/harness:review and /harness:review. Park: /harness:harness.\n")
    assert (toy / "docs" / "notes.md").read_text() == "/harness:status\n"
    assert step.describe(toy) == []


def test_skill_names_step_edits_a_010_marked_claude_md(toy):
    (toy / "CLAUDE.md").write_text(
        f"# CLAUDE.md\n{AGENTS_MARKER}\nUse /harness:premortem.\n")
    step = _step("w2.skill-names")
    step.apply(toy, NO)
    assert "/harness:architect." in (toy / "CLAUDE.md").read_text()
    assert step.describe(toy) == []


def test_skill_names_step_only_advises_on_unmarked_files(toy):
    text = "# Our agents\nUse /harness:shadow-context and myharness:status.\n"
    (toy / "AGENTS.md").write_text(text)
    step = _step("w2.skill-names")
    assert step.describe(toy) == []
    assert step.apply(toy, NO) == []
    assert (toy / "AGENTS.md").read_text() == text
    advice = _advice("w2.skill-names", toy)
    assert len(advice) == 1
    assert advice[0].startswith("check: AGENTS.md names removed skills")
    assert "harness:shadow-context -> harness:build" in advice[0]


# ------------------------------------------------------------ w2.contracts
def test_contracts_step_only_advises(toy):
    (toy / "contracts").mkdir()
    (toy / "contracts" / "api.yaml").write_text("openapi: 3.0.3\n")
    step = _step("w2.contracts")
    assert step.describe(toy) == []
    assert step.apply(toy, NO) == []
    advice = _advice("w2.contracts", toy)
    assert len(advice) == 1
    assert advice[0].startswith("check: ")
    assert "no longer checks contracts/" in advice[0]
    assert "gates.exempt_paths" in advice[0]
    assert (toy / "contracts" / "api.yaml").exists()
    assert not (toy / ".harness" / "cache" / "w2-contracts-reported").exists()


def test_contracts_advice_drops_the_exempt_hint_once_exempt(toy):
    (toy / "contracts").mkdir()
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text(cfg.read_text().replace('"explore/"]', '"explore/", "contracts/"]'))
    advice = _advice("w2.contracts", toy)
    assert len(advice) == 1 and "exempt_paths" not in advice[0]


def test_contracts_advice_counts_the_prefix_w2_config_will_add(toy):
    """R3: when w2.config is about to add contracts/, do not tell the user
    to add it by hand."""
    (toy / ".harness" / "config.yaml").write_text(OLD_CONFIG)
    (toy / "contracts").mkdir()
    advice = _advice("w2.contracts", toy)
    assert len(advice) == 1 and "exempt_paths" not in advice[0]


def test_dry_run_plan_shows_w2_advice(toy):
    (toy / "contracts").mkdir()
    ids = [row["id"] for row in upgrade_010.advice(toy)]
    assert "w2.contracts" in ids


def test_a_09_substrate_converges_in_one_run(toy):
    _close_042(toy)
    (toy / ".harness" / "config.yaml").write_text(
        "schema: 1\r\ngates:\r\n  g3_mode: block\r\n  g5_override: x\r\n"
        "ensemble:\r\n  samples: 3\r\ntelemetry:\r\n"
        "  compaction_is_defect: true\r\n")
    _write_telemetry(toy, {"id": "a", "ts": "t", "kind": "event",
                           "meta": {"slice": "slice-042",
                                    "gates": ["gate:G3"]}})
    upgrade_010.run(toy, YES, dry_run=False)
    assert upgrade_010.plan(toy) == []
    assert yaml.safe_load((toy / ".harness" / "config.yaml").read_text()) == {
        "schema": 1, "review": {"ensemble": False},
        "gates": {"exempt_paths": DEFAULT_EXEMPT}}
    assert upgrade_010.run(toy, YES, dry_run=False) == []
