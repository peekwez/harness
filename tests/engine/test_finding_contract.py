"""STE-80 finding contract (spec 9.2, 14 "#7"): every finding message has
25 words or fewer, every non-advisory finding carries a fix, and every
code has a catalog entry. Checked statically over every make_finding call
under engine/, so a call site that no test reaches is still checked."""
import ast

import pytest

from conftest import PLUGIN_ROOT
from engine.findings import CATALOG, MAX_MESSAGE_WORDS

DYNAMIC_CODE_FILES = {"engine/review/rubrics.py"}  # codes are rubric ids

# Files whose messages are not rewritten yet. Tasks 7-10 empty this set.
PENDING = {
    "engine/review/layer0.py",
    "engine/review/rubrics.py",
}


def _engine_files():
    return sorted(
        str(p.relative_to(PLUGIN_ROOT))
        for p in (PLUGIN_ROOT / "engine").rglob("*.py")
        if "make_finding(" in p.read_text(encoding="utf-8")
        and p.name != "events.py")


CHECKED = [f for f in _engine_files() if f not in PENDING]


def _module_strings(tree):
    out = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node.value.value
    return out


def _calls(rel):
    tree = ast.parse((PLUGIN_ROOT / rel).read_text(encoding="utf-8"))
    consts = _module_strings(tree)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "make_finding"):
            yield node, consts


def _arg(call, index, name):
    if len(call.args) > index:
        return call.args[index]
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _clip_limit(node):
    """clip_words(text) -> 25 words; clip_words(text, n) -> n; else None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "clip_words"):
        limit = _arg(node, 1, "limit")
        return limit.value if isinstance(limit, ast.Constant) else MAX_MESSAGE_WORDS
    return None


def message_words(node, consts):
    """Upper bound of the words in a message, or None when the expression
    is not a literal, a constant, an f-string or clip_words(...)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return None if "\n" in node.value else len(node.value.split())
    if isinstance(node, ast.Name) and node.id in consts:
        return len(consts[node.id].split())
    limit = _clip_limit(node)
    if limit is not None:
        return limit
    if isinstance(node, ast.JoinedStr):
        parts = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                if "\n" in part.value:
                    return None
                parts.append(part.value)
                continue
            value = part.value
            if isinstance(value, ast.Name) and value.id in consts:
                n = len(consts[value.id].split())
            else:
                n = _clip_limit(value) or 1
            parts.append(" " + " ".join(["X"] * n) + " ")
        return len("".join(parts).split())
    return None


def _where(rel, node):
    return f"{rel}:{node.lineno}"


@pytest.mark.parametrize("rel", CHECKED)
def test_messages_are_short(rel):
    bad = []
    for node, consts in _calls(rel):
        n = message_words(_arg(node, 2, "message"), consts)
        if n is None or n > MAX_MESSAGE_WORDS:
            bad.append(f"{_where(rel, node)}: {n} words")
    assert not bad, ("messages must be literal text, an f-string or "
                     "clip_words(...), with 25 words or fewer:\n"
                     + "\n".join(bad))


@pytest.mark.parametrize("rel", CHECKED)
def test_non_advisory_findings_carry_a_fix(rel):
    bad = []
    for node, _consts in _calls(rel):
        sev = _arg(node, 3, "severity")
        if sev is None or (isinstance(sev, ast.Constant)
                           and sev.value == "advisory"):
            continue
        fix = _arg(node, 8, "fix")
        if fix is None or (isinstance(fix, ast.Constant) and fix.value is None):
            bad.append(_where(rel, node))
    assert not bad, "pass fix= on these findings:\n" + "\n".join(bad)


