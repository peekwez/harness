"""W6 upgrade step: add explore to the AGENTS.md workflow line."""
from conftest import run_cli

MARK = "<!-- harness:agents-md 0.10 -->"
OLD = "init -> architect -> author-gate            # Phase 0: a human signs"
NEW = "init -> explore -> architect -> author-gate # Phase 0: a human signs"
STEP = "w6.agents-md-explore"


def _agents(root, body):
    (root / "AGENTS.md").write_text(body)


def _step():
    from engine import upgrade_010
    return next(s for s in upgrade_010.STEPS if s.id == STEP)


def test_only_one_w6_step():
    from engine import upgrade_010
    assert [s.id for s in upgrade_010.STEPS
            if s.id.startswith("w6.")] == [STEP]


def test_marked_agents_lacking_explore_is_pending_and_apply_inserts(toy):
    _agents(toy, f"{MARK}\n# AGENTS\n\n```\n{OLD}\nbacklog\n```\n")
    step = _step()
    assert step.describe(toy)
    assert step.apply(toy, None)
    assert (toy / "AGENTS.md").read_text() == (
        f"{MARK}\n# AGENTS\n\n```\n{NEW}\nbacklog\n```\n")


def test_second_run_is_a_no_op(toy):
    _agents(toy, f"{MARK}\n```\n{OLD}\n```\n")
    step = _step()
    step.apply(toy, None)
    after = (toy / "AGENTS.md").read_text()
    assert step.describe(toy) == []
    assert step.apply(toy, None) == []
    assert (toy / "AGENTS.md").read_text() == after


def test_unmarked_agents_gets_check_line_and_nothing_pending(toy):
    _agents(toy, f"# mine\n{OLD}\n")
    step = _step()
    assert step.describe(toy) == []
    advice = step.advise(toy)
    assert len(advice) == 1 and advice[0].startswith("check:")
    assert len(advice[0].split(".")[0].split()) <= 25
    assert step.apply(toy, None) == []
    assert (toy / "AGENTS.md").read_text() == f"# mine\n{OLD}\n"


def test_no_agents_md_has_nothing_pending(toy):
    (toy / "AGENTS.md").unlink(missing_ok=True)
    step = _step()
    assert step.describe(toy) == [] and step.advise(toy) == []


def test_marked_agents_with_no_workflow_line_is_left_alone(toy):
    _agents(toy, f"{MARK}\n# AGENTS\n")
    assert _step().describe(toy) == []


def test_the_template_workflow_line_is_the_step_output():
    from engine.upgrade_w6 import WORKFLOW_NEW
    from engine.context_cost import PLUGIN_ROOT
    assert WORKFLOW_NEW in (PLUGIN_ROOT / "templates/agents-md.md").read_text()


def test_a_repo_without_explore_verifies_with_no_g9_finding(toy):
    proc = run_cli("verify", root=toy)
    assert "EXPLORE_IMPORT" not in proc.stdout
    assert not (toy / "explore").exists()


def test_marked_agents_with_a_custom_workflow_line_gets_a_check_line(toy):
    body = (f"{MARK}\n```\ninit -> architect -> review -> author-gate "
            f"# mine\n```\n")
    _agents(toy, body)
    step = _step()
    assert step.describe(toy) == []
    assert step.advise(toy) == [
        "check: add explore before architect in the AGENTS.md workflow "
        "line by hand."]
    assert step.apply(toy, None) == []
    assert (toy / "AGENTS.md").read_text() == body


def test_marked_agents_with_explore_or_old_line_gets_no_check_line(toy):
    step = _step()
    _agents(toy, f"{MARK}\n```\n{NEW}\n```\n")
    assert step.advise(toy) == []
    _agents(toy, f"{MARK}\n```\n{OLD}\n```\n")
    assert step.advise(toy) == []
    _agents(toy, f"{MARK}\n# AGENTS\n")
    assert step.advise(toy) == []
