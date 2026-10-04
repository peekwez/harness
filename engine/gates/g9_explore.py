"""G9 explore-isolation: production code does not import from `explore/`.

A touched file outside `explore/` whose imports resolve to a file under
`explore/` is a block (spec 5.6). G9 runs at `post_change` and
`unit_complete`, and `harness verify` runs it over every file in scope.

Import sources:

- Python: the shadow from `shadow_for`. A module id that is `explore` or
  starts with `explore.` resolves into `explore/`.
- Rust: the source text. The shadow keeps only the text before a `{`, so
  it misses `use crate::{explore::toy, x}`. A path whose first module
  segment is `explore` resolves into `explore/`, in or out of a brace group.
- TypeScript, JavaScript and Go: the raw import strings from the source.
  The shadow keeps only the first segment (TypeScript) or the last
  segment (Go), so it cannot show the whole path.
  - TypeScript and JavaScript: a relative path is joined to the file's
    folder; a path that starts with `/` is read from the repo root; a bare
    path is read from the repo root (a `baseUrl: "."` setup).
  - Go: the import path starts with `<module>/explore`, where `<module>`
    comes from the nearest `go.mod` above the file.

G9 is active only when `explore/DECISIONS.md` exists, so a repo that never
ran `harness explore` sees no change.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path, PurePosixPath

from ..events import make_finding
from ..explore import EXPLORE_DIR, explore_active

GATE = {"id": "G9", "rule_ref": "gate:G9",
        "preferred": ("post_change", "unit_complete"), "fallback": ()}

G9_LANGS = {".py": "python", ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
            ".cjs": "javascript", ".go": "go", ".rs": "rust"}

_PY_FROM = re.compile(r"^\s*from\s+([\w.]+)\s+import\b", re.M)
_PY_IMPORT = re.compile(r"^\s*import\s+([\w.]+(?:\s+as\s+\w+)?"
                        r"(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)", re.M)
_RS_USE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;]+);", re.M)
_RS_CRATE = re.compile(r"^\s*extern\s+crate\s+(\w+)", re.M)
_JS_SPEC = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)"""
    r"""(['"])([^'"\n]+)\1""", re.M)
