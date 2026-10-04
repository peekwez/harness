"""W7: the docs site. Page structure, STE-80 text and real names."""
import re
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT

DOCS = PLUGIN_ROOT / "docs"
# never published (mkdocs.yml exclude_docs); hooks/ holds build inputs
NOT_PUBLIC = ("internal", "superpowers", "design-reviews")


def public_docs() -> list:
    """Every Markdown file a reader of the site or the repo sees."""
    return [p for p in sorted(DOCS.rglob("*.md"))
            if p.relative_to(DOCS).parts[0] not in NOT_PUBLIC]


def public_docs_text() -> str:
    return "\n".join(p.read_text() for p in public_docs())


def _glossary():
    path = DOCS / "glossary.md"
    return path if path.exists() else None


REQUIRED_HEADINGS = {
    "index.md": [
        "# harness", "## What harness does", "## Who it is for",
        "## Two-minute tour", "## What you get", "## What it costs",
        "## Install", "## Where to go next"],
    "trade-offs.md": [
        "# Trade-offs and limits", "## What harness does not catch",
        "## Where enforcement depends on the host", "## Languages",
        "## Costs you pay", "## Design choices you may disagree with",
        "## When not to use harness", "## How to change a limit"],
}

# Task 4: Concepts, Workflow, Verification, Decision cards and Memory.
# Placed before the parametrized tests: they read the keys at import time.
REQUIRED_HEADINGS.update({
    "concepts/philosophy.md": [
        "# Philosophy", "## Three jobs", "## Why 0.10 changed course",
        "## Lookup, never interpret",
        "## Deterministic gates, advisory judgement",
        "## Skill level changes explanation, not checks",
        "## Writing for humans", "## Architecture in one table"],
    "concepts/lifecycle.md": [
        "# Slice lifecycle", "## From idea to landed code", "## Slice states",
        "## What each transition checks", "## Events and gates",
        "## Parks and adjudication"],
    "concepts/substrate.md": [
        "# Substrate files", "## Two trees", "## Authored, derived and cache",
        "## File map", "## Merge drivers", "## CI workflow"],
    "workflow/index.md": [
        "# Workflow", "## Steps at a glance", "## Who signs what"],
    "workflow/explore.md": [
        "# Explore", "## When explore is required", "## The seven steps",
        "## Files", "## Freeze", "## Isolation from production code"],
    "workflow/architect.md": [
        "# Architect", "## Three ways to start", "## Stages",
        "## Design review by a second model", "## Compile", "## Author gate"],
    "workflow/backlog.md": [
        "# Backlog", "## What a slice holds", "## Add a slice",
        "## Context cost", "## Split proposals",
        "## Statements without a slice"],
    "workflow/build.md": [
        "# Build", "## One command starts a slice", "## The red record",
        "## Context injection", "## Gates on each edit",
        "## The permission layer", "## Composing with superpowers"],
    "workflow/review.md": [
        "# Review", "## The forked reviewer", "## Four layers",
        "## The findings contract", "## Park and adjudicate"],
    "workflow/close.md": [
        "# Close", "## Close checks",
        "## Drift acknowledgements and overrides", "## What close writes",
        "## Promote memory"],
    "workflow/land.md": [
        "# Land", "## Local mode", "## Pull request mode",
        "## Re-land after a failure", "## Update a slice branch",
        "## Egress permits"],
    "verification.md": [
        "# Verification", "## Statements", "## Test links",
        "## The red record", "## Close checks", "## Acceptance command",
        "## The closed-slice suite", "## Verification skill",
        "## Slices from before 0.10"],
    "decision-cards.md": [
        "# Decision cards", "## When to write a card", "## Card format",
        "## Rules", "## From card to decision row",
        "## Decision rows and ADRs"],
    "memory.md": [
        "# Memory", "## Personal memory", "## Shared memory",
        "## Promote a fact", "## Guards", "## Upgrading from 0.9"],
})

# Task 5: Extending, Internals and Upgrading.
REQUIRED_HEADINGS.update({
    "extending/extra-gates.md": [
        "# Repo-local gates", "## Declare a gate", "## The gate context",
        "## Cite a non-goal", "## Failure modes", "## Gates in CI",
        "## Exempt paths"],
    "extending/hosts.md": [
        "# Other hosts", "## The five-event contract", "## Write an adapter",
        "## Conformance tests", "## Degraded mode", "## Host matrix",
        "## Codex"],
    "extending/contracts.md": [
        "# Contracts recipe", "## Why contracts left core",
        "## A contract gate", "## A CI linter instead"],
    "internals.md": [
        "# Internals", "## Engine layout", "## Event flow",
        "## Verdicts and findings", "## Sidecar state", "## Fail closed",
        "## Tests", "## Change the engine", "## Build the docs"],
    "upgrading.md": [
        "# Upgrading 0.9 to 0.10", "## Before you start", "## Run the upgrade",
        "## What upgrade changes", "## Renamed and removed",
        "## Slices in flight", "## Check the result"],
})


