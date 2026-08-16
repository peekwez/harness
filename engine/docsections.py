"""Typed sections in the Phase-0 working document (ADR-002, row D-013).

Decision rows and abstractions may be authored in `docs/architecture.md`
inside fenced ```` ```harness-decisions ```` / ```` ```harness-abstractions ````
pipe tables instead of ADR frontmatter, so a repo that already owns a long
spec compiles it rather than re-deriving it Socratically. This module owns
the two directions of that seam:

- `parse_doc_blocks` reads the tables (fail closed: a malformed row names the
  document and the line);
- `merge_doc_blocks` folds them into the compiler's in-flight substrate maps
  (an id claimed by both an ADR and the doc is a hard error naming both);
- `seed_doc_from_spec` writes the initial document from an existing spec.

It stays out of `compiler.py` to keep every module readable whole.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import HarnessError

#: `created` placeholder the scaffold writes; never propagated (see compiler).
EPOCH_PREFIX = "1970-"

DECISION_COLUMNS = ("id", "domain", "question", "answer", "adr_ref", "security")
#: the canonical abstraction header. `source`/`module_id` are what let a
#: doc-authored abstraction ever flip planned -> built: without one of them
#: the resolver never injects its shadow and G5 only matches an import whose
#: dotted name happens to equal the entry id (ADR-002 / D-013, D-008).
ABSTRACTION_COLUMNS = ("id", "kind", "guidance_ref", "source", "module_id")
#: the 0.7 three-column header, still accepted verbatim
ABSTRACTION_COLUMNS_V1 = ("id", "kind", "guidance_ref")
#: fence info string -> (result key, accepted column tuples, required columns).
#: The first tuple is canonical; the rest are back-compatible headers, and a
#: row is matched to the variant with its column count.
BLOCKS = {
    "harness-decisions": ("decisions", (DECISION_COLUMNS,),
                          ("id", "domain", "answer")),
    "harness-abstractions": ("abstractions",
                             (ABSTRACTION_COLUMNS, ABSTRACTION_COLUMNS_V1),
                             ("id", "kind")),
}
DECISIONS_TABLE_HEADER = ("| " + " | ".join(DECISION_COLUMNS) + " |",
                          "| " + " | ".join(["---"] * len(DECISION_COLUMNS)) + " |")

_TRUTHY = {"true", "yes", "y", "x", "1", "✓"}
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*(\S*)")
_SEPARATOR_CELL = re.compile(r"^:?-+:?$")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_TYPED_FENCE = re.compile(
    r"^\s*(?:`{3,}|~{3,})\s*harness-(?:decisions|abstractions)\b", re.M)
_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*#*\s*$")
_LIST_MARKER = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)]|>)\s+)*")
_QUESTION = re.compile(r"^(?:todo\b|tbd\b|open:)", re.I)
_SEED_HEADER = "# Architecture — seeded from {spec}"
_STAGE_MARKER = "<!-- stage: 3 -->"
_NO_SUMMARY = "(no summary)"


def mentions_typed_blocks(text: str) -> bool:
    """True if the text opens a `harness-decisions`/`-abstractions` fence.

    A lexical scan, never a parse: `compile` uses it only to warn that
    `--doc` was omitted, and a malformed table must not turn that warning
    into an error.
    """
    return bool(_TYPED_FENCE.search(text))


def doc_ref_for(root, working_doc) -> str:
    """Root-relative label for the working document, quoted in every error."""
    try:
        return str(Path(working_doc).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(working_doc)


def _headers(variants) -> str:
    """Human-readable list of the header rows a block accepts."""
    return " or ".join("'| " + " | ".join(v) + " |'" for v in variants)


def _cells(line: str) -> list:
    """Splits one pipe-table row into stripped cells (`\\|` is a literal)."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.replace("\\|", "|").strip() for c in _CELL_SPLIT.split(body)]


def _row(cells: list, spec, where: str) -> dict:
    """Validates one table row against a block's column spec.

    A block may accept more than one header (the abstraction table grew
    `source`/`module_id` in 0.8); the row is matched to the variant with its
    column count, so a three-column row keeps exactly the three keys it
    always had.

    Args:
        cells: The row's stripped cell values.
        spec: The `(key, variants, required)` triple for the block.
        where: `"<doc>:<line>"`, quoted in every error.

    Returns:
        The row as a dict keyed by column name.

    Raises:
        HarnessError: No accepted header has this column count, or a
            required cell was left empty.
    """
    _key, variants, required = spec
    columns = next((v for v in variants if len(v) == len(cells)), None)
    if columns is None:
        expected = " or ".join(f"{len(v)} ({' | '.join(v)})" for v in variants)
        raise HarnessError(
            f"{where}: table row has {len(cells)} columns, expected "
            f"{expected} — escape any literal "
            f"pipe in a cell as \\|: {' | '.join(cells)}")
    row = dict(zip(columns, cells))
    for col in required:
        if not row[col]:
            raise HarnessError(f"{where}: table row is missing {col!r}: "
                               f"{' | '.join(cells)}")
    return row


