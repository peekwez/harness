"""D-0.10-13: the Reference pages come from the code, so they cannot drift.
Removing a gate removes it from the gates page in the same PR."""
import argparse
import importlib.util
import inspect
import json
import re

import pytest

from conftest import PLUGIN_ROOT

HOOK = PLUGIN_ROOT / "docs" / "hooks" / "reference.py"


@pytest.fixture(scope="module")
def hook():
    spec = importlib.util.spec_from_file_location("docs_reference_hook", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pages(hook):
    return hook.build_pages(PLUGIN_ROOT)


def _flatten(d, prefix=""):
    for key, value in d.items():
        if isinstance(value, dict) and value:
            yield from _flatten(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}"


def test_build_parser_covers_the_dispatch_table():
    from engine.cli import COMMANDS, build_parser
    parser = build_parser()
    assert parser.prog == "harness"
    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == set(COMMANDS)


def test_build_pages_returns_every_generated_page(hook, pages):
    assert set(pages) == set(hook.GENERATED_PAGES)
    for name, text in pages.items():
        assert text.startswith("# "), name


def test_cli_page_lists_every_subcommand(pages):
    from engine.cli import COMMANDS
    page = pages["reference/cli.md"]
    missing = [c for c in COMMANDS if f"`harness {c}`" not in page]
    assert not missing, f"CLI reference lacks: {missing}"


@pytest.mark.parametrize("nested", [
    "gates override", "gates ack-drift", "gates explain", "backlog add",
    "registry refresh", "memory promote", "graph note"])
def test_cli_page_lists_nested_subcommands(pages, nested):
    assert f"`harness {nested}`" in pages["reference/cli.md"]


def test_cli_page_documents_options(pages):
    page = pages["reference/cli.md"]
    assert "`--root`" in page
    assert "`--dry-run`" in page


def test_gates_page_lists_every_builtin_gate_and_no_removed_gate(pages):
    from engine.gates import builtin_gates
    page = pages["reference/gates.md"]
    ids = {g.GATE["id"] for g in builtin_gates()}
    assert ids == {"G1", "G3", "G5", "G6", "G9", "G10"}
    for gid in ids:
        assert f"\n## {gid}\n" in page, gid
    for gone in ("G2", "G4", "G7", "G8"):
        assert f"## {gone}\n" not in page, gone


def test_gates_page_carries_each_module_docstring(pages):
    from engine.gates import builtin_gates
    page = pages["reference/gates.md"]
    for gate in builtin_gates():
        first = inspect.getdoc(gate).split("\n\n")[0]
        assert " ".join(first.split()).replace("|", "\\|") in page, first


def test_config_page_lists_every_default_key(pages):
    from engine import DEFAULT_CONFIG
    page = pages["reference/config.md"]
    missing = [k for k in _flatten(DEFAULT_CONFIG) if f"`{k}`" not in page]
    assert not missing, missing
    assert "```yaml" in page   # the annotated template
    assert "only in the annotated template" in page   # W7-P23


def test_template_only_sentence_is_computed(hook, pages):
    """Final review: the sentence names template keys minus the defaults."""
    from engine import DEFAULT_CONFIG
    template = (PLUGIN_ROOT / "templates" / "harness.yaml").read_text()
    defaults = set(_flatten(DEFAULT_CONFIG))
    only = [k for k in hook.template_keys(template) if k not in defaults
            and not any(d.startswith(k + ".") for d in defaults)]
    line = next(ln for ln in pages["reference/config.md"].splitlines()
                if "only in the annotated template" in ln)
    for key in ("gates.extra", "gates.degraded_mode", "acceptance.cmd",
                "landing.mode", "run.max_close_attempts",
                "review.run_at_close", "gates.regression_at_close"):
        assert key in only, key
    assert all(f"`{k}`" in line for k in only), line
    assert "`gates.g3_mode`" not in line
    assert "`languages`" not in line   # a default section, not a new key


def test_template_is_valid_yaml():
    import yaml
    text = (PLUGIN_ROOT / "templates" / "harness.yaml").read_text()
    doc = yaml.safe_load(text.replace("{{languages}}", "  python: true"))
    assert doc["schema"] == 1 and "gates" in doc


# A config read in the engine: `config.get("a"...).get("b"`,
# `config["a"].get("b"`, `(config or {}).get("a")`, and so on. Each quoted
# key after the first `config` on the line is one more dotted segment.
# The first step must follow `config` at once: `f(config, x.get("id"))`
# passes config on and reads no key.
_CONFIG_READ = re.compile(
    r"\bconfig\b(\s*(?:or \{\}\))?\s*(?:\.get\(|\[)\s*[\"']\w+[\"'].*)")
_KEY_STEP = re.compile(r"(?:\.get\(|\[)\s*[\"'](\w+)[\"']")
# `name = <config read of section S>` makes `name.get("k")` read S.k
_ALIAS = re.compile(r"^\s*(\w+) = .*\bconfig\b.*\.get\(\s*[\"'](\w+)[\"']\)")
# helper accessors: the call returns one config section
_HELPERS = {"_acceptance_block(config)": "acceptance",
            "landing_config(config)": "landing"}
# keys read without a literal at the call site; each names its reason
_NOT_STATIC = {
    # landing.py validates every key against LANDING_DEFAULTS
    "landing": ["landing." + k for k in ("mode", "remote", "base", "pr_cmd")],
}


def engine_config_reads() -> set:
    keys = set()
    for path in sorted((PLUGIN_ROOT / "engine").rglob("*.py")):
        aliases = {}
        for line in path.read_text().splitlines():
            code = line.split("#", 1)[0]
            alias = _ALIAS.match(code)
            if alias and alias.group(1) != "config":
                aliases[alias.group(1)] = alias.group(2)
            for helper, section in _HELPERS.items():
                for m in re.finditer(re.escape(helper)
                                     + r"(?:\.get\(|\[)\s*[\"'](\w+)", code):
                    keys.add(f"{section}.{m.group(1)}")
            for name, section in aliases.items():
                for m in re.finditer(rf"\b{name}\.get\(\s*[\"'](\w+)", code):
                    keys.add(f"{section}.{m.group(1)}")
            found = _CONFIG_READ.search(code)
            if found:
                keys.add(".".join(_KEY_STEP.findall(found.group(1))))
    for extra in _NOT_STATIC.values():
        keys.update(extra)
    return keys


def test_every_engine_config_read_is_on_the_config_page(pages):
    """Final review: a key the engine reads is a key the page documents."""
    page = pages["reference/config.md"]
    reads = engine_config_reads()
    assert {"run.max_close_attempts", "gates.regression_at_close",
            "review.run_at_close", "gates.degraded_mode",
            "acceptance.gate_cmd"} <= reads, reads
    missing = sorted(k for k in reads
                     if f"`{k}`" not in page
                     and not ("." not in k and f"`{k}." in page))
    assert not missing, missing


def test_findings_page_lists_every_catalog_code(pages):
    from engine.findings import CATALOG
    assert CATALOG
    page = pages["reference/findings.md"]
    missing = [c for c in CATALOG if f"`{c}`" not in page]
    assert not missing, missing


def test_hooks_page_lists_every_host_and_engine_event(pages):
    from engine.events import EVENTS
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    page = pages["reference/hooks.md"]
    for name in hooks["hooks"]:
        assert f"`{name}`" in page, name
    for name in EVENTS:
        assert f"`{name}`" in page, name


def test_file_formats_page_lists_each_schema_field(pages):
    from engine.schema import SCHEMAS
    page = pages["reference/file-formats.md"]
    assert "`.harness/verify.jsonl`" in page
    for filename, spec in SCHEMAS.items():
        assert f"`.harness/{filename}`" in page
        for field, _type, _required in spec["fields"]:
            assert f"`{field}`" in page, (filename, field)


def test_changelog_page_is_the_changelog_file(pages):
    assert pages["changelog.md"] == (PLUGIN_ROOT / "CHANGELOG.md").read_text()


def test_table_cells_escape_pipes(hook):
    table = hook._table(["a"], [["x|y"]]).splitlines()
    assert table[2] == "| x\\|y |"


def test_help_with_percent_default_is_formatted(hook):
    parser = argparse.ArgumentParser(prog="t")
    parser.add_argument("--doc", default="docs/a.md",
                        help="doc (default: %(default)s)")
    parser.add_argument("base", help="driver (%%O %%A %%B)")
    helps = [row[-1] for row in hook._arguments(parser)]
    assert "doc (default: docs/a.md)" in helps
    assert "driver (%O %A %B)" in helps


def test_gate_title_is_the_whole_first_paragraph(pages):
    from engine.gates import builtin_gates
    g5 = next(g for g in builtin_gates() if g.GATE["id"] == "G5")
    assert "similarity threshold vs registry signature_digests." in \
        pages["reference/gates.md"]
    assert inspect.getdoc(g5).split("\n\n")[0].count("\n") == 1


def test_file_formats_prose_passes_the_text_lint():
    import subprocess
    import sys
    out = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "bin" / "harness"), "lint-text",
         "--glossary", str(PLUGIN_ROOT / "templates" / "glossary.md"),
         str(HOOK.parent / "file-formats.md")],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
