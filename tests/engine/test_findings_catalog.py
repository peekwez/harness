"""Spec 9.2: make_finding(fix=), the finding catalog, `gates explain`."""
import pytest

from conftest import run_cli
from engine.events import (FINDING_CODES, VerdictError, make_finding,
                           validate_finding)
from engine.findings import CATALOG, MAX_MESSAGE_WORDS, clip_words, explain
from engine.lint_text import lint_text

MSG = "rogue.py is outside the declared files of slice slice-042."


def test_make_finding_carries_the_fix():
    f = make_finding("UNDECLARED_FILE", "gate:G3", MSG, key="k",
                     fix="Add rogue.py to predicted_files.")
    assert f["fix"] == "Add rogue.py to predicted_files."
    validate_finding(f)


def test_fix_defaults_to_none():
    assert make_finding("UNDECLARED_FILE", "gate:G3", MSG)["fix"] is None


def test_the_fix_does_not_change_the_finding_id():
    a = make_finding("UNDECLARED_FILE", "gate:G3", MSG, key="k")
    b = make_finding("UNDECLARED_FILE", "gate:G3", MSG, key="k", fix="Do X.")
    assert a["finding_id"] == b["finding_id"]


def test_validate_rejects_an_empty_or_non_string_fix():
    for bad in ("", "   ", 3):
        f = make_finding("UNDECLARED_FILE", "gate:G3", MSG)
        f["fix"] = bad
        with pytest.raises(VerdictError, match="fix"):
            validate_finding(f)


def test_validate_rejects_an_empty_message():
    f = make_finding("UNDECLARED_FILE", "gate:G3", "")
    with pytest.raises(VerdictError, match="message"):
        validate_finding(f)


def test_validate_accepts_a_finding_without_a_fix_key():
    """A repo-local gates.extra gate may build its dict by hand."""
    f = make_finding("NAMESPACE_CAPTURE", "adr:002", MSG, severity="block")
    del f["fix"]
    validate_finding(f)


def test_clip_words_keeps_the_word_limit():
    text = " ".join(f"w{i}" for i in range(40))
    clipped = clip_words(text)
    assert len(clipped.split()) == MAX_MESSAGE_WORDS
    assert clipped.endswith("…")
    assert clip_words("a b c", 2) == "a b…"
    assert clip_words("a  b\nc") == "a b c"


def test_finding_codes_is_the_catalog():
    assert FINDING_CODES == frozenset(CATALOG)


def test_every_catalog_entry_passes_lint_text():
    for code, text in CATALOG.items():
        assert lint_text(text + "\n", code) == [], code


def test_explain_matches_without_regard_to_case():
    assert explain("undeclared_file").startswith("UNDECLARED_FILE\n\n")
    assert explain("r-uses").startswith("R-uses\n\n")
    assert explain("NO_SUCH_CODE") is None


def test_gates_explain_prints_the_entry():
    proc = run_cli("gates", "explain", "UNDECLARED_FILE")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("UNDECLARED_FILE\n\n")
    assert CATALOG["UNDECLARED_FILE"] in proc.stdout


def test_gates_explain_unknown_code_suggests_close_matches():
    proc = run_cli("gates", "explain", "UNDECLARED_FIEL")
    assert proc.returncode == 1
    assert "UNDECLARED_FILE" in proc.stderr


def _emitted_codes():
    """Every code a make_finding call site can emit, found by a static scan."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "engine"
    codes, unresolved = set(), []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        consts = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                consts[node.targets[0].id] = node.value.value
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args
                    and getattr(node.func, "id", getattr(
                        node.func, "attr", None)) == "make_finding"):
                continue
            found = set()
            keys = {id(s.slice) for s in ast.walk(node.args[0])
                    if isinstance(s, ast.Subscript)}
            for sub in ast.walk(node.args[0]):
                if id(sub) in keys:
                    continue
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    found.add(sub.value)
                elif isinstance(sub, ast.Name) and sub.id in consts:
                    found.add(consts[sub.id])
            if not found:
                unresolved.append(f"{path.name}:{node.lineno}")
            codes |= found
    return codes, unresolved


def test_every_emitted_code_has_a_catalog_entry():
    codes, unresolved = _emitted_codes()
    assert len(codes) > 20
    assert not set(codes) - set(CATALOG), set(codes) - set(CATALOG)
    # the only call sites without a literal code: review rubric ids, and
    # `review --record-finding` (args.code with literal defaults)
    assert all(u.startswith("rubrics.py") for u in unresolved), unresolved


def test_every_review_rubric_id_has_a_catalog_entry():
    import re
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2]
            / "engine/review/rubrics.py").read_text()
    ids = set(re.findall(r'"id": "(R-[\w-]+)"', text))
    assert ids and not ids - set(CATALOG), ids - set(CATALOG)