def parse_doc_blocks(text: str, source=None) -> dict:
    """Reads the working document's typed fenced tables.

    Tables nested inside a wider code fence are prose (a document may show
    the syntax without compiling it), and a `harness-*` block that is never
    closed is an error rather than a silently truncated table.

    Args:
        text: The whole working document.
        source: Path quoted in errors (default: a generic label).

    Returns:
        `{"decisions": [row, ...], "abstractions": [row, ...]}`; decision
        rows carry `adr_ref` (None when the cell is empty) and a boolean
        `security`.

    Raises:
        HarnessError: Malformed row, unknown header, or unterminated block.
    """
    doc = source or "the working document"
    out: dict = {"decisions": [], "abstractions": []}
    fence = None          # (marker, info, opened_at) while inside any fence
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _FENCE.match(line)
        if fence is None:
            if m:
                fence = (m.group(1), m.group(2), lineno)
            continue
        marker, info, _opened = fence
        if m and not m.group(2) and m.group(1)[0] == marker[0] \
                and len(m.group(1)) >= len(marker):
            fence = None
            continue
        if info not in BLOCKS:
            continue                      # ordinary code block: prose
        spec = BLOCKS[info]
        body = line.strip()
        if not body:
            continue
        where = f"{doc}:{lineno}"
        if not body.startswith("|"):
            raise HarnessError(f"{where}: every {info} row must start with "
                               f"'|' (pipe table, outer pipes included), "
                               f"got: {body}")
        cells = _cells(line)
        if any(cells) and all(_SEPARATOR_CELL.match(c) for c in cells if c):
            continue                      # | --- | --- | alignment row
        if any([c.lower() for c in cells] == list(v) for v in spec[1]):
            continue                      # header row (any accepted variant)
        if cells and cells[0].lower() == "id":
            raise HarnessError(f"{where}: {info} header must be "
                               f"{_headers(spec[1])}, got: {body}")
        row = _row(cells, spec, where)
        if spec[0] == "decisions":
            row["adr_ref"] = row["adr_ref"] or None
            row["security"] = row["security"].lower() in _TRUTHY
        out[spec[0]].append(row)
    if fence is not None and fence[1] in BLOCKS:
        raise HarnessError(f"{doc}:{fence[2]}: ```{fence[1]} block is never "
                           f"closed — fail closed rather than compile half a "
                           f"table")
    return out


def _doc_module(root, source, module_id, config, aid, doc_ref, report):
    """Resolve an abstraction row's `(source, module_id)` pair.

    A module-level abstraction is only visible to G5 and the resolver when
    the registry entry carries the dotted module id of its source, so the
    id is derived from `source` exactly as the extractor derives it
    (ADR-002 / D-008) unless the row states it outright.

    Args:
        root: Substrate root, or None when the caller has no repo context.
        source: The row's `source` cell (already normalized to None/str).
        module_id: The row's `module_id` cell (None/str).
        config: Loaded engine config (supplies `extractor.src_roots`).
        aid: The abstraction id, quoted in the warning.
        doc_ref: The working document, quoted in the warning.
        report: The compile report, appended to on a failed derivation.

    Returns:
        `(source, module_id)` with the id derived when it can be.
    """
    if module_id or not source:
        return source, module_id
    if root is None:
        return source, None
    from .extractor.engine import module_id_for
    try:
        return source, module_id_for(root, Path(root) / source, config)
    except HarnessError as exc:
        report["warnings"].append(
            f"{doc_ref}: abstraction {aid!r} names source {source!r} whose "
            f"module id could not be derived ({exc}) — give the row an "
            f"explicit module_id or G5/the resolver cannot see it")
        return source, None


