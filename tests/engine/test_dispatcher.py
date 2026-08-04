"""`harness run` — the campaign dispatcher: walks the dependency DAG,
provisions each ready slice, invokes the configured builder, merges closes,
parks failures, and stops loudly. The engine orchestrates; the AGENT is the
host's (run.builder_cmd) — that boundary is the portability contract."""
import json
import os
import textwrap

from conftest import git, run_cli
from engine import read_jsonl

BUILDER = textwrap.dedent("""\
    import json, os, subprocess, sys

    HB = os.environ["HARNESS_BIN"]
    WT = os.environ["HARNESS_WORKTREE"]
    SID = os.environ["HARNESS_SLICE"]
    with open(os.path.join(WT, "impl.json")) as fh:
        IMPL = json.load(fh)

    def h(*a):
        return subprocess.run([sys.executable, HB, "--root", WT, *a],
                              capture_output=True, text=True)

    fname, content = IMPL[SID]
    with open(os.path.join(WT, fname), "w") as fh:
        fh.write(content)
    h("extract", os.path.join(WT, fname))
    subprocess.run(["git", "-C", WT, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", WT, "commit", "-qm", SID], capture_output=True)
    p = h("close-slice", "--slice", SID, "--session", "builder",
          "--commit", "HEAD")
    out = json.loads(p.stdout) if p.stdout.strip() else {}
    sys.exit(0 if out.get("closed") else 1)
    """)


IMPL = {
    "slice-a": ["alpha.py", "def alpha():\n    return 1\n"],
    "slice-b": ["beta.py",
                "import alpha\n\n\ndef beta():\n    return alpha.alpha() + 1\n"],
    "slice-c": ["gamma.py",
                "import beta\n\n\ndef gamma():\n    return beta.beta() + 1\n"],
}


def _campaign(toy, builder=BUILDER, builder_cmd=None, impl=None):
    """Three chained slices + a scripted builder, all committed to main."""
    (toy / "builder.py").write_text(builder)
    (toy / "impl.json").write_text(json.dumps(impl or IMPL))
    tests_dir = toy / "tests" / "slices"
    for sid, test in (
        ("slice-a", "import alpha\n\ndef test_a():\n    assert alpha.alpha() == 1\n"),
        ("slice-b", "import beta\n\ndef test_b():\n    assert beta.beta() == 2\n"),
        ("slice-c", "import gamma\n\ndef test_c():\n    assert gamma.gamma() == 3\n"),
    ):
        (tests_dir / f"{sid.replace('slice-', '0')}_t.py").write_text(test)
    import yaml
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["run"] = {"builder_cmd": builder_cmd or "python3 builder.py",
                  "max_slice_attempts": 2, "builder_timeout": 120}
    cfg_path.write_text(yaml.safe_dump(cfg))
    deps = {"slice-a": [], "slice-b": ["slice-a"], "slice-c": ["slice-b"]}
    files = {"slice-a": "alpha.py", "slice-b": "beta.py", "slice-c": "gamma.py"}
    for sid in ("slice-a", "slice-b", "slice-c"):
        args = ["backlog", "add", "--id", sid, "--title", sid,
                "--predicts", files[sid], "--acceptance",
                f"tests/slices/{sid.replace('slice-', '0')}_t.py"]
        if deps[sid]:
            args += ["--depends", *deps[sid]]
        assert run_cli(*args, root=toy).returncode == 0
    # slice-042 (the fixture's own) would block the campaign; close it out
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows = [r for r in rows if r["id"] != "slice-042"]
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "campaign setup")


def _run(toy, *extra):
    env = dict(os.environ)
    env["CLAUDE_SESSION_ID"] = ""
    return run_cli("run", *extra, root=toy, env=env)


