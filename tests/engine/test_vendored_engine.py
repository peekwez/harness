"""The scaffolded CI workflow must run with nothing but the consumer repo.

`harness init` vendors the engine (`bin/harness` + `engine/`) into
`.harness/engine/`, the workflow prefers that copy over any clone, and
`harness upgrade` brings a substrate scaffolded by an older plugin up to
the installed one (vendored engine + workflow + schema + merge drivers)
without touching anything hand-authored.
"""
import json
import subprocess
import sys

import yaml
from conftest import PLUGIN_ROOT, build_toy_repo, git, run_cli
from engine import ENGINE_VERSION

VENDOR = (".harness", "engine")


def _init(tmp_path, name="v"):
    root = tmp_path / name
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return root


def _locate_step(root):
    wf = yaml.safe_load((root / ".github" / "workflows" /
                         "harness-verify.yml").read_text())
    return next(s for s in wf["jobs"]["verify"]["steps"]
                if "harness engine" in s.get("name", ""))["run"]


def _run_locate(root):
    env_file = root / "gh_env"
    env_file.write_text("")
    proc = subprocess.run(["bash", "-c", _locate_step(root)], cwd=root,
                          capture_output=True, text=True,
                          env={"GITHUB_ENV": str(env_file),
                               "PATH": "/usr/bin:/bin"})
    return proc, env_file.read_text()


# ---------------------------------------------------------------- init vendors
def test_init_vendors_the_engine_into_the_substrate(tmp_path):
    root = _init(tmp_path)
    vendored = root.joinpath(*VENDOR)
    assert (vendored / "bin" / "harness").exists()
    assert (vendored / "engine" / "__init__.py").exists()
    assert (vendored / "engine" / "cli" / "verify.py").exists()
    # the tree-sitter query packs are part of the engine (G7 regenerates
    # shadows in CI)
    assert (vendored / "engine" / "extractor" / "queries" / "python" /
            "symbols.scm").exists()
    # only the engine: no tests, templates, skills, caches
    assert not (vendored / "templates").exists()
    assert not (vendored / "tests").exists()
    assert not list(vendored.rglob("__pycache__"))
    assert not list(vendored.rglob("*.pyc"))
    assert (vendored / "bin" / "harness").stat().st_mode & 0o111
    assert (vendored / "VERSION").read_text().strip() == ENGINE_VERSION


