"""A human approves each `harness memory promote` (spec section 8)."""
import json

import pytest

from conftest import PLUGIN_ROOT, run_cli
from engine.permits import (command_allowed, command_decision, needs_human,
                            paths_in_scope)

PROMOTE_FORMS = [
    "harness memory promote --text 'x'",
    '"/plug/bin/harness" memory promote /tmp/a.md',
    "python3 /plug/bin/harness --root /repo memory promote --text x",
    "cd /repo && /plug/bin/harness memory promote a.md",
    "bash -c '/plug/bin/harness memory  promote a.md'",
    "bin/harness --root /repo memory promote a.md",
    '${CLAUDE_PLUGIN_ROOT}/bin/harness memory promote a.md',
]


@pytest.mark.parametrize("command", PROMOTE_FORMS)
def test_promote_is_never_auto_approved(command):
    assert needs_human(command)
    decision, allow, reason = command_decision(command, slice_id="slice-042")
    assert (decision, allow) == ("ask", False)
    assert "harness memory promote" in reason
    assert command_allowed(command, slice_id="slice-042")[0] is False


def test_other_harness_commands_stay_auto_approved():
    assert needs_human("/plug/bin/harness memory changed --slice s") is None
    assert command_decision("/plug/bin/harness verify",
                            slice_id="slice-042")[0] == "allow"


def test_permit_cli_asks_even_without_a_bound_slice(toy):
    proc = run_cli("permit", "--command", "harness memory promote --text x",
                   "--session", "nobody", root=toy,
                   env={"CLAUDE_SESSION_ID": ""})
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["decision"] == "ask" and out["allow"] is False


def test_paths_in_shared_memory_are_never_auto_approved():
    row = {"predicted_files": [".claude/memory/shared/x.md"],
           "acceptance": [], "declares_dep": []}
    assert paths_in_scope(row, [], [".claude/memory/shared/x.md"]) is False


SHARED_WRITES = [
    "echo x > .claude/memory/shared/a.md",
    "echo x >> .claude/memory/shared/MEMORY.md",
    "ls && echo hi > .claude/memory/shared/x",
    "echo x >.claude/memory/shared/a.md",
    "echo x > .claude/memory/./shared//a.md",
    "echo x > .claude/memory/other/../shared/a.md",
    "echo x > .CLAUDE/Memory/SHARED/a.md",
    "echo x > /repo/.claude/memory/shared/a.md",
    "cp /tmp/a.md .claude/memory/shared/a.md",
    "tee .claude/memory/shared/a.md",
    "cat <<EOF > .claude/memory/shared/a.md",
]


@pytest.mark.parametrize("command", SHARED_WRITES)
def test_commands_touching_shared_memory_are_not_auto_approved(command):
    decision, allow, _ = command_decision(command, slice_id="slice-042")
    assert allow is False and decision != "allow"


def test_echo_redirect_is_not_auto_approved_anywhere():
    assert command_allowed("echo x > notes.txt", slice_id="s")[0] is False
    assert command_allowed("echo hi", slice_id="s")[0] is True


def test_autonomy_profile_asks_before_promote():
    profile = json.loads(
        (PLUGIN_ROOT / "templates" / "claude-settings.json").read_text())
    perms = profile["permissions"]
    harness_allows = [r for r in perms["allow"] if "bin/harness" in r]
    assert harness_allows
    for rule in harness_allows:
        assert rule.replace(":*)", " memory promote:*)") in perms["ask"]
