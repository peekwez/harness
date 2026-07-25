"""Shared core for the non-Claude adapters (Codex, Gemini CLI, Cursor).

Each adapter translates only: host hook JSON -> the five-event engine
contract -> host verdict format. All policy lives in the engine.

Contract every adapter honors:
- repos without a .harness/ substrate are inert (allow everything);
- engine errors in an initialised repo fail closed (deny);
- Stop-style hooks never re-block in a loop (host loop guards respected);
- injections are clipped to stay under host output caps.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HARNESS = os.environ.get(
    "HARNESS_BIN",
    str(Path(__file__).resolve().parent.parent / "bin" / "harness"))

MAX_OUTPUT_CHARS = 9500

_PATCH_MARKER = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def resolve_root(files=None, cwd=None):
    """The substrate the event belongs to: walk up from the edited file
    first, then the given/process cwd. The hook process runs in the MAIN
    tree even when the builder edits inside a slice worktree — without
    this, worktree edits normalize to out-of-root paths and shadows never
    regenerate there (parallel-worktree field report W2). Every file is a
    candidate — the first that resolves wins. None -> engine default (its
    own cwd walk)."""
    for start in [*(files or []), cwd or os.getcwd()]:
        if not start:
            continue
        p = Path(start)
        if not p.is_absolute():
            p = Path(cwd or os.getcwd()) / p
        if not p.is_dir():   # file path (possibly not yet created)
            p = p.parent
        for cand in (p, *p.parents):
            if (cand / ".harness").is_dir():
                return cand
    return None


def permit(session: str, files=None, command=None, cwd=None) -> tuple:
    """(allow, reason) — would the bound slice's gates approve this tool
    call? A separate question from the enforcement verdict: the gates are
    the approval layer, so declared work never stops for a prompt. False
    means "not auto-approved", leaving the host's normal flow in charge."""
    root = resolve_root(files, cwd)
    cmd = [sys.executable, HARNESS]
    if root:
        cmd += ["--root", str(root)]
    cmd += ["permit"]
    if command is not None:
        cmd += ["--command", command]
    if files:
        cmd += ["--paths", *files]
    if session:
        cmd += ["--session", session]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return False, ""
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, ""
    return bool(out.get("allow")), out.get("reason", "")


def call_engine(event: str, session: str, files=None, prompt=None,
                slice_id=None) -> dict:
    payload = {
        "event": event,
        "session_id": session or "unknown-session",
        "work_unit_id": slice_id or os.environ.get("HARNESS_SLICE"),
        "payload": {
            "files": [{"path": f, "proposed_content_hash": None}
                      for f in (files or [])],
            "context_loaded": [], "diff": None, "prompt": prompt,
        },
    }
    root = resolve_root(files)
    cmd = [sys.executable, HARNESS]
    if root:
        cmd += ["--root", str(root)]
    proc = subprocess.run(cmd + ["event"],
                          input=json.dumps(payload),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        err = proc.stdout.strip() or proc.stderr.strip()
        if "no .harness substrate" in err:
            return {"verdict": "allow", "findings": [], "injections": [],
                    "inert": True}
        return {"verdict": "block", "findings": [], "injections": [],
                "engine_error": err}
    return json.loads(proc.stdout)


def extract_paths(tool_input) -> list:
    """Best-effort file paths from a host tool_input: common key names,
    nested edit lists, and apply_patch '*** Update File:' markers."""
    paths = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("file_path", "path", "absolute_path", "target_file",
                        "filePath", "file"):
                v = node.get(key)
                if isinstance(v, str) and v:
                    paths.append(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and "*** " in node:
            paths.extend(_PATCH_MARKER.findall(node))

    walk(tool_input if isinstance(tool_input, (dict, list)) else {})
    seen, out = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def reasons_text(verdict: dict) -> str:
    if verdict.get("engine_error"):
        return f"harness engine error: {verdict['engine_error']}"
    return "; ".join(
        f"[{f['code']} {f['rule_ref']}] {f['message']}"
        + (("\n" + "\n".join(f.get("inject", []))) if f.get("inject") else "")
        for f in verdict.get("findings", []))


def injections_text(verdict: dict) -> str:
    return "\n\n".join(verdict.get("injections", []))


def clip(text: str, slice_id=None) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    pointer = ("\n\n[harness: clipped to fit the host hook output cap; run "
               f"`harness resolve --slice {slice_id or '<active-slice>'}` "
               "for the full context]")
    return text[:MAX_OUTPUT_CHARS - len(pointer)] + pointer


def flush_compaction(session: str) -> int:
    """PreCompact duty: memory flush + COMPACTION_REACHED telemetry only."""
    root = resolve_root()
    cmd = [sys.executable, HARNESS]
    if root:
        cmd += ["--root", str(root)]
    proc = subprocess.run(cmd + ["memory", "flush",
                                 "--session", session or "unknown-session",
                                 "--compaction"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        err = proc.stdout.strip() or proc.stderr.strip()
        if "no .harness substrate" in err:
            return 0
        print(f"harness compaction flush failed: {err}", file=sys.stderr)
        return 1
    return 0


def emit(obj) -> None:
    print(json.dumps(obj))
