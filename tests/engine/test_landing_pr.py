"""Landing modes (ADR-002 / D-009, D-010, D-011).

`local` is the historical behaviour and must stay byte-identical. `pr` makes
close-slice the landing: it pushes `slice/<id>` and opens a pull request,
`merge-slice` refuses, the permit layer auto-approves exactly the egress the
flow needs, and provenance survives the squash that lands the PR.
"""
import json

import pytest
from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine import HarnessError, read_jsonl
from engine.cli.landing import landing_config, pr_title
from engine.events import handle_event
from engine.permits import command_allowed

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")

NO_ENV = {"CLAUDE_SESSION_ID": ""}


def _fake_gh(tmp_path, extra=""):
    """A stand-in for `gh` that records its argv and the PR body, counts its
    invocations, and prints a URL the way the real one does."""
    script = tmp_path / "fake-gh.sh"
    args_file = tmp_path / "gh-args.txt"
    body_file = tmp_path / "gh-body.txt"
    script.write_text(
        "#!/bin/sh\n"
        f'echo call >> {tmp_path / "gh-calls.txt"}\n'
        f'printf "%s\\n" "$@" > {args_file}\n'
        'prev=""\n'
        'for a in "$@"; do\n'
        f'  if [ "$prev" = "--body-file" ]; then cp "$a" {body_file}; fi\n'
        '  prev="$a"\n'
        "done\n"
        f"{extra}\n"
        'echo "https://github.com/goodwork-eng/harness/pull/42"\n')
    script.chmod(0o755)
    return script, args_file, body_file


def _gh_calls(tmp_path):
    calls = tmp_path / "gh-calls.txt"
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def _pr_cmd(script):
    return (f"{script} pr create --base {{base}} --head {{branch}} "
            f"--title {{title}} --body-file {{body}}")


def _set_landing(root, **keys):
    cfg = (root / ".harness" / "config.yaml").read_text()
    block = "landing:\n" + "".join(f"  {k}: \"{v}\"\n" for k, v in keys.items())
    (root / ".harness" / "config.yaml").write_text(cfg + block)


