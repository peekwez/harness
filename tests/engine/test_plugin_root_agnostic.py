"""Nothing harness writes may name the plugin's install location.

`${CLAUDE_PLUGIN_ROOT}` is only defined while a skill of THIS plugin is
running; a `allowed-tools` rule or a generated `settings.json` that bakes in
the expanded path (`~/.claude/plugins/cache/harness@…/bin/harness`) breaks
the moment the plugin is reinstalled, versioned, or checked out somewhere
else on another machine — and a committed profile carrying `/Users/<name>/…`
is worse than useless to the next contributor (ADR-002, D-015).

The CI half of the same rule: the workflow that fetches the engine must be
able to clone a PRIVATE engine repo, which means an optional `HARNESS_TOKEN`
secret injected into the clone URL and never echoed.
"""
import json
import re

import yaml
from conftest import PLUGIN_ROOT, build_toy_repo, git, run_cli

ALLOWED_TOOLS = re.compile(r"^allowed-tools:\s*(.+)$", re.M)
FORBIDDEN = ("/Users", "plugins/cache", str(PLUGIN_ROOT))

CI_WORKFLOWS = (PLUGIN_ROOT / "templates" / "ci-verify.yml",
                PLUGIN_ROOT / ".github" / "workflows" / "harness-verify.yml")


def _allowed_tools():
    """Yield (path, value) for every SKILL.md frontmatter allowed-tools."""
    for path in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
        front = path.read_text().split("---", 2)
        if len(front) < 3:
            continue
        m = ALLOWED_TOOLS.search(front[1])
        if m:
            yield path, m.group(1).strip()


def _settings_text(root, name="settings.json"):
    return (root / ".claude" / name).read_text()


# ------------------------------------------------- skill frontmatter
def test_no_skill_allowed_tools_names_the_plugin_root():
    offenders = [f"{p.relative_to(PLUGIN_ROOT)}: {v}"
                 for p, v in _allowed_tools() if "CLAUDE_PLUGIN_ROOT" in v]
    assert not offenders, (
        "allowed-tools is matched against the command text the host sees; a "
        "rule naming ${CLAUDE_PLUGIN_ROOT} is install-path-specific — use "
        "Bash(*/bin/harness *):\n" + "\n".join(offenders))


def test_every_engine_rule_is_the_path_agnostic_form():
    seen = [v for _, v in _allowed_tools() if "bin/harness" in v]
    assert seen, "the loop skills must still pre-approve the engine"
    for value in seen:
        assert "Bash(*/bin/harness *)" in value, value


def test_preflights_may_still_use_the_plugin_root():
    """Only the frontmatter is install-path-sensitive: a `!`…` preflight is
    expanded by the host at invocation time, where the variable is defined."""
    body = (PLUGIN_ROOT / "skills" / "status" / "SKILL.md").read_text()
    assert '!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json`' in body


# ------------------------------------------------- generated settings
def test_init_autonomy_writes_no_absolute_plugin_path(tmp_path):
    root = tmp_path / "auto"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    proc = run_cli("init", "--autonomy", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = _settings_text(root)
    for needle in FORBIDDEN:
        assert needle not in text, f"{needle!r} leaked into the profile"
    rules = json.loads(text)["permissions"]["allow"]
    assert any("*/bin/harness" in r for r in rules), rules


def test_start_writes_no_absolute_plugin_path(tmp_path):
    toy = build_toy_repo(tmp_path / "toy")
    proc = run_cli("start", "--slice", "slice-042", "--session", "pra",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wt = toy / ".worktrees" / "slice-042"
    text = _settings_text(wt, "settings.local.json")
    for needle in FORBIDDEN:
        assert needle not in text, f"{needle!r} leaked into the worktree profile"


def test_the_note_for_a_hand_authored_profile_names_no_absolute_path(tmp_path):
    """The 'merge it yourself' hint is prose, but it printed the same
    absolute path — a user pasting it gets the same brittle rule."""
    root = tmp_path / "hand"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text('{"permissions": {}}')
    proc = run_cli("init", "--autonomy", root=root)
    assert proc.returncode == 0, proc.stderr
    assert "not touched" in proc.stdout
    assert str(PLUGIN_ROOT) not in proc.stdout, proc.stdout


# ------------------------------------------------- CI token
def test_ci_workflows_accept_a_token_for_a_private_engine_repo():
    for path in CI_WORKFLOWS:
        wf = yaml.safe_load(path.read_text())
        triggers = wf.get(True) or wf.get("on")   # bare `on:` parses as True
        secrets = triggers["workflow_call"]["secrets"]
        assert "HARNESS_TOKEN" in secrets, path
        assert secrets["HARNESS_TOKEN"]["required"] is False, path
        env = wf["jobs"]["verify"]["env"]
        assert env["HARNESS_TOKEN"] == "${{ secrets.HARNESS_TOKEN }}", path


def test_the_clone_never_echoes_the_credentialled_url():
    for path in CI_WORKFLOWS:
        wf = yaml.safe_load(path.read_text())
        step = next(s for s in wf["jobs"]["verify"]["steps"]
                    if "harness engine" in s.get("name", ""))
        clone = next(ln for ln in step["run"].splitlines()
                     if ln.strip().startswith("git clone"))
        assert "--quiet" in clone, f"{path}: {clone}"
        assert "x-access-token" in step["run"], path


def test_readme_documents_the_private_engine_repo_setup():
    body = (PLUGIN_ROOT / "README.md").read_text()
    assert "HARNESS_TOKEN" in body and "HARNESS_REPO" in body


# ------------------------------------------------- Codex as Layer 3
def test_codex_is_wired_as_a_second_layer3_advisory():
    """A second independent reviewer is only real if the files the reviewer
    actually reads say so — and it must inherit the findings contract."""
    missing = []
    for rel in ("skills/review/SKILL.md", "agents/reviewer.md",
                "templates/agents-md.md"):
        body = (PLUGIN_ROOT / rel).read_text()
        if "odex" not in body:
            missing.append(f"{rel}: no Codex hand-off")
        elif "record-finding" not in body:
            missing.append(f"{rel}: Codex findings bypass the findings contract")
    assert not missing, missing


def test_codex_never_fixes_inside_the_slice():
    body = (PLUGIN_ROOT / "skills" / "review" / "SKILL.md").read_text()
    assert "rule_ref" in body
    assert "auto-fix" in body, \
        "the reviewer must be told Codex never edits the slice"