@pytest.mark.parametrize("rel", CHECKED)
def test_codes_have_catalog_entries(rel):
    bad = []
    for node, consts in _calls(rel):
        first = _arg(node, 0, "code")
        if isinstance(first, ast.Subscript) and rel in DYNAMIC_CODE_FILES:
            continue
        if isinstance(first, ast.Constant):
            codes = {first.value}
        elif isinstance(first, ast.Name) and first.id in consts:
            codes = {consts[first.id]}
        else:
            codes = {n.value for n in ast.walk(first)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            if not codes:
                bad.append(f"{_where(rel, node)}: code is not a literal")
                continue
        bad.extend(f"{_where(rel, node)}: {c}" for c in codes
                   if c not in CATALOG)
    assert not bad, "add CATALOG entries in engine/findings.py:\n" + "\n".join(bad)


def test_pending_names_only_files_that_emit_findings():
    assert PENDING <= set(_engine_files())


def test_message_words_counts_fstrings_and_clipped_text():
    consts = {"REASON": "acceptance gate command failed"}
    expr = ast.parse(
        'f"{REASON} in {cwd!r}: {clip_words(cmd, 12)}"', mode="eval").body
    assert message_words(expr, consts) == 4 + 2 + 1 + 12
    assert message_words(ast.parse('"a\\nb"', mode="eval").body, {}) is None
    assert message_words(ast.parse("str(exc)", mode="eval").body, {}) is None


def _error_classes(trees):
    """HarnessError plus every class in engine/ that subclasses it,
    transitively."""
    names = {"HarnessError"}
    changed = True
    while changed:
        changed = False
        for tree in trees.values():
            for node in ast.walk(tree):
                if (isinstance(node, ast.ClassDef) and node.name not in names
                        and any(isinstance(b, ast.Name) and b.id in names
                                for b in node.bases)):
                    names.add(node.name)
                    changed = True
    return names


def _error_words(node, consts):
    """Words in an error message: literals, constants, f-strings and `+`
    joins of those. None when the expression cannot be evaluated."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value.split())
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        # A dynamic operand (str(x), "; ".join(...)) counts as one word,
        # like an f-string placeholder.
        left = _error_words(node.left, consts)
        right = _error_words(node.right, consts)
        return (1 if left is None else left) + (1 if right is None else right)
    if isinstance(node, ast.IfExp):
        return max(_error_words(node.body, consts) or 0,
                   _error_words(node.orelse, consts) or 0)
    if isinstance(node, ast.JoinedStr):
        # message_words rejects newlines; errors may have them, so count
        # the f-string pieces directly.
        text = ""
        for part in node.values:
            if isinstance(part, ast.Constant):
                text += part.value
                continue
            value = part.value
            n = (len(consts[value.id].split())
                 if isinstance(value, ast.Name) and value.id in consts
                 else _clip_limit(value) or 1)
            text += " " + " ".join(["X"] * n) + " "
        return len(text.split())
    return message_words(node, consts)


def _error_inventory():
    trees = {p: ast.parse(p.read_text(encoding="utf-8"))
             for p in sorted((PLUGIN_ROOT / "engine").rglob("*.py"))}
    classes = _error_classes(trees)
    long, unevaluated = [], []
    for p, tree in trees.items():
        consts = _module_strings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args
                    and isinstance(node.func, ast.Name)
                    and node.func.id in classes):
                continue
            where = f"{p.relative_to(PLUGIN_ROOT)}:{node.lineno}"
            n = _error_words(node.args[0], consts)
            if n is None:
                unevaluated.append(f"{where}: {node.func.id}")
            elif n > MAX_MESSAGE_WORDS:
                long.append(f"{where}: {node.func.id} {n} words")
    return long, unevaluated


def test_error_string_inventory_is_report_only(capsys):
    """W4-11: HarnessError (and subclass) messages over 25 words. W8
    rewrites them. This test reports the inventory and never fails."""
    long, unevaluated = _error_inventory()
    with capsys.disabled():
        print(f"\n[inventory] {len(long)} long error messages in engine/")
        for line in long:
            print("  " + line)
        print(f"[inventory] {len(unevaluated)} unevaluated error messages")
        for line in unevaluated:
            print("  unevaluated " + line)
    if long or unevaluated:
        pytest.xfail(f"{len(long)} long, {len(unevaluated)} unevaluated "
                     "error messages (report-only)")


def test_make_finding_is_only_called_by_name():
    """The call-site matcher looks for Name calls; keep it honest."""
    bad = []
    for p in sorted((PLUGIN_ROOT / "engine").rglob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "make_finding"):
                bad.append(f"{p.relative_to(PLUGIN_ROOT)}:{node.lineno}: attribute call")
            if (isinstance(node.func, ast.Name) and node.func.id == "make_finding"
                    and any(k.arg is None for k in node.keywords)):
                bad.append(f"{p.relative_to(PLUGIN_ROOT)}:{node.lineno}: **kwargs")
    assert not bad, "\n".join(bad)