@pytest.mark.parametrize("page", sorted(REQUIRED_HEADINGS))
def test_page_has_required_headings(page):
    lines = (DOCS / page).read_text().splitlines()
    missing = [h for h in REQUIRED_HEADINGS[page] if h not in lines]
    assert not missing, f"docs/{page} lacks {missing}"


@pytest.mark.parametrize("page", sorted(REQUIRED_HEADINGS))
def test_page_passes_lint_text(page):
    from engine.lint_text import lint_paths
    findings = lint_paths([DOCS / page], _glossary())
    assert findings == [], "\n".join(
        f"{f['path']}:{f['line']}: {f['rule']}: {f['text']}"
        for f in findings)


def test_trade_offs_names_the_limits_a_reader_must_know():
    text = (DOCS / "trade-offs.md").read_text()
    for needle in ("kills:", "G3", "G9", "lint-text", "fail", "sandbox",
                   "--body-file", "CONTEXT_OVER_CAP", "legacy",
                   "Cursor CLI",
                   # W7-P10: residuals carried from W3-W6
                   "G10", "memory/shared", "ask", "write-deny",
                   "python3 -m engine.cli memory promote", "importlib",
                   "JUnit", "--skip-explore", "--from-spec",
                   "gates explain", "gates.extra"):
        assert needle in text, needle


def test_trade_offs_states_the_shared_memory_gaps():
    """Fix round 1: G10 scope, the host permit gap, the glob residual."""
    text = (DOCS / "trade-offs.md").read_text()
    for needle in ("G10 sees only edit-tool writes",
                   "a human who reads the committed diff",
                   "Only the Claude Code hook runs the permit layer on shell",
                   "`.claude/memory/sh*/a.md`",
                   "sandbox.filesystem.denyWrite"):
        assert needle in text, needle


def test_home_names_every_builtin_gate():
    """W7-P2: the Home page lists the gates the engine ships."""
    from engine.gates import builtin_gates
    text = (DOCS / "index.md").read_text()
    for gate in builtin_gates():
        assert re.search(rf"\b{gate.GATE['id']}\b", text), gate.GATE["id"]


FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CMD = re.compile(r"`harness ([a-z][a-z-]*)")
FENCED_CMD = re.compile(r"^\s*(?:\$\s+)?harness ([a-z][a-z-]*)")
SLASH = re.compile(r"/harness:([a-z][a-z-]*)")
# a line that tells the reader a name is gone may name it
HISTORY = re.compile(r"\b(removed|renamed|replaced)\b", re.IGNORECASE)


def _command_mentions(text):
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if HISTORY.search(line):
            continue
        if in_fence:
            m = FENCED_CMD.match(line)
            if m:
                yield n, m.group(1)
        else:
            for m in INLINE_CMD.finditer(line):
                yield n, m.group(1)


def test_command_mentions_reads_inline_and_fenced_text():
    text = ("Run `harness verify`.\n```bash\nharness upgrade --dry-run\n```\n"
            "`harness run` was removed.\n")
    assert list(_command_mentions(text)) == [(1, "verify"), (3, "upgrade")]


def test_public_docs_name_real_commands():
    from engine.cli import COMMANDS
    bad = [f"{p.relative_to(PLUGIN_ROOT)}:{n}: harness {cmd}"
           for p in public_docs()
           for n, cmd in _command_mentions(p.read_text())
           if cmd not in COMMANDS]
    assert not bad, "unknown commands:\n" + "\n".join(bad)


def test_public_docs_name_real_skills():
    skills = {d.name for d in (PLUGIN_ROOT / "skills").iterdir()
              if (d / "SKILL.md").exists()}
    bad = [f"{p.relative_to(PLUGIN_ROOT)}:{n}: /harness:{m.group(1)}"
           for p in public_docs()
           for n, line in enumerate(p.read_text().splitlines(), 1)
           if not HISTORY.search(line)
           for m in SLASH.finditer(line)
           if m.group(1) not in skills]
    assert not bad, "unknown skills:\n" + "\n".join(bad)


def test_task4_pages_state_the_code_facts():
    """The facts where the code differs from the plan text (W7-P2..P9,
    P21): each page names the behavior the engine has today."""
    needles = {
        "concepts/lifecycle.md": ["max_close_attempts", "G10", "bind",
                                  "harness adjudicate"],
        "workflow/explore.md": ["frozen_digest", "re-freeze", "user.name"],
        "workflow/architect.md": ["supersedes", "keeps its stage",
                                  "--force", "[open-question]"],
        "workflow/build.md": ["runner_error", "is not a test.",
                              "never overwritten"],
        "workflow/review.md": ["/harness:harness", "decided_by"],
        "verification.md": ["red_timeout", "runner error", "GREEN_AT_START",
                            "verification:green-at-start", "KILLS_MISSING",
                            "comma or space"],
        "decision-cards.md": ["(recommended)", "**Domain:**",
                              "explain more about X", "delegated:"],
        "memory.md": ["legacy-memory", "G10", "ask",
                      "sandbox.filesystem.denyWrite"],
    }
    missing = [f"{page}: {n}" for page, ns in needles.items()
               for n in ns if n not in (DOCS / page).read_text()]
    assert not missing, missing


