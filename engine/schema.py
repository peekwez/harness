"""Substrate row schemas (§5.5 / §5.6) — validated, not assumed.

Rows reach substrate from ADR compilation, the CLI, and (historically) hand
edits. A malformed row used to surface three ceremonies later as a confusing
failure; here it fails loud at `harness verify` / `harness doctor`, naming
the file, the row, and the field.
"""
from __future__ import annotations

SLICE_STATUS = ("planned", "in_progress", "parked", "closed")
REGISTRY_STATUS = ("planned", "built", "deprecated")
REGISTRY_KIND = ("logging", "telemetry", "config", "errors", "util",
                 "component", "other")
DECISION_ORIGIN = ("phase0", "adjudication")

# file -> (id_field, [(field, type, required)], {field: allowed_values})
SCHEMAS = {
    "backlog.jsonl": {
        "id_field": "id",
        "fields": [("id", str, True), ("status", str, True),
                   ("declares_dep", list, True), ("acceptance", list, True),
                   ("predicted_files", list, True), ("depends_on", list, False),
                   ("title", str, False), ("spec", str, False)],
        "enums": {"status": SLICE_STATUS},
    },
    "registry.jsonl": {
        "id_field": "id",
        "fields": [("id", str, True), ("kind", str, True),
                   ("status", str, True), ("manifest", list, False),
                   ("guidance_refs", list, False)],
        "enums": {"status": REGISTRY_STATUS, "kind": REGISTRY_KIND},
    },
    "decisions.jsonl": {
        "id_field": "id",
        "fields": [("id", str, True), ("domain", str, True),
                   ("question", str, True), ("answer", str, True),
                   ("origin", str, False)],
        "enums": {"origin": DECISION_ORIGIN},
    },
}


def validate_rows(filename: str, rows: list) -> list:
    """Returns a list of human-readable problems (empty = valid)."""
    spec = SCHEMAS.get(filename)
    if spec is None:
        return []
    problems, seen = [], set()
    for i, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            problems.append(f"{filename}:{i}: row is not an object")
            continue
        rid = row.get(spec["id_field"], f"<line {i}>")
        if rid in seen:
            problems.append(f"{filename}: duplicate id {rid!r} — ids must be "
                            f"unique (a keyed merge would silently drop one)")
        seen.add(rid)
        for field, typ, required in spec["fields"]:
            if field not in row or row[field] is None:
                if required:
                    problems.append(
                        f"{filename}: row {rid!r} is missing required field "
                        f"{field!r}")
                continue
            if not isinstance(row[field], typ):
                problems.append(
                    f"{filename}: row {rid!r} field {field!r} must be "
                    f"{typ.__name__}, got {type(row[field]).__name__}")
        for field, allowed in spec["enums"].items():
            value = row.get(field)
            if value is not None and value not in allowed:
                problems.append(
                    f"{filename}: row {rid!r} has {field}={value!r}; "
                    f"expected one of {list(allowed)}")
    return problems


def validate_substrate(root) -> list:
    """Every known substrate file. Unreadable files are reported by the
    caller's own loud-failure path, not swallowed here."""
    from . import HarnessError, harness_dir, read_jsonl
    problems = []
    for filename in SCHEMAS:
        path = harness_dir(root) / filename
        if not path.exists():
            continue
        try:
            rows = read_jsonl(path)
        except HarnessError as exc:
            problems.append(str(exc))
            continue
        problems.extend(validate_rows(filename, rows))
    return problems
