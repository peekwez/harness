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


def test_home_names_every_builtin_gate():
    """W7-P2: the Home page lists the gates the engine ships."""
    from engine.gates import builtin_gates
    text = (DOCS / "index.md").read_text()
    for gate in builtin_gates():
        assert re.search(rf"\b{gate.GATE['id']}\b", text), gate.GATE["id"]