def _pr_repo(tmp_path, pr_cmd="true", linear=None):
    """Toy repo whose `origin` is a bare repo, configured for pr landing and
    checked out on the slice branch."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "--initial-branch=main")
    toy = build_toy_repo(tmp_path / "work")
    git(toy, "branch", "-M", "main")
    _set_landing(toy, mode="pr", remote="origin", base="main", pr_cmd=pr_cmd)
    if linear:
        rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
        for r in rows:
            if r["id"] == "slice-042":
                r["linear"] = linear
        from engine import write_jsonl
        write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "landing config")
    git(toy, "remote", "add", "origin", str(origin))
    git(toy, "push", "-q", "origin", "main")
    git(toy, "checkout", "-q", "-b", "slice/slice-042")
    return toy, origin


def _work_and_commit(toy, session="pr"):
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    return session


def _close(toy, session="pr"):
    return run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy, env=NO_ENV)


def _row(toy, slice_id="slice-042"):
    return {r["id"]: r for r in
            read_jsonl(toy / ".harness" / "backlog.jsonl")}[slice_id]


# ------------------------------------------------------------------ config
def test_no_landing_key_is_local_mode():
    assert landing_config({})["mode"] == "local"
    assert landing_config({"landing": {}})["remote"] == "origin"
    assert landing_config(None)["base"] == "main"


def test_an_unknown_landing_mode_fails_loud():
    with pytest.raises(HarnessError) as exc:
        landing_config({"landing": {"mode": "bogus"}})
    assert "landing.mode" in str(exc.value) and "bogus" in str(exc.value)


def test_an_unknown_landing_key_names_itself():
    with pytest.raises(HarnessError) as exc:
        landing_config({"landing": {"branch": "x"}})
    assert "landing.branch" in str(exc.value)


def test_a_bogus_landing_mode_stops_the_cli(toy):
    _set_landing(toy, mode="bogus")
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1
    assert "landing.mode" in proc.stderr


def test_pr_title_carries_the_linear_id():
    assert pr_title({"id": "slice-042", "title": "orders"}) == \
        "orders (slice slice-042)"
    assert pr_title({"id": "slice-042", "title": "orders",
                     "linear": "GOO-75"}) == "GOO-75: orders (slice slice-042)"


# ------------------------------------------------------------------ D-009
def test_pr_mode_close_pushes_the_branch_and_opens_a_pr(tmp_path):
    script, args_file, body_file = _fake_gh(tmp_path)
    toy, origin = _pr_repo(tmp_path, pr_cmd=_pr_cmd(script), linear="GOO-75")
    main_before = git(origin, "rev-parse", "main").stdout.strip()
    _work_and_commit(toy)
    proc = _close(toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] and out["landed"] is True

    assert "refs/heads/slice/slice-042" in git(
        toy, "ls-remote", "origin", "refs/heads/slice/slice-042").stdout
    assert git(origin, "rev-parse", "main").stdout.strip() == main_before, \
        "pr landing must never write to the base branch"

    row = _row(toy)
    assert row["landed_via"] == "pr"
    assert row["pr_url"] == "https://github.com/goodwork-eng/harness/pull/42"
    assert out["pr_url"] == row["pr_url"]

    argv = args_file.read_text().splitlines()
    assert argv[:4] == ["pr", "create", "--base", "main"]
    assert "slice/slice-042" in argv
    assert "GOO-75: orders service (slice slice-042)" in argv
    body = body_file.read_text()
    assert "slice-042" in body
    assert "https://linear.app/goodwork-ai/issue/GOO-75" in body
    assert "tests/slices/042_orders.py" in body, "acceptance belongs in the PR"
    assert out["note_tree_hash"] and out["note_tree_hash"] in body


def test_a_failed_pr_command_still_records_the_close(tmp_path):
    toy, _ = _pr_repo(tmp_path, pr_cmd="false")
    _work_and_commit(toy)
    proc = _close(toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["closed"] is True and out["landed"] is False
    assert out["error"], "the agent must see why the landing failed"
    assert _row(toy)["status"] == "closed"


def test_merge_slice_refuses_in_pr_mode(tmp_path):
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    git(toy, "checkout", "-q", "main")
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["merged"] is False
    finding = next(f for f in out["findings"] if f["code"] == "LANDING_MODE_PR")
    assert finding["rule_ref"] == "adr:002"
    assert finding["severity"] == "block"


def test_run_refuses_in_pr_mode(tmp_path):
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    for extra in ([], ["--dry-run"]):
        proc = run_cli("run", *extra, root=toy, env=NO_ENV)
        assert proc.returncode == 1, proc.stdout
        assert "landing.mode" in proc.stderr


def test_local_mode_close_never_pushes(tmp_path):
    """Backward compatibility: no landing key -> nothing leaves the machine."""
    toy = build_toy_repo(tmp_path / "local")
    origin = tmp_path / "origin.git"
    origin.mkdir()
    git(origin, "init", "-q", "--bare", "--initial-branch=main")
    git(toy, "remote", "add", "origin", str(origin))
    _work_and_commit(toy)
    proc = _close(toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "landed" not in out and "pr_url" not in out
    assert not git(toy, "ls-remote", "origin").stdout.strip(), \
        "local mode must not touch the remote"
    assert "landed_via" not in _row(toy)


# ------------------------------------------------------------------ D-010
def _squash_land(toy, origin, tmp_path):
    """Land the pushed slice branch the way a squash-merge PR does, then
    bring the working repo to that main and make the noted commit
    unreachable."""
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    git(clone, "config", "user.email", "t@t")
    git(clone, "config", "user.name", "t")
    git(clone, "checkout", "-q", "main")
    assert git(clone, "merge", "--squash",
               "origin/slice/slice-042").returncode == 0
    git(clone, "commit", "-qm", "squash: slice-042 (#1)")
    assert git(clone, "push", "-q", "origin", "main").returncode == 0
    git(clone, "push", "-q", "origin", "--delete", "slice/slice-042")

    git(toy, "fetch", "-q", "--prune", "origin")
    git(toy, "fetch", "-q", "origin", "main:main")
    assert git(toy, "checkout", "-q", "main").returncode == 0
    git(toy, "branch", "-qD", "slice/slice-042")
    git(toy, "reflog", "expire", "--expire=now", "--all")
    git(toy, "gc", "-q", "--prune=now")


def test_a_squashed_slice_resolves_by_tree_hash(tmp_path):
    """The complaint ADR-002 records: the note lands on the pre-squash sha,
    so every squash used to leave verify reporting ORPHANED_NOTE forever."""
    toy, origin = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    noted = git(toy, "notes", "--ref=refs/notes/harness",
                "list").stdout.split()[1]
    rows = read_jsonl(toy / ".harness" / "notes.jsonl")
    assert [r for r in rows if r["slice_id"] == "slice-042"], \
        "the derived notes log is the second key"
    assert all({"ts", "slice_id", "commit", "tree_hash"} <= set(r) for r in rows)

    _squash_land(toy, origin, tmp_path)
    assert noted not in git(toy, "rev-list", "--all").stdout, \
        "the noted commit must be unreachable for this test to mean anything"

    proc = run_cli("verify", root=toy)
    out = json.loads(proc.stdout)
    codes = [f["code"] for f in out["findings"]]
    assert "ORPHANED_NOTE" not in codes and "MISSING_PROVENANCE_NOTE" not in codes
    assert proc.returncode == 0, proc.stdout
    assert out["resolved_via"]["slice-042"] == "tree_hash"


def test_a_squashed_slice_resolves_with_the_notes_ref_gone(tmp_path):
    """CI clones without `refs/notes/*`: the committed notes log is what
    proves provenance travelled with the repo (D-010)."""
    toy, origin = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    _squash_land(toy, origin, tmp_path)
    git(toy, "update-ref", "-d", "refs/notes/harness")
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 0, proc.stdout
    out = json.loads(proc.stdout)
    assert "MISSING_PROVENANCE_NOTE" not in [f["code"] for f in out["findings"]]
    assert out["resolved_via"]["slice-042"] in ("tree_hash", "notes_row")


def test_a_slice_with_neither_key_is_still_missing_provenance(toy):
    """The finding must not go toothless: no note and no notes.jsonl row is
    still a hole in the provenance chain."""
    session = _work_and_commit(toy, session="none")
    assert run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy, env=NO_ENV).returncode == 0
    git(toy, "update-ref", "-d", "refs/notes/harness")
    (toy / ".harness" / "notes.jsonl").unlink()
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    assert "MISSING_PROVENANCE_NOTE" in [f["code"]
                                         for f in json.loads(proc.stdout)["findings"]]


def test_graph_note_repoints_a_slice_onto_the_squashed_commit(tmp_path):
    toy, origin = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    _squash_land(toy, origin, tmp_path)
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("graph", "note", "--repoint", "slice-042", head, root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["note_written"] and out["commit"] == head
    notes = git(toy, "notes", "--ref=refs/notes/harness", "list").stdout
    assert head in notes, "the note must now live on the reachable commit"
    rows = read_jsonl(toy / ".harness" / "notes.jsonl")
    assert any(r["commit"] == head and r["slice_id"] == "slice-042"
               for r in rows)
    assert run_cli("verify", root=toy).returncode == 0


def test_notes_jsonl_is_union_merged_substrate(tmp_path):
    """Append-only derived logs conflict by construction across parallel
    slices — the merge driver entry is not optional."""
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    assert run_cli("init", root=root).returncode == 0
    assert ".harness/notes.jsonl merge=union" in \
        (root / ".gitattributes").read_text()


# ------------------------------------------------------------------ D-011
PR_CFG = {"landing": {"mode": "pr", "remote": "origin", "base": "main"}}
LOCAL_CFG = {}


@pytest.mark.parametrize("command", [
    "git push -u origin slice/slice-042",
    "git push --set-upstream origin slice/slice-042",
    "git push origin slice/slice-042",
    "git push origin HEAD:slice/slice-042",
    "git fetch origin",
    "git fetch origin --prune",
    "git fetch origin --tags",
    "gh pr create --base main --head slice/slice-042 --title t --body-file /tmp/b",
    "gh pr view 42",
    "gh pr checks",
    "gh pr status",
])
def test_pr_mode_auto_approves_exactly_its_egress(command):
    allow, reason = command_allowed(command, config=PR_CFG,
                                    slice_id="slice-042")
    assert allow, reason


@pytest.mark.parametrize("command", [
    "git push origin main",                      # never the base branch
    "git push origin slice/other",               # not the bound slice
    "git push upstream slice/slice-042",         # not landing.remote
    "git push --force origin slice/slice-042",   # history rewrite
    "git push -u origin slice/slice-042 --force",
    "git push",
    "git pull origin main",
    "git clone https://example.com/x",
    # --upload-pack runs a command of the caller's choosing (locally, and on
    # the server for an ssh remote): fetch takes the remote and nothing else
    "git fetch origin --upload-pack=/tmp/evil.sh",
    "git fetch origin --upload-pack='sh -c whoami'",
    "git fetch origin main:main",              # rewrites a local ref
    "git fetch origin refs/heads/main:refs/heads/main",
    "git fetch origin main",                   # still a refspec, still no
    "git fetch --all",
    "git fetch attacker",
    # gh must stay pointed at THIS repo and this terminal
    "gh pr create --repo attacker/repo --base main --head slice/slice-042",
    "gh pr create -R attacker/repo --base main",
    "gh pr create -Rattacker/repo --base main",
    "gh pr create --repo=attacker/repo",
    "gh pr view --web",
    "gh pr view -w",
    "gh pr view 42 --web",
    "gh repo delete",
    "gh pr merge 42",
    "gh auth token",
])
def test_pr_mode_auto_approves_nothing_else(command):
    allow, _ = command_allowed(command, config=PR_CFG, slice_id="slice-042")
    assert not allow, f"{command!r} must fall through to the human"


@pytest.mark.parametrize("command", [
    "git push -u origin slice/slice-042",
    "git fetch origin",
    "gh pr create --base main --head slice/slice-042 --title t --body-file /b",
])
def test_local_mode_auto_approves_no_egress_at_all(command):
    allow, _ = command_allowed(command, config=LOCAL_CFG, slice_id="slice-042")
    assert not allow
    allow, _ = command_allowed(command)      # the historical signature
    assert not allow


def test_pr_mode_egress_needs_a_bound_slice():
    allow, _ = command_allowed("git push -u origin slice/slice-042",
                               config=PR_CFG, slice_id=None)
    assert not allow


def test_permit_answers_for_the_bound_slice_in_pr_mode(tmp_path):
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    run_cli("slice", "--slice", "slice-042", "--session", "permit", root=toy)
    proc = run_cli("permit", "--session", "permit", "--command",
                   "git push -u origin slice/slice-042", root=toy)
    assert json.loads(proc.stdout)["allow"] is True, proc.stdout
    proc = run_cli("permit", "--session", "permit", "--command",
                   "git push origin main", root=toy)
    assert json.loads(proc.stdout)["allow"] is False


# ------------------------------------------------------------------ profile
def _profile(root, config):
    from engine.cli.init import _write_autonomy_settings
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    _write_autonomy_settings(root, quiet=True, config=config)
    return json.loads((root / ".claude" / "settings.json").read_text())


def test_pr_mode_profile_opens_nothing_the_hook_cannot_scope(tmp_path):
    """A prefix rule cannot express "this slice's branch": `Bash(git push
    origin slice/:*)` also matches `slice/x:main`. The profile only removes
    the blanket denies (a deny outranks the hook); the harness PreToolUse
    decision is the sole opener."""
    rules = _profile(tmp_path, PR_CFG)["permissions"]
    for opened in ("Bash(git push:*)", "Bash(git fetch:*)"):
        assert opened not in rules["deny"], opened
    for rule in rules["allow"]:
        assert not rule.startswith(("Bash(git push", "Bash(git fetch",
                                    "Bash(gh ")), rule
    assert "Bash(git remote:*)" in rules["deny"], "other egress stays denied"
    assert "Bash(git clone:*)" in rules["deny"]
    assert not any(" *)" in r for r in rules["allow"] + rules["deny"])


def test_local_mode_profile_is_byte_identical_to_the_template(tmp_path):
    from engine.cli.common import PLUGIN_ROOT
    from engine.cli.init import _write_autonomy_settings
    (tmp_path / ".claude").mkdir()
    _write_autonomy_settings(tmp_path, quiet=True, config=LOCAL_CFG)
    expected = (PLUGIN_ROOT / "templates" / "claude-settings.json").read_text()
    expected = expected.replace("{{HARNESS_BIN}}",
                                str(PLUGIN_ROOT / "bin" / "harness"))
    expected = expected.replace("{{PROJECT_DIR}}", str(tmp_path.resolve()))
    assert (tmp_path / ".claude" / "settings.json").read_text() == expected


# ------------------------------------------------ landing metadata is committed
def test_pr_landing_commits_and_pushes_its_own_metadata(tmp_path):
    """W4 in pr mode: `landed_via`/`pr_url` are written AFTER the ceremony's
    substrate commit, so the landing must commit and push them itself —
    otherwise the tree is left dirty and the metadata never reaches the PR."""
    script, _, _ = _fake_gh(tmp_path)
    toy, origin = _pr_repo(tmp_path, pr_cmd=_pr_cmd(script))
    _work_and_commit(toy)
    proc = _close(toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not git(toy, "status", "--porcelain").stdout.strip(), \
        "a pr-mode close must leave nothing uncommitted"
    landed = git(toy, "show",
                 "origin/slice/slice-042:.harness/backlog.jsonl").stdout
    assert '"landed_via": "pr"' in landed
    assert "https://github.com/goodwork-eng/harness/pull/42" in landed


def test_a_failed_landing_is_recorded_and_re_landable(tmp_path):
    """A closed-but-not-landed slice is a real state: it must be durable
    substrate, visible to verify, and re-landable with one command."""
    toy, _ = _pr_repo(tmp_path, pr_cmd="false")
    _work_and_commit(toy)
    assert _close(toy).returncode == 1
    row = _row(toy)
    assert row["landed_via"] == "pending"
    assert row["landing_error"], "the failure must be recorded, not just printed"
    assert not git(toy, "status", "--porcelain").stdout.strip()

    proc = run_cli("verify", root=toy)
    assert proc.returncode == 0, "a pending landing is advisory, never a block"
    out = json.loads(proc.stdout)
    pending = next(f for f in out["findings"] if f["code"] == "LANDING_PENDING")
    assert pending["severity"] == "advisory"
    assert pending["rule_ref"] == "adr:002" and "slice-042" in pending["message"]

    script, _, _ = _fake_gh(tmp_path)
    _set_landing(toy, mode="pr", remote="origin", base="main",
                 pr_cmd=_pr_cmd(script))
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "fix pr_cmd")
    proc = run_cli("land", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["landed"] is True
    row = _row(toy)
    assert row["landed_via"] == "pr" and "landing_error" not in row
    assert not git(toy, "status", "--porcelain").stdout.strip()
    assert "LANDING_PENDING" not in json.loads(
        run_cli("verify", root=toy).stdout)["findings"].__str__()


def test_land_refuses_an_already_landed_slice(tmp_path):
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    assert _close(toy).returncode == 0
    proc = run_cli("land", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1
    assert "landed" in (proc.stdout + proc.stderr)


def test_landing_refuses_to_push_from_the_wrong_branch(tmp_path):
    """Closing from the main tree would push whatever `slice/<id>` happens to
    point at — a stale branch, silently."""
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    _work_and_commit(toy)
    git(toy, "checkout", "-q", "-b", "detour")
    proc = _close(toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["closed"] is True and out["landed"] is False
    assert "detour" in out["error"] and "slice/slice-042" in out["error"]
    # the abort happens BEFORE any write: a pending marker committed onto
    # whatever branch happens to be checked out is substrate vandalism
    assert "landed_via" not in _row(toy)
    assert not git(toy, "status", "--porcelain").stdout.strip()
    assert "landing" not in git(toy, "log", "-1", "--format=%s").stdout


def test_an_unknown_pr_cmd_placeholder_fails_loud():
    with pytest.raises(HarnessError) as exc:
        landing_config({"landing": {"pr_cmd": "gh pr create --repo {repo}"}})
    assert "{repo}" in str(exc.value) and "pr_cmd" in str(exc.value)


# ------------------------------------------------------------------ profile
def test_pr_mode_profile_opens_the_forge_and_fetch(tmp_path):
    profile = _profile(tmp_path, PR_CFG)
    rules = profile["permissions"]
    assert "Bash(git fetch:*)" not in rules["deny"], \
        "a pr-mode slice must be able to fetch its base branch"
    domains = profile["sandbox"]["network"]["allowedDomains"]
    for host in ("github.com", "api.github.com", "ssh.github.com"):
        assert host in domains, host
    assert "pypi.org" in domains, "the base domains must survive"


def test_pr_mode_profile_derives_the_forge_host_from_the_remote(tmp_path):
    cfg = {"landing": {"mode": "pr",
                       "remote": "https://git.example.com/goodwork/kente.git"}}
    domains = _profile(tmp_path, cfg)["sandbox"]["network"]["allowedDomains"]
    assert "git.example.com" in domains


def test_local_mode_profile_keeps_every_egress_denied(tmp_path):
    rules = _profile(tmp_path, LOCAL_CFG)["permissions"]
    for rule in ("Bash(git push:*)", "Bash(git fetch:*)", "Bash(git remote:*)"):
        assert rule in rules["deny"], rule


# ------------------------------------------------------------------ misc
def test_verify_resolves_against_a_remote_tracking_base(tmp_path):
    """A developer who never checks main out still has origin/main."""
    from engine.graph import reachable_trees
    toy, _ = _pr_repo(tmp_path, pr_cmd="true")
    origin_main = git(toy, "rev-parse", "origin/main").stdout.strip()
    git(toy, "branch", "-qD", "main")
    trees = reachable_trees(toy, "main", remote="origin")
    assert git(toy, "rev-parse", f"{origin_main}^{{tree}}").stdout.strip() in trees


def test_init_creates_an_empty_notes_log(tmp_path):
    root = tmp_path / "fresh2"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    assert run_cli("init", root=root).returncode == 0
    assert (root / ".harness" / "notes.jsonl").exists()


# --------------------------------------------- metadata push failure (B)
def test_a_failed_metadata_push_is_a_failed_landing(tmp_path):
    """The PR exists but its branch does not carry `landed_via`/`pr_url`:
    reporting success there would leave the row claiming a landing the forge
    never saw."""
    refuse = tmp_path / "refuse-pushes"
    script, _, _ = _fake_gh(tmp_path, extra=f'touch {refuse}')
    toy, origin = _pr_repo(tmp_path, pr_cmd=_pr_cmd(script))
    hook = origin / "hooks" / "pre-receive"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n"
                    f'if [ -f {refuse} ]; then echo "refused"; exit 1; fi\n'
                    "exit 0\n")
    hook.chmod(0o755)
    _work_and_commit(toy)

    proc = _close(toy)
    assert proc.returncode == 1, proc.stdout
    out = json.loads(proc.stdout)
    assert out["landed"] is False and "metadata" in out["error"]
    row = _row(toy)
    assert row["landed_via"] == "pending"
    assert row["pr_url"] == "https://github.com/goodwork-eng/harness/pull/42", \
        "the PR exists — its URL must survive, or `land` would open a second"
    assert not git(toy, "status", "--porcelain").stdout.strip()
    assert _gh_calls(tmp_path) == 1

    refuse.unlink()                       # the remote accepts pushes again
    proc = run_cli("land", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["landed"] is True and out["pr_url"].endswith("/42")
    assert _gh_calls(tmp_path) == 1, \
        "re-landing must not open a second pull request"
    row = _row(toy)
    assert row["landed_via"] == "pr" and "landing_error" not in row
    assert '"landed_via": "pr"' in git(
        toy, "show", "origin/slice/slice-042:.harness/backlog.jsonl").stdout


# ------------------------------------------- egress classifier (D-011)
def _decision(command, config=PR_CFG, slice_id="slice-042"):
    from engine.permits import command_decision
    return command_decision(command, config=config, slice_id=slice_id)[0]


EGRESS_SPELLINGS = [
    # git global options sit BEFORE the subcommand
    "git -C . push origin main",
    "git -C /tmp/other push origin main",
    "git -c user.name=x push origin main",
    "git --git-dir=/tmp/x push origin main",
    "git --work-tree=/tmp/x fetch origin main:main",
    "git -p push origin main",
    "/usr/bin/git -C . fetch origin --upload-pack=/tmp/evil.sh",
    # leading environment assignments
    "GIT_DIR=x git push origin main",
    "env FOO=1 git push origin main",
    "GIT_SSH_COMMAND='ssh -i /tmp/k' git push origin main",
    # wrappers and interpreters
    "bash -c \"git push origin main\"",
    "sh -lc 'gh pr create --repo attacker/repo'",
    "timeout 5 git push origin main",
    "nohup git push origin main",
    "nice -n 10 git push origin main",
    "xargs -0 git push",
    "xargs -I {} git push origin main",
    "eval \"git push origin main\"",
    "sudo git push origin main",
    # other remote-talking git subcommands
    "git ls-remote origin",
    "git archive --remote=ssh://x/y HEAD",
    # shell LONG options must never masquerade as `-c` (they contain a `c`)
    "bash --norc -c 'git push origin main'",
    "bash --rcfile /dev/null -c 'git push origin main'",
    "env bash --norc -c 'git push origin main'",
    "bash --noprofile --norc -c \"git push origin main\"",
    "sh --posix -c 'gh pr create --repo a/b'",
    "bash --init-file x -c 'git push origin main'",
    # unknown long option before the script: opaque, so it fails closed
    "bash --frobnicate -c 'ls'",
    # `-c` with no script at all is not something to wave through
    "bash -c",
    # short clusters ending in an arg-taking letter (-o optname, -O shopt):
    # the option argument is not the script — the token after it is
    "bash -co pipefail 'git push origin main'",
    "bash -cO expand_aliases 'git push origin main'",
    "bash -eco pipefail 'git push origin main'",
    "sh -co posix 'gh pr create --repo a/b'",
    "bash -oc pipefail 'git push origin main'",
]


@pytest.mark.parametrize("command", EGRESS_SPELLINGS)
def test_pr_mode_denies_every_spelling_of_egress(command):
    """`defer` means silent, and silent means the host decides — which in pr
    mode is a sandboxed shell with the forge reachable. Anything that talks
    to a remote and is not the slice's own landing must be DENIED."""
    assert _decision(command) == "deny", command


