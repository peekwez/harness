"""Spec 12 and 14: a 0.8 repo and a 0.9.4 astralabs repo reach 0.10 in one run.

Every fixture variant runs the real CLI, `harness upgrade --yes`, in a fresh
process. Each test reads the result of that one run.
"""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from conftest import (CONTRACT_STUB, PLUGIN_ROOT, REMOVED_SKILLS,
                      build_astralabs_094_repo, build_legacy_08_repo, git,
                      legacy_events, loaded_context, make_event, run_cli,
                      tree_bytes, write_legacy_sidecar)
from engine import read_jsonl, write_jsonl

VARIANTS = {
    "0.8": (build_legacy_08_repo, {}),
    "0.8+worktree": (build_legacy_08_repo, {"with_worktree": True}),
    "0.9.4": (build_astralabs_094_repo, {}),
    "0.9.4+broad-site-ignore": (build_astralabs_094_repo, {"ignore_site_broad": True}),
    "0.9.4+worktree": (build_astralabs_094_repo, {"with_worktree": True}),
}
BUILDERS = {"0.8": build_legacy_08_repo, "0.9.4": build_astralabs_094_repo}
CLOSED = {"0.8": "slice-040", "0.9.4": "slice-041"}
IN_FLIGHT = {"0.8": "slice-042", "0.9.4": "slice-043"}
FACT = {"0.8": "Span names use snake_case", "0.9.4": "Invoices round half-even"}
INDEX_DELETIONS = (".harness/shadows/", ".harness/memory/")
REMOVED_MERGE_RULES = (".harness/telemetry.jsonl", ".harness/memory/",
                       ".harness/shadows")


def _build(variant, path):
    build, kwargs = VARIANTS[variant]
    return build(path, **kwargs)


def _upgrade(root, *args):
    proc = run_cli("upgrade", "--yes", *args, root=root)
    assert proc.stdout.strip(), proc.stderr
    return proc, json.loads(proc.stdout)


