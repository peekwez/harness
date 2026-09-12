"""Codex Astra handoff, wave 1: the integrity fixes that need no new rule.

- E5 (bug): `backlog` split only ever rewrites PLANNED rows nobody depends
  on — a closed slice's provenance and other slices' `depends_on` survive.
- E3 (guard): `adjudicate --decision-id` refuses an id that already exists,
  before any write.
- E1: one closed-slice acceptance selector shared by close, merge and the
  new `harness acceptance --closed` entry point; a declared suite that
  disappeared fails loud, naming the slice and pattern.
- E6: the resolver and the backlog estimate build guidance candidates
  through one layer — same supersession, anchors and dedup — and a missing
  anchor is a reported fallback, not a silent whole-file load.
- Proposed ADRs that carry frontmatter decision rows are warned about at
  compile: rows bind regardless of `status`, so say so.
"""
import json

import yaml
from conftest import PLUGIN_ROOT, build_toy_repo, git, run_cli
from engine import load_config, read_jsonl, write_jsonl


def _backlog(root):
    return read_jsonl(root / ".harness" / "backlog.jsonl")


def _set_backlog(root, rows):
    write_jsonl(root / ".harness" / "backlog.jsonl", rows)


def _set_acceptance(root, **keys):
    cfg_path = root / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("acceptance", {}).update(keys)
    cfg_path.write_text(yaml.safe_dump(cfg))


def _closed(sid, acceptance, **extra):
    row = {"id": sid, "spec": "s", "title": sid, "status": "closed",
           "declares_dep": [], "acceptance": acceptance,
           "predicted_files": list(acceptance), "context_cost_estimate": 0,
           "depends_on": [], "worktree": None}
    row.update(extra)
    return row