@pytest.mark.parametrize("command", [
    "git push -u origin slice/slice-042",
    "git push origin slice/slice-042",
    "git fetch origin",
    "gh pr checks",
])
def test_the_exact_landing_shapes_stay_allowed(command):
    assert _decision(command) == "allow", command


@pytest.mark.parametrize("command", [
    "git -C . push -u origin slice/slice-042",       # not the plain shape
    "git -c x=y push -u origin slice/slice-042",
    "GIT_DIR=x git push -u origin slice/slice-042",
])
def test_normalized_spellings_do_not_widen_the_allow_list(command):
    assert _decision(command) == "deny", command


@pytest.mark.parametrize("command", [
    "git -C . status",
    "git status",
    "bash -c \"ls\"",
    "bash --norc -c \"ls\"",
    "bash --rcfile /dev/null -c \"make test\"",
    "bash -co pipefail 'ls'",
    "bash -eco pipefail 'make test'",
    "env",
    "git config user.name",
    "python3 -m pytest tests/",
    "make test",
])
def test_harmless_commands_are_never_denied(command):
    assert _decision(command) != "deny", command


@pytest.mark.parametrize("command", EGRESS_SPELLINGS + [
    "bash -c \"git push\"", "gh pr create --repo a/b",
])
def test_local_mode_never_denies_anything(command):
    assert _decision(command, config=LOCAL_CFG) == "defer", command
