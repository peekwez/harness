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

from engine.findings import clip_words
from engine import (ENGINE_VERSION, IGNORED_DIRS, SCHEMA_VERSION, HarnessError,
                    sha256_file)

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
                 checks, is_repo, advice=(), edited=()) -> list[str]:
    """`edited`: files an earlier run wrote that the human changed since."""
    out = [f"{row['id']}: {row['check']}" for row in advice]
    for row in steps:
        for line in step_lines(row):
            if line.startswith(CHECK) or NEEDS_CONFIRMATION in line:
                out.append(f"{row['id']}: {line}")
    if pending:
        out.append(f"{CHECK}steps {_few(pending)} still have changes. "
                   "Run: harness upgrade --yes")
    touched = set(files["added"]) | set(files["modified"]) | set(files["removed"])
    mixed = sorted((set(dirty_before) & touched) | set(edited))
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


# The changes of a run that proposed no commit, with the bytes it left. The
# next run adds a path to its own changes only while the path still holds
# those bytes; anything else is the human's edit.
CARRY_REL = ".harness/cache/upgrade-carry.json"
COMMITTED = ("upgraded", "already on 0.10")


def _head(root) -> str | None:
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "HEAD"],
                          capture_output=True, text=True)
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def _same_history(root, recorded) -> bool:
    """The record still applies: HEAD is the recorded commit or descends from it."""
    if not _is_repo(root):
        return True
    head = _head(root)
    if recorded is None or head is None:
        return recorded == head
    return recorded == head or subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", recorded, head],
        capture_output=True).returncode == 0


def _digest(root, rel):
    path = Path(root) / rel
    return sha256_file(path) if path.is_file() else None