def test_run_completes_a_campaign_unattended(toy):
    """The intended goal, end to end: architecture + backlog done -> every
    slice builds, reviews, closes and merges with zero interventions."""
    _campaign(toy)
    proc = _run(toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["completed"] == ["slice-a", "slice-b", "slice-c"]
    assert out["parked"] == []
    # the work landed in main, in dependency order
    for f in ("alpha.py", "beta.py", "gamma.py"):
        assert (toy / f).exists(), f
    rows = {r["id"]: r["status"]
            for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert set(rows.values()) == {"closed"}
    # provenance notes for every slice
    notes = git(toy, "notes", "--ref=refs/notes/harness", "list").stdout
    assert notes.strip()
    # worktrees cleaned, verify green, substrate healthy
    assert not any((toy / ".worktrees").glob("slice-*"))
    assert run_cli("verify", root=toy).returncode == 0
    assert run_cli("doctor", "--substrate", root=toy).returncode == 0


def test_run_parks_a_failing_slice_and_stops_loudly(toy):
    impl = dict(IMPL)
    impl["slice-a"] = ["alpha.py", "def alpha():\n    return 99\n"]
    _campaign(toy, impl=impl)
    proc = _run(toy)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "slice-a" in out["parked"]
    assert out["completed"] == []
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert rows["slice-a"]["status"] == "parked"
    assert rows["slice-a"]["parked_reason"]
    assert rows["slice-b"]["status"] == "planned", "dependents must not start"
    assert "adjudicate" in out["next"] or "re-bind" in out["next"]


def test_run_requires_a_builder_command(toy):
    proc = _run(toy)
    assert proc.returncode == 2
    assert "run.builder_cmd" in proc.stderr


def test_run_dry_run_prints_the_waves(toy):
    _campaign(toy)
    proc = _run(toy, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["waves"] == [["slice-a"], ["slice-b"], ["slice-c"]]
    rows = {r["id"]: r["status"]
            for r in read_jsonl(toy / ".harness" / "backlog.jsonl")}
    assert set(rows.values()) == {"planned"}, "dry-run must not mutate"


def test_run_parallel_lanes_complete_independent_slices(toy):
    _campaign(toy)
    # make b independent of a so the first wave has two lanes
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    for r in rows:
        if r["id"] == "slice-b":
            r["depends_on"] = []
            r["predicted_files"] = ["beta.py"]
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    (toy / "impl.json").write_text(json.dumps({
        **IMPL, "slice-b": ["beta.py", "def beta():\n    return 2\n"]}))
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "parallel setup")
    proc = _run(toy, "--lanes", "2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert set(out["completed"]) == {"slice-a", "slice-b", "slice-c"}
    assert run_cli("verify", root=toy).returncode == 0


def test_claude_builder_template_trusts_only_a_closed_slice(tmp_path):
    """The reference builder's exit code mirrors the dispatcher's check:
    the agent exiting 0 means nothing — only status=closed counts."""
    import subprocess
    from conftest import PLUGIN_ROOT
    script = PLUGIN_ROOT / "templates" / "claude-builder.sh"
    wt = tmp_path / "wt"
    (wt / ".harness").mkdir(parents=True)
    env = dict(os.environ)
    env.update({"HARNESS_BIN": "harness", "HARNESS_SLICE": "slice-a",
                "HARNESS_WORKTREE": str(wt), "CLAUDE_BIN": "true"})
    row = {"id": "slice-a", "status": "in_progress"}
    (wt / ".harness" / "backlog.jsonl").write_text(json.dumps(row) + "\n")
    proc = subprocess.run(["bash", str(script)], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "not closed" in proc.stderr
    row["status"] = "closed"
    (wt / ".harness" / "backlog.jsonl").write_text(json.dumps(row) + "\n")
    proc = subprocess.run(["bash", str(script)], env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_init_makes_acceptance_tests_collectable_by_bare_pytest(tmp_path):
    """The engine passes explicit paths, so IT always saw them — but a
    human's bare `pytest` silently skipping tests/slices/ is a hidden trap."""
    root = tmp_path / "collect"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=root).returncode == 0
    ini = (root / "pytest.ini").read_text()
    assert "[0-9]*_*.py" in ini
    # a repo with its own pytest config is left alone, with a note
    root2 = tmp_path / "cfg"
    root2.mkdir()
    (root2 / "app.py").write_text("x = 1\n")
    (root2 / "pytest.ini").write_text("[pytest]\naddopts = -q\n")
    proc = run_cli("init", root=root2)
    assert proc.returncode == 0
    assert "addopts = -q" in (root2 / "pytest.ini").read_text()
    assert "python_files" in proc.stdout or "python_files" in proc.stderr
