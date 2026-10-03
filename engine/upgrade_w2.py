"""Harness 0.10 upgrade steps owned by W2: slice metrics, telemetry, config
keys, renamed skills and the contracts notice (spec section 12, steps 2, 4,
5 and 7). Each step is idempotent: after `apply`, `describe` returns []."""
from __future__ import annotations

import copy
import json
import re
import sqlite3
from pathlib import Path

from . import (DEFAULT_EXEMPT_PATHS, HarnessError, append_jsonl, harness_dir,
               load_backlog, now_iso)
from .upgrade_010 import SKIPPED, Ask, Step, register
from .upgrade_w1 import strip_child_keys

LEGACY_TELEMETRY = ("telemetry.archive.jsonl", "telemetry.jsonl",
                    "telemetry.quarantine.jsonl")
OLD_UNION_LINE = ".harness/telemetry.jsonl merge=union"
METRICS_LINE = ".harness/slice-metrics.jsonl merge=harness-substrate"
G3_BLOCK_NOTE = ("G3 scope is advisory in 0.10. To block a path, cite its "
                 "non-goal from a gates.extra gate.")
# Removed skill -> the skill that now holds its content (spec 10.1).
# Adjudication is a main-session task, so it routes to the harness skill.
SKILL_RENAMES = {
    "status": "harness",
    "adjudicate": "harness",
    "review-rubrics": "review",
    "premortem": "architect",
    "contract-first": "architect",
    "shadow-context": "build",
    "slice-decomposition": "backlog",
    "decision-tables": "adr-authoring",
}
_OLD_SKILL = re.compile(r"(?<![\w-])harness:(%s)(?![\w-])" % "|".join(
    sorted(map(re.escape, SKILL_RENAMES), key=len, reverse=True)))
# Files the skill-names step may edit, each only with the marker that says
# harness wrote it. A file without its marker is only advised on.
MANAGED_FILES = ("AGENTS.md", "CLAUDE.md",
                 ".github/workflows/harness-verify.yml")
AGENTS_MARKERS = ("# AGENTS.md — this repo is harness-enforced",   # 0.9 line 1
                  "<!-- harness:agents-md 0.10 -->")
WORKFLOW_MARKER = "# harness verify — CI enforcement"
_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


# ------------------------------------------------------- w2.slice-metrics
def _ga_lines(root: Path) -> list:
    ga = Path(root) / ".gitattributes"
    return ga.read_text().splitlines() if ga.exists() else []


def _metrics_describe(root: Path) -> list:
    out = []
    if not (harness_dir(root) / "slice-metrics.jsonl").exists():
        out.append("create .harness/slice-metrics.jsonl")
    lines = [line.strip() for line in _ga_lines(root)]
    if OLD_UNION_LINE in lines:
        out.append(f"remove '{OLD_UNION_LINE}' from .gitattributes")
    if METRICS_LINE not in lines:
        out.append(f"add '{METRICS_LINE}' to .gitattributes")
    return out


def _metrics_apply(root: Path, ask: Ask) -> list:
    changes = _metrics_describe(root)
    if not changes:
        return []
    metrics = harness_dir(root) / "slice-metrics.jsonl"
    if not metrics.exists():
        metrics.touch()
    lines = [line for line in _ga_lines(root) if line.strip() != OLD_UNION_LINE]
    if METRICS_LINE not in (line.strip() for line in lines):
        lines.append(METRICS_LINE)
    (Path(root) / ".gitattributes").write_text("\n".join(lines) + "\n")
    return changes


# ---------------------------------------------------------- w2.telemetry
def _sidecar(root: Path) -> Path:
    return harness_dir(root) / "sidecar.db"


def _has_buffer(root: Path) -> bool:
    if not _sidecar(root).exists():
        return False
    try:
        con = sqlite3.connect(str(_sidecar(root)))
        try:
            return con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='telemetry_buffer'").fetchone() is not None
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False          # unreadable cache: nothing to convert


def _buffer_rows(root: Path) -> list:
    if not _has_buffer(root):
        return []
    con = sqlite3.connect(str(_sidecar(root)))
    try:
        raw_rows = con.execute(
            "SELECT row FROM telemetry_buffer ORDER BY id").fetchall()
    finally:
        con.close()
    out = []
    for (raw,) in raw_rows:
        try:
            row = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _drop_buffer(root: Path) -> None:
    if not _has_buffer(root):
        return
    con = sqlite3.connect(str(_sidecar(root)))
    try:
        con.execute("DROP TABLE telemetry_buffer")
        con.commit()
    finally:
        con.close()


