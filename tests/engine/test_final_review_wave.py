"""The 0.8 pre-release fix wave (GOO-72): the final whole-branch review.

Every test here is one review finding made executable — doc-authored
abstractions that can actually flip to built (I-1), `backlog add --linear`
(I-3), doctor's provenance check using verify's own resolution (I-4), and
the minor hardening items (M-1 … M-5, M-8).
"""
import json

import pytest
from conftest import build_toy_repo, git, run_cli

from engine import HarnessError, read_jsonl
from engine.docsections import parse_doc_blocks
from engine.extractor.modules import RegistryIndex

DOC_5COL = """# Architecture

```harness-abstractions
| id | kind | guidance_ref | source | module_id |
| --- | --- | --- | --- | --- |
| orders | component | docs/architecture.md | orders.py | |
```
"""

DOC_3COL = """# Architecture

```harness-abstractions
| id | kind | guidance_ref |
| --- | --- | --- |
| orders | component | docs/architecture.md |
```
"""

DOC_MODULE_ID = """# Architecture

```harness-abstractions
| id | kind | guidance_ref | source | module_id |
| --- | --- | --- | --- | --- |
| kcfg | component | docs/architecture.md | | kente.config |
```
"""


def _write_doc(root, body):
    doc = root / "docs" / "architecture.md"
    doc.parent.mkdir(exist_ok=True)
    doc.write_text(body)
    return doc


def _entry(root, entry_id):
    return {e["id"]: e for e in
            read_jsonl(root / ".harness" / "registry.jsonl")}[entry_id]


# ------------------------------------------------------------------ I-1
def test_the_abstraction_table_accepts_source_and_module_id(toy):
    """A doc-authored abstraction with no `source` can never flip to built:
    the resolver never injects its shadow and G5 never matches its imports."""
    blocks = parse_doc_blocks(DOC_5COL, source="docs/architecture.md")
    assert blocks["abstractions"] == [
        {"id": "orders", "kind": "component",
         "guidance_ref": "docs/architecture.md",
         "source": "orders.py", "module_id": ""}]


def test_the_three_column_abstraction_table_still_compiles(toy):
    """Backward compatibility: the 0.7 header stays legal, unchanged."""
    assert parse_doc_blocks(DOC_3COL)["abstractions"] == [
        {"id": "orders", "kind": "component",
         "guidance_ref": "docs/architecture.md"}]