def _commit(out):
    commit = out["commit"]
    done = subprocess.run(["bash", "-c", commit["command"]], cwd=commit["cwd"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def _backlog(root):
    return {r["id"]: r for r in read_jsonl(root / ".harness/backlog.jsonl")}


def _status_entries(root):
    """(XY, path) for each entry of `git status`, untracked files one by one."""
    raw = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    return [(e[:2], e[3:]) for e in raw.split("\0") if e]


@pytest.fixture(scope="module", params=sorted(VARIANTS))
def upgraded(request, tmp_path_factory):
    variant = request.param
    version = variant.split("+")[0]
    root = _build(variant, tmp_path_factory.mktemp(variant.replace(".", "_")) / "repo")
    tracked_before = set(git(root, "ls-files").stdout.splitlines())
    proc, out = _upgrade(root)
    return SimpleNamespace(variant=variant, version=version, root=root, proc=proc,
                           out=out, tracked_before=tracked_before)


def test_one_run_reaches_schema_2_and_passes_doctor_and_verify(upgraded):
    out = upgraded.out
    assert upgraded.proc.returncode == 0, json.dumps(out.get("failures"), indent=1)
    assert out["status"] == "upgraded"
    assert out["failures"] == []
    assert (upgraded.root / ".harness/schema_version").read_text() == "2\n"
    assert out["checks"]["doctor"]["passed"] and out["checks"]["verify"]["passed"]
    verify = run_cli("verify", root=upgraded.root)
    assert verify.returncode == 0, verify.stdout
    doctor = json.loads(run_cli("doctor", "--substrate", root=upgraded.root).stdout)
    assert doctor["substrate_healthy"] is True, doctor


def test_every_step_with_work_applies_and_none_is_left(upgraded):
    applied = [row["id"] for row in upgraded.out["steps"]]
    for step in ("w1.untrack-shadows", "w1.drop-registry-shadow", "w2.telemetry",
                 "w2.config", "w2.skill-names", "w3.retire-durable-memory",
                 "w3.memory-git-lines", "w3.shared-memory-index",
                 "w3.claude-md-import", "w4.glossary", "w5.legacy-verification",
                 "w8.agents-md"):
        assert step in applied, (step, applied)
    assert not any("error" in row for row in upgraded.out["steps"])
    assert not any("skipped" in line for row in upgraded.out["steps"]
                   for line in row.get("report", []))


def test_upgrade_itself_makes_no_commit(upgraded):
    assert git(upgraded.root, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_shadows_are_untracked_deleted_and_the_cache_is_ignored(upgraded):
    root = upgraded.root
    assert not (root / ".harness/shadows").exists()
    assert git(root, "ls-files", ".harness/shadows").stdout == ""
    assert ".harness/cache/" in (root / ".gitignore").read_text().splitlines()
    assert ".harness/shadows" not in (root / ".gitattributes").read_text()
    assert ".harness/memory/session/" not in (root / ".gitignore").read_text()
    assert all("shadow" not in row for row in read_jsonl(root / ".harness/registry.jsonl"))


def test_an_ignored_untracked_shadow_is_deleted_too(upgraded):
    if upgraded.variant != "0.9.4+broad-site-ignore":
        pytest.skip("only the broad site ignore leaves a shadow on disk but untracked")
    site_shadow = ".harness/shadows/site/assets/javascripts/bundle.js.json"
    assert site_shadow not in upgraded.tracked_before
    assert not (upgraded.root / site_shadow).exists()


def test_telemetry_becomes_slice_metrics(upgraded):
    root = upgraded.root
    assert not (root / ".harness/telemetry.jsonl").exists()
    assert not (root / ".harness/telemetry.archive.jsonl").exists()
    rows = read_jsonl(root / ".harness/slice-metrics.jsonl")
    assert any(CLOSED[upgraded.version] in json.dumps(r) for r in rows), rows
    # 0.8 rows had no ids: the closed slice still converts, the open one waits
    assert not any(IN_FLIGHT[upgraded.version] in json.dumps(r) for r in rows), rows


def test_durable_memory_is_moved_not_deleted(upgraded):
    root = upgraded.root
    assert not (root / ".harness/memory").exists()
    assert git(root, "ls-files", ".harness/memory").stdout == ""
    stamps = list((root / ".harness/cache/legacy-memory").iterdir())
    assert len(stamps) == 1, stamps
    assert FACT[upgraded.version] in (stamps[0] / "durable.jsonl").read_text()
    assert list((stamps[0] / "session").glob("*.jsonl"))
    # these fixtures hold no attempt or adjudication rows: nothing to export
    assert not (root / ".harness/cache/durable-memory-export.md").exists()


def test_contracts_stay_and_the_report_says_so(upgraded):
    assert (upgraded.root / "contracts/api.yaml").read_text() == CONTRACT_STUB
    assert any("contracts/" in line for line in upgraded.out["human_checks"])


def test_config_is_rewritten(upgraded):
    cfg = yaml.safe_load((upgraded.root / ".harness/config.yaml").read_text())
    assert not {"budget_tokens", "ranking", "degrade"} & set(cfg.get("resolver") or {})
    assert "compaction_is_defect" not in (cfg.get("telemetry") or {})
    assert "ensemble" not in cfg
    assert "g5_override" not in (cfg.get("gates") or {})
    assert cfg["review"]["ensemble"] is False
    assert ".harness/" in cfg["gates"]["exempt_paths"]
    assert "contracts/" in cfg["gates"]["exempt_paths"]


def test_merge_rules_for_removed_files_are_gone(upgraded):
    attrs = (upgraded.root / ".gitattributes").read_text()
    for rule in REMOVED_MERGE_RULES:
        assert rule not in attrs, (rule, attrs)
    assert ".harness/slice-metrics.jsonl merge=harness-substrate" in attrs.splitlines()


def test_harness_owned_files_are_refreshed_with_no_removed_skill_names(upgraded):
    root = upgraded.root
    assert "@.claude/memory/shared/MEMORY.md" in (root / "CLAUDE.md").read_text()
    assert (root / ".claude/memory/shared/MEMORY.md").exists()
    for name in ("AGENTS.md", "CLAUDE.md", ".github/workflows/harness-verify.yml"):
        text = (root / name).read_text()
        for skill in REMOVED_SKILLS:
            assert f"/harness:{skill}" not in text, (name, skill)
            assert f"harness:{skill} " not in text, (name, skill)
    assert ((root / ".github/workflows/harness-verify.yml").read_text()
            == (PLUGIN_ROOT / "templates/ci-verify.yml").read_text())
    assert "harness autonomy profile" in (root / ".claude/settings.json").read_text()
    assert (root / "docs/glossary.md").exists()


def test_a_harness_written_agents_md_is_replaced_with_a_backup_and_a_check(upgraded):
    root = upgraded.root
    assert ((root / "AGENTS.md").read_text()
            == (PLUGIN_ROOT / "templates/agents-md.md").read_text())
    backup = root / ".harness/cache/AGENTS.md.pre-0.10"
    assert "/harness:status" not in backup.read_text()
    assert any(line.startswith("w8.agents-md: check: ")
               and ".harness/cache/AGENTS.md.pre-0.10" in line
               for line in upgraded.out["human_checks"])


def test_open_slices_are_legacy_and_closed_slices_are_not(upgraded):
    rows = _backlog(upgraded.root)
    assert rows[IN_FLIGHT[upgraded.version]]["legacy_verification"] is True
    for row in rows.values():
        assert row.get("legacy_verification", False) is (row["status"] != "closed"), row


def test_an_in_flight_worktree_gets_one_check_line(upgraded):
    lines = [line for line in upgraded.out["human_checks"]
             if line.startswith("w5.legacy-verification: check: ")]
    if "worktree" in upgraded.variant:
        assert lines == [f"w5.legacy-verification: check: run harness upgrade in "
                         f".worktrees/{IN_FLIGHT[upgraded.version]} to mark its "
                         f"in-flight slice legacy."]
    else:
        assert lines == []


def test_old_gate_overrides_stay_as_history(upgraded):
    rules = {e["meta"].get("rule_ref")
             for e in read_jsonl(upgraded.root / ".harness/edges.jsonl")
             if e["type"] == "override"}
    assert "gate:G2" in rules
    if upgraded.version == "0.9.4":
        assert {"gate:G3", "gate:G7"} <= rules


def test_the_commit_proposal_covers_every_change_and_the_index_deletions(upgraded):
    root, commit = upgraded.root, upgraded.out["commit"]
    assert commit["message"] == "harness: upgrade to 0.10"
    assert commit["cwd"] == str(root.resolve())
    assert commit["command"].count("&&") == 1
    assert commit["command"].startswith("git --literal-pathspecs add -A -- ")
    assert commit["command"].endswith('git commit -m "harness: upgrade to 0.10"')
    staged = git(root, "diff", "--cached", "--name-only", "--no-renames").stdout.split()
    tracked_deleted = sorted(p for p in upgraded.tracked_before
                             if p.startswith(INDEX_DELETIONS))
    assert sorted(staged) == tracked_deleted
    uncovered = [(xy, p) for xy, p in _status_entries(root)
                 if xy != "D " and p not in commit["paths"]]
    assert uncovered == []


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_the_proposed_command_leaves_a_clean_tree_and_a_rerun_is_a_no_op(tmp_path, variant):
    root = _build(variant, tmp_path / "repo")
    _, out = _upgrade(root)
    _commit(out)
    assert git(root, "status", "--porcelain").stdout == ""
    assert git(root, "log", "-1", "--format=%s").stdout.strip() == "harness: upgrade to 0.10"
    assert git(root, "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert git(root, "ls-files", *INDEX_DELETIONS).stdout == ""
    before = tree_bytes(root)
    proc, again = _upgrade(root)
    assert proc.returncode == 0, again.get("failures")
    assert again["status"] == "already on 0.10"
    assert again["steps"] == [] and again["commit"] is None
    assert tree_bytes(root) == before
    assert git(root, "status", "--porcelain").stdout == ""


@pytest.mark.parametrize("version", sorted(BUILDERS))
def test_second_run_changes_no_file_and_reports_already_on_010(tmp_path, version):
    root = BUILDERS[version](tmp_path / "repo")
    _upgrade(root)
    before, status = tree_bytes(root), git(root, "status", "--porcelain").stdout
    proc, out = _upgrade(root)
    assert proc.returncode == 0, out.get("failures")
    assert out["status"] == "already on 0.10"
    assert out["commit"] is None
    assert tree_bytes(root) == before
    assert git(root, "status", "--porcelain").stdout == status


@pytest.mark.parametrize("version", sorted(BUILDERS))
def test_dry_run_changes_no_file_and_lists_every_step(tmp_path, version):
    from engine import upgrade_010
    root = BUILDERS[version](tmp_path / "repo")
    before, status = tree_bytes(root), git(root, "status", "--porcelain").stdout
    proc = run_cli("upgrade", "--dry-run", root=root)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert [r["id"] for r in out["steps"]] == [s.id for s in upgrade_010.STEPS]
    pending = "\n".join(c for r in out["steps"] for c in r["changes"])
    for needle in (".harness/shadows", "telemetry", ".harness/memory", "config.yaml"):
        assert needle in pending, needle
    assert out["plan"][-1] == "propose one commit"
    assert tree_bytes(root) == before
    assert git(root, "status", "--porcelain").stdout == status


@pytest.mark.parametrize("version", sorted(BUILDERS))
def test_without_a_terminal_upgrade_stops_short_then_yes_finishes_it(tmp_path, version):
    root = BUILDERS[version](tmp_path / "repo")
    proc = run_cli("upgrade", root=root)           # stdin is a pipe, not a TTY
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["status"] == "incomplete" and out["commit"] is None
    skipped = [row["id"] for row in out["steps"]
               if "skipped: needs confirmation" in row.get("report", [])]
    assert skipped[0] == "w1.untrack-shadows"
    assert set(skipped) == {"w1.untrack-shadows", "w2.telemetry",
                            "w3.retire-durable-memory", "w8.agents-md"}
    # nothing destructive happened, and the half-way repo is still consistent
    assert git(root, "ls-files", ".harness/shadows").stdout.strip()
    assert (root / ".harness/memory/durable.jsonl").exists()
    assert (root / ".harness/telemetry.jsonl").exists()
    assert git(root, "diff", "--cached", "--name-only").stdout == ""
    assert out["checks"]["doctor"]["passed"] and out["checks"]["verify"]["passed"]
    assert any("harness upgrade --yes" in line for line in out["human_checks"])

    proc, out = _upgrade(root)
    assert proc.returncode == 0, out.get("failures")
    assert out["status"] == "upgraded"
    assert not any("uncommitted edits" in line for line in out["human_checks"])
    _commit(out)
    assert git(root, "status", "--porcelain").stdout == ""
    proc, out = _upgrade(root)
    assert proc.returncode == 0 and out["status"] == "already on 0.10"


def test_the_kept_rows_are_exported_for_review(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    durable = root / ".harness/memory/durable.jsonl"
    write_jsonl(durable, read_jsonl(durable) + [{
        "id": "mem-attempt0001", "scope": "durable", "slice_id": "slice-041",
        "commit": None, "kind": "attempt", "content": "Rounding with float failed.",
        "attempt": {"approach": "float round", "outcome": "off by a cent",
                    "why": "binary floats"}, "edges": []}])
    git(root, "commit", "-qam", "an attempt row")
    proc, out = _upgrade(root)
    assert proc.returncode == 0, out.get("failures")
    export = (root / ".harness/cache/durable-memory-export.md").read_text()
    assert "Rounding with float failed." in export
    assert "harness memory promote --text" in export
    assert FACT["0.9.4"] not in export          # observations are not offered
    assert not (root / ".harness/memory").exists()


def test_the_worktree_check_line_works_in_that_worktree(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra", with_worktree=True)
    _, out = _upgrade(root)
    _commit(out)
    tree = root / ".worktrees/slice-043"
    proc, wout = _upgrade(tree)
    assert proc.returncode == 0, json.dumps(wout.get("failures"), indent=1)
    assert wout["status"] == "upgraded"
    assert _backlog(tree)["slice-043"]["legacy_verification"] is True


def test_in_flight_slice_closes_after_upgrade_without_a_red_record(tmp_path):
    from engine.events import handle_event
    root = build_astralabs_094_repo(tmp_path / "astra")
    _, out = _upgrade(root)
    _commit(out)
    assert _backlog(root)["slice-043"]["legacy_verification"] is True
    red = root / ".harness/verification/slice-043.json"
    run_cli("slice", "--slice", "slice-043", "--session", "up1", root=root)
    loaded_context(root, session="up1", slice_id="slice-043")
    orders = root / "libs/core/src/astra_core/orders.py"
    orders.write_text(orders.read_text() + "# CAD is the default currency.\n")
    rel = "libs/core/src/astra_core/orders.py"
    handle_event(make_event("post_change", session="up1", slice_id="slice-043",
                            files=[rel]), root)
    handle_event(make_event("unit_complete", session="up1", slice_id="slice-043"), root)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "slice-043 work")
    assert not red.exists()
    proc = run_cli("close-slice", "--slice", "slice-043", "--session", "up1",
                   "--commit", "HEAD", root=root, env={"CLAUDE_SESSION_ID": ""})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _backlog(root)["slice-043"]["status"] == "closed"
    assert not red.exists()


def test_unmarked_agent_files_are_untouched_and_the_report_prints_the_lines(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra", marked=False)
    before = {n: (root / n).read_bytes() for n in ("AGENTS.md", "CLAUDE.md")}
    proc, out = _upgrade(root)
    assert proc.returncode == 0, out.get("failures")
    assert {n: (root / n).read_bytes() for n in before} == before
    checks = "\n".join(out["human_checks"])
    assert "AGENTS.md" in checks
    assert "@.claude/memory/shared/MEMORY.md" in checks
    assert not (root / ".harness/cache/AGENTS.md.pre-0.10").exists()


def test_a_09_machine_with_a_live_sidecar_upgrades(tmp_path):
    root = build_astralabs_094_repo(tmp_path / "astra")
    write_legacy_sidecar(root, binding=("s-old", "slice-043"),
                         buffered=legacy_events("slice-043", 12, 3))
    proc, out = _upgrade(root)
    assert proc.returncode == 0, out.get("failures")
    doctor = json.loads(run_cli("doctor", "--substrate", root=root).stdout)
    assert doctor["substrate_healthy"] is True, doctor
    metrics = root / ".harness/slice-metrics.jsonl"
    kept = metrics.exists() and "slice-043" in metrics.read_text()
    reported = any("telemetry" in line for line in out["human_checks"])
    kept_in_cache = "slice-043" in (root / ".harness/cache/events.jsonl").read_text()
    assert kept or reported or kept_in_cache
