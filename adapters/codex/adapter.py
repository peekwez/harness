#!/usr/bin/env python3
"""OpenAI Codex CLI adapter (hooks GA 2026-05).

Codex adopted the Claude Code hook wire shape, so this is a near-1:1
translation. Bindings (register via adapters/codex/hooks.json):

  SessionStart      -> session_start   (additionalContext injection)
  UserPromptSubmit  -> pre_context     (additionalContext injection)
  PreToolUse        -> pre_change      (permissionDecision deny; matcher
                                        apply_patch aliases Edit|Write)
  PostToolUse       -> post_change     (decision block replaces tool result)
  Stop              -> unit_complete   (decision block forces continuation)
  PreCompact        -> memory flush + COMPACTION_REACHED telemetry ONLY

Codex documents PreToolUse as "a guardrail rather than a complete
enforcement boundary" (unified_exec paths not yet intercepted) — keep
`harness verify` in CI as the backstop.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import (call_engine, clip, emit, extract_paths,  # noqa: E402
                    flush_compaction, injections_text, permit, reasons_text)

ENGINE_EVENT = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "pre_context",
    "PreToolUse": "pre_change",
    "PostToolUse": "post_change",
    "Stop": "unit_complete",
}


def main():
    hook = json.load(sys.stdin)
    name = hook.get("hook_event_name", "")
    session = hook.get("session_id", "codex-session")

    if name in ("PreCompact",):
        return flush_compaction(session)
    if name not in ENGINE_EVENT:
        return 0

    files = extract_paths(hook.get("tool_input"))
    verdict = call_engine(ENGINE_EVENT[name], session, files=files,
                          prompt=hook.get("prompt"))
    if verdict.get("inert"):
        return 0
    reasons = reasons_text(verdict)
    injections = injections_text(verdict)
    slice_id = os.environ.get("HARNESS_SLICE")

    if name in ("SessionStart", "UserPromptSubmit"):
        ctx = (injections + ("\n\n" + reasons if reasons else "")).strip()
        if ctx:
            emit({"hookSpecificOutput": {"hookEventName": name,
                                         "additionalContext": clip(ctx, slice_id)}})
        return 0

    if name == "PreToolUse":
        if verdict["verdict"] == "block":
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": clip(reasons or
                                                 "blocked by harness gates",
                                                 slice_id)}})
        elif files:
            # the gates are the approval layer: declared work inside the
            # bound slice never stops for a prompt
            allowed, why = permit(session, files=files, cwd=hook.get("cwd"))
            if allowed:
                emit({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": f"harness: {why}"}})
        return 0

    if name == "PostToolUse":
        if verdict["verdict"] == "block":
            emit({"decision": "block", "reason": clip(reasons, slice_id)})
        elif reasons:
            emit({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                         "additionalContext": clip(reasons, slice_id)}})
        return 0

    if name == "Stop":
        # never loop: respect the host's already-continued flag
        if verdict["verdict"] == "block" and not hook.get("stop_hook_active"):
            emit({"decision": "block", "reason": clip(reasons, slice_id)})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