def _tolerant_rows(path: Path) -> tuple:
    """(rows, unreadable line count). Torn and non-object lines are counted."""
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad += 1
    return rows, bad


def _telemetry_describe(root: Path) -> list:
    out = [f"convert and delete .harness/{name}" for name in LEGACY_TELEMETRY
           if (harness_dir(root) / name).exists()]
    if _has_buffer(root):
        out.append("convert and drop the sidecar telemetry_buffer table")
    return out


def _telemetry_apply(root: Path, ask: Ask) -> list:
    from . import telemetry
    from .graph import load_edges
    if not ask("Convert old telemetry into .harness/slice-metrics.jsonl and "
               "delete the old files? Git history keeps them."):
        return [SKIPPED]
    rows, bad = [], 0
    for name in ("telemetry.archive.jsonl", "telemetry.jsonl"):
        path = harness_dir(root) / name
        if path.exists():
            got, skipped = _tolerant_rows(path)
            rows += got
            bad += skipped
    rows += _buffer_rows(root)
    seen, unique = set(), []
    for row in rows:              # the buffer may repeat a flushed row
        rid = row.get("id")
        if rid is not None and rid in seen:
            continue
        if rid is not None:
            seen.add(rid)
        unique.append(row)
    try:
        closed = {s.get("id") for s in load_backlog(root)
                  if isinstance(s, dict) and s.get("status") == "closed"}
    except HarnessError:
        closed = set()
    # computed before any write: a malformed slice-metrics file fails here
    have = {r.get("id") for r in telemetry.load_summaries(root)}
    edges = load_edges(root)
    summaries = []
    for sid in sorted(s for s in closed - have if s):
        mine = [r for r in unique if (r.get("meta") or {}).get("slice") == sid]
        if not mine:
            continue
        summary = telemetry.summarize(sid, unique, edges)
        closes = [r["ts"] for r in mine
                  if r.get("kind") == "slice_closed" and r.get("ts")]
        summary.update({"closed_at": max(closes) if closes else now_iso(),
                        "source": "upgrade"})
        summaries.append(summary)
    kept = [r for r in unique
            if (r.get("meta") or {}).get("slice") not in closed]

    for summary in summaries:
        telemetry.write_summary(root, summary)
    events = Path(root) / telemetry.EVENTS_PATH
    for row in kept:
        append_jsonl(events, {"ts": row.get("ts") or now_iso(),
                              "kind": row.get("kind"),
                              "meta": row.get("meta") or {}})
    for name in LEGACY_TELEMETRY:
        (harness_dir(root) / name).unlink(missing_ok=True)
    _drop_buffer(root)
    written = [s["id"] for s in summaries]
    report = [f"wrote {len(written)} slice-metrics rows: "
              f"{', '.join(written) or 'none'}",
              f"kept {len(kept)} unclosed-slice event rows in "
              f"{telemetry.EVENTS_PATH}",
              "deleted the old telemetry files; git history keeps them"]
    if bad:
        report.append(f"skipped {bad} unreadable telemetry lines")
    return report


# ------------------------------------------------------------- w2.config
def _config_path(root: Path) -> Path:
    return harness_dir(root) / "config.yaml"


def _load_yaml(text: str):
    import yaml
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise HarnessError(
            f"w2.config: .harness/config.yaml is not valid YAML: {exc}. "
            f"Fix it, then run: harness upgrade") from exc


def _exempt_default(root: Path) -> list:
    paths = list(DEFAULT_EXEMPT_PATHS)
    if (Path(root) / "contracts").is_dir():
        paths.append("contracts/")   # it left the default list in 0.10
    return paths


def _mapping(doc: dict, key: str) -> dict | None:
    """doc[key] when it is a mapping, None when absent or empty."""
    value = doc.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HarnessError(
            f"w2.config: `{key}` in .harness/config.yaml is not a mapping. "
            f"Fix it, then run: harness upgrade")
    return value


