"""Init/first-run UX fixes: a fresh repo must not greet the user with
errors about files that cannot exist yet.

Two defect classes from the field:
- `/harness:architect` and `/harness:backlog` run `author-gate --doc
  docs/architecture.md` as a skill preamble; on a fresh repo the CLI raised
  a HarnessError before the gate could report the missing doc as an ordinary
  gap.
- `init` seeded decisions.jsonl and backlog.jsonl with EDIT-ME placeholder
  rows that read as defects. The author-gate's domain-coverage check (every
  registry domain needs a decision row) already provides the same guarantee
  with a clearer message, and seeded backlog rows contradict the
  never-hand-edit-backlog rule.
"""
import json

from conftest import run_cli

from engine import read_jsonl
from engine.compiler import author_gate


# ---------------------------------------------------------------- author-gate
def test_author_gate_missing_doc_is_a_gap_not_an_error(tmp_path):
    """First `/harness:architect` on a fresh repo: the preamble author-gate
    must report the missing working document as a gate gap that names the
    next action, not raise."""
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    proc = run_cli("author-gate", "--doc", "docs/architecture.md", root=target)
    assert proc.returncode == 1  # gate fails — loud, never silent
    assert "Traceback" not in proc.stderr
    assert "silent degradation" not in proc.stderr  # the old scary error
    result = json.loads(proc.stdout)
    assert result["passed"] is False
    gap = "\n".join(result["gaps"])
    assert "docs/architecture.md" in gap
    assert "architect" in gap  # points at the command that creates it


def test_author_gate_report_mode_exits_zero_on_gaps(tmp_path):
    """`--report` is the skill-preamble spelling: the architect/backlog
    skills run author-gate at every invocation for workflow-state context,
    where gaps are the normal Phase-0 state — a nonzero exit renders as a
    shell error in the host. The verdict lives in the JSON (`passed`);
    the bare command keeps exit 1 for automation."""
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    proc = run_cli("author-gate", "--report", "--doc", "docs/architecture.md",
                   root=target)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["passed"] is False and result["gaps"]


# ---------------------------------------------------------------- init seeds
def test_init_scaffolds_without_placeholder_rows(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    assert read_jsonl(target / ".harness" / "decisions.jsonl") == []
    assert read_jsonl(target / ".harness" / "backlog.jsonl") == []
    # registry still carries the planned standard-abstraction slots
    ids = {e["id"] for e in read_jsonl(target / ".harness" / "registry.jsonl")}
    assert {"config", "logging", "errors", "telemetry"} <= ids


def test_fresh_init_gate_reports_domain_gaps_not_edit_me(tmp_path):
    """The guarantee the seeds provided survives without them: the gate
    still blocks until every registry domain has a decision row."""
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    result = author_gate(target)
    assert not result["passed"]
    gaps = "\n".join(result["gaps"])
    assert "EDIT ME" not in gaps
    for domain in ("config", "logging", "errors", "telemetry"):
        assert f"domain {domain!r}" in gaps


def test_init_creates_no_harness_memory(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    assert not (target / ".harness" / "memory").exists()
    gitignore = (target / ".gitignore").read_text()
    assert ".harness/memory" not in gitignore
    assert ".harness/cache/" in gitignore.splitlines()
    assert "memory" not in (target / ".gitattributes").read_text()


def test_claude_md_template_imports_shared_memory():
    from conftest import PLUGIN_ROOT
    from engine.shared_memory import CLAUDE_IMPORT, CLAUDE_MARKER
    text = (PLUGIN_ROOT / "templates" / "claude-md.md").read_text()
    assert CLAUDE_IMPORT in text.splitlines()
    assert "@AGENTS.md" in text.splitlines()
    assert CLAUDE_MARKER in text.casefold()


def test_claude_md_template_is_current_for_the_upgrade_check(tmp_path):
    from conftest import PLUGIN_ROOT
    from engine.shared_memory import claude_md_state
    (tmp_path / "CLAUDE.md").write_text(
        (PLUGIN_ROOT / "templates" / "claude-md.md").read_text())
    assert claude_md_state(tmp_path) == "current"


def test_init_scaffolds_shared_memory_and_claude_import(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=target).returncode == 0
    index = target / ".claude" / "memory" / "shared" / "MEMORY.md"
    assert index.read_text().startswith("# Shared memory")
    claude = (target / "CLAUDE.md").read_text().splitlines()
    assert "@AGENTS.md" in claude
    assert "@.claude/memory/shared/MEMORY.md" in claude


def test_init_keeps_an_existing_claude_md_and_names_the_import(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    (target / "CLAUDE.md").write_text("# mine\n")
    proc = run_cli("init", root=target)
    assert proc.returncode == 0
    assert (target / "CLAUDE.md").read_text() == "# mine\n"
    assert "@.claude/memory/shared/MEMORY.md" in proc.stdout
