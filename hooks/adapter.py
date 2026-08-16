#!/usr/bin/env python3
"""Claude Code adapter — translates only (~100 lines of framework awareness).

Claude Code hook JSON <-> the five-event engine contract. Porting harness to
another agent framework means writing one new file like this one.

Bindings: SessionStart->session_start, UserPromptSubmit->pre_context,
PreToolUse(Edit|Write|MultiEdit)->pre_change, PostToolUse(same)->post_change,
Stop->unit_complete, PreCompact->memory flush + COMPACTION_REACHED telemetry
ONLY (no re-injection: session cycling, not compaction, is the strategy).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HARNESS = os.environ.get(
    "HARNESS_BIN", str(Path(__file__).resolve().parent.parent / "bin" / "harness"))

EVENT_MAP = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "pre_context",
    "PreToolUse": "pre_change",
    "PostToolUse": "post_change",
    "Stop": "unit_complete",
}

# Claude Code caps hook output strings (additionalContext etc.) at 10,000
# characters; beyond that the text is dumped to a file with a preview, which
# would silently degrade Phase-1 injection. Clip with a pointer instead.
MAX_HOOK_OUTPUT_CHARS = 9500

# Fail-closed fallback for the one case the engine cannot answer: it is
# down. The adapter stays dependency-free (no yaml, no engine import — the
# engine being broken is exactly when importing it is a bad idea), so both
# checks below are deliberately crude text scans, and both only ever DENY.
_LANDING_LINE = re.compile(r"^landing:\s*$")
_MODE_PR = re.compile(r"^\s+mode:\s*[\"']?pr[\"']?\s*(#.*)?$")
_EGRESS_SHAPE = re.compile(
    r"(^|[\s;|&(`$])(gh|curl|wget|ssh|scp|sftp|rsync|nc|telnet)\b"
    r"|\bgit\b[^;|&]*?\b(push|fetch|pull|clone|remote|ls-remote|submodule"
    r"|send-email|request-pull)\b")
ENGINE_ERROR_DENY = ("harness engine error — egress refused, see the engine "
                     "output; run `harness doctor` (landing.mode: pr fails "
                     "closed on anything that talks to a remote)")


def pr_landing(root):
    """Whether `.harness/config.yaml` sets `landing.mode: pr`.

    A minimal text read, not a YAML parse: the adapter must keep working
    with no third-party import available, and the only decision it drives
    is a refusal.

    Args:
        root: The substrate root the event routed to; None walks up from the
            process cwd, the way the engine itself resolves a root (a Bash
            permission question carries no file to route on).

    Returns:
        True when the config declares pr landing.
    """
    start = Path(root) if root else Path(os.getcwd())
    config = None
    for cand in (start, *start.parents):
        if (cand / ".harness" / "config.yaml").is_file():
            config = cand / ".harness" / "config.yaml"
            break
    if config is None:
        return False
    try:
        lines = config.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    inside = False
    for line in lines:
        if _LANDING_LINE.match(line):
            inside = True
            continue
        if inside:
            if _MODE_PR.match(line):
                return True
            if line.strip() and not line[:1].isspace():
                inside = False
    return False


def egress_shaped(command):
    """Whether a command looks like it talks to a remote.

    Used only when the engine could not answer (`engine/permits.py` owns the
    real classification): over-refusing here costs a prompt, under-refusing
    costs an unreviewed push.

    Args:
        command: The command line the host asked about.

    Returns:
        True when the command mentions a remote-talking program.
    """
    return bool(_EGRESS_SHAPE.search(command or ""))


def clip(text, slice_id=None):
    if len(text) <= MAX_HOOK_OUTPUT_CHARS:
        return text
    pointer = ("\n\n[harness: injection clipped to fit Claude Code's 10k-char "
               "hook output cap; run "
               '"${CLAUDE_PLUGIN_ROOT}/bin/harness" resolve --slice '
               f"{slice_id or '<active-slice>'} for the full context]")
    return text[:MAX_HOOK_OUTPUT_CHARS - len(pointer)] + pointer


def files_from_tool_input(tool_input):
    files = []
    if not isinstance(tool_input, dict):
        return files
    if tool_input.get("file_path"):
        files.append({"path": tool_input["file_path"], "proposed_content_hash": None})
    for edit in tool_input.get("edits", []) or []:
        if isinstance(edit, dict) and edit.get("file_path"):
            files.append({"path": edit["file_path"], "proposed_content_hash": None})
    return files


def resolve_root(files, hook_cwd):
    """The substrate the event belongs to: walk up from the edited file
    first, then the hook's cwd. The hook process runs in the MAIN tree even
    when the builder edits inside a slice worktree — without this, worktree
    edits normalize to out-of-root paths and shadows never regenerate there
    (parallel-worktree field report W2). Every file is a candidate — the
    first that resolves wins, so a stray first file (scratchpad, /tmp) does
    not blind the routing. None -> engine default (cwd)."""
    candidates = [f["path"] for f in files] + [hook_cwd]
    for start in candidates:
        if not start:
            continue
        p = Path(start)
        if not p.is_absolute():
            p = Path(hook_cwd or os.getcwd()) / p
        if not p.is_dir():   # file path (possibly not yet created): walk
            p = p.parent     # up from its directory
        for cand in (p, *p.parents):
            if (cand / ".harness").is_dir():
                return cand
    return None


def permit(session, root=None, command=None, paths=None):
    """Ask the engine whether the bound slice's gates approve this tool call.

    A separate question from the enforcement verdict (which never grows
    fields): policy lives in engine/permits.py, the adapter only translates.

    Returns:
        `(decision, reason)` where decision is `allow` (auto-approve),
        `deny` (pr-mode egress outside D-011's surface — the settings profile
        cannot express "this slice's branch", so the hook is the decider) or
        `defer` (stay silent; the host's own flow decides).

        When the engine itself fails, a pr-mode repo denies anything
        egress-shaped rather than deferring: the profile has dropped its
        blanket push/fetch denies precisely because the hook decides, so
        silence there is an auto-approved push. The bound slice cannot be
        read with the engine down, so the repo-level mode is the fact used.
    """
    def _engine_down():
        if command and pr_landing(root) and egress_shaped(command):
            return "deny", ENGINE_ERROR_DENY
        return "defer", ""

    cmd = [sys.executable, HARNESS]
    if root:
        cmd += ["--root", str(root)]
    cmd += ["permit"]
    if command is not None:
        cmd += ["--command", command]
    if paths:
        cmd += ["--paths", *paths]
    if session:
        cmd += ["--session", session]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return _engine_down()
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _engine_down()
    return (out.get("decision") or ("allow" if out.get("allow") else "defer"),
            out.get("reason", ""))


def call_engine(event, root=None):
    cmd = [sys.executable, HARNESS]
    if root:
        cmd += ["--root", str(root)]
    proc = subprocess.run(cmd + ["event"],
                          input=json.dumps(event), capture_output=True, text=True)
    if proc.returncode != 0:
        err = proc.stdout.strip() or proc.stderr.strip()
        if "no .harness substrate" in err:
            # Deliberate stance: repos that never ran /harness:init are not
            # enforced — the plugin is inert there, not a global edit-brick.
            return {"verdict": "allow", "findings": [], "injections": [],
                    "inert": True}
        # Any other engine error in an initialised repo: fail loud + closed.
        return {"verdict": "block", "findings": [], "injections": [],
                "engine_error": err}
    return json.loads(proc.stdout)


def main():
    hook = json.load(sys.stdin)
    hook_name = hook.get("hook_event_name", "")
    session = hook.get("session_id", "unknown-session")

    root = resolve_root(files_from_tool_input(hook.get("tool_input")),
                        hook.get("cwd"))

    if hook_name == "PreCompact":
        # Flush + telemetry only. Compaction firing is a defect signal (§1.5).
        cmd = [sys.executable, HARNESS]
        if root:
            cmd += ["--root", str(root)]
        proc = subprocess.run(cmd + ["memory", "flush",
                                     "--session", session, "--compaction"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            err = proc.stdout.strip() or proc.stderr.strip()
            if "no .harness substrate" not in err:
                print(f"harness PreCompact flush failed: {err}", file=sys.stderr)
                return 1  # fail loud: losing the defect signal is itself a defect
        return 0

    # Bash is a permission question, not an EnforcementEvent: the five-event
    # contract is about file changes. A bound slice's own loop commands are
    # auto-approved so nothing stalls; anything else stays silent and the
    # host's normal permission flow decides.
    if hook_name == "PreToolUse" and hook.get("tool_name") == "Bash":
        command = (hook.get("tool_input") or {}).get("command", "")
        decision, reason = permit(session, root, command=command)
        if decision in ("allow", "deny"):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": f"harness: {reason}"}}))
        return 0

    engine_event = EVENT_MAP.get(hook_name)
    if engine_event is None:
        return 0  # unbound hook: nothing to translate

    verdict = call_engine({
        "event": engine_event,
        "session_id": session,
        "work_unit_id": os.environ.get("HARNESS_SLICE"),
        "payload": {
            "files": files_from_tool_input(hook.get("tool_input")),
            "context_loaded": [],
            "diff": None,
            "prompt": hook.get("prompt"),
        },
    }, root=root)

    reasons = "; ".join(
        f"[{f['code']} {f['rule_ref']}] {f['message']}"
        + (("\n" + "\n".join(f.get("inject", []))) if f.get("inject") else "")
        for f in verdict.get("findings", []))
    if verdict.get("engine_error"):
        reasons = f"harness engine error: {verdict['engine_error']}"
    injections = "\n\n".join(verdict.get("injections", []))

    if hook_name in ("SessionStart", "UserPromptSubmit"):
        if injections or reasons:
            ctx = (injections + ("\n\n" + reasons if reasons else "")).strip()
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": hook_name,
                "additionalContext": clip(ctx, os.environ.get("HARNESS_SLICE")),
            }}))
        return 0

    if hook_name == "PreToolUse":
        if verdict["verdict"] == "block":
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reasons or "blocked by harness gates",
            }}))
        elif not verdict.get("inert"):
            # The gates ARE the approval layer: an edit they allow, inside
            # the bound slice's declared scope, must not stop for a prompt.
            # Undeclared work stays silent here — wandering keeps its prompt.
            files = [f["path"] for f in
                     files_from_tool_input(hook.get("tool_input"))]
            decision, reason = permit(session, root, paths=files) if files \
                else ("defer", "")
            if decision == "allow":
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": f"harness: {reason}",
                }}))
        return 0

    if hook_name == "PostToolUse":
        if verdict["verdict"] == "block":
            print(json.dumps({"decision": "block", "reason": reasons}))
        elif reasons:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": reasons}}))
        return 0

    if hook_name == "Stop":
        # stop_hook_active means this hook already blocked this stop once —
        # re-blocking loops (Claude Code force-overrides after 8). The engine
        # event above still ran, so shadows/edges/telemetry are recorded.
        if verdict["verdict"] == "block" and not hook.get("stop_hook_active"):
            print(json.dumps({"decision": "block", "reason": clip(reasons)}))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