def _config_plan(root: Path, doc) -> tuple:
    """(expected data, child keys to strip {parent: keys}, change lines).

    The single source of the intended config; the line edit is written only
    when it parses to exactly this data.
    """
    if not isinstance(doc, dict):
        raise HarnessError("w2.config: .harness/config.yaml is not a mapping. "
                           "Fix it, then run: harness upgrade")
    want, strip, changes = copy.deepcopy(doc), {}, []
    gates = _mapping(want, "gates")
    review = _mapping(want, "review")
    telemetry = _mapping(want, "telemetry")
    if gates is not None:
        drop = ["g5_override"] if "g5_override" in gates else []
        if gates.get("g3_mode") == "block":
            drop.append("g3_mode")
        for key in drop:
            gates.pop(key)
            changes.append(f"remove gates.{key} from .harness/config.yaml")
        if drop:
            strip["gates"] = tuple(drop)
    if "ensemble" in want:
        want.pop("ensemble")
        changes.append("remove ensemble from .harness/config.yaml")
    if telemetry is not None and "compaction_is_defect" in telemetry:
        telemetry.pop("compaction_is_defect")
        if not telemetry:
            want.pop("telemetry")
        strip["telemetry"] = ("compaction_is_defect",)
        changes.append("remove telemetry.compaction_is_defect from "
                       ".harness/config.yaml")
    if review is None or "ensemble" not in review:
        want["review"] = {**(review or {}), "ensemble": False}
        changes.append("add review.ensemble: false to .harness/config.yaml")
    if gates is None or "exempt_paths" not in gates:
        want["gates"] = {**(gates or {}), "exempt_paths": _exempt_default(root)}
        changes.append("add gates.exempt_paths to .harness/config.yaml")
    return want, strip, changes


def _drop_top_key(text: str, key: str) -> str:
    """Remove a top-level `key:` and its indented lines. Blank lines after
    the block stay."""
    lines = text.splitlines(keepends=True)
    out, i = [], 0
    while i < len(lines):
        m = _TOP_KEY.match(lines[i])
        if not m or m.group(1) != key:
            out.append(lines[i])
            i += 1
            continue
        j, last = i + 1, i
        while j < len(lines) and (not lines[j].strip()
                                  or lines[j][:1] in (" ", "\t")):
            if lines[j].strip():
                last = j
            j += 1
        i = last + 1
    return "".join(out)


def _add_child(text: str, parent: str, child: str, value) -> str:
    """Add `parent.child: value` to a block mapping, or append the parent.
    A flow-style parent is left unchanged (the semantic check catches it)."""
    rendered = json.dumps(value)
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    header = re.compile(rf"^{re.escape(parent)}\s*:\s*(#.*)?$")
    for i, line in enumerate(lines):
        if not header.match(line.rstrip("\r\n")):
            continue
        j, last, indent = i + 1, i, None
        while j < len(lines) and (not lines[j].strip()
                                  or lines[j][:1] in (" ", "\t")):
            stripped = lines[j].strip()
            if stripped:
                last = j
                if indent is None and not stripped.startswith("#"):
                    indent = lines[j][:len(lines[j]) - len(lines[j].lstrip())]
            j += 1
        lines.insert(last + 1, f"{indent or '  '}{child}: {rendered}\n")
        return "".join(lines)
    if any((m := _TOP_KEY.match(line)) and m.group(1) == parent
           for line in lines):
        return "".join(lines)            # flow style: leave it
    lines.append(f"{parent}:\n  {child}: {rendered}\n")
    return "".join(lines)


def _config_edit(text: str, original: dict, want: dict, strip: dict) -> str:
    for parent, keys in strip.items():
        text = strip_child_keys(text, parent, keys)
    if "ensemble" in original:
        text = _drop_top_key(text, "ensemble")
    if "ensemble" not in (original.get("review") or {}):
        text = _add_child(text, "review", "ensemble", False)
    if "exempt_paths" not in (original.get("gates") or {}):
        text = _add_child(text, "gates", "exempt_paths",
                          want["gates"]["exempt_paths"])
    return text


def _config_describe(root: Path) -> list:
    path = _config_path(root)
    if not path.exists():
        return []
    return _config_plan(root, _load_yaml(path.read_text()))[2]


def _config_apply(root: Path, ask: Ask) -> list:
    import yaml
    path = _config_path(root)
    if not path.exists():
        return []
    text = path.read_text()
    original = _load_yaml(text)
    want, strip, changes = _config_plan(root, original)
    if not changes:
        return []
    new = _config_edit(text, original, want, strip)
    try:
        same = yaml.safe_load(new) == want
    except yaml.YAMLError:
        same = False
    past = {"remove": "removed", "add": "added"}
    report = [past[line.split(" ", 1)[0]] + " " + line.split(" ", 1)[1]
              for line in changes]
    if not same:
        # flow style or an unusual layout: rewrite through YAML (comments go)
        new = yaml.safe_dump(want, sort_keys=False)
        report.append("rewrote .harness/config.yaml without comments; its "
                      "layout was not line-editable")
    path.write_text(new)
    if (original.get("gates") or {}).get("g3_mode") == "block":
        report.append(G3_BLOCK_NOTE)
    return report


