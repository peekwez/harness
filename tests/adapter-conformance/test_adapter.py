"""Adapter conformance suite: event translation, verdict handling, injection
format. Any future framework adapter must pass the equivalents of these.
PreCompact: memory flush + COMPACTION_REACHED telemetry ONLY, no injection."""
import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT / "tests"))
sys.path.insert(0, str(PLUGIN_ROOT))

ADAPTER = PLUGIN_ROOT / "hooks" / "adapter.py"


def run_adapter(hook_json, cwd, slice_id=None):
    env = dict(os.environ)
    env["HARNESS_BIN"] = str(PLUGIN_ROOT / "bin" / "harness")
    if slice_id:
        env["HARNESS_SLICE"] = slice_id
    proc = subprocess.run([sys.executable, str(ADAPTER)],
                          input=json.dumps(hook_json), capture_output=True,
                          text=True, cwd=str(cwd), env=env)
    out = None
    if proc.stdout.strip():
        out = json.loads(proc.stdout)
    return proc.returncode, out, proc.stderr


def test_session_start_translates_and_injects(toy):
    code, out, err = run_adapter(
        {"hook_event_name": "SessionStart", "session_id": "ac-1"},
        toy, slice_id="slice-042")
    assert code == 0, err
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "shadow:telemetry" in ctx or "emit_span" in ctx  # injection format


def test_pre_tool_use_deny_with_reason(toy):
    code, out, err = run_adapter(
        {"hook_event_name": "PreToolUse", "session_id": "ac-2",
         "tool_name": "Edit",
         "tool_input": {"file_path": str(toy / "orders.py")}},
        toy, slice_id="slice-042")
    assert code == 0
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "gate:G2" in hso["permissionDecisionReason"]


def test_pre_tool_use_allows_after_session_start(toy):
    run_adapter({"hook_event_name": "SessionStart", "session_id": "ac-3"},
                toy, slice_id="slice-042")
    code, out, err = run_adapter(
        {"hook_event_name": "PreToolUse", "session_id": "ac-3",
         "tool_name": "Edit",
         "tool_input": {"file_path": str(toy / "orders.py")}},
        toy, slice_id="slice-042")
    assert code == 0 and out is None  # silent allow


def test_post_tool_use_findings_as_context(toy):
    run_adapter({"hook_event_name": "SessionStart", "session_id": "ac-4"},
                toy, slice_id="slice-042")
    (toy / "main.rb").write_text("puts 1\n")
    code, out, err = run_adapter(
        {"hook_event_name": "PostToolUse", "session_id": "ac-4",
         "tool_name": "Write",
         "tool_input": {"file_path": str(toy / "main.rb")}},
        toy, slice_id="slice-042")
    assert code == 0
    assert "UNSHADOWED_FILE" in out["hookSpecificOutput"]["additionalContext"]


def test_stop_maps_to_unit_complete_and_can_block(toy):
    run_adapter({"hook_event_name": "SessionStart", "session_id": "ac-5"},
                toy, slice_id="slice-042")
    # hand-edit a derived shadow -> G7 must block the Stop
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    s = json.loads(sp.read_text())
    s["symbols"][0]["signature"] = "hacked"
    sp.write_text(json.dumps(s, sort_keys=True, indent=1) + "\n")
    code, out, err = run_adapter(
        {"hook_event_name": "Stop", "session_id": "ac-5"},
        toy, slice_id="slice-042")
    assert code == 0
    assert out["decision"] == "block"
    assert "DERIVATION_MISMATCH" in out["reason"]


def test_stop_hook_active_prevents_reblock_loop(toy):
    """Docs: a Stop hook must check stop_hook_active and not re-block —
    Claude Code force-overrides after 8 consecutive blocks anyway."""
    run_adapter({"hook_event_name": "SessionStart", "session_id": "ac-loop"},
                toy, slice_id="slice-042")
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    s = json.loads(sp.read_text())
    s["symbols"][0]["signature"] = "hacked"
    sp.write_text(json.dumps(s, sort_keys=True, indent=1) + "\n")
    # first Stop: blocks
    code, out, err = run_adapter(
        {"hook_event_name": "Stop", "session_id": "ac-loop"},
        toy, slice_id="slice-042")
    assert out and out["decision"] == "block"
    # second Stop with stop_hook_active: must NOT block again
    code, out, err = run_adapter(
        {"hook_event_name": "Stop", "session_id": "ac-loop",
         "stop_hook_active": True},
        toy, slice_id="slice-042")
    assert code == 0 and out is None


def test_injection_clipped_under_hook_output_cap():
    """Docs: hook output strings are capped at 10,000 chars; the adapter must
    clip and point at the full resolve command instead of overflowing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adapter", str(PLUGIN_ROOT / "hooks" / "adapter.py"))
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    huge = "x" * 40000
    clipped = adapter.clip(huge, "slice-042")
    assert len(clipped) <= 10000
    assert "harness" in clipped and "slice-042" in clipped
    assert adapter.clip("short", "slice-042") == "short"


def test_precompact_flush_and_telemetry_only(toy):
    telemetry_file = toy / ".harness" / "telemetry.jsonl"
    before = telemetry_file.read_text()
    code, out, err = run_adapter(
        {"hook_event_name": "PreCompact", "session_id": "ac-6"},
        toy, slice_id="slice-042")
    assert code == 0
    assert out is None, "PreCompact must not inject anything"
    after = telemetry_file.read_text()
    assert "COMPACTION_REACHED" in after and "COMPACTION_REACHED" not in before


def test_unbound_hook_is_noop(toy):
    code, out, err = run_adapter(
        {"hook_event_name": "Notification", "session_id": "ac-7"}, toy)
    assert code == 0 and out is None


def test_hooks_json_binds_all_required_events():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "UserPromptSubmit", "PreToolUse",
                          "PostToolUse", "Stop", "PreCompact"}
    for name in ("PreToolUse", "PostToolUse"):
        assert hooks[name][0]["matcher"] == "Edit|Write|MultiEdit"


def test_gates_declare_preferred_and_fallback_events():
    """T1 portability: pre_change gates declare post_change fallbacks so
    post-only frameworks can run degraded revert-and-retry mode."""
    from engine.gates import all_gates, gates_for_event
    for g in all_gates():
        assert "preferred" in g.GATE and "fallback" in g.GATE
    normal = {g.GATE["id"] for g in gates_for_event("post_change")}
    degraded = {g.GATE["id"] for g in gates_for_event("post_change", degraded=True)}
    assert {"G2", "G3"} <= (degraded - normal), \
        "degraded mode must re-run pre_change gates at post_change"
    assert degraded > normal


def test_plugin_inert_in_repo_without_substrate(tmp_path):
    """Deliberate stance: repos that never ran /harness:init are not
    enforced — installing the plugin must not brick Edit everywhere."""
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "app.py").write_text("x = 1\n")
    code, out, err = run_adapter(
        {"hook_event_name": "PreToolUse", "session_id": "inert-1",
         "tool_name": "Edit", "tool_input": {"file_path": str(bare / "app.py")}},
        bare)
    assert code == 0 and out is None  # silent allow, no deny, no crash
    code, out, err = run_adapter(
        {"hook_event_name": "PreCompact", "session_id": "inert-1"}, bare)
    assert code == 0 and out is None
