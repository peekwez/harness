"""Layer 0 — deterministic fact assembly.

Gate outputs, uses/declares diff, duplicate candidates, decision rows in
scope, shadows of everything the diff imports. No model, no judgment.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import get_slice, load_decisions
from ..extractor import engine as _ex
from ..extractor.engine import LANG_BY_EXT, RegistryIndex, shadow_for
from ..graph import uses_vs_declares
from ..registry import load_registry


def diff_files(diff_text: str) -> list:
    files = []
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff_text or "", re.M):
        files.append(m.group(1))
    for m in re.finditer(r"^diff --git a/(\S+) b/(\S+)$", diff_text or "", re.M):
        if m.group(2) not in files:
            files.append(m.group(2))
    return files


# Deterministic secret patterns over ADDED diff lines. Deliberately narrow:
# a false-positive storm teaches agents to override reflexively. Findings
# never echo the matched text — a report that repeats the secret IS a leak.
SECRET_PATTERNS = (
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("assigned-credential", re.compile(
        r"(?i)\b(api[_-]?key|secret|token|passw(?:or)?d)\b[\"']?\s*[:=]"
        r"\s*[\"'][A-Za-z0-9+/_\-]{16,}[\"']")),
)


def _secret_findings(root, diff_text, slice_id):
    """Layer-0 secret scan (the seed-leak class, caught deterministically on
    every slice — not only when a fork reviewer runs). A recorded override
    edge `secret:<file>` downgrades a named false positive, auditable."""
    from ..events import make_finding
    from ..graph import load_edges
    findings, current = [], None
    overridden = {e["to"].split(":", 1)[-1] for e in load_edges(root)
                  if e["from"] == f"slice:{slice_id}"
                  and e["type"] == "override" and e["to"].startswith("secret:")}
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                sev = "advisory" if current in overridden else "block"
                where = current or "<unknown file>"
                if sev == "advisory":
                    findings.append(make_finding(
                        "SECRET_IN_DIFF", "review:layer0",
                        f"{where}: an added line matches the {label} pattern; "
                        f"a recorded override accepts it.",
                        severity="advisory", key=f"{current}|{label}"))
                else:
                    findings.append(make_finding(
                        "SECRET_IN_DIFF", "review:layer0",
                        f"{where}: an added line matches the {label} secret "
                        f"pattern.",
                        severity="block", key=f"{current}|{label}",
                        fix=f"Remove the secret, or record a false positive: "
                            f"harness gates override --slice {slice_id} "
                            f"--target secret:{current} --rule-ref "
                            f"review:layer0 --justification \"<why>\""))
                break
    return findings


_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _added_lines(diff_text):
    """{path: set of new-file line numbers added by the diff}.

    Hunk line counts decide where a hunk ends, so a `+++ ` line inside a
    hunk is an added line, not a file header. A deleted file
    (`+++ /dev/null`) adds nothing.
    """
    out, path, new_no, old_left, new_left = {}, None, 0, 0, 0
    for line in (diff_text or "").splitlines():
        if old_left > 0 or new_left > 0:
            tag = line[:1]
            if tag == "+":
                if path:
                    out.setdefault(path, set()).add(new_no)
                new_no += 1
                new_left -= 1
                continue
            if tag == "-":
                old_left -= 1
                continue
            if tag == " " or line == "":
                new_no += 1
                new_left -= 1
                old_left -= 1
                continue
            if tag == "\\":
                continue
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            continue
        m = _HUNK.match(line)
        if m:
            old_left = int(m.group(1) or 1)
            new_no = int(m.group(2))
            new_left = int(m.group(3) or 1)
    return out


def _glossary_findings(root, diff_text):
    """Advisory GLOSSARY_SYNONYM findings over added markdown lines.

    It runs the lint-text synonym scan on each changed markdown file's
    working-tree content, so fences, headings, tables, comments and front
    matter are skipped as lint-text skips them. Only a synonym on an added
    line counts. Each synonym is reported once per file.
    """
    from ..events import make_finding
    from ..lint_text import (GLOSSARY_PATH, _units, find_synonyms,
                             load_glossary)
    glossary = load_glossary(Path(root) / GLOSSARY_PATH)
    if not glossary:
        return []
    findings = []
    for path, added in _added_lines(diff_text).items():
        if not path.lower().endswith(".md") or path == GLOSSARY_PATH:
            continue
        try:
            text = (Path(root) / path).read_bytes().decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        seen = set()
        units, _ = _units(text.splitlines())
        for first, _kind, unit, last in units:
            if not added.intersection(range(first, last + 1)):
                continue
            for syn, term in find_synonyms(unit, glossary):
                if syn in seen:
                    continue
                seen.add(syn)
                findings.append(make_finding(
                    "GLOSSARY_SYNONYM", "review:layer0",
                    f"{path}: added text uses {syn!r}; the glossary term is "
                    f"{term!r}.",
                    severity="advisory", key=f"{path}|{syn}",
                    fix=f"Replace {syn!r} with {term!r}, or edit "
                        f"{GLOSSARY_PATH}."))
    return findings


def assemble(root, diff_text: str, slice_id: str, config: dict) -> dict:
    """Substrate + diff only. The reviewer never receives the builder's own
    notes — independent derivation from the same ground truth is the point."""
    root = Path(root)
    registry = load_registry(root)
    files = diff_files(diff_text)

    # gate outputs (post_change + unit_complete packs, dry over the diff files)
    from ..events import Sidecar
    from ..gates import run_gates
    sidecar = Sidecar(root)
    try:
        gate_findings = []
        for event_name in ("post_change", "unit_complete"):
            evt = {"event": event_name, "session_id": f"review:{slice_id}",
                   "work_unit_id": slice_id,
                   "payload": {"files": [{"path": f, "proposed_content_hash": None}
                                         for f in files],
                               "context_loaded": [], "diff": diff_text, "prompt": None,
                               # a dry run over a diff, not a tool edit: G10
                               # reads it (host events cannot carry this key)
                               "source": "review"}}
            gate_findings.extend(run_gates(root, evt, config, sidecar))
    finally:
        sidecar.close()
    gate_findings.extend(_secret_findings(root, diff_text, slice_id))
    gate_findings.extend(_glossary_findings(root, diff_text))

    ud = uses_vs_declares(root, slice_id)
    sl = get_slice(root, slice_id)
    domains = set()
    reg_by_id = {e["id"]: e for e in registry}
    index = RegistryIndex(registry)
    for did in sl.get("declares_dep", []):
        if did in reg_by_id:
            domains.add(reg_by_id[did].get("kind", "other"))
    decisions_in_scope = [d for d in load_decisions(root)
                          if d.get("domain") in domains]

    dup_candidates = [f for f in gate_findings if f["code"] == "DUPLICATE_CANDIDATE"]

    imported_shadows = {}
    from .. import HarnessError
    _ex.validate_shadow_config(config)       # loud, outside the catch below
    known_modules = _ex.python_module_ids(root, config)            # once
    ignored = _ex.git_ignored_set(
        root, list(files) + [e["source"] for e in registry if e.get("source")])
    kw = {"known_modules": known_modules, "ignored": ignored}
    for f in files:
        if Path(f).suffix.lower() not in LANG_BY_EXT:
            continue
        try:
            shadow = shadow_for(root, root / f, config, **kw)
        except HarnessError:
            continue
        if shadow is None:
            continue
        for imp in shadow.get("imports", []):
            # longest dotted prefix, like G5 and the resolver (D-008):
            # exact-id matching drops `telemetry.spans` -> `telemetry`
            entry = index.match(imp)
            if entry and entry.get("source"):
                dep = shadow_for(root, root / entry["source"], config, **kw)
                if dep is not None:
                    imported_shadows[imp] = dep

    return {
        "slice": slice_id,
        "diff_files": files,
        "gate_findings": gate_findings,
        "uses_declares": ud,
        "duplicate_candidates": dup_candidates,
        "decisions_in_scope": decisions_in_scope,
        "imported_shadows": {k: {"module_id": v["module_id"],
                                 "exports": v.get("exports"),
                                 "symbols": [s["signature"] for s in v.get("symbols", [])
                                             if s.get("visibility") == "public"]}
                             for k, v in sorted(imported_shadows.items())},
    }