def _python_blocks(text):
    return re.findall(r"```python\n(.*?)```", text, re.DOTALL)


def test_contract_recipe_gate_is_valid_python(tmp_path):
    """The recipe must run: a reader copies it into .harness/gates/."""
    blocks = _python_blocks((DOCS / "extending" / "contracts.md").read_text())
    assert blocks, "contracts recipe has no python block"
    namespace = {}
    exec(compile(blocks[0], "contracts-recipe", "exec"), namespace)
    gate = namespace["GATE"]
    assert gate["id"] == "API1" and "unit_complete" in gate["preferred"]

    class Ctx:
        root = tmp_path

        def touched_files(self):
            return ["contracts/api.yaml"]

        def rel(self, p):
            return p

    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "api.yaml").write_text(
        "openapi: 3.1.0\npaths:\n  /orders:\n    get: {}\n")
    findings = namespace["run"](Ctx())
    assert [f["code"] for f in findings] == ["CONTRACT_NO_OPERATION_ID"]


def test_extra_gate_example_loads_through_the_engine(tmp_path):
    """W7-P20: the Declare a gate example passes the real loader."""
    from engine.gates import reserved_gate_ids
    from engine.gates.extra import load_extra_gates, run_gate
    blocks = _python_blocks(
        (DOCS / "extending" / "extra-gates.md").read_text())
    assert blocks, "extra-gates page has no python block"
    (tmp_path / ".harness" / "gates").mkdir(parents=True)
    (tmp_path / ".harness" / "gates" / "example.py").write_text(blocks[0])
    config = {"gates": {"extra": [".harness/gates/example.py"]}}
    gates, errors = load_extra_gates(tmp_path, config,
                                     reserved_ids=reserved_gate_ids())
    assert errors == [] and len(gates) == 1

    class Ctx:
        root = tmp_path

        def touched_files(self):
            return []

        def rel(self, p):
            return p

    assert run_gate(gates[0], Ctx()) == []


def test_upgrading_lists_every_registered_step():
    """W7-P11: the page names each step id and title from the code."""
    from engine.upgrade_010 import STEPS
    text = (DOCS / "upgrading.md").read_text()
    missing = [s.id for s in STEPS
               if f"`{s.id}`" not in text or s.title not in text]
    assert not missing, f"docs/upgrading.md lacks steps {missing}"


def test_task5_pages_state_the_code_facts():
    """W7-P11, W7-P20 and the Task 3 carry: the facts the code has now."""
    needles = {
        "extending/extra-gates.md": [
            "run(ctx)", "check(ctx)", "G2, G4, G7 and G8", ":ATTR",
            "EXTRA_GATE_LOAD_ERROR", "EXTRA_GATE_RUN_ERROR", "rule_ref",
            "harness compile", "advisory only", "G9"],
        "extending/hosts.md": [
            "346 lines", "afterFileEdit", "followup_message", "--root",
            "July 2026", "Exit 2"],
        "internals.md": [
            "500 lines or fewer", "40 lines or fewer", "check(ctx)",
            "build_parser()", "allow_with_findings", "started_at_commit"],
        "upgrading.md": [
            "--dry-run", "--yes", "check:", "legacy-memory",
            "git rm --cached", "harness init --migrate", "W8",
            "legacy_verification: true", "/harness:harness"],
    }
    missing = [f"{page}: {n}" for page, ns in needles.items()
               for n in ns if n not in (DOCS / page).read_text()]
    assert not missing, missing


def test_no_text_claims_cursor_reverts_edits():
    """Task 3 carry: Cursor only observes afterFileEdit; nothing reverts."""
    paths = [*public_docs(), PLUGIN_ROOT / "ADAPTERS.md",
             PLUGIN_ROOT / "engine" / "gates" / "__init__.py"]
    bad = [str(p.relative_to(PLUGIN_ROOT)) for p in paths
           if re.search(r"revert[- ]and[- ]retry", p.read_text(), re.I)]
    assert not bad, bad


# Task 6: harness's own glossary.
REQUIRED_HEADINGS["glossary.md"] = ["# Glossary"]

GLOSSARY_TERMS = (
    "slice", "substrate", "shadow", "gate", "finding", "decision row",
    "decision card", "statement", "red record", "explore", "toy", "non-goal",
    "override", "drift acknowledgement", "kills text", "shared memory",
    "verdict", "event", "rule reference", "binding", "park", "adjudication",
    "injection", "close", "landing", "ADR", "author gate", "acceptance suite",
    "regression suite", "permit", "STE-80")


def test_glossary_defines_each_core_term():
    text = (DOCS / "glossary.md").read_text()
    missing = [t for t in GLOSSARY_TERMS
               if not re.search(rf"^- {re.escape(t)} — ", text, re.MULTILINE)]
    assert not missing, missing


def test_glossary_synonyms_are_enforced(tmp_path):
    """Proves lint_text parses this file: a `not:` word in a page is flagged."""
    from engine.lint_text import lint_paths
    page = tmp_path / "page.md"
    page.write_text("Each ticket is small.\n")
    findings = lint_paths([page], DOCS / "glossary.md")
    assert any("ticket" in f["text"].lower() for f in findings), findings
