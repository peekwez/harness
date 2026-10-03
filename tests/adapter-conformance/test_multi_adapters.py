"""Conformance for the Codex, Gemini CLI, and Cursor adapters: event
translation, verdict handling, injection format, compaction semantics,
inert-without-substrate. Same dimensions as the Claude Code adapter suite."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT / "tests"))
sys.path.insert(0, str(PLUGIN_ROOT))
from conftest import cite_non_goals  # noqa: E402

ADAPTERS = {
    "codex": PLUGIN_ROOT / "adapters" / "codex" / "adapter.py",
    "gemini": PLUGIN_ROOT / "adapters" / "gemini" / "adapter.py",
    "cursor": PLUGIN_ROOT / "adapters" / "cursor" / "adapter.py",
}

# per-adapter event names + deny shape probes
SPEC = {
    "codex": {
        "session_start": {"hook_event_name": "SessionStart"},
        "pre_change": lambda p: {"hook_event_name": "PreToolUse",
                                 "tool_name": "apply_patch",
                                 "tool_input": {"input": f"*** Update File: {p}\n@@..."}},
        "compact": {"hook_event_name": "PreCompact"},
        "ctx_of": lambda o: o["hookSpecificOutput"]["additionalContext"],
        "is_deny": lambda o: o["hookSpecificOutput"]["permissionDecision"] == "deny",
        "deny_reason": lambda o: o["hookSpecificOutput"]["permissionDecisionReason"],
    },
    "gemini": {
        "session_start": {"hook_event_name": "SessionStart"},
        "pre_change": lambda p: {"hook_event_name": "BeforeTool",
                                 "tool_name": "write_file",
                                 "tool_input": {"file_path": p}},
        "compact": {"hook_event_name": "PreCompress"},
        "ctx_of": lambda o: o["hookSpecificOutput"]["additionalContext"],
        "is_deny": lambda o: o["decision"] == "deny",
        "deny_reason": lambda o: o["reason"],
    },
    "cursor": {
        "session_start": {"hook_event_name": "sessionStart"},
        "pre_change": lambda p: {"hook_event_name": "preToolUse",
                                 "tool_input": {"file_path": p}},
        "compact": {"hook_event_name": "preCompact"},
        "ctx_of": lambda o: o["additional_context"],
        "is_deny": lambda o: o["permission"] == "deny",
        "deny_reason": lambda o: o["agent_message"],
    },
}


def run_adapter(name, hook_json, cwd, slice_id="slice-042", session="mc-1"):
    env = dict(os.environ)
    env["HARNESS_BIN"] = str(PLUGIN_ROOT / "bin" / "harness")
    if slice_id:
        env["HARNESS_SLICE"] = slice_id
    hook = dict(hook_json)
    hook.setdefault("session_id", session)
    hook.setdefault("conversation_id", session)  # cursor's name for it
    proc = subprocess.run([sys.executable, str(ADAPTERS[name])],
                          input=json.dumps(hook), capture_output=True,
                          text=True, cwd=str(cwd), env=env)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


def _drift_and_touch(toy, session):
    """Bind a G6 baseline, change telemetry's interface, record the touch."""
    from conftest import loaded_context, make_event
    from engine.events import handle_event
    loaded_context(toy, session=session)
    src = toy / "telemetry.py"
    src.write_text(src.read_text().replace(
        "def emit_span(name: str, attrs: dict) -> dict:",
        "def emit_span(name: str, attrs: dict, level: int = 0) -> dict:"))
    handle_event(make_event("post_change", session=session,
                            files=["telemetry.py"]), toy)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_allow_then_inject_then_allow(toy, name):
    spec = SPEC[name]
    session = f"{name}-flow"
    # 1. an edit before Phase 1 is allowed: context does not gate edits
    code, out, err = run_adapter(name, spec["pre_change"]("orders.py"), toy,
                                 session=session)
    assert code == 0, err
    assert out is None or not spec["is_deny"](out), out
    # 2. session start -> context injection in the host's dialect
    code, out, err = run_adapter(name, spec["session_start"], toy,
                                 session=session)
    assert code == 0
    assert "D-041" in spec["ctx_of"](out)
    # 3. the same edit is still allowed
    code, out, err = run_adapter(name, spec["pre_change"]("orders.py"), toy,
                                 session=session)
    assert code == 0
    if out is not None:  # cursor emits explicit allow; codex/gemini stay silent
        assert not spec["is_deny"](out)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_non_goal_boundary_denied(toy, name):
    cite_non_goals(toy, "adr:007")
    spec = SPEC[name]
    session = f"{name}-ng"
    run_adapter(name, spec["session_start"], toy, session=session)
    code, out, err = run_adapter(name, spec["pre_change"]("legacy/exporter.py"),
                                 toy, session=session)
    assert spec["is_deny"](out)
    assert "NON_GOAL" in spec["deny_reason"](out)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_compaction_counted_and_nothing_injected(toy, name):
    spec = SPEC[name]
    events = toy / ".harness" / "cache" / "events.jsonl"
    before = events.read_text() if events.exists() else ""
    code, out, err = run_adapter(name, spec["compact"], toy)
    assert code == 0 and out is None, (out, err)
    after = events.read_text()
    assert "COMPACTION_REACHED" in after and "COMPACTION_REACHED" not in before


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_inert_without_substrate(tmp_path, name):
    spec = SPEC[name]
    bare = tmp_path / "bare"
    bare.mkdir()
    code, out, err = run_adapter(name, spec["pre_change"]("a.py"), bare,
                                 slice_id=None)
    assert code == 0
    assert out is None or not spec["is_deny"](out)


