"""D-012: the command that decides acceptance is configurable.

`acceptance.cmd` with `{paths}` substituted (default: the historical
`<python> -m pytest {paths} -q`), run from `acceptance.cwd` with
`acceptance.env`; `acceptance.gate_cmd` runs once at close/merge and a
non-zero exit is the blocking finding `ACCEPTANCE_GATE_FAILED`.
"""
import json
import os
import sys

import pytest
import yaml
from conftest import git, loaded_context, make_event, run_cli
from engine import HarnessError, load_config
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")

NO_ENV = {"CLAUDE_SESSION_ID": ""}


def _set_acceptance(root, **keys):
    """Merge an `acceptance:` block into the toy repo's config."""
    cfg_path = root / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("acceptance", {}).update(keys)
    cfg_path.write_text(yaml.safe_dump(cfg))
    return cfg


def _work_and_commit(toy, session="ar"):
    run_cli("start", "--slice", "slice-042", "--session", session,
            "--no-worktree", root=toy)
    loaded_context(toy, session=session)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    handle_event(make_event("post_change", session=session,
                            files=["orders.py"]), toy)
    handle_event(make_event("unit_complete", session=session), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 work")
    return session


# ------------------------------------------------------------- command build
def test_default_command_is_byte_identical_to_the_historical_one(toy):
    """No `acceptance` key in config → exactly what the engine always ran."""
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    assert _acceptance_cmd(cfg, ["tests/slices/042_orders.py"], "/py") == \
        ["/py", "-m", "pytest", "tests/slices/042_orders.py", "-q"]


def test_custom_cmd_substitutes_paths_including_ones_with_spaces(toy):
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    cfg["acceptance"] = {"cmd": "make test PATHS={paths}"}
    assert _acceptance_cmd(cfg, ["tests/my tests/a.py", "b.py"], "/py") == \
        ["make", "test", "PATHS=tests/my tests/a.py", "b.py"]


def test_cmd_without_the_placeholder_gets_the_paths_appended(toy):
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    cfg["acceptance"] = {"cmd": "uv run pytest -q"}
    assert _acceptance_cmd(cfg, ["tests/a b.py"], "/py") == \
        ["uv", "run", "pytest", "-q", "tests/a b.py"]


def test_non_string_env_value_fails_loud_naming_the_key(toy):
    from engine.cli.acceptance import _acceptance_env
    cfg = load_config(toy)
    cfg["acceptance"] = {"env": {"CI": True}}
    with pytest.raises(HarnessError) as exc:
        _acceptance_env(toy, cfg)
    assert "CI" in str(exc.value)


def test_env_and_cwd_are_applied_to_the_acceptance_command(toy):
    """cwd is root-relative; env overlays os.environ."""
    from engine.cli.acceptance import run_acceptance
    sub = toy / "sub"
    sub.mkdir()
    probe = sub / "probe.sh"
    probe.write_text('#!/bin/sh\nprintf "%s\\n%s\\n" "$PWD" "$PROBE" '
                     '> probe.out\n')
    probe.chmod(0o755)
    _set_acceptance(toy, cmd="./probe.sh {paths}", cwd="sub",
                    env={"PROBE": "hello"})
    cfg = load_config(toy)
    ok, _evidence = run_acceptance(
        toy, {"id": "slice-042", "acceptance": ["tests/slices/042_orders.py"]},
        cfg)
    assert ok, _evidence
    out = (sub / "probe.out").read_text().splitlines()
    assert os.path.realpath(out[0]) == os.path.realpath(str(sub))
    assert out[1] == "hello"


def test_a_red_custom_cmd_fails_acceptance(toy):
    from engine.cli.acceptance import run_acceptance
    _set_acceptance(toy, cmd="false")
    ok, _evidence = run_acceptance(
        toy, {"id": "slice-042", "acceptance": ["tests/slices/042_orders.py"]},
        load_config(toy))
    assert not ok


def test_a_missing_default_interpreter_still_fails_loud(toy):
    """Backward compatibility: the historical fail-loud path is untouched."""
    from engine.cli.slice import _acceptance_green
    cfg = load_config(toy)
    cfg["gates"]["acceptance_python"] = "/custom/python"
    ok, msg = _acceptance_green(
        toy, {"acceptance": ["tests/slices/042_orders.py"]}, cfg)
    assert not ok and "does not exist" in msg


# ------------------------------------------------------------------ gate_cmd
def test_gate_cmd_failure_blocks_the_close(toy):
    session = _work_and_commit(toy)
    _set_acceptance(toy, gate_cmd="false")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["closed"] is False
    assert "ACCEPTANCE_GATE_FAILED" in json.dumps(out)
    assert "adr:002" in json.dumps(out)


def test_gate_cmd_success_closes_the_slice(toy):
    session = _work_and_commit(toy)
    _set_acceptance(toy, gate_cmd="true")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["closed"] is True


def test_gate_cmd_output_tail_is_reported(toy):
    """The message carries the last lines of combined stdout/stderr — a
    silent 'gate failed' is unfixable."""
    session = _work_and_commit(toy)
    _set_acceptance(toy, gate_cmd=(
        f"{sys.executable} -c \"import sys; print('GATE-TAIL-MARKER'); "
        "sys.exit(3)\""))
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "GATE-TAIL-MARKER" in proc.stdout


def test_no_gate_cmd_configured_is_a_no_op(toy):
    session = _work_and_commit(toy)
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_merge_slice_blocks_when_the_gate_cmd_fails(toy):
    """D-012: the same code blocks the merged tree, and the merge rolls
    back — the gate protects `main`, not just the worktree."""
    wt = toy / ".worktrees" / "slice-042"
    assert git(toy, "worktree", "add", str(wt), "-b",
               "slice/slice-042").returncode == 0
    run_cli("slice", "--slice", "slice-042", "--session", "mg", root=wt)
    (wt / "orders.py").write_text(GOOD_ORDERS)
    run_cli("extract", str(wt / "orders.py"), root=wt)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "slice-042 in worktree")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", "mg",
                   "--commit", "HEAD", root=wt)
    assert proc.returncode == 0, proc.stdout + proc.stderr

    _set_acceptance(toy, gate_cmd="false")
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "gate_cmd on main")
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False
    assert "ACCEPTANCE_GATE_FAILED" in json.dumps(out)
    assert out["rolled_back"] is True