def test_the_vendored_engine_runs_verify_by_itself(tmp_path):
    """The whole point: `python3 .harness/engine/bin/harness verify` with
    the plugin absent."""
    root = _init(tmp_path)
    git(root, "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-q", "-m", "substrate")
    vendored_bin = root.joinpath(*VENDOR) / "bin" / "harness"
    proc = subprocess.run([sys.executable, str(vendored_bin), "verify"],
                          cwd=root, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["passed"] is True, out
    # and it is the installed engine, not some other copy
    proc = subprocess.run([sys.executable, str(vendored_bin), "doctor"],
                          cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_the_vendored_engine_is_not_extracted_as_project_source(tmp_path):
    """`.harness/` is substrate; the engine's own .py files must not become
    shadows, registry gaps or G8 surface in the consumer repo."""
    root = _init(tmp_path)
    proc = run_cli("extract", "--all", root=root)
    assert proc.returncode == 0, proc.stderr
    shadows = list((root / ".harness" / "shadows").rglob("*.json"))
    assert not any("engine" in p.parts[p.parts.index("shadows") + 1:]
                   for p in shadows), shadows
    cfg = (root / ".harness" / "config.yaml").read_text()
    assert "python: true" in cfg          # detected from app.py, not the engine


# ---------------------------------------------------------------- workflow
def test_workflow_prefers_the_vendored_engine(tmp_path):
    root = _init(tmp_path)
    # even with a root-level bin/harness AND a repo variable, the vendored
    # copy wins: it is the one that matches the substrate's schema
    (root / "bin").mkdir()
    (root / "bin" / "harness").write_text("#!/bin/sh\n")
    (root / "bin" / "harness").chmod(0o755)
    proc, env = _run_locate(root)
    assert proc.returncode == 0, proc.stderr
    assert "HARNESS_BIN=.harness/engine/bin/harness" in env


def test_workflow_failure_names_upgrade_as_the_fix(tmp_path):
    root = _init(tmp_path)
    import shutil
    shutil.rmtree(root.joinpath(*VENDOR))
    proc, _ = _run_locate(root)
    assert proc.returncode == 1
    assert "harness upgrade" in proc.stdout + proc.stderr


def test_workflow_verify_step_does_not_need_the_plugin_repo(tmp_path):
    """No step may clone or reference the plugin repo when the engine is
    vendored: the clone is a fallback inside the locate step only."""
    root = _init(tmp_path)
    wf = yaml.safe_load((root / ".github" / "workflows" /
                         "harness-verify.yml").read_text())
    steps = wf["jobs"]["verify"]["steps"]
    for s in steps:
        if "harness engine" in s.get("name", ""):
            continue
        assert "git clone" not in s.get("run", ""), s
        assert "harness" not in s.get("uses", ""), s


# ---------------------------------------------------------------- upgrade
def test_upgrade_brings_an_older_substrate_up_to_date(tmp_path):
    """A repo scaffolded by an older plugin: no vendored engine, an old
    workflow that only knows how to clone. One command fixes both."""
    import shutil
    root = _init(tmp_path)
    shutil.rmtree(root.joinpath(*VENDOR))
    wf_path = root / ".github" / "workflows" / "harness-verify.yml"
    old_wf = wf_path.read_text().replace(
        ".harness/engine/bin/harness", "./nowhere/harness")
    wf_path.write_text(old_wf)

    proc = run_cli("upgrade", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["vendored_engine"]["action"] == "installed"
    assert out["vendored_engine"]["version"] == ENGINE_VERSION
    assert out["workflow"]["action"] == "refreshed"
    assert (root.joinpath(*VENDOR) / "bin" / "harness").exists()
    assert ".harness/engine/bin/harness" in wf_path.read_text()
    # idempotent
    out2 = json.loads(run_cli("upgrade", root=root).stdout)
    assert out2["vendored_engine"]["action"] == "unchanged"
    assert out2["workflow"]["action"] == "unchanged"


def test_upgrade_replaces_a_stale_vendored_engine_wholesale(tmp_path):
    root = _init(tmp_path)
    vendored = root.joinpath(*VENDOR)
    (vendored / "VERSION").write_text("0.0.1\n")
    (vendored / "engine" / "stale_module.py").write_text("x = 1\n")
    (vendored / "engine" / "cli" / "verify.py").write_text("broken\n")
    out = json.loads(run_cli("upgrade", root=root).stdout)
    assert out["vendored_engine"]["action"] == "refreshed"
    assert out["vendored_engine"]["from"] == "0.0.1"
    assert not (vendored / "engine" / "stale_module.py").exists()
    assert (vendored / "engine" / "cli" / "verify.py").read_text() == \
        (PLUGIN_ROOT / "engine" / "cli" / "verify.py").read_text()


def test_upgrade_never_overwrites_a_hand_authored_workflow(tmp_path):
    root = _init(tmp_path)
    wf_path = root / ".github" / "workflows" / "harness-verify.yml"
    custom = "name: mine\non: [push]\njobs: {}\n"
    wf_path.write_text(custom)
    proc = run_cli("upgrade", root=root)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["workflow"]["action"] == "kept"
    assert wf_path.read_text() == custom
    assert ".harness/engine/bin/harness" in out["workflow"]["note"]


def test_upgrade_writes_the_workflow_when_it_is_missing(tmp_path):
    root = _init(tmp_path)
    wf_path = root / ".github" / "workflows" / "harness-verify.yml"
    wf_path.unlink()
    out = json.loads(run_cli("upgrade", root=root).stdout)
    assert out["workflow"]["action"] == "written"
    assert wf_path.exists()


def test_upgrade_runs_the_schema_migration_and_merge_drivers(tmp_path):
    root = _init(tmp_path)
    out = json.loads(run_cli("upgrade", root=root).stdout)
    assert "schema" in out and out["schema"]["to"] >= 1
    drivers = subprocess.run(["git", "-C", str(root), "config", "--get",
                              "merge.harness-substrate.driver"],
                             capture_output=True, text=True).stdout
    assert "merge-substrate" in drivers


def test_upgrade_refuses_a_repo_without_a_substrate(tmp_path):
    root = tmp_path / "bare"
    root.mkdir()
    proc = run_cli("upgrade", root=root)
    assert proc.returncode != 0
    assert "init" in proc.stderr


def test_init_migrate_is_the_same_as_upgrade(tmp_path):
    import shutil
    root = _init(tmp_path)
    shutil.rmtree(root.joinpath(*VENDOR))
    proc = run_cli("init", "--migrate", root=root)
    assert proc.returncode == 0, proc.stderr
    assert (root.joinpath(*VENDOR) / "bin" / "harness").exists()


# ---------------------------------------------------------------- doctor
def test_doctor_flags_a_missing_or_stale_vendored_engine(tmp_path):
    import shutil
    root = _init(tmp_path)
    out = json.loads(run_cli("doctor", "--substrate", root=root).stdout)
    assert out["vendored_engine"]["status"] == "current"
    assert out["substrate_healthy"] is True, out

    (root.joinpath(*VENDOR) / "VERSION").write_text("0.0.1\n")
    proc = run_cli("doctor", "--substrate", root=root)
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["vendored_engine"]["status"] == "stale"
    assert out["substrate_healthy"] is False
    assert "harness upgrade" in out["next"]

    shutil.rmtree(root.joinpath(*VENDOR))
    out = json.loads(run_cli("doctor", "--substrate", root=root).stdout)
    assert out["vendored_engine"]["status"] == "missing"
    assert "harness upgrade" in out["next"]


def test_doctor_on_the_self_hosted_plugin_repo_is_not_stale():
    """This repo carries the engine at its root; nothing to vendor."""
    proc = run_cli("doctor", "--substrate", root=PLUGIN_ROOT)
    out = json.loads(proc.stdout)
    assert out["vendored_engine"]["status"] == "self-hosted", out


def test_toy_repo_doctor_stays_healthy(tmp_path):
    """Test fixtures built without `init` must not start failing doctor."""
    toy = build_toy_repo(tmp_path / "toy")
    out = json.loads(run_cli("doctor", "--substrate", root=toy).stdout)
    assert out["substrate_healthy"] is True, out


# ---------------------------------------------------------------- docs
def test_readme_documents_vendoring_and_upgrade():
    body = (PLUGIN_ROOT / "README.md").read_text()
    assert ".harness/engine" in body
    assert "`upgrade`" in body
