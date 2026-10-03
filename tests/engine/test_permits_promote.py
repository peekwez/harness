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
    "harness memory pro''mote --text x",
    'harness memory "pro"mote',
    "harness memory pro\\mote",
    "harness memory promot\\e",
    'harness mem""ory promote',
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


REDIRECT_PROBES = [
    "harness verify > .claude/memory/sh*/a.md",
    "harness verify > .claude/memory/sh?red/a.md",
    "harness verify > .claude/memory/[s]hared/a.md",
    "harness verify > .claude/memory/{shared,x}/a.md",
    "harness verify > .claude/memory/s\\hared/a.md",
    "cd .claude/memory && harness verify > shared/a.md",
    "cd .claude && harness verify > memory/shared/a.md",
    "cd .claude/memory && pytest > shared/a.md",
    "pytest > log.txt",
    "echo x > notes.txt",
    "harness verify &> out.txt",
    "harness verify >| out.txt",
    "harness verify 2> err.txt",
]


@pytest.mark.parametrize("command", REDIRECT_PROBES)
def test_file_redirects_are_never_auto_approved(command):
    decision, allow, _ = command_decision(command, slice_id="slice-042")
    assert allow is False and decision != "allow"


@pytest.mark.parametrize("command", [
    "echo hi", "ls 2>/dev/null", "pytest -q 2>&1", "harness verify >/dev/null",
    "harness verify &>/dev/null", "echo x 1>&2", "pytest 2>&1 >/dev/null",
])
def test_harmless_redirects_stay_auto_approved(command):
    assert command_allowed(command, slice_id="s")[0] is True


def test_autonomy_profile_asks_before_promote():
    profile = json.loads(
        (PLUGIN_ROOT / "templates" / "claude-settings.json").read_text())
    perms = profile["permissions"]
    harness_allows = [r for r in perms["allow"] if "bin/harness" in r]
    assert harness_allows
    for rule in harness_allows:
        assert rule.replace(":*)", " memory promote:*)") in perms["ask"]


PROBES = ['echo "a" >x', "echo 'a'>x", 'harness verify <<< x', 'harness verify <<<"a>b"', 'harness verify | tee >(cat > f)', 'harness verify | tee .claude/memory/shared/a.md', 'harness verify>f', 'harness verify 3>f', 'harness verify >&out.txt', 'harness verify >&2x', 'echo x >&2x', "echo \\' > f \\'", "cd .claude/memory && echo \\' > shared/a.md \\'", "echo \\' > .claude/memory/sh*/a.md \\'", 'echo \\" > f \\"', 'harness verify "\\" > f \\""', 'echo a\\"b > f "c"', 'harness verify 2>/dev/null>f', 'harness verify >/dev/null2', 'harness verify &>>/dev/null', 'harness verify > /dev/null', 'harness verify 1>/dev/null 2>&1', 'harness verify <> f', 'git diff --output=.claude/memory/shared/x HEAD', 'cd .claude/memory && git diff --output=shared/a.md HEAD', 'cd .claude && git diff --output memory/shared/a.md HEAD', 'git diff --output=.claude/memory/{,shared}/a.md HEAD', 'git log --output=.claude/memory/s[h]ared/a.md', 'git mv a.md .claude/memory/s[h]ared', 'cd .claude/memory && git mv ../../a.md shared/', 'git diff --output=/tmp/r.diff main...HEAD', 'harness memory pro${x}mote --text x', 'harness memory ${P:-promote} --text x', "harness memory pro$'m'ote --text x", "harness memory $'promote' --text x", 'harness memory -- promote --text x', 'harness memory prom* --text x', 'harness memory\\ promote', 'harness   memory\tpromote --text x', 'harness memory promote', "harness memory 'promote'", 'HARNESS=1 /x/bin/harness memory promote', 'python3 -m engine.cli memory promote --text x', '/x/bin/harness --root . memory "pro"\'mo\'te']


@pytest.mark.parametrize("command", PROBES)
def test_review_probes_are_never_auto_approved(command):
    decision, allow, _ = command_decision(command, slice_id="slice-042")
    assert allow is False and decision != "allow"