def carry_record(root) -> dict:
    """{path: sha256 or None for a removal} from an earlier run on this line
    of history. A missing, unreadable or foreign record is empty."""
    try:
        data = json.loads((Path(root) / CARRY_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    paths = data.get("paths") if isinstance(data, dict) else None
    if not isinstance(paths, dict) or not _same_history(root, data.get("head")):
        return {}
    return {p: h for p, h in paths.items()
            if isinstance(p, str) and (h is None or isinstance(h, str))}


def carried_paths(root, record=None) -> list[str]:
    """The recorded paths that still hold the bytes the upgrade left."""
    record = carry_record(root) if record is None else record
    return sorted(p for p, h in record.items() if _digest(root, p) == h)


def carry_files(root, files: dict, carried) -> dict:
    """This run's files plus the carried paths that are still uncommitted."""
    root = Path(root)
    touched = set(files["added"]) | set(files["modified"]) | set(files["removed"])
    extra = set(carried) - touched
    if not extra:
        return files
    head = set()
    if _is_repo(root):
        extra &= set(dirty_paths(root))     # the human may have committed some
        if _head(root):
            head = set(_nul_list(_git(root, "ls-tree", "-r", "-z", "--name-only",
                                      "HEAD").stdout))
    out = {k: list(v) for k, v in files.items()}
    for rel in extra:
        key = ("removed" if not (root / rel).exists()
               else "modified" if rel in head else "added")
        out[key].append(rel)
    return {k: sorted(v) for k, v in out.items()}


def save_carry(root, status: str, files: dict) -> None:
    """Keep this run's paths, their bytes and HEAD for the next run when it
    proposed no commit. Otherwise forget the record. A run with no changes
    clears it too: no recorded path still holds the upgrade's bytes. The
    record lives in the gitignored cache only."""
    root = Path(root)
    path = root / CARRY_REL
    paths = sorted(set(files["added"]) | set(files["modified"]) | set(files["removed"]))
    if status in COMMITTED or not paths:
        path.unlink(missing_ok=True)
        return
    if _is_repo(root) and subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", CARRY_REL],
            capture_output=True).returncode != 0:
        return                  # never leave an untracked file in the tree
    record = {"head": _head(root) if _is_repo(root) else None,
              "paths": {rel: _digest(root, rel) for rel in paths}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


HARNESS_BIN = Path(__file__).resolve().parents[1] / "bin" / "harness"
STEP_FIX = "fix the cause, then run: harness upgrade --yes"
STEP_ERROR_WORDS = 11   # keeps the whole STEP_FAILED line within 25 words
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
        out.append({**failure, "step": step, "line": line})
    return out


def pending_ids(root, steps) -> list[str]:
    """The steps that still have work. A `describe` that raises counts as work,
    so the report never crashes after the upgrade wrote files."""
    out = []
    for step in steps:
        try:
            pending = step.describe(root)
        except Exception:
            pending = ["describe failed"]
        if pending:
            out.append(step.id)
    return out


def stage_failure(stage: str, exc: Exception) -> dict:
    """A pipeline stage after the migration raised. The text stays short;
    the exception text is in `detail`."""
    return {"check": "upgrade", "code": "STAGE_FAILED", "stage": stage, "step": "none",
            "text": f"stage {stage} raised {type(exc).__name__}",
            "detail": str(exc)[-400:], "fix": STEP_FIX}


def load_config_or_fail(root, failures: list):
    """The config after the steps, or None with a CONFIG_INVALID row. Only
    the config's own errors are caught; None means "write no settings"."""
    from engine import load_config
    try:
        import yaml
        errors = (HarnessError, yaml.YAMLError)
    except ImportError:          # load_config reports the missing PyYAML
        errors = (HarnessError,)
    try:
        return load_config(root)
    except errors as exc:
        failures.append({"check": "schema", "code": "CONFIG_INVALID", "text": str(exc),
                         "fix": "correct .harness/config.yaml, then run: harness upgrade --yes"})
        return None


def run_stage(failures: list, stage: str, func, default=None):
    """Run one stage. An exception becomes a STAGE_FAILED row; the upgrade goes on."""
    try:
        return func()
    except Exception as exc:  # the report must come back after any write
        failures.append(stage_failure(stage, exc))
        return default


def reported_step_errors(rows) -> list:
    return [{"check": "upgrade", "code": "STEP_FAILED",
             "text": clip_words(str(row["error"]), STEP_ERROR_WORDS),
             "step": row["id"], "fix": STEP_FIX}
            for row in rows if row.get("error")]


def upgrade_status(*, schema_from, current, files, steps, pending, failures) -> str:
    """A declined destructive step leaves the upgrade "incomplete"."""
    if any(f.get("code") in ("STEP_FAILED", "STAGE_FAILED") for f in failures):
        return "failed"
    skipped = any(NEEDS_CONFIRMATION in line for row in steps for line in step_lines(row))
    if pending or skipped:
        return "incomplete"
    if failures:
        return "checks failed"
    if schema_from == current and not any(files.values()):
        return "already on 0.10"
    return "upgraded"


def make_ask(yes: bool, stdin=None, stderr=None):
    """The `Ask` the 0.10 steps call before they move or delete files.

    `--yes` accepts every prompt. Without a TTY the answer is no, so CI and
    pipes never wait; the step then reports "skipped: needs confirmation".
    With no streams given, it is `upgrade_010.tty_ask`.
    """
    from engine import upgrade_010
    if yes:
        return upgrade_010.always_yes
    if stdin is None and stderr is None:
        return lambda question: upgrade_010.tty_ask(question)
    stdin = stdin if stdin is not None else sys.stdin
    stderr = stderr if stderr is not None else sys.stderr

    def ask(question: str) -> bool:
        if not stdin.isatty():
            return False
        stderr.write(f"{question} [y/N] ")
        stderr.flush()
        return stdin.readline().strip().lower() in ("y", "yes")
    return ask


def step_warnings(steps: list, workflow: dict, claude: dict, codex: dict) -> list:
    from engine.upgrade_010 import SKIPPED
    out = [f"{row['id']}: {SKIPPED}. Run: harness upgrade --yes"
           for row in steps if SKIPPED in row.get("report", [])]
    if workflow.get("note"):
        out.append(workflow["note"])
    out.extend(v["note"] for v in claude.values()
               if v.get("action") == "kept" and v.get("note"))
    if codex.get("warning"):
        out.append(codex["warning"])
    if codex.get("action") in ("missing", "kept"):
        out.append(codex["note"])
    return out


def dry_run_report(root: Path, version: int, plan: list, codex: dict) -> dict:
    """The schema preflight and the plan. Nothing here writes."""
    from engine import upgrade_010
    from engine.migrate import MIGRATIONS
    from engine.overrides import repair_legacy_overrides
    if version > SCHEMA_VERSION:
        raise HarnessError(
            f"substrate schema {version} is newer than engine "
            f"{SCHEMA_VERSION}; upgrade the plugin")
    missing = [v for v in range(version, SCHEMA_VERSION) if v not in MIGRATIONS]
    if missing:
        raise HarnessError(
            f"no migration path from schema {missing[0]} to "
            f"{SCHEMA_VERSION} (fail closed)")
    return {"dry_run": True, "plan": plan,
            "schema": {"from": version, "to": SCHEMA_VERSION,
                       "would_apply": list(range(version + 1, SCHEMA_VERSION + 1))},
            "engine_version": ENGINE_VERSION,
            "steps": upgrade_010.preview(root),
            "advice": upgrade_010.advice(root),
            "legacy_overrides": repair_legacy_overrides(root, dry_run=True),
            "codex_adapter": codex}