_GO_COMMENT = re.compile(r"//[^\n]*")
_GO_BLOCK = re.compile(r"^\s*import\s*\((.*?)\)", re.M | re.S)
_GO_SINGLE = re.compile(r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"', re.M)
_GO_PATH = re.compile(r'"([^"]+)"')
_GO_MODULE = re.compile(r"^\s*module\s+(\S+)", re.M)


# ------------------------------------------------------------------ readers
def _python_specs(text: str) -> list[str]:
    specs = [m.group(1) for m in _PY_FROM.finditer(text)]
    for m in _PY_IMPORT.finditer(text):
        specs += [part.split()[0] for part in m.group(1).split(",")]
    return specs


def _rust_split(text: str) -> list[str]:
    """Split on commas that sit outside nested braces."""
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def _rust_firsts(path: str) -> list[str]:
    """First module name of each path in a `use` tree, brace groups open."""
    path = "".join(path.split())
    if path.startswith("{") and path.endswith("}"):
        return [n for part in _rust_split(path[1:-1])
                for n in _rust_firsts(part)]
    prefix, brace, rest = path.partition("{")
    segments = [s for s in prefix.split("::") if s]
    while segments and segments[0] in ("crate", "self", "super"):
        segments.pop(0)
    if segments:
        return [segments[0]]
    if brace:
        return _rust_firsts("{" + rest)
    return []


def _rust_specs(text: str) -> list[str]:
    specs = []
    for m in _RS_USE.finditer(text):
        specs += _rust_firsts(m.group(1))
    specs += [m.group(1) for m in _RS_CRATE.finditer(text)]
    return specs


def _js_specs(text: str) -> list[str]:
    return [m.group(2) for m in _JS_SPEC.finditer(text)]


def _go_specs(text: str) -> list[str]:
    text = _GO_COMMENT.sub("", text)
    specs = [m.group(1) for m in _GO_SINGLE.finditer(text)]
    for block in _GO_BLOCK.finditer(text):
        specs += _GO_PATH.findall(block.group(1))
    return specs


READERS = {"python": _python_specs, "rust": _rust_specs,
           "typescript": _js_specs, "javascript": _js_specs,
           "go": _go_specs}


def import_specs(root, rel: str, config, *, in_scope: bool = False) -> tuple[str | None, list[str]]:
    """The language and import strings of one file.

    Args:
        root: Repo root.
        rel: Repo-relative POSIX path.
        config: Loaded engine config.
        in_scope: True when the caller listed `rel` from `scope_files`, so
            the per-file scope check (one `git check-ignore`) is skipped.

    Returns:
        (language, import strings). (None, []) for a file that G9 does not
        read: an unknown extension, a file outside shadow scope, or a
        deleted file.
    """
    from ..extractor.engine import in_shadow_scope, shadow_for
    lang = G9_LANGS.get(PurePosixPath(rel).suffix.lower())
    path = Path(root) / rel
    if lang is None or not path.is_file():
        return None, []
    if not in_scope and not in_shadow_scope(root, rel, config):
        return None, []
    if lang == "python":
        shadow = shadow_for(root, path, config,
                            ignored=set() if in_scope else None)
        if shadow is not None and shadow.get("language") == lang:
            return lang, list(shadow.get("imports", []))
        # no shadow (language off) or a degenerate one (no tree-sitter):
        # read the source, so G9 never passes in silence
    text = path.read_text(encoding="utf-8", errors="replace")
    return lang, READERS[lang](text)


# ------------------------------------------------------------------ resolution
def go_explore_prefix(root, rel: str) -> str | None:
    """`<module>/explore` for the nearest `go.mod` above `rel`, or None."""
    root = Path(root).resolve()
    explore = root / EXPLORE_DIR
    folder = (root / rel).parent
    while True:
        gomod = folder / "go.mod"
        if gomod.is_file():
            m = _GO_MODULE.search(gomod.read_text(encoding="utf-8",
                                                  errors="replace"))
            if not m:
                return None
            try:
                sub = explore.relative_to(folder).as_posix()
            except ValueError:
                return None  # explore/ is outside this Go module
            return f"{m.group(1)}/{sub}"
        if folder == root or folder.parent == folder:
            return None
        folder = folder.parent


def resolves_into_explore(root, rel: str, lang: str, spec: str,
                          go_prefix: str | None = None) -> bool:
    """True when import `spec` in file `rel` names code under `explore/`."""
    if lang == "python":
        return spec == EXPLORE_DIR or spec.startswith(EXPLORE_DIR + ".")
    if lang == "rust":
        return EXPLORE_DIR in _rust_firsts(spec)
    if lang in ("typescript", "javascript"):
        if spec.startswith("."):
            target = posixpath.join(posixpath.dirname(rel), spec)
        elif spec.startswith("/"):
            try:
                target = Path(spec).relative_to(
                    Path(root).resolve()).as_posix()
            except ValueError:
                target = spec.lstrip("/")
        else:
            target = spec
        target = posixpath.normpath(target)
        return target == EXPLORE_DIR or target.startswith(EXPLORE_DIR + "/")
    if lang == "go":
        return bool(go_prefix) and (spec == go_prefix
                                    or spec.startswith(go_prefix + "/"))
    return False


def file_findings(root, rel: str, config, *, in_scope: bool = False) -> list:
    """G9 findings for one repo-relative file.

    `in_scope`: the file came from `scope_files`; skip the scope check."""
    from . import exempt
    rel = PurePosixPath(rel).as_posix()
    if rel == EXPLORE_DIR or rel.startswith(EXPLORE_DIR + "/") \
            or exempt(rel, config):
        return []
    lang, specs = import_specs(root, rel, config, in_scope=in_scope)
    if lang is None:
        return []
    go_prefix = go_explore_prefix(root, rel) if lang == "go" else None
    findings = []
    for spec in sorted(set(specs)):
        if not resolves_into_explore(root, rel, lang, spec, go_prefix):
            continue
        findings.append(make_finding(
            "EXPLORE_IMPORT", GATE["rule_ref"],
            f"G9: {rel} imports {spec}, which is toy code in explore/. "
            f"Production code must not import explore/.",
            severity="block", key=f"{rel}|{spec}",
            fix="Copy the code you need out of explore/. Import the copy."))
    return findings


# ------------------------------------------------------------------ entry points
def check(ctx) -> list:
    if not explore_active(ctx.root):
        return []
    touched = [ctx.rel(p) for p in ctx.touched_files()]
    if not touched and ctx.work_unit_id:
        touched = sorted(ctx.sidecar.touched_paths(slice_id=ctx.work_unit_id))
    findings = []
    for rel in touched:
        if Path(rel).is_absolute():
            continue  # out-of-root rows: never a crash
        findings.extend(file_findings(ctx.root, rel, ctx.config))
    return findings


def explore_findings(root, config) -> list:
    """G9 over every file in scope, for `harness verify`."""
    if not explore_active(root):
        return []
    from ..extractor.engine import scope_files
    findings = []
    for rel in scope_files(root, config):
        if PurePosixPath(rel).suffix.lower() in G9_LANGS:
            findings.extend(file_findings(root, rel, config, in_scope=True))
    return findings
