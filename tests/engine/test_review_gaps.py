"""Regression tests for the adversarial-review findings (S1–S10) plus the
verification pass's minor gaps: worktree state-split, cache kind-awareness,
shadow pruning, poisoned-path resilience, glob acceptance, driver self-heal."""
import json
import subprocess
import sys

from conftest import (PLUGIN_ROOT, build_toy_repo, git, loaded_context,
                      make_event, run_cli)
from engine import load_config, read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def codes(verdict):
    return {f["code"] for f in verdict["findings"]}


# ---------------------------------------------------------------- S2
def test_extract_all_works_when_repo_lives_under_an_ignored_dir_name(tmp_path):
    """IGNORED_DIRS must filter path parts RELATIVE to the root — a worktree
    at .worktrees/<slice> (or a repo cloned under ~/venv/…) has an ignored
    name in its ABSOLUTE parts and extract --all silently extracted nothing."""
    root = build_toy_repo(tmp_path / ".worktrees" / "slice-x")
    (root / "newmod.py").write_text("def fresh():\n    return 1\n")
    proc = run_cli("extract", "--all", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "newmod.py" in out["written"], \
        "NEW files inside the worktree must be discoverable, not just " \
        "refreshes of already-stored shadows"


# ---------------------------------------------------------------- S1
def test_bind_backfills_started_at_commit_and_snapshots_baseline(toy):
    """A worktree checkout carries the committed row (no started_at_commit)
    and an empty sidecar. Re-binding there must repair BOTH: the git-diff
    anchor and the G6 baseline — regardless of the row's current status."""
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "in_progress"          # already flipped elsewhere
    rows[0].pop("started_at_commit", None)
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    proc = run_cli("slice", "--slice", "slice-042", "--session", "s1", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    assert rows[0].get("started_at_commit"), "anchor must backfill on re-bind"
    sc = Sidecar(toy)
    try:
        assert sc.snapshot_get("slice-042"), \
            "bind must snapshot the G6 baseline (Phase-1 may never run here)"
    finally:
        sc.close()


def test_worktree_close_is_not_vacuous(toy, tmp_path):
    """S1's demonstrated symptom: close inside a worktree saw touched=[] and
    waved through undeclared, unshadowed files. With bind-in-worktree, the
    close must see real touches and list the rogue file as scope_advisory."""
    wt = toy / ".worktrees" / "slice-042"
    r = git(toy, "worktree", "add", str(wt), "-b", "slice/slice-042")
    assert r.returncode == 0, r.stderr
    proc = run_cli("slice", "--slice", "slice-042", "--session", "wt", root=wt)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (wt / "orders.py").write_text(GOOD_ORDERS)
    (wt / "rogue_helper.py").write_text("def sneak():\n    return 1\n")
    run_cli("extract", str(wt / "orders.py"), str(wt / "rogue_helper.py"),
            root=wt)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "slice-042 in worktree")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", "wt",
                   "--commit", "HEAD", root=wt)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "orders.py" in out["touched"] and "rogue_helper.py" in out["touched"]
    assert out["scope_advisory"] == ["rogue_helper.py"]


def test_close_warns_when_started_at_commit_is_missing(toy):
    session = "no-anchor"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0].pop("started_at_commit", None)     # legacy row
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "x")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "started_at_commit" in proc.stderr, \
        "skipping the git-diff union must be loud, not silent"


