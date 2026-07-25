#!/usr/bin/env python3
"""Cursor adapter (IDE agent hooks; camelCase events, permission verdicts).

Bindings (register via adapters/cursor/hooks.json):

  sessionStart       -> session_start  (additional_context injection)
  beforeSubmitPrompt -> pre_context    (attachments/context; never blocks)
  preToolUse         -> pre_change     (permission deny; matcher Write|Delete)
  afterFileEdit      -> post_change    (observe-only in Cursor)
  stop               -> unit_complete  (followup_message to continue)
  preCompact         -> memory flush + COMPACTION_REACHED telemetry ONLY

Set "failClosed": true on preToolUse (Cursor hooks default to fail-open).
Cursor CLI (headless) does not fire preToolUse yet — it runs harness in
degraded post-only mode (see ADAPTERS.md); Cursor can also load Claude Code
hook configs directly via Settings -> Third-party skills as an alternative
to this adapter.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import (call_engine, clip, emit, extract_paths,  # noqa: E402
                    flush_compaction, injections_text, reasons_text)

ENGINE_EVENT = {
    "sessionStart": "session_start",
    "beforeSubmitPrompt": "pre_context",
    "preToolUse": "pre_change",
    "afterFileEdit": "post_change",
    "stop": "unit_complete",
}

MAX_STOP_CONTINUATIONS = 2


def _files(hook):
    if hook.get("hook_event_name") == "afterFileEdit":
        return [hook["file_path"]] if hook.get("file_path") else []
    return extract_paths(hook.get("tool_input") or hook.get("input"))


def main():
    hook = json.load(sys.stdin)
    name = hook.get("hook_event_name", "")
    session = (hook.get("conversation_id") or hook.get("session_id")
               or "cursor-session")

    if name == "preCompact":
        return flush_compaction(session)
    if name not in ENGINE_EVENT:
        return 0

    verdict = call_engine(ENGINE_EVENT[name], session, files=_files(hook),
                          prompt=hook.get("prompt"))
    if verdict.get("inert"):
        return 0
    reasons = reasons_text(verdict)
    injections = injections_text(verdict)
    slice_id = os.environ.get("HARNESS_SLICE")

    if name == "sessionStart":
        ctx = (injections + ("\n\n" + reasons if reasons else "")).strip()
        if ctx:
            emit({"additional_context": clip(ctx, slice_id)})
        return 0

    if name == "beforeSubmitPrompt":
        out = {"continue": True}
        ctx = injections.strip()
        if ctx:
            out["additional_context"] = clip(ctx, slice_id)
        emit(out)
        return 0

    if name == "preToolUse":
        if verdict["verdict"] == "block":
            emit({"permission": "deny",
                  "agent_message": clip(reasons or "blocked by harness gates",
                                        slice_id)})
        else:
            emit({"permission": "allow"})
        return 0

    if name == "afterFileEdit":
        # observe-only in Cursor; the engine still records touches/shadows.
        return 0

    if name == "stop":
        # loop guard: Cursor supplies loop_count; never continue forever
        if verdict["verdict"] == "block" and \
                int(hook.get("loop_count", 0)) < MAX_STOP_CONTINUATIONS:
            emit({"followup_message": clip(
                "harness gates block completion — fix and finish:\n" + reasons,
                slice_id)})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