def _config_advise(root: Path) -> list:
    path = _config_path(root)
    if not path.exists():
        return []
    doc = _load_yaml(path.read_text())
    gates = doc.get("gates") if isinstance(doc, dict) else None
    if isinstance(gates, dict) and gates.get("g3_mode") == "block":
        return [f"check: {G3_BLOCK_NOTE}"]
    return []


# --------------------------------------------------------- w2.skill-names
def _harness_marked(rel: str, text: str) -> bool:
    if rel.endswith(".yml"):
        return text.startswith(WORKFLOW_MARKER)
    head = [line.strip() for line in text.splitlines()[:5]]
    return bool(head) and (head[0] == AGENTS_MARKERS[0]
                           or AGENTS_MARKERS[1] in head)


def _skill_hits(root: Path) -> list:
    """[(rel, text, marked, sorted old names)] for files naming removed skills."""
    out = []
    for rel in MANAGED_FILES:
        path = Path(root) / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        old = sorted(set(_OLD_SKILL.findall(text)))
        if old:
            out.append((rel, text, _harness_marked(rel, text), old))
    return out


def _skill_describe(root: Path) -> list:
    return [f"{rel}: harness:{name} -> harness:{SKILL_RENAMES[name]}"
            for rel, _text, marked, old in _skill_hits(root) if marked
            for name in old]


def _skill_apply(root: Path, ask: Ask) -> list:
    changes = _skill_describe(root)
    for rel, text, marked, _old in _skill_hits(root):
        if marked:
            new = _OLD_SKILL.sub(
                lambda m: f"harness:{SKILL_RENAMES[m.group(1)]}", text)
            (Path(root) / rel).write_text(new, encoding="utf-8")
    return changes


def _skill_advise(root: Path) -> list:
    out = []
    for rel, _text, marked, old in _skill_hits(root):
        if not marked:
            renames = ", ".join(f"harness:{n} -> harness:{SKILL_RENAMES[n]}"
                                for n in old)
            out.append(f"check: {rel} names removed skills. Harness does not "
                       f"edit it. Rename them by hand: {renames}.")
    return out


# ------------------------------------------------------------ w2.contracts
def _exempt_paths(root: Path) -> list:
    path = _config_path(root)
    doc = _load_yaml(path.read_text()) if path.exists() else {}
    gates = doc.get("gates") if isinstance(doc, dict) else None
    if isinstance(gates, dict) and "exempt_paths" in gates:
        return list(gates["exempt_paths"] or [])
    return list(DEFAULT_EXEMPT_PATHS)


def _contracts_advise(root: Path) -> list:
    if not (Path(root) / "contracts").is_dir():
        return []
    line = ("check: harness no longer checks contracts/. Keep the folder if "
            "you use it.")
    if not any(str(p).rstrip("/") == "contracts" for p in _exempt_paths(root)):
        line += (" To keep it out of scope findings, add contracts/ to "
                 "gates.exempt_paths.")
    return [line]


register(Step(
    id="w2.slice-metrics",
    title="Add .harness/slice-metrics.jsonl and its merge rule.",
    describe=_metrics_describe, apply=_metrics_apply))
register(Step(
    id="w2.telemetry",
    title="Convert old telemetry into slice-metrics rows, then delete it.",
    describe=_telemetry_describe, apply=_telemetry_apply, destructive=True))
register(Step(
    id="w2.config",
    title="Remove retired config keys. Add review.ensemble and "
          "gates.exempt_paths.",
    describe=_config_describe, apply=_config_apply, advise=_config_advise))
register(Step(
    id="w2.skill-names",
    title="Rename removed skills in harness-marked AGENTS.md, CLAUDE.md and "
          "the CI workflow.",
    describe=_skill_describe, apply=_skill_apply, advise=_skill_advise))
register(Step(
    id="w2.contracts",
    title="Report that harness no longer checks contracts/.",
    describe=lambda root: [], apply=lambda root, ask: [],
    advise=_contracts_advise))