# ---------------------------------------------------------------- S3
def test_cache_invalidated_when_language_is_toggled_off(toy):
    """Language toggled off: the cached real shadow must not be served."""
    from engine.extractor.engine import shadow_path_for
    import yaml
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["languages"]["python"] = False
    cfg_path.write_text(yaml.safe_dump(cfg))
    proc = run_cli("extract", "--all", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "telemetry.py" in json.loads(proc.stdout)["written"]
    sp = shadow_path_for(toy, toy / "telemetry.py")
    assert json.loads(sp.read_text())["language"] == "unknown"


def test_cache_invalidated_when_deps_arrive_after_degenerate_shadow(toy):
    """A degenerate shadow written while tree-sitter was missing must be a
    cache MISS once the deps exist."""
    from engine.extractor.engine import (EXTRACTOR_VERSION, _degenerate_shadow,
                                         write_shadow)
    src = toy / "telemetry.py"
    shadow = _degenerate_shadow(toy, src, src.read_bytes())
    assert shadow["extractor_version"] == EXTRACTOR_VERSION
    write_shadow(toy, src, shadow)             # what a deps-less run left behind
    proc = run_cli("extract", "--all", root=toy)
    out = json.loads(proc.stdout)
    assert "telemetry.py" in out["written"], \
        "same hash + same version but wrong KIND must not cache-hit"


def test_extract_all_prunes_shadows_of_deleted_sources(toy):
    """A deleted source leaves a stale cache entry; --all removes it."""
    from engine.extractor.engine import shadow_path_for
    sp = shadow_path_for(toy, toy / "config.py")
    (toy / "config.py").unlink()
    proc = run_cli("extract", "--all", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "config.py" in out.get("pruned", []), out
    assert not sp.exists()


def test_extract_all_prunes_a_corrupt_out_of_root_shadow(toy):
    from engine.extractor.engine import shadow_path_for
    evil = shadow_path_for(toy, toy / "evil")       # <cache>/evil.json
    evil.parent.mkdir(parents=True, exist_ok=True)
    evil.write_text(json.dumps({"source_path": "../outside.py",
                                "source_hash": "sha256:0", "symbols": []}))
    (toy.parent / "outside.py").write_text("x = 1\n")
    proc = run_cli("gates", "--event", "unit_complete", "--slice", "slice-042",
                   root=toy)
    assert proc.returncode in (0, 1), proc.stderr
    assert "verdict" in proc.stdout, "hooks must get a verdict, not an error"
    run_cli("extract", "--all", root=toy)
    assert not evil.exists()





# ---------------------------------------------------------------- S4


# ---------------------------------------------------------------- S5


def test_relative_traversal_paths_never_poison_the_sidecar(toy):
    session = "traverse"
    loaded_context(toy, session=session)
    (toy.parent / "outside.py").write_text("x = 1\n")
    handle_event(make_event("post_change", session=session,
                            files=["../outside.py"]), toy)
    sc = Sidecar(toy)
    try:
        assert not any("outside" in t for t in
                       sc.touched_paths(session_id=session))
        sc.touch(session, "slice-042", ["../outside.py"])  # legacy poison row
    finally:
        sc.close()
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert v["verdict"] in ("allow", "allow_with_findings", "block")


# ---------------------------------------------------------------- S6
def test_close_releases_g6_snapshots(toy):
    session = "snapclear"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    sc = Sidecar(toy)
    try:
        assert sc.snapshot_get("slice-042")     # baseline exists after bind
    finally:
        sc.close()
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "x")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sc = Sidecar(toy)
    try:
        assert not sc.snapshot_get("slice-042"), \
            "stale baselines cause phantom drift when the id is rebound"
    finally:
        sc.close()


# ---------------------------------------------------------------- S7
def test_glob_acceptance_with_zero_matches_blocks(toy):
    (toy / "tests" / "slices" / "042_orders.py").unlink()
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["acceptance"] = ["tests/slices/*.py"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    session = "glob0"
    loaded_context(toy, session=session)
    v = handle_event(make_event("pre_change", session=session,
                                files=["orders.py"]), toy)
    assert "MANIFEST_INCOMPLETE" in codes(v), \
        "an existing dir with zero matching tests is not red-test-first"


def test_glob_acceptance_expands_at_close(toy):
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["acceptance"] = ["tests/slices/04*_orders.py"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    session = "globby"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "x")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, \
        "matching, passing tests must close — the glob was passed to pytest " \
        "literally: " + proc.stdout


# ---------------------------------------------------------------- S8
def test_bind_self_heals_merge_driver_config_on_fresh_clones(toy, tmp_path):
    clone = tmp_path / "clone"
    r = subprocess.run(["git", "clone", "-q", str(toy), str(clone)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not git(clone, "config", "merge.harness-substrate.driver").stdout.strip()
    proc = run_cli("slice", "--slice", "slice-042", "--session", "c1",
                   root=clone)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    driver = git(clone, "config", "merge.harness-substrate.driver").stdout
    assert "merge-substrate %O %A %B" in driver, \
        "repo-local driver config doesn't travel with clones — bind restores it"
    assert git(clone, "config", "merge.ours.driver").stdout.strip() == "true"


# ---------------------------------------------------------------- S9
def test_merge_substrate_rejects_duplicate_ids(tmp_path):
    base = tmp_path / "base.jsonl"
    ours = tmp_path / "ours.jsonl"
    theirs = tmp_path / "theirs.jsonl"
    write_jsonl(base, [{"id": "a", "v": 1}])
    write_jsonl(ours, [{"id": "a", "v": 1}, {"id": "a", "v": 2}])
    write_jsonl(theirs, [{"id": "a", "v": 1}])
    before = ours.read_text()
    proc = run_cli("merge-substrate", base, ours, theirs)
    assert proc.returncode == 1, "duplicate ids silently collapsed"
    assert "duplicate" in (proc.stdout + proc.stderr).lower()
    assert ours.read_text() == before


# ---------------------------------------------------------------- S10
def test_closing_an_already_closed_slice_refuses(toy):
    session = "reclose"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "x")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1
    assert "already closed" in json.loads(proc.stdout)["reason"]


# ------------------------------------------------- pass-1 minor gaps
def test_adapter_routes_by_any_file_not_just_the_first(toy, tmp_path):
    """A multi-file edit whose FIRST file lives outside any substrate must
    still route by the file that does resolve."""
    wt = build_toy_repo(tmp_path / "wt2")
    (wt / "orders.py").write_text(GOOD_ORDERS)
    hook = {"hook_event_name": "PostToolUse", "session_id": "multi",
            "cwd": str(tmp_path),               # cwd resolves to NO substrate
            "tool_input": {"edits": [
                {"file_path": str(tmp_path / "stray.py")},
                {"file_path": str(wt / "orders.py")}]}}
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "adapter.py")],
        input=json.dumps(hook), capture_output=True, text=True, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    sc = Sidecar(wt)
    try:
        assert "orders.py" in sc.touched_paths(session_id="multi")
    finally:
        sc.close()