def test_a_doc_abstraction_with_source_derives_its_module_id(toy):
    (toy / "orders.py").write_text("def create_order(sku):\n    return sku\n")
    _write_doc(toy, DOC_5COL)
    proc = run_cli("compile", "--doc", "docs/architecture.md", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    entry = _entry(toy, "orders")
    assert entry["source"] == "orders.py"
    assert entry["module_id"] == "orders"


def test_a_doc_abstraction_may_name_its_module_id_directly(toy):
    _write_doc(toy, DOC_MODULE_ID)
    assert run_cli("compile", "--doc", "docs/architecture.md",
                   root=toy).returncode == 0
    entry = _entry(toy, "kcfg")
    assert entry["module_id"] == "kente.config" and entry["source"] is None


def test_registry_index_matches_a_doc_authored_namespace_module():
    """`id: config` + `module_id: kente.config` must answer for every import
    under it — the whole point of carrying the module id."""
    index = RegistryIndex([{"id": "config", "module_id": "kente.config"}])
    assert index.match("kente.config.settings")["id"] == "config"
    assert index.match("kente.telemetry") is None


# ------------------------------------------------------------------ I-3
def test_backlog_add_records_a_linear_id(toy):
    proc = run_cli("backlog", "add", "--id", "slice-100", "--acceptance",
                   "tests/slices/100_x.py", "--linear", "GOO-73", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["linear"] == "GOO-73"
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-100"]["linear"] == "GOO-73"


def test_backlog_add_without_linear_writes_no_key(toy):
    assert run_cli("backlog", "add", "--id", "slice-101", "--acceptance",
                   "tests/slices/101_x.py", root=toy).returncode == 0
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert "linear" not in rows["slice-101"]


@pytest.mark.parametrize("bad", ["goo-73", "GOO73", "G-73", "GOO-", "GOO-7a"])
def test_backlog_add_rejects_a_malformed_linear_id(toy, bad):
    proc = run_cli("backlog", "add", "--id", "slice-102", "--acceptance",
                   "tests/slices/102_x.py", "--linear", bad, root=toy)
    assert proc.returncode == 1
    assert "linear" in (proc.stdout + proc.stderr).lower()
    assert not any(r["id"] == "slice-102"
                   for r in read_jsonl(toy / ".harness" / "backlog.jsonl"))


# ------------------------------------------------------------------ M-1
def test_start_refuses_no_worktree_in_pr_mode(tmp_path):
    """pr landing pushes the slice's own branch — a close in the main tree
    would push whatever `slice/<id>` points at, or nothing at all."""
    root = build_toy_repo(tmp_path / "toy")
    (root / ".harness" / "config.yaml").write_text(
        (root / ".harness" / "config.yaml").read_text()
        + "landing:\n  mode: \"pr\"\n")
    proc = run_cli("start", "--slice", "slice-042", "--no-worktree", root=root)
    assert proc.returncode == 1, proc.stdout
    err = proc.stdout + proc.stderr
    assert "--no-worktree" in err and "landing.mode: local" in err


def test_start_with_a_worktree_still_works_in_pr_mode(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    (root / ".harness" / "config.yaml").write_text(
        (root / ".harness" / "config.yaml").read_text()
        + "landing:\n  mode: \"pr\"\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "landing config")
    proc = run_cli("start", "--slice", "slice-042", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["branch"] == "slice/slice-042"


# ------------------------------------------------------------------ M-2
def test_compile_resolves_the_doc_under_root(tmp_path):
    """`--doc docs/architecture.md` must mean the same thing `architect`
    means: root-relative, not cwd-relative."""
    root = build_toy_repo(tmp_path / "toy")
    (root / "orders.py").write_text("def create_order(sku):\n    return sku\n")
    _write_doc(root, DOC_5COL)
    proc = run_cli("compile", "--doc", "docs/architecture.md", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "orders" in [e["id"] for e in
                        read_jsonl(root / ".harness" / "registry.jsonl")]


def test_compile_names_a_missing_doc_without_a_traceback(toy):
    proc = run_cli("compile", "--doc", "docs/nope.md", root=toy)
    assert proc.returncode == 1
    assert "docs/nope.md" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_author_gate_names_a_missing_doc_without_a_traceback(toy):
    proc = run_cli("author-gate", "--doc", "docs/nope.md", root=toy)
    assert proc.returncode == 1
    assert "docs/nope.md" in (proc.stdout + proc.stderr)
    assert "Traceback" not in proc.stderr


def test_author_gate_resolves_the_doc_under_root(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    _write_doc(root, "# Architecture\n\n<!-- stage: 5 -->\n")
    proc = run_cli("author-gate", "--doc", "docs/architecture.md", root=root)
    assert "does not exist" not in proc.stdout, proc.stdout


# ------------------------------------------------------------------ M-3
def test_graph_note_resolves_a_symbolic_commit(toy):
    """`--commit HEAD` is the permission-auto-approvable spelling; storing
    the literal 'HEAD' makes the notes row unresolvable forever."""
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("graph", "note", "--slice", "slice-042", "--commit", "HEAD",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["commit"] == head
    rows = read_jsonl(toy / ".harness" / "notes.jsonl")
    assert rows[-1]["commit"] == head
    assert rows[-1]["tree_hash"]


def test_graph_note_rejects_an_unresolvable_commit(toy):
    proc = run_cli("graph", "note", "--slice", "slice-042", "--commit",
                   "no-such-ref", root=toy)
    assert proc.returncode == 1
    assert "no-such-ref" in (proc.stdout + proc.stderr)


# ------------------------------------------------------------------ M-4
PR_CFG = {"landing": {"mode": "pr", "remote": "origin", "base": "main"}}
LOCAL_CFG = {"landing": {"mode": "local"}}


def _decision(command, config=None):
    from engine.permits import command_decision
    return command_decision(command, config=config or PR_CFG,
                            slice_id="slice-042")[0]


@pytest.mark.parametrize("command", [
    "git config alias.up 'push origin HEAD'",
    "git config --global user.email x@y",
    "git config --system core.editor vim",
    "git config core.sshCommand 'ssh -i /tmp/k'",
    "git config url.https://x@github.com/.insteadOf https://github.com/",
    "git config remote.origin.url https://x@github.com/a/b",
    "git config credential.helper '!f() { echo x; }; f'",
    "git config http.proxy http://evil:8080",
    "git config core.hooksPath .githooks",
    "git config --local alias.p push",
])
def test_pr_mode_denies_config_that_enables_later_egress(command):
    assert _decision(command) == "deny", command


@pytest.mark.parametrize("command", [
    "git config user.name t",
    "git config user.email t@t",
    "git config core.editor vim",
    "git config --get user.name",
    "git config --list",
])
def test_pr_mode_leaves_harmless_git_config_alone(command):
    assert _decision(command) != "deny", command


@pytest.mark.parametrize("command", [
    "git config alias.up 'push origin HEAD'",
    "git config --global user.email x@y",
    "git config core.hooksPath .githooks",
])
def test_local_mode_git_config_is_unchanged(command):
    assert _decision(command, config=LOCAL_CFG) != "deny", command


# ------------------------------------------------------------------ M-5
GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _close_toy(root, gate_cmd=None):
    from conftest import loaded_context, make_event
    from engine.events import handle_event
    if gate_cmd:
        (root / ".harness" / "config.yaml").write_text(
            (root / ".harness" / "config.yaml").read_text()
            + f"acceptance:\n  gate_cmd: \"{gate_cmd}\"\n")
    run_cli("slice", "--slice", "slice-042", "--session", "m5", root=root)
    loaded_context(root, session="m5")
    (root / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session="m5", files=["orders.py"]),
                 root)
    handle_event(make_event("unit_complete", session="m5"), root)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "slice-042 work")
    return run_cli("close-slice", "--slice", "slice-042", "--session", "m5",
                   "--commit", "HEAD", root=root,
                   env={"CLAUDE_SESSION_ID": ""})


def test_close_reports_a_skipped_acceptance_gate(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    proc = _close_toy(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["acceptance_gate"] == "skipped"


def test_close_reports_a_passed_acceptance_gate(tmp_path):
    root = build_toy_repo(tmp_path / "toy")
    proc = _close_toy(root, gate_cmd="true")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["acceptance_gate"] == "passed"


# ------------------------------------------------------------------ M-8
def test_the_three_declared_versions_agree():
    from pathlib import Path

    import engine
    root = Path(engine.__file__).resolve().parents[1]
    plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((root / ".claude-plugin" / "marketplace.json").read_text())
    versions = {plugin["version"], engine.ENGINE_VERSION,
                *[p["version"] for p in market["plugins"]
                  if p["name"] == plugin["name"]]}
    assert versions == {"0.8.0"}, versions


def test_the_readme_changelogs_the_release():
    from pathlib import Path

    import engine
    readme = (Path(engine.__file__).resolve().parents[1]
              / "README.md").read_text()
    assert "## Changelog" in readme
    assert "0.8.0" in readme
    for issue in ("GOO-73", "GOO-74", "GOO-75", "GOO-76", "GOO-77", "GOO-78",
                  "GOO-79"):
        assert issue in readme, issue


# ------------------------------------------------------------------ I-4
def test_doctor_uses_verifys_note_resolution(tmp_path):
    """A pr-landed slice on a fresh clone has no git note at all — doctor
    must resolve it the way verify does, or every clone looks unhealthy."""
    from test_landing_pr import _close, _pr_repo, _squash_land, _work_and_commit
    toy, origin = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    _squash_land(toy, origin, tmp_path)
    git(toy, "update-ref", "-d", "refs/notes/harness")
    proc = run_cli("doctor", "--substrate", root=toy)
    out = json.loads(proc.stdout)
    assert out["missing_notes"] == [], out
    assert out["substrate_healthy"] is True, out


def test_doctor_still_reports_a_slice_with_no_provenance_at_all(toy):
    from conftest import loaded_context, make_event
    from engine.events import handle_event
    run_cli("slice", "--slice", "slice-042", "--session", "d1", root=toy)
    loaded_context(toy, session="d1")
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session="d1", files=["orders.py"]),
                 toy)
    handle_event(make_event("unit_complete", session="d1"), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    assert run_cli("close-slice", "--slice", "slice-042", "--session", "d1",
                   "--commit", "HEAD", root=toy,
                   env={"CLAUDE_SESSION_ID": ""}).returncode == 0
    git(toy, "update-ref", "-d", "refs/notes/harness")
    (toy / ".harness" / "notes.jsonl").unlink()
    out = json.loads(run_cli("doctor", "--substrate", root=toy).stdout)
    assert out["missing_notes"] == ["slice-042"]
    assert "harness land" in out["next"] or "repoint" in out["next"]


def test_a_malformed_linear_id_is_a_harness_error():
    from engine.cli.author import validate_linear
    assert validate_linear("GOO-73") == "GOO-73"
    with pytest.raises(HarnessError):
        validate_linear("nope")
