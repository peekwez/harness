"""Prompt-free slice loop: worktrees live INSIDE the workspace so host
permission modes (acceptEdits, workspace-write sandboxes, workspace-scoped
Write allows) cover them, and every adapter routes events to the substrate
the edited file belongs to."""
import importlib.util
import json

from conftest import PLUGIN_ROOT, build_toy_repo, git, run_cli
from engine.events import Sidecar


def _load_adapters_common():
    spec = importlib.util.spec_from_file_location(
        "harness_adapters_common", PLUGIN_ROOT / "adapters" / "common.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------- in-repo worktrees
def test_extract_all_never_walks_into_worktrees(toy):
    """.worktrees/ holds full checkouts — walking into them would shadow
    every file twice (once per tree) in the MAIN substrate."""
    from engine import load_config
    from engine.extractor.engine import extract_all
    inner = toy / ".worktrees" / "slice-042" / "src"
    inner.mkdir(parents=True)
    (inner / "dupe.py").write_text("def f():\n    return 1\n")
    out = extract_all(toy, load_config(toy))
    assert not any(".worktrees" in p for p in out["written"] + out["cached"])
    assert not (toy / ".harness" / "shadows" / ".worktrees").exists()


def test_init_gitignores_the_worktrees_dir(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ".worktrees/" in (root / ".gitignore").read_text().splitlines()


# ------------------------------------------------- prompt-free commands
def test_close_slice_resolves_symbolic_commit_refs(toy):
    """`--commit $(git rev-parse HEAD)` can never be auto-approved (command
    substitution defeats permission prefix-matching) — the ceremony must
    accept `--commit HEAD` and resolve the ref itself."""
    from conftest import loaded_context, make_event
    from engine.events import handle_event
    session = "sym-ref"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(
        "import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
        "    telemetry.emit_span('create_order', {'sku': sku})\n"
        "    return {'sku': sku}\n")
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042: orders")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] and out["note_written"]
    # the note must live on the resolved sha, not the literal string "HEAD"
    notes = git(toy, "notes", "--ref=refs/notes/harness", "list").stdout
    assert head in notes
    # provenance rows must carry the stable sha, never a moving ref name
    from engine.graph import load_edges
    for e in load_edges(toy):
        assert e.get("commit") != "HEAD", e
    assert any(e.get("commit") == head for e in load_edges(toy)
               if e["type"] == "implements")


def test_autonomy_profile_uses_prefix_rule_syntax(tmp_path):
    """Claude Code Bash rules prefix-match with `:*`; the space-glob form
    matches nothing and leaves every builder command prompting."""
    root = tmp_path / "auto"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    proc = run_cli("init", "--autonomy", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    settings = (root / ".claude" / "settings.json").read_text()
    rules = json.loads(settings)["permissions"]
    assert any(r.startswith("Bash(git add:") for r in rules["allow"])
    assert not any(" *)" in r for r in rules["allow"] + rules["deny"]), \
        "space-glob rules never match a real command"
    assert any(r.startswith("Bash(git push:") for r in rules["deny"])


def test_init_autonomy_refreshes_its_own_stale_profile(tmp_path):
    """A previously-written harness profile (broken rule syntax) must be
    refreshed on re-run — only hand-authored settings are left alone."""
    root = tmp_path / "stale"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    target = root / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "_comment": "harness autonomy profile — old broken version",
        "permissions": {"defaultMode": "acceptEdits",
                        "allow": ["Bash(git add *)"], "deny": []}}))
    proc = run_cli("init", "--autonomy", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rules = json.loads(target.read_text())["permissions"]
    assert any(r.startswith("Bash(git add:") for r in rules["allow"])
    # hand-authored settings (no harness marker) stay untouched
    target.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    run_cli("init", "--autonomy", root=root)
    assert json.loads(target.read_text())["permissions"]["allow"] == ["Bash(ls)"]


# ------------------------------------------------- adapter root routing
def test_common_adapter_routes_events_by_file_path(toy, tmp_path, monkeypatch):
    """Non-Claude adapters (Codex/Gemini/Cursor) share call_engine: an edit
    inside a worktree must reach the WORKTREE's substrate even though the
    hook process runs in the main tree (W2 parity)."""
    common = _load_adapters_common()
    wt = build_toy_repo(tmp_path / "wt")
    (wt / "orders.py").write_text("def create_order(s):\n    return {}\n")
    monkeypatch.chdir(toy)
    verdict = common.call_engine("post_change", "route-sess",
                                 files=[str(wt / "orders.py")])
    assert "verdict" in verdict and not verdict.get("engine_error")
    sc = Sidecar(wt)
    try:
        assert "orders.py" in sc.touched_paths(session_id="route-sess")
    finally:
        sc.close()
    sc_main = Sidecar(toy)
    try:
        assert "orders.py" not in sc_main.touched_paths(session_id="route-sess")
    finally:
        sc_main.close()