def test_codex_stop_loop_guard(toy):
    _drift_and_touch(toy, "mc-1")
    code, out, err = run_adapter("codex", {"hook_event_name": "Stop"}, toy)
    assert out["decision"] == "block" and "INTERFACE_DRIFT" in out["reason"]
    code, out, err = run_adapter(
        "codex", {"hook_event_name": "Stop", "stop_hook_active": True}, toy)
    assert out is None  # never re-block


def test_cursor_stop_uses_followup_and_loop_count(toy):
    _drift_and_touch(toy, "mc-1")
    code, out, err = run_adapter("cursor", {"hook_event_name": "stop",
                                            "loop_count": 0}, toy)
    assert "followup_message" in out and "INTERFACE_DRIFT" in out["followup_message"]
    code, out, err = run_adapter("cursor", {"hook_event_name": "stop",
                                            "loop_count": 5}, toy)
    assert out is None  # loop guard


def test_gemini_after_agent_blocks_once(toy):
    _drift_and_touch(toy, "mc-1")
    code, out, err = run_adapter("gemini", {"hook_event_name": "AfterAgent"}, toy)
    assert out["decision"] == "block"
    code, out, err = run_adapter("gemini", {"hook_event_name": "AfterAgent",
                                            "agent_loop_active": True}, toy)
    assert out is None


def test_pi_extension_parses_as_typescript():
    """No TS runtime in this suite: strip types via a tolerant regex pass and
    require node to accept the result as ESM — catches gross syntax errors."""
    import re
    import shutil
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = (PLUGIN_ROOT / "adapters" / "pi" / "harness.ts").read_text()
    js = re.sub(r"^type Verdict = \{.*?\};\n", "", src, flags=re.S | re.M)
    js = re.sub(r"import \* as path.*\n", "import * as path from 'node:path';\n", js)
    js = re.sub(r": (Verdict|string\[\]|string \| null|string|unknown|void|any)"
                r"(\[\])?(?=[,)\s=])", "", js)
    js = js.replace(" as Verdict", "").replace(" as Record<string, unknown>", "")
    js = re.sub(r"<[A-Za-z, \[\]{}:;|]+>(?=\()", "", js)
    proc = subprocess.run(["node", "--input-type=module", "--check", "-"],
                          input=js, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[:800]


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_compaction_clears_hashes_so_session_start_reinjects(toy, name):
    spec = SPEC[name]
    session = f"{name}-compact"
    code, out, err = run_adapter(name, spec["session_start"], toy, session=session)
    assert "D-041" in spec["ctx_of"](out)
    code, out, err = run_adapter(name, spec["session_start"], toy, session=session)
    assert out is None, "unchanged blocks are not sent again"
    code, out, err = run_adapter(name, spec["compact"], toy, session=session)
    assert code == 0, err
    code, out, err = run_adapter(name, spec["session_start"], toy, session=session)
    assert "D-041" in spec["ctx_of"](out)
