"""What `harness upgrade` reports: changed files, final checks, the step that
owns each failure, the lines a human must check, and one commit proposal.

Nothing in this module changes a file or the git index.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from engine import IGNORED_DIRS, HarnessError, sha256_file

COMMIT_MESSAGE = "harness: upgrade to 0.10"
CHECK = "check: "
NEEDS_CONFIRMATION = "needs confirmation"
# gitignored machine state: never part of the upgrade's file report
MACHINE_STATE = (".harness/cache/", ".harness/sidecar.db")


def _git(root, *args) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise HarnessError(f"git {args[0]} failed in {root}. "
                           "Repair the repository, then run: harness upgrade")
    return done


def _few(paths, limit=3) -> str:
    shown = ", ".join(list(paths)[:limit])
    extra = len(paths) - limit
    return f"{shown} and {extra} more" if extra > 0 else shown


def _is_repo(root) -> bool:
    return (Path(root) / ".git").exists()


def _nul_list(text: str) -> list[str]:
    return [p for p in text.split("\0") if p]


def _listed(root: Path) -> list[str]:
    if _is_repo(root):
        out = _git(root, "ls-files", "-z", "--cached", "--others",
                   "--exclude-standard").stdout
        return sorted(set(_nul_list(out)))
    skip = IGNORED_DIRS - {".harness"}
    paths = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_dir() or any(part in skip for part in rel.parts):
            continue
        paths.append(rel.as_posix())
    return sorted(paths)


def snapshot(root) -> dict:
    """Map each tracked or untracked, non-ignored path to its sha256.

    A tracked path that is gone from disk maps to None.
    """
    root = Path(root)
    out = {}
    for rel in _listed(root):
        if rel.startswith(MACHINE_STATE):
            continue
        path = root / rel
        out[rel] = sha256_file(path) if path.is_file() else None
    return out


def changed_files(before: dict, after: dict) -> dict:
    old = {k for k, v in before.items() if v is not None}
    new = {k for k, v in after.items() if v is not None}
    return {"added": sorted(new - old),
            "modified": sorted(k for k in old & new if before[k] != after[k]),
            "removed": sorted(old - new)}


def staged_paths(root) -> list[str]:
    if not _is_repo(root):
        return []
    return sorted(_nul_list(_git(root, "diff", "--cached", "--name-only", "--no-renames", "-z").stdout))


def dirty_paths(root) -> list[str]:
    if not _is_repo(root):
        return []
    entries = _nul_list(_git(root, "status", "--porcelain=v1", "-z",
                             "--untracked-files=all").stdout)
    paths, skip_next = [], False
    for entry in entries:
        if skip_next:            # the source path of a rename or copy
            skip_next = False
            continue
        paths.append(entry[3:])
        skip_next = entry[0] in "RC"
    return sorted(paths)


def step_lines(row: dict) -> list[str]:
    lines = row.get("report")
    if lines is None:
        lines = row.get("changes", [])
    return [str(line) for line in lines]


def human_checks(steps, *, pending, staged_before, dirty_before, files,
                 checks, is_repo, advice=()) -> list[str]:
    out = [f"{row['id']}: {row['check']}" for row in advice]
    for row in steps:
        for line in step_lines(row):
            if line.startswith(CHECK) or NEEDS_CONFIRMATION in line:
                out.append(f"{row['id']}: {line}")
    if pending:
        out.append(f"{CHECK}steps {_few(pending)} still have changes. "
                   "Run: harness upgrade --yes")
    touched = set(files["added"]) | set(files["modified"]) | set(files["removed"])
    mixed = sorted(set(dirty_before) & touched)
    if mixed:
        out.append(f"{CHECK}you had uncommitted edits in {_few(mixed)}. "
                   "Review them before you commit.")
    if staged_before:
        out.append(f"{CHECK}the index held staged changes before the upgrade: "
                   f"{_few(staged_before)}. Commit or unstage them first.")
    deps = ((checks or {}).get("doctor") or {}).get("deps_missing") or []
    if deps:
        out.append(f"{CHECK}engine dependencies are missing: {' '.join(deps)}. "
                   f"Run: pip install {' '.join(deps)}")
    if not is_repo:
        out.append(f"{CHECK}this folder is not a git repository. "
                   "Commit the upgrade with your own tool.")
    return out


def commit_proposal(root, files) -> dict | None:
    """The one commit the human runs from the repo root. Paths that are gone
    from disk and from the index are already staged deletions."""
    root = Path(root)
    if not _is_repo(root):
        return None
    changed = sorted(set(files["added"]) | set(files["modified"]) | set(files["removed"]))
    if not changed:
        return None
    index = set(_nul_list(_git(root, "ls-files", "-z", "--cached").stdout))
    paths = [p for p in changed if (root / p).exists() or p in index]
    commit = f'git commit -m "{COMMIT_MESSAGE}"'
    command = (f"git --literal-pathspecs add -A -- {' '.join(shlex.quote(p) for p in paths)} && {commit}"
               if paths else commit)
    return {"message": COMMIT_MESSAGE, "paths": paths, "cwd": str(root),
            "command": command}


HARNESS_BIN = Path(__file__).resolve().parents[1] / "bin" / "harness"
STEP_FIX = "fix the cause, then run: harness upgrade --yes"
DOCTOR_LISTS = ("schema_problems", "stale_bindings", "stale_worktrees", "missing_notes")
DOCTOR_COUNTS = ("parked_findings",)
_PATH_TOKEN = re.compile(r"[\w.\-]+(?:/[\w.\-]*)+|[\w\-]+\.(?:jsonl|yaml|yml|md|json|toml)")


def _run_json(root, *args) -> dict:
    proc = subprocess.run([sys.executable, str(HARNESS_BIN), "--root", str(root), *args],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = proc.stderr or proc.stdout or f"exit {proc.returncode}, no output"
        return {"error": detail.strip()[-400:]}
    return payload if isinstance(payload, dict) else {"error": "output is not a JSON object"}


def doctor_failures(report: dict) -> list:
    if "error" in report:
        return [{"check": "doctor", "code": "DOCTOR_CRASHED", "text": report["error"],
                 "fix": "run: harness doctor --substrate"}]
    if report.get("substrate_healthy", False):
        return []
    fallback = report.get("next") or "run: harness doctor --substrate"
    out = []
    for key in DOCTOR_LISTS + DOCTOR_COUNTS:
        value = report.get(key)
        if isinstance(value, list):
            for item in value:
                text = item if isinstance(item, str) else json.dumps(item, sort_keys=True)
                fix = item.get("remove_with") if isinstance(item, dict) else None
                out.append({"check": "doctor", "code": key, "text": text,
                            "fix": fix or fallback})
        elif isinstance(value, int) and not isinstance(value, bool) and value > 0:
            out.append({"check": "doctor", "code": key,
                        "text": f"{value} {key.replace('_', ' ')}", "fix": fallback})
    vendored = report.get("vendored_engine") or {}
    if vendored.get("status") == "stale":
        out.append({"check": "doctor", "code": "vendored_engine",
                    "text": (f"vendored engine {vendored.get('version')} is not "
                             f"{vendored.get('engine_version')}"),
                    "fix": "run: harness upgrade --yes"})
    if not out:
        out.append({"check": "doctor", "code": "unhealthy",
                    "text": "doctor reports the substrate unhealthy", "fix": fallback})
    return out


def verify_failures(report: dict) -> list:
    if "error" in report:
        return [{"check": "verify", "code": "VERIFY_CRASHED", "text": report["error"],
                 "fix": "run: harness verify"}]
    out = [{"check": "verify", "code": f["code"], "text": f.get("message", ""),
            "fix": f.get("fix") or f"harness gates explain {f['code']}"}
           for f in report.get("findings", []) if f.get("severity") == "block"]
    if not out and report.get("passed") is False:
        out.append({"check": "verify", "code": "VERIFY_FAILED",
                    "text": "verify did not pass", "fix": "run: harness verify"})
    return out


def final_checks(root) -> dict:
    """Run doctor and verify as CI would: a fresh process each."""
    doctor = _run_json(root, "doctor", "--substrate")
    verify = _run_json(root, "verify")
    deps = sorted(k for k, v in (doctor.get("deps") or {}).items() if v == "MISSING")
    d_fail, v_fail = doctor_failures(doctor), verify_failures(verify)
    return {"doctor": {"passed": not d_fail, "deps_missing": deps, "failures": d_fail},
            "verify": {"passed": not v_fail, "failures": v_fail}}


def _tokens(lines) -> set:
    found = set()
    for line in lines:
        for token in _PATH_TOKEN.findall(line):
            token = token.strip(".,:;`'\"()")
            if not token:
                continue
            found.add(token)
            name = token.rstrip("/").rsplit("/", 1)[-1]
            if "." in name.strip("."):
                found.add(name)
    return found


def _owner(fix: str) -> str:
    """Who acts on a fix: the upgrade (rerun it), a later command, or the human."""
    if "harness upgrade" in fix:
        return "the upgrade"
    if fix.startswith(("harness ", "run: harness", "Run: harness")):
        return "a later command"
    return "the human"


def attribute(failures, steps) -> list:
    """Name the step and the owner of each failure. The step is the last one
    whose report names a file that the failure names; `none` means no step
    touched it."""
    owners = [(row["id"], _tokens(step_lines(row))) for row in reversed(steps)]
    out = []
    for failure in failures:
        step = failure.get("step") or next(
            (sid for sid, tokens in owners if any(t in failure["text"] for t in tokens)),
            "none")
        line = (f"{failure['check']} {failure['code']}: {failure['text']}. "
                f"Step: {step}. Fix: {failure['fix']}")
        out.append({**failure, "step": step, "owner": _owner(failure["fix"]), "line": line})
    return out


def step_failure(root, exc, steps) -> dict:
    """A step raised inside `upgrade_010.run`. The first step, in order, that
    still has pending changes is the one that stopped."""
    owner = "none"
    for step in steps:
        try:
            pending = step.describe(root)
        except Exception:
            pending = ["describe failed"]
        if pending:
            owner = step.id
            break
    return {"check": "upgrade", "code": "STEP_FAILED",
            "text": f"{type(exc).__name__}: {exc}", "step": owner, "fix": STEP_FIX}


def reported_step_errors(rows) -> list:
    return [{"check": "upgrade", "code": "STEP_FAILED", "text": str(row["error"]),
             "step": row["id"], "fix": STEP_FIX}
            for row in rows if row.get("error")]


def upgrade_status(*, schema_from, current, files, steps, pending, failures) -> str:
    """A declined destructive step leaves the upgrade "incomplete"."""
    if any(f.get("code") == "STEP_FAILED" for f in failures):
        return "failed"
    skipped = any(NEEDS_CONFIRMATION in line for row in steps for line in step_lines(row))
    if pending or skipped:
        return "incomplete"
    if failures:
        return "checks failed"
    if schema_from == current and not any(files.values()):
        return "already on 0.10"
    return "upgraded"
