"""Verification first: the red record, the pre-edit advisory, close checks.

Spec 6.3 and 6.4 (D-0.10-03). Binding a slice runs its acceptance suite
once and writes `.harness/verification/<slice>.json`. Close reads that
record, and the statement links from `engine.statements`.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from engine import HarnessError, harness_dir, now_iso

RULE_RED = "verify:red-record"
RULE_COVERAGE = "verify:statement-coverage"
GREEN_OVERRIDE = "verification:green-at-start"
RECORD_DIR = "verification"


def red_record_path(root, slice_id: str) -> Path:
    """Absolute path of the slice's red record."""
    return harness_dir(root) / RECORD_DIR / f"{slice_id}.json"


def record_rel(slice_id: str) -> str:
    """Repo-relative path of the slice's red record, for messages."""
    return f".harness/{RECORD_DIR}/{slice_id}.json"


def load_red_record(root, slice_id: str):
    """The slice's red record, or None when it does not exist.

    Raises:
        HarnessError: The file is not a JSON object.
    """
    path = red_record_path(root, slice_id)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"{record_rel(slice_id)} is not valid JSON. "
                           f"Repair or delete it, then bind again.") from exc
    if not isinstance(record, dict):
        raise HarnessError(f"{record_rel(slice_id)} is not a JSON object. "
                           f"Repair or delete it, then bind again.")
    return record


def _runner_disabled(config) -> bool:
    return config.get("gates", {}).get("acceptance_runner", "pytest") == "none"


def _head(root):
    if not (Path(root) / ".git").exists():
        return None
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def parse_junit(path) -> list[dict]:
    """Each test case's outcome from a JUnit XML file.

    Returns:
        `[{"test": "<classname>::<name>", "outcome": "passed" | "failed" |
        "skipped"}]`, sorted by test.

    Raises:
        HarnessError: The XML cannot be read or parsed.
    """
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        raise HarnessError(f"JUnit XML is not readable: {exc}. Check the "
                           f"{{junit}} path in acceptance.cmd.") from exc
    out = []
    for case in tree.iter("testcase"):
        name, cls = case.get("name", ""), case.get("classname")
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "failed"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        out.append({"test": f"{cls}::{name}" if cls else name,
                    "outcome": outcome})
    return sorted(out, key=lambda r: r["test"])


def record_red(root, sl, config) -> dict:
    """Run the slice's suite once and write its red record.

    Returns:
        The record written, or `{"skipped": reason}` (nothing written) when
        `gates.acceptance_runner` is `none`.
    """
    from engine.cli.acceptance import junit_enabled, run_slice_suite
    sid = sl["id"]
    if _runner_disabled(config):
        return {"skipped": "gates.acceptance_runner is none"}
    junit = None
    if junit_enabled(config):
        junit = (harness_dir(root) / "cache" / "junit" / f"{sid}.xml").resolve()
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.unlink(missing_ok=True)
    try:
        run = run_slice_suite(root, sl, config,
                              junit=str(junit) if junit else None)
        ran = run["runner_error"] is None
        record = {"slice": sid, "commit": _head(root), "ran_at": now_iso(),
                  "exit_code": run["exit_code"],
                  "output_tail": run["output_tail"],
                  "red": ran and run["exit_code"] != 0,
                  "green_at_start": ran and run["exit_code"] == 0}
        if not ran:
            record["runner_error"] = run["runner_error"]
        if junit is not None:
            if junit.is_file():
                try:
                    record["per_test"] = parse_junit(junit)
                except HarnessError as exc:
                    record["junit_error"] = str(exc)
            else:
                record["junit_error"] = (
                    f"no JUnit XML at {_rel(root, junit)}. "
                    f"Add {{junit}} to acceptance.cmd.")
    finally:
        if junit is not None:
            junit.unlink(missing_ok=True)
    path = red_record_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return record


def _rel(root, path) -> str:
    try:
        return str(Path(path).relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _summary(record: dict, reused: bool) -> dict:
    out = {"path": record_rel(record["slice"]),
           "red": bool(record.get("red")),
           "green_at_start": bool(record.get("green_at_start")),
           "exit_code": record.get("exit_code"), "reused": reused}
    for key in ("runner_error", "junit_error"):
        if record.get(key):
            out[key] = record[key]
    return out


def ensure_red_record(root, sl, config) -> dict:
    """The bind-time red record (spec 6.3).

    A red record is never overwritten: re-binding after code exists must
    not replace evidence that the tests failed first. A green record or a
    runner error runs the suite again. A corrupt record fails loud: it may
    hold real red evidence, so it is never replaced silently.

    Returns:
        A summary for the bind output, or `{"skipped": reason}`.

    Raises:
        HarnessError: The existing record is not valid JSON.
    """
    existing = load_red_record(root, sl["id"])
    if existing and existing.get("red"):
        return _summary(existing, reused=True)
    record = record_red(root, sl, config)
    if "skipped" in record:
        return record
    return _summary(record, reused=False)
