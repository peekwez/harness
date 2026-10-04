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

from engine import HarnessError, get_slice, harness_dir, now_iso

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


def red_advisory(root, slice_id, paths, config) -> list:
    """One advisory when a non-test file is edited before the red record.

    Engine-side, not a gate: spec 4.1's gate table does not change. Legacy
    and closed slices, a disabled runner, test files, acceptance files and
    `gates.exempt_paths` give nothing. It reads the record path only: no
    subprocess, no test run, and a corrupt record never raises (a hook must
    not crash). A record that exists, valid or not, silences the advisory.

    Returns:
        `[]` or one `NO_RED_RECORD` advisory finding.
    """
    from engine.events import make_finding, rel_in_root
    from engine.gates import exempt
    from engine.statements import expand_suite, is_test_path
    if not slice_id or _runner_disabled(config):
        return []
    try:
        sl = get_slice(root, slice_id)
        if sl.get("legacy_verification") or sl.get("status") == "closed":
            return []
        if red_record_path(root, slice_id).exists():
            return []
        suite = set(expand_suite(root, sl.get("acceptance") or []))
        for raw in paths:
            if not rel_in_root(root, raw):
                continue
            rel = Path(raw).as_posix()
            if rel in suite or is_test_path(rel) or exempt(rel, config):
                continue
            return [make_finding(
                "NO_RED_RECORD", RULE_RED,
                f"No red record for slice {slice_id}: {rel} is not a test.",
                severity="advisory", key=slice_id,
                fix=f"harness slice --slice {slice_id}")]
    except (HarnessError, OSError):
        return []
    return []


def close_checks(root, sl, config):
    """Spec 6.4 checks 3, 4 and 5 for one slice.

    3. A red record exists. A record that was green at start needs an
       override with a reason (`verification:green-at-start`).
    4. Each statement in `verifies` has a test with a `verifies:` comment
       in an acceptance suite: the slice's own, or a closed slice's.
    5. Each such test has `kills:` text.

    `legacy_verification: true` skips all three. Unknown IDs in the slice's
    own acceptance files are advisory.

    Returns:
        `(findings, report)`. Blocking findings stop the close.
    """
    from engine.cli.acceptance import closed_acceptance
    from engine.events import make_finding
    from engine.findings import clip_words
    from engine.graph import override_targets
    from engine.statements import (expand_suite, load_statements,
                                   scan_test_links)
    sid = sl["id"]
    report = {"legacy": bool(sl.get("legacy_verification")),
              "red_record": None, "red_before_green": False,
              "green_at_start": False, "green_at_start_override": False,
              "statements": {}, "unknown_test_links": []}
    if report["legacy"]:
        report["red_record"] = "skipped: legacy_verification: true"
        return [], report
    findings = []

    # check 3: the red record
    if _runner_disabled(config):
        report["red_record"] = "skipped: gates.acceptance_runner is none"
    else:
        try:
            record, problem = load_red_record(root, sid), None
        except HarnessError as exc:
            record, problem = None, str(exc)
            report["red_record_corrupt"] = True
        if record is None:
            findings.append(make_finding(
                "RED_RECORD_MISSING", RULE_RED,
                clip_words(problem or f"No red record for slice {sid}: "
                                      f"{record_rel(sid)} does not exist."),
                severity="block", key=sid,
                fix=f"harness slice --slice {sid}"))
        else:
            report["red_record"] = record_rel(sid)
            if record.get("red"):
                report["red_before_green"] = True
            elif record.get("green_at_start"):
                report["green_at_start"] = True
                overrides = override_targets(root, sid, RULE_RED,
                                             {"verification"})
                if "green-at-start" in overrides:
                    report["green_at_start_override"] = True
                else:
                    findings.append(make_finding(
                        "GREEN_AT_START", RULE_RED,
                        f"Slice {sid} acceptance tests passed at bind: "
                        f"{record_rel(sid)}.",
                        severity="block", key=sid,
                        fix=(f"harness gates override --slice {sid} --target "
                             f"{GREEN_OVERRIDE} --rule-ref {RULE_RED} "
                             f"--justification \"<why>\"")))
            else:
                reason = record.get("runner_error") or "no failing exit code"
                findings.append(make_finding(
                    "RED_RECORD_MISSING", RULE_RED,
                    clip_words(f"Red record for slice {sid} is not red: "
                               f"{reason}."),
                    severity="block", key=sid,
                    fix=f"harness slice --slice {sid}"))

    # checks 4 and 5: statement coverage and kills text
    own = expand_suite(root, sl.get("acceptance") or [])
    regression = expand_suite(
        root, closed_acceptance(root, exclude=sid)["paths"])
    links = scan_test_links(root, sorted(set(own) | set(regression)))
    known = {r["id"] for r in load_statements(root)}
    target = (sl.get("acceptance") or ["a test file"])[0]
    for stid in sl.get("verifies") or []:
        if stid not in known:
            findings.append(make_finding(
                "UNKNOWN_STATEMENT", RULE_COVERAGE,
                f"Slice {sid} verifies {stid}, which is not in "
                f".harness/verify.jsonl.",
                severity="block", key=f"{sid}|{stid}",
                fix="harness compile --doc <working document>"))
            continue
        found = links.get(stid, [])
        report["statements"][stid] = found
        if not found:
            findings.append(make_finding(
                "STATEMENT_UNTESTED", RULE_COVERAGE,
                f"Statement {stid} has no test with a verifies: comment in "
                f"the acceptance suites of slice {sid}.",
                severity="block", key=f"{sid}|{stid}",
                fix=f"Add a comment `verifies: {stid} kills: <mistake>` to a "
                    f"test in the slice's suite ({target})."))
        for link in found:
            if not link["kills"]:
                findings.append(make_finding(
                    "KILLS_MISSING", RULE_COVERAGE,
                    f"{link['path']}:{link['line']}: the verifies: {stid} "
                    f"comment has no kills: text.",
                    severity="block",
                    key=f"{stid}|{link['path']}:{link['line']}",
                    fix="Add 'kills: <the bug this test catches>' to the "
                        "comment."))
    own_files = set(own)
    for tid, found in sorted(links.items()):
        if tid in known:
            continue
        for link in found:
            if link["path"] not in own_files:
                continue
            report["unknown_test_links"].append({"id": tid, **link})
            findings.append(make_finding(
                "UNKNOWN_TEST_LINK", RULE_COVERAGE,
                f"{link['path']}:{link['line']}: verifies: {tid} is not in "
                f".harness/verify.jsonl.",
                severity="advisory",
                key=f"{tid}|{link['path']}:{link['line']}",
                fix="Fix the ID, or add the statement and run harness "
                    "compile."))
    return findings, report


def slice_metrics(report: dict) -> dict:
    """The W5 fields for `record_slice_summary(..., extra=...)`."""
    if report.get("legacy") or str(report.get("red_record") or "").startswith(
            "skipped"):
        return {}
    return {"red_before_green": bool(report.get("red_before_green")),
            "green_at_start": bool(report.get("green_at_start"))}