# =============================================================== E5: split
def test_split_never_rewrites_a_closed_slice(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", budget=100)   # everything is oversized
    rows = _backlog(toy)
    rows[0]["status"] = "closed"
    _set_backlog(toy, rows)
    out = json.loads(run_cli("backlog", root=toy).stdout)
    assert out["split"] == []
    ids = [r["id"] for r in _backlog(toy)]
    assert ids == ["slice-042"], ids
    assert any(r["id"] == "slice-042" and r["reason"].startswith("status")
               for r in out["split_refused"]), out


def test_split_never_rewrites_a_bound_or_parked_slice(tmp_path):
    for status in ("in_progress", "parked"):
        toy = build_toy_repo(tmp_path / status, budget=100)
        rows = _backlog(toy)
        rows[0]["status"] = status
        _set_backlog(toy, rows)
        out = json.loads(run_cli("backlog", root=toy).stdout)
        assert out["split"] == [], status
        assert [r["id"] for r in _backlog(toy)] == ["slice-042"], status


def test_split_refuses_a_parent_other_slices_depend_on(tmp_path):
    """Replacing slice-042 with -a/-b would leave slice-043's depends_on
    pointing at a row that no longer exists."""
    toy = build_toy_repo(tmp_path / "toy", budget=100)
    rows = _backlog(toy)
    rows.append({"id": "slice-043", "spec": "s", "title": "after",
                 "status": "planned", "declares_dep": ["orders"],
                 "acceptance": ["tests/slices/043_x.py"], "predicted_files": [],
                 "context_cost_estimate": 0, "depends_on": ["slice-042"],
                 "worktree": None})
    _set_backlog(toy, rows)
    out = json.loads(run_cli("backlog", root=toy).stdout)
    assert out["split"] == []
    refused = {r["id"]: r["reason"] for r in out["split_refused"]}
    assert "slice-043" in refused["slice-042"]
    ids = [r["id"] for r in _backlog(toy)]
    assert ids == ["slice-042", "slice-043"]
    # the dependency edge is intact
    assert _backlog(toy)[1]["depends_on"] == ["slice-042"]


def test_split_of_a_free_planned_slice_requires_authored_child_contracts(tmp_path):
    toy = build_toy_repo(tmp_path / "toy", budget=100)
    out = json.loads(run_cli("backlog", root=toy).stdout)
    assert out["split"] == []
    assert out["split_proposals"][0]["child_ids"] == ["slice-042-a",
                                                        "slice-042-b"]
    assert "authored" in out["split_refused"][0]["reason"]
    assert [row["id"] for row in _backlog(toy)] == ["slice-042"]


# ========================================================= E3: adjudicate
def _park_one(toy):
    proc = run_cli("review", "--park", "--slice", "slice-042", "--session", "rv",
                   "--code", "REVIEW_UNCERTAIN", "--rule-ref", "decision:D-041",
                   "--message", "unsure whether span names conform", root=toy)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["finding"]["finding_id"]


def test_adjudicate_refuses_an_existing_decision_id_before_writing(toy):
    fid = _park_one(toy)
    before_decisions = (toy / ".harness" / "decisions.jsonl").read_text()
    before_edges = (toy / ".harness" / "edges.jsonl").read_text()
    before_parked = (toy / ".harness" / "parked.jsonl").read_text()
    proc = run_cli("adjudicate", "--finding-id", fid, "--resolution", "r",
                   "--decision-id", "D-041", "--domain", "telemetry", root=toy)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "D-041" in proc.stderr and "adr/007-telemetry.md" in proc.stderr
    assert "new id" in proc.stderr
    # nothing moved: no row, no edge, the park is still queued
    assert (toy / ".harness" / "decisions.jsonl").read_text() == before_decisions
    assert (toy / ".harness" / "edges.jsonl").read_text() == before_edges
    assert (toy / ".harness" / "parked.jsonl").read_text() == before_parked


def test_adjudicate_with_a_fresh_id_still_writes_the_row(toy):
    fid = _park_one(toy)
    proc = run_cli("adjudicate", "--finding-id", fid, "--resolution", "r",
                   "--decision-id", "D-900", "--domain", "telemetry", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert any(d["id"] == "D-900" for d in
               read_jsonl(toy / ".harness" / "decisions.jsonl"))


# =================================================== E1: closed acceptance
def test_selector_names_owners_and_dedupes(toy):
    from engine.cli.acceptance import closed_acceptance
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    (toy / "tests" / "slices" / "002_b.py").write_text("def test_b(): pass\n")
    rows = _backlog(toy)
    rows += [_closed("slice-001", ["tests/slices/001_a.py"]),
             _closed("slice-002", ["tests/slices/002_b.py",
                                   "tests/slices/001_a.py"]),   # shared file
             {**_closed("slice-003", ["tests/slices/001_a.py"]),
              "status": "planned"}]                              # not closed
    _set_backlog(toy, rows)
    sel = closed_acceptance(toy)
    assert sel["paths"] == ["tests/slices/001_a.py", "tests/slices/002_b.py"]
    assert sel["owners"]["tests/slices/001_a.py"] == ["slice-001", "slice-002"]
    assert sel["problems"] == []
    # exclusion of the slice being closed
    assert closed_acceptance(toy, exclude="slice-002")["paths"] == \
        ["tests/slices/001_a.py"]


def test_a_missing_literal_is_a_named_problem_not_a_silent_drop(toy):
    from engine.cli.acceptance import closed_acceptance, run_regression
    rows = _backlog(toy) + [_closed("slice-009", ["tests/slices/009_gone.py"])]
    _set_backlog(toy, rows)
    sel = closed_acceptance(toy)
    assert sel["paths"] == []
    assert sel["problems"] == [{"slice": "slice-009",
                                "pattern": "tests/slices/009_gone.py",
                                "reason": "missing file"}]
    ok, detail = run_regression(toy, load_config(toy))
    assert ok is False
    assert "slice-009" in detail and "009_gone.py" in detail


def test_an_unmatched_glob_is_a_named_problem(toy):
    from engine.cli.acceptance import closed_acceptance
    rows = _backlog(toy) + [_closed("slice-010", ["tests/slices/010_*.py"])]
    _set_backlog(toy, rows)
    sel = closed_acceptance(toy)
    assert sel["problems"] == [{"slice": "slice-010",
                                "pattern": "tests/slices/010_*.py",
                                "reason": "glob matches nothing"}]


def test_a_missing_declaration_does_not_go_green_on_another_slices_test(toy):
    """Another closed slice having a valid suite must not mask the hole."""
    from engine.cli.acceptance import run_regression
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    rows = _backlog(toy) + [_closed("slice-001", ["tests/slices/001_a.py"]),
                            _closed("slice-009", ["tests/slices/009_gone.py"])]
    _set_backlog(toy, rows)
    _set_acceptance(toy, cmd="sh -c 'echo {paths} > ran.txt'")
    ok, detail = run_regression(toy, load_config(toy))
    assert ok is False and "slice-009" in detail
    assert not (toy / "ran.txt").exists(), "must not run with a hole"


def test_honestly_empty_declarations_are_not_a_problem(toy):
    from engine.cli.acceptance import closed_acceptance, run_regression
    rows = _backlog(toy) + [_closed("slice-011", [])]
    _set_backlog(toy, rows)
    sel = closed_acceptance(toy)
    assert sel["problems"] == [] and sel["paths"] == []
    assert sel["empty"] == ["slice-011"]
    ok, detail = run_regression(toy, load_config(toy))
    assert ok is True and "no closed-slice" in detail


def test_disabled_runner_is_reported_as_disabled_not_run(toy):
    from engine.cli.acceptance import run_regression
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    _set_backlog(toy, _backlog(toy) + [_closed("slice-001",
                                               ["tests/slices/001_a.py"])])
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["gates"]["acceptance_runner"] = "none"
    cfg_path.write_text(yaml.safe_dump(cfg))
    _set_acceptance(toy, cmd="sh -c 'echo {paths} > ran.txt'")
    ok, detail = run_regression(toy, load_config(toy))
    assert ok is True and "disabled" in detail
    assert not (toy / "ran.txt").exists()
    out = json.loads(run_cli("acceptance", "--closed", root=toy).stdout)
    assert out["disabled"] is True and out["ran"] is False


def test_cli_list_mode_never_executes(toy):
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    _set_backlog(toy, _backlog(toy) + [_closed("slice-001",
                                               ["tests/slices/001_a.py"])])
    _set_acceptance(toy, cmd="sh -c 'echo {paths} > ran.txt'")
    proc = run_cli("acceptance", "--closed", "--list", root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["paths"] == ["tests/slices/001_a.py"]
    assert out["owners"] == {"tests/slices/001_a.py": ["slice-001"]}
    assert out["ran"] is False
    assert not (toy / "ran.txt").exists()


def test_cli_execution_runs_the_same_paths_the_selector_lists(toy):
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    (toy / "tests" / "slices" / "002_b.py").write_text("def test_b(): pass\n")
    _set_backlog(toy, _backlog(toy) + [
        _closed("slice-001", ["tests/slices/001_a.py"]),
        _closed("slice-002", ["tests/slices/002_*.py"])])
    _set_acceptance(toy, cmd="sh -c 'echo {paths} > ran.txt'")
    proc = run_cli("acceptance", "--closed", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["ran"] is True and out["ok"] is True
    assert (toy / "ran.txt").read_text().split() == \
        ["tests/slices/001_a.py", "tests/slices/002_b.py"]
    listed = json.loads(run_cli("acceptance", "--closed", "--list",
                                root=toy).stdout)["paths"]
    assert listed == out["paths"] == ["tests/slices/001_a.py",
                                      "tests/slices/002_b.py"]


def test_cli_list_reports_problems_with_exit_1(toy):
    _set_backlog(toy, _backlog(toy) + [_closed("slice-009",
                                               ["tests/slices/009_gone.py"])])
    proc = run_cli("acceptance", "--closed", "--list", root=toy)
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["problems"][0]["slice"] == "slice-009"


def test_cli_execution_failure_is_exit_1_with_the_tail(toy):
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): assert 0\n")
    _set_backlog(toy, _backlog(toy) + [_closed("slice-001",
                                               ["tests/slices/001_a.py"])])
    _set_acceptance(toy, cmd="sh -c 'echo boom; exit 3'")
    proc = run_cli("acceptance", "--closed", root=toy)
    assert proc.returncode == 1
    out = json.loads(proc.stdout)
    assert out["ok"] is False and "boom" in out["detail"]


def test_cli_spawn_failure_is_a_result_not_a_traceback(toy):
    (toy / "tests" / "slices" / "001_a.py").write_text("def test_a(): pass\n")
    _set_backlog(toy, _backlog(toy) + [_closed("slice-001",
                                               ["tests/slices/001_a.py"])])
    _set_acceptance(toy, cmd="/no/such/binary {paths}")
    proc = run_cli("acceptance", "--closed", root=toy)
    assert proc.returncode == 1 and "Traceback" not in proc.stderr
    assert "cannot run" in json.loads(proc.stdout)["detail"]


def test_ci_template_offers_closed_acceptance_opt_in():
    wf = yaml.safe_load((PLUGIN_ROOT / "templates" / "ci-verify.yml").read_text())
    triggers = wf.get(True) or wf.get("on")
    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["closed-acceptance"]["type"] == "boolean"
    assert inputs["closed-acceptance"]["default"] is False
    assert "acceptance-setup" in inputs
    steps = wf["jobs"]["verify"]["steps"]
    step = next(s for s in steps if "acceptance" in s.get("name", "").lower())
    assert "inputs.closed-acceptance" in step["if"]
    assert "acceptance --closed" in step["run"]
    assert (PLUGIN_ROOT / ".github" / "workflows" /
            "harness-verify.yml").read_text() == \
        (PLUGIN_ROOT / "templates" / "ci-verify.yml").read_text()


# =================================================== E6: context estimate
def test_estimate_and_resolver_share_one_guidance_layer(toy):
    """The number `backlog` writes is the number `resolve` needs for the
    declared deps' shadows + guidance — same supersession, same anchors."""
    from engine.resolver import context_cost_breakdown, resolve
    config = load_config(toy)
    config["resolver"]["budget_tokens"] = 10**6
    res = resolve(toy, "slice-042", config)
    est = context_cost_breakdown(toy, ["telemetry", "config"], config)
    assert est["total"] == res["declared_demand"], (est, res["declared_demand"])
    assert est["total"] == est["shadows"] + est["guidance"]
    # telemetry is built with s2 superseded: the estimate skips s2 too
    assert "adr/007-telemetry.md#s2" in est["superseded"]
    # demand is everything that qualified; what fit (token_estimate) also
    # holds the decisions block and one-hop shadows, which the declared
    # figure deliberately excludes
    assert res["demand"] >= res["declared_demand"]
    assert res["demand"] >= res["token_estimate"]


def test_repeated_anchor_counted_once_distinct_anchors_kept(toy):
    from engine.resolver import context_cost_breakdown
    config = load_config(toy)
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    for r in rows:
        if r["id"] == "orders":
            r["guidance_refs"] = ["adr/007-telemetry.md#s1",
                                  "adr/007-telemetry.md#s1",     # repeat
                                  "adr/007-telemetry.md#s3"]     # distinct
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    one = context_cost_breakdown(toy, ["orders"], config)
    assert one["guidance_refs"] == ["adr/007-telemetry.md#s1",
                                    "adr/007-telemetry.md#s3"]
    # config also references #s1: across deps it is still counted once
    both = context_cost_breakdown(toy, ["orders", "config"], config)
    assert both["guidance"] == one["guidance"]
    # and the resolver injects it once
    from engine.resolver import resolve
    config["resolver"]["budget_tokens"] = 10**6
    rows = _backlog(toy)
    rows[0]["declares_dep"] = ["orders", "config"]
    _set_backlog(toy, rows)
    res = resolve(toy, "slice-042", config)
    hits = [b for b in res["injections"]
            if b.startswith("=== guidance adr/007-telemetry.md#s1")]
    assert len(hits) == 1, hits


def test_missing_anchor_is_a_reported_fallback_with_its_cost(toy):
    from engine.resolver import context_cost_breakdown, resolve
    config = load_config(toy)
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    for r in rows:
        if r["id"] == "orders":
            r["guidance_refs"] = ["adr/007-telemetry.md#nope"]
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    est = context_cost_breakdown(toy, ["orders"], config)
    assert est["anchor_fallbacks"] == ["adr/007-telemetry.md#nope"]
    from engine import token_estimate
    whole = token_estimate((toy / "adr" / "007-telemetry.md").read_text())
    # the whole file (plus the block header) is what it costs — far more
    # than the section a valid anchor would have cost
    assert est["guidance"] >= whole
    for r in rows:
        if r["id"] == "orders":
            r["guidance_refs"] = ["adr/007-telemetry.md#s1"]
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    assert context_cost_breakdown(toy, ["orders"], config)["guidance"] < whole
    for r in rows:
        if r["id"] == "orders":
            r["guidance_refs"] = ["adr/007-telemetry.md#nope"]
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    backlog = _backlog(toy)
    backlog[0]["declares_dep"] = ["orders"]
    _set_backlog(toy, backlog)
    config["resolver"]["budget_tokens"] = 10**6
    res = resolve(toy, "slice-042", config)
    fallback = [d for d in res["dropped"] if d["kind"] == "anchor-missing"]
    assert fallback and fallback[0]["ids"] == ["adr/007-telemetry.md#nope"]
    assert "whole file" in fallback[0]["reason"]


def test_missing_guidance_file_is_reported_by_the_estimate(toy):
    from engine.resolver import context_cost_breakdown
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    for r in rows:
        if r["id"] == "orders":
            r["guidance_refs"] = ["adr/099-gone.md#s1"]
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    est = context_cost_breakdown(toy, ["orders"], load_config(toy))
    assert est["missing_refs"] == ["adr/099-gone.md#s1"]
    assert est["guidance"] == 0


def test_backlog_output_carries_the_breakdown(toy):
    out = json.loads(run_cli("backlog", "--no-split", root=toy).stdout)
    est = out["estimates"]["slice-042"]
    assert set(est) >= {"total", "shadows", "guidance", "guidance_refs",
                        "anchor_fallbacks", "missing_refs", "superseded"}
    assert est["total"] == _backlog(toy)[0]["context_cost_estimate"]


def test_estimate_is_deterministic(toy):
    from engine.resolver import context_cost_breakdown
    config = load_config(toy)
    a = context_cost_breakdown(toy, ["config", "telemetry"], config)
    b = context_cost_breakdown(toy, ["telemetry", "config"], config)
    assert a == b


# =================================================== compile: proposed ADRs
def test_compile_warns_when_a_proposed_adr_carries_binding_rows(toy):
    (toy / "adr" / "008-draft.md").write_text(
        '---\nid: "008"\nstatus: proposed\ndomains: [telemetry]\n'
        'supersedes: []\ndecision_table_rows:\n  - id: D-777\n'
        '    domain: telemetry\n    question: "q?"\n    answer: "a"\n'
        'abstractions: []\napi_surface: []\n---\n\n# ADR-008\n')
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert any("008" in w and "proposed" in w for w in out["warnings"]), out
    # the row still binds (no silent behaviour change); the warning says so
    assert any(d["id"] == "D-777" for d in
               read_jsonl(toy / ".harness" / "decisions.jsonl"))


def test_the_lifecycle_adr_is_proposed_and_binds_nothing():
    """ADR-003 gates E2/E3/E4/E5-cancel: its rows live in prose until
    accepted, so compiling this repo adds no decision row from it."""
    from engine.compiler import parse_frontmatter
    path = next(PLUGIN_ROOT.glob("adr/003-*.md"))
    fm, body = parse_frontmatter(path.read_text())
    assert fm["status"] == "proposed"
    assert not fm.get("decision_table_rows")
    for needle in ("finding", "snapshot", "lifecycle", "follow-up",
                   "cancel"):
        assert needle in body.lower(), needle


def test_readme_documents_the_new_surface():
    body = (PLUGIN_ROOT / "README.md").read_text()
    assert "`acceptance`" in body
    assert "split_refused" in body or "never split" in body
    assert "anchor" in body
