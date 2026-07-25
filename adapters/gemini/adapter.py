#!/usr/bin/env python3
"""Google Gemini CLI adapter (hooks GA v0.26+, 2026-01).

Bindings (register via adapters/gemini/settings-hooks.json):

  SessionStart -> session_start   (additionalContext injection)
  BeforeAgent  -> pre_context     (additionalContext injection)
  BeforeTool   -> pre_change      (decision deny; matcher write_file|replace)
  AfterTool    -> post_change     (additionalContext feedback)
  AfterAgent   -> unit_complete   (decision block forces another turn)
  PreCompress  -> memory flush + COMPACTION_REACHED telemetry ONLY

CAVEAT: Gemini CLI hooks are fail-open by design — a crashed hook lets the
action proceed with only a warning. harness compensates because `harness
verify` in CI is fail-closed; treat the hook layer as guidance-grade there.
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
    "BeforeAgent": "pre_context",
    "BeforeTool": "pre_change",
    "AfterTool": "post_change",
    "AfterAgent": "unit_complete",
}


def _tool_input(hook):
    for key in ("tool_input", "toolArgs", "args", "tool_args", "input"):
        if key in hook and hook[key] is not None:
            return hook[key]
    return hook.get("hookSpecificOutput", {}).get("tool_input")


def main():
    hook = json.load(sys.stdin)
    name = hook.get("hook_event_name", "")
    session = hook.get("session_id", "gemini-session")

    if name == "PreCompress":
        return flush_compaction(session)
    if name not in ENGINE_EVENT:
        return 0

    files = extract_paths(_tool_input(hook))
    verdict = call_engine(ENGINE_EVENT[name], session, files=files,
                          prompt=hook.get("prompt"))
    if verdict.get("inert"):
        return 0
    reasons = reasons_text(verdict)
    injections = injections_text(verdict)
    slice_id = os.environ.get("HARNESS_SLICE")

    if name in ("SessionStart", "BeforeAgent"):
        ctx = (injections + ("\n\n" + reasons if reasons else "")).strip()
        if ctx:
            emit({"hookSpecificOutput": {"hookEventName": name,
                                         "additionalContext": clip(ctx, slice_id)}})
        return 0

    if name == "BeforeTool":
        if verdict["verdict"] == "block":
            emit({"decision": "deny",
                  "reason": clip(reasons or "blocked by harness gates", slice_id)})
        elif files:
            # the gates are the approval layer: declared work inside the
            # bound slice never stops for a prompt
            allowed, why = permit(session, files=files, cwd=hook.get("cwd"))
            if allowed:
                emit({"decision": "allow", "reason": f"harness: {why}"})
        return 0

    if name == "AfterTool":
        if reasons:
            out = {"hookSpecificOutput": {"hookEventName": "AfterTool",
                                          "additionalContext": clip(reasons, slice_id)}}
            if verdict["verdict"] == "block":
                out["decision"] = "block"
                out["reason"] = clip(reasons, slice_id)
            emit(out)
        return 0

    if name == "AfterAgent":
        # loop guard: only block the first completion attempt per turn chain
        if verdict["verdict"] == "block" and not hook.get("agent_loop_active"):
            emit({"decision": "block", "reason": clip(reasons, slice_id)})
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