@pytest.mark.parametrize("command", [
    "pytest -q tests/x.py 2>&1", "harness verify", "git status",
    "harness memory changed --slice s1", "cd /repo && git diff HEAD",
    "/plug/bin/harness close-slice --slice s1 --commit HEAD",
    "${CLAUDE_PLUGIN_ROOT}/bin/harness verify",
    '"${CLAUDE_PLUGIN_ROOT}/bin/harness" verify',
    "git diff --stat HEAD", "python3 -m pytest tests/x.py -q",
])
def test_plain_commands_stay_auto_approved(command):
    assert command_decision(command, slice_id="s1")[0] == "allow"


@pytest.mark.parametrize("command", [
    "harness memory compact", "harness memory", "git log --out=x.txt",
    "cd .claude && git status", "cd ../.CLAUDE/memory",
    "git -C .claude/memory status",
])
def test_other_memory_subcommands_and_claude_dir_are_not_auto_approved(command):
    assert command_decision(command, slice_id="s1")[0] != "allow"


@pytest.mark.parametrize("command", [
    'git commit -m "multi word"', "git commit -m 'it''s fine'",
    'pytest -k "a and b"', "git commit -m 'a > b; c | d'",
    'git commit -m "a && b"', "git add -A && git commit -m 'both'",
])
def test_quoted_arguments_stay_auto_approved(command):
    assert command_decision(command, slice_id="s1")[0] == "allow"


@pytest.mark.parametrize("command", [
    'echo "$HOME" > f', 'git commit -m "$(cat x)"', 'git commit -m "a\\"b"',
    "echo 'a' > f", "cd '.claude/memory'", 'cd ".claude"', "git commit -m 'x",
    'git commit -m "a`id`b"', 'git commit -m "hi!"', "echo a\\ b",
    "git log --output='x.txt'", "harness verify 'a;b' > f", "echo 'a'>x",
])
def test_quoted_hazards_are_not_auto_approved(command):
    assert command_decision(command, slice_id="s1")[0] != "allow"


def test_quoted_promote_asks():
    assert command_decision("harness memory 'promote' --text x",
                            slice_id="s1")[:2] == ("ask", False)


# Round 4: under the shipped profile a `defer` runs the command, so every
# protective outcome is `ask`.
@pytest.mark.parametrize("command", [
    "/plug/bin/harness me${x}mory promote a", "/plug/bin/harness mem$'o'ry promote a",
    "/plug/bin/harness $'\\x6demory' promote a",
    "/plug/bin/har${x}ness memory promote a", "/plug/bin/harnes? memory promote a",
    "/plug/bin/harnes[s] memory promote a", "/plug/bin/HARNESS me${x}mory promote a",
    "/plug/bin/HARNESS memory promote a",
])
def test_unresolved_harness_spellings_ask(command):
    assert command_decision(command, slice_id="s1")[:2] == ("ask", False)


@pytest.mark.parametrize("command", [
    "echo x > .claude/memory/shared/a.md", "cp a.md .claude/memory/shared/",
    "git mv a.md .claude/memory/shared/a.md",
])
def test_shared_memory_touch_asks(command):
    assert command_decision(command, slice_id="s1")[:2] == ("ask", False)


@pytest.mark.parametrize("command", [
    'harness memory "changed"', "harness memory 'changed'",
    "harness memory changed; git status", "harness memory changed&&git status",
    "git diff HEAD~1", "git log HEAD~3..HEAD", "git show HEAD^",
    "git reset --hard HEAD~1",
])
def test_round4_plain_commands_are_allowed(command):
    assert command_decision(command, slice_id="s1")[0] == "allow"


@pytest.mark.parametrize("command", [
    "ls ~", "ls ~/x", "git diff ~1", "X=~/a git status", "git log a:~/b",
    "git show ^HEAD", "git log @{u}",
])
def test_tilde_and_caret_that_bash_expands_are_not_allowed(command):
    assert command_decision(command, slice_id="s1")[0] != "allow"


def test_permit_cli_asks_for_shared_memory_without_a_bound_slice(toy):
    proc = run_cli("permit", "--command", "cp a.md .claude/memory/shared/",
                   "--session", "nobody", root=toy,
                   env={"CLAUDE_SESSION_ID": ""})
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["decision"] == "ask" and out["allow"] is False