# ------------------------------------------------- unspawnable commands (R1)
def test_a_gate_cmd_that_cannot_be_spawned_blocks_the_close(toy):
    """A missing binary must be an ordinary red result, not a traceback:
    an escaping OSError sails past every rollback branch."""
    session = _work_and_commit(toy)
    _set_acceptance(toy, gate_cmd="/definitely/not/here --check")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "ACCEPTANCE_GATE_FAILED" in json.dumps(out)
    assert "cannot run" in out["evidence"]
    assert "Traceback" not in proc.stderr


def test_a_nonexistent_acceptance_cwd_is_a_red_result_not_a_crash(toy):
    from engine.cli.acceptance import run_acceptance, run_gate_cmd
    _set_acceptance(toy, cwd="nope", gate_cmd="true")
    cfg = load_config(toy)
    ok, evidence = run_acceptance(
        toy, {"id": "slice-042", "acceptance": ["tests/slices/042_orders.py"]},
        cfg)
    assert not ok and "cannot run" in evidence
    ok, tail = run_gate_cmd(toy, cfg)
    assert not ok and "cannot run" in tail


def test_merge_slice_rolls_back_when_the_gate_cmd_cannot_be_spawned(toy):
    """The failure mode that left `main` merged but unvalidated."""
    wt = toy / ".worktrees" / "slice-042"
    assert git(toy, "worktree", "add", str(wt), "-b",
               "slice/slice-042").returncode == 0
    run_cli("slice", "--slice", "slice-042", "--session", "mx", root=wt)
    (wt / "orders.py").write_text(GOOD_ORDERS)
    run_cli("extract", str(wt / "orders.py"), root=wt)
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "slice-042 in worktree")
    assert run_cli("close-slice", "--slice", "slice-042", "--session", "mx",
                   "--commit", "HEAD", root=wt).returncode == 0

    _set_acceptance(toy, gate_cmd="/definitely/not/here")
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "gate_cmd on main")
    head = git(toy, "rev-parse", "HEAD").stdout.strip()
    proc = run_cli("merge-slice", "--slice", "slice-042", root=toy, env=NO_ENV)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["merged"] is False and out["rolled_back"] is True
    assert "ACCEPTANCE_GATE_FAILED" in json.dumps(out)
    assert "cannot run" in out["evidence"]
    assert git(toy, "rev-parse", "HEAD").stdout.strip() == head, \
        "main must be back where it was — never merged-but-unvalidated"
    assert not (toy / "orders.py").exists()


# ------------------------------------------------- reason vs evidence (R2)
def test_the_persisted_reason_never_carries_raw_gate_output(toy):
    """`reason` is written into parked_reason in the COMMITTED backlog."""
    session = _work_and_commit(toy)
    _set_acceptance(toy, gate_cmd=(
        f"{sys.executable} -c \"import sys; print('GATE-TAIL-MARKER'); "
        "sys.exit(3)\""))
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    out = json.loads(proc.stdout)
    assert out["reason"] == "acceptance gate command failed"
    assert "GATE-TAIL-MARKER" not in out["reason"]
    assert "GATE-TAIL-MARKER" in out["evidence"]
    assert "GATE-TAIL-MARKER" in out["findings"][0]["message"]


# ------------------------------------------------------ config containment
def test_an_escaping_or_absolute_cwd_is_rejected(toy):
    from engine.cli.acceptance import _acceptance_cwd
    cfg = load_config(toy)
    for bad in ("/etc", "../outside"):
        cfg["acceptance"] = {"cwd": bad}
        with pytest.raises(HarnessError) as exc:
            _acceptance_cwd(toy, cfg)
        assert "acceptance.cwd" in str(exc.value)


def test_a_non_string_cwd_fails_loud(toy):
    from engine.cli.acceptance import _acceptance_cwd
    cfg = load_config(toy)
    cfg["acceptance"] = {"cwd": 3}
    with pytest.raises(HarnessError) as exc:
        _acceptance_cwd(toy, cfg)
    assert "acceptance.cwd" in str(exc.value)


def test_a_non_mapping_acceptance_block_fails_loud(toy):
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    cfg["acceptance"] = "uv run pytest"
    with pytest.raises(HarnessError) as exc:
        _acceptance_cmd(cfg, ["a.py"], "/py")
    assert "acceptance" in str(exc.value)


def test_the_gate_tail_is_truncated_to_twenty_lines(toy):
    from engine.cli.acceptance import run_gate_cmd
    _set_acceptance(toy, gate_cmd=(
        f"{sys.executable} -c \"import sys; "
        "[print('line%d' % i) for i in range(40)]; sys.exit(1)\""))
    ok, tail = run_gate_cmd(toy, load_config(toy))
    assert not ok
    lines = tail.splitlines()
    assert len(lines) == 20
    assert lines[0] == "line20" and lines[-1] == "line39"