def merge_doc_blocks(blocks: dict, doc_ref: str, *, decisions: dict,
                     registry: dict, authored: dict, report: dict, now: str,
                     adr_sources: dict, kinds: set, root=None,
                     config=None) -> None:
    """Folds doc-authored rows into the compiler's in-flight substrate.

    Doc rows are `origin: phase0` exactly like ADR rows: adjudicated rows
    still outrank them, and `adr_ref` comes from the table (may be null).

    Args:
        blocks: `parse_doc_blocks` output.
        doc_ref: Root-relative path of the working document.
        decisions: id -> decision row, mutated in place.
        registry: id -> registry entry, mutated in place.
        authored: id -> per-compile authored view, mutated in place.
        report: The compile report, appended to.
        now: Compile timestamp.
        adr_sources: `{"decisions": {id: adr_ref}, "abstractions": {...}}`.
        kinds: The registry `kind` enum in force (`registry_kinds`).
        root: Substrate root, for deriving `module_id` from `source`.
        config: Loaded engine config (`extractor.src_roots`).

    Raises:
        HarnessError: An id is claimed by both an ADR and the document, or
            twice by the document.
    """
    seen: set = set()
    for row in blocks["decisions"]:
        rid = row["id"]
        owner = adr_sources["decisions"].get(rid)
        if owner:
            raise HarnessError(f"decision {rid} defined in {owner} and "
                               f"{doc_ref} — one id, one source of truth")
        if rid in seen:
            raise HarnessError(f"decision {rid} defined twice in {doc_ref}")
        seen.add(rid)
        existing = decisions.get(rid)
        if existing and existing.get("origin") == "adjudication":
            continue                      # adjudicated rows outrank phase0
        changed = existing is not None and any(
            existing.get(k) != row[k] for k in ("domain", "question", "answer"))
        created = existing.get("created") if existing else now
        if not created or str(created).startswith(EPOCH_PREFIX):
            created = now
        new_row = {"id": rid, "domain": row["domain"],
                   "question": row["question"], "answer": row["answer"],
                   "adr_ref": row["adr_ref"], "origin": "phase0",
                   "created": created}
        if row["security"]:
            new_row["security"] = True
        if changed:
            new_row["updated"] = now
        decisions[rid] = new_row
        report["decisions"].append(rid)

    for ab in blocks["abstractions"]:
        aid = ab["id"]
        owner = adr_sources["abstractions"].get(aid)
        if owner:
            raise HarnessError(f"abstraction {aid!r} defined in {owner} and "
                               f"{doc_ref} — one id, one source of truth")
        requested_kind = ab["kind"]
        kind = requested_kind
        if kind not in kinds:
            report["warnings"].append(
                f"{doc_ref}: abstraction {aid!r} kind {requested_kind!r} is "
                f"not in the registry enum {sorted(kinds)}; coerced "
                f"to 'other' but preserved as domain {requested_kind!r} for "
                f"decision-row matching and author-gate coverage")
            kind = "other"
        ref = ab.get("guidance_ref") or doc_ref
        source = (ab.get("source") or "").strip() or None
        module_id = (ab.get("module_id") or "").strip() or None
        source, module_id = _doc_module(root, source, module_id, config, aid,
                                        doc_ref, report)
        auth = authored.setdefault(aid, {"kind": kind,
                                         "domain": requested_kind, "refs": []})
        auth["kind"], auth["domain"] = kind, requested_kind
        if ref not in auth["refs"]:
            auth["refs"].append(ref)
        if aid not in registry:
            registry[aid] = {
                "id": aid, "kind": kind, "domain": requested_kind,
                "status": "planned", "module_id": module_id, "source": source,
                "source_hash": None, "shadow": None, "guidance_refs": [ref],
                "supersedes_guidance": [], "manifest": [],
                "signature_digest": None,
            }
            report["registry"].append(aid)
        elif registry[aid].get("status") == "planned":
            # a planned entry adopts what the doc now states, exactly as the
            # ADR path does — a seed with source: null would otherwise never
            # qualify for the planned->built flip at close-slice
            entry = registry[aid]
            if source and not entry.get("source"):
                entry["source"] = source
            if module_id and not entry.get("module_id"):
                entry["module_id"] = module_id


def _first_paragraph(lines: list, start: int) -> str:
    """Collapses the first paragraph under a heading to one line."""
    i = start
    while i < len(lines) and not lines[i].strip():
        i += 1
    para = []
    while i < len(lines):
        line = lines[i]
        if not line.strip() or _HEADING.match(line) or line.startswith("#") \
                or _FENCE.match(line):
            break
        para.append(line.strip())
        i += 1
    return re.sub(r"\s+", " ", " ".join(para)).strip() or _NO_SUMMARY


def seed_doc_from_spec(text: str, spec_ref: str) -> str:
    """Renders a working document from an existing spec (`--from-spec`).

    Every `##`/`###` heading becomes a `[constraint]` block carrying its
    first paragraph, every `TODO`/`TBD`/`Open:` line (after list markers)
    becomes an `[open-question]`, and the document ends with an empty
    `harness-decisions` table so rows are filled in the same file.

    Args:
        text: The source spec's markdown.
        spec_ref: Path quoted in the seeded document's header.

    Returns:
        The document body, staged at `<!-- stage: 3 -->`.
    """
    lines = text.splitlines()
    constraints, questions = [], []
    fence = None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif not m.group(2) and m.group(1)[0] == fence[0] \
                    and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if fence is not None:
            continue
        heading = _HEADING.match(line)
        if heading:
            constraints.append((heading.group(2).strip(),
                                _first_paragraph(lines, i + 1)))
            continue
        body = line[_LIST_MARKER.match(line).end():].strip()
        if _QUESTION.match(body):
            questions.append(body)
    out = [_SEED_HEADER.format(spec=spec_ref), "", _STAGE_MARKER, ""]
    for heading, summary in constraints:
        out += [f"[constraint] {heading}", summary, ""]
    for question in questions:
        out += [f"[open-question] {question}", ""]
    out += ["```harness-decisions", *DECISIONS_TABLE_HEADER, "```", ""]
    return "\n".join(out)
