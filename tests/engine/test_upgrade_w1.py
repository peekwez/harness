"""W1 upgrade steps: a 0.9.4 substrate with committed shadows reaches 0.10."""
from __future__ import annotations

import json
import shutil

import yaml

from conftest import build_toy_repo, git, run_cli
from engine import read_jsonl, write_jsonl
from engine import upgrade_010

W1_STEPS = ["w1.gitignore-cache", "w1.untrack-shadows",
            "w1.drop-registry-shadow", "w1.drop-resolver-config"]

LEGACY_CONFIG = """\
# harness per-repo engine config (authored — edit freely, then commit)
schema: 1
resolver:
  budget_tokens: 8000
  ranking: [direct_deps, one_hop_types, durable_memories]
  degrade: drop_docstrings_before_modules
gates:
  g3_mode: allow_with_findings      # or: block | radius
  g5_override: recorded_justification
  g5_similarity_threshold: 0.6
languages:
  python: true
"""


def _w1(rows):
    return [row["id"] for row in rows if row["id"].startswith("w1.")]


def legacy_094_repo(tmp_path):
    """A 0.9.4-shaped substrate: schema 1, committed shadows, registry shadow
    fields, resolver config, the shadows merge attribute, no cache ignore."""
    root = build_toy_repo(tmp_path / "legacy")
    hdir = root / ".harness"
    shutil.rmtree(hdir / "cache", ignore_errors=True)
    (hdir / "schema_version").write_text("1\n")
    (hdir / "config.yaml").write_text(LEGACY_CONFIG)
    shadows = hdir / "shadows"
    shadows.mkdir()
    (shadows / "telemetry.py.json").write_text('{"source_path": "telemetry.py"}\n')
    (shadows / "config.py.json").write_text('{"source_path": "config.py"}\n')
    rows = read_jsonl(hdir / "registry.jsonl")
    for r in rows:
        r["shadow"] = (".harness/shadows/telemetry.py.json"
                       if r["id"] == "telemetry" else None)
    write_jsonl(hdir / "registry.jsonl", rows)
    ga = root / ".gitattributes"
    ga.write_text(ga.read_text() + ".harness/shadows/** merge=ours\n")
    gi = root / ".gitignore"
    gi.write_text("".join(line + "\n" for line in gi.read_text().splitlines()
                          if line != ".harness/cache/"))
    git(root, "add", "-A")
    git(root, "commit", "-qm", "0.9.4 substrate")
    return root


def test_plan_lists_every_w1_step_for_a_legacy_repo(tmp_path):
    root = legacy_094_repo(tmp_path)
    assert _w1(upgrade_010.plan(root)) == W1_STEPS


def test_a_current_repo_has_no_w1_work(toy):
    assert _w1(upgrade_010.plan(toy)) == []


def test_upgrade_yes_moves_a_legacy_repo_onto_w1(tmp_path):
    root = legacy_094_repo(tmp_path)
    proc = run_cli("upgrade", "--yes", root=root, stdin="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    hdir = root / ".harness"
    assert (hdir / "schema_version").read_text() == "2\n"
    assert not (hdir / "shadows").exists()
    assert git(root, "ls-files", ".harness/shadows").stdout.strip() == ""
    assert ".harness/cache/" in (root / ".gitignore").read_text().splitlines()
    assert "shadows" not in (root / ".gitattributes").read_text()
    assert all("shadow" not in r for r in read_jsonl(hdir / "registry.jsonl"))
    config = yaml.safe_load((hdir / "config.yaml").read_text())
    assert "resolver" not in config
    assert config["gates"]["g3_mode"] == "allow_with_findings"
    assert _w1(upgrade_010.plan(root)) == []
    verify = run_cli("verify", root=root)
    assert verify.returncode == 0, verify.stdout


def test_upgrade_without_yes_skips_only_the_destructive_step(tmp_path):
    root = legacy_094_repo(tmp_path)
    proc = run_cli("upgrade", root=root, stdin="")   # stdin is a pipe, not a TTY
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    reports = {row["id"]: row.get("report") for row in out["steps"]}
    assert reports["w1.untrack-shadows"] == ["skipped: needs confirmation"]
    assert (root / ".harness" / "shadows").exists()
    assert any("w1.untrack-shadows" in w for w in out["warnings"])
    assert any(h.startswith("w1.untrack-shadows:") for h in out["human_checks"])
    assert out["status"] == "incomplete" 
    assert _w1(upgrade_010.plan(root)) == ["w1.untrack-shadows"]


def test_dry_run_lists_w1_steps_and_changes_nothing(tmp_path):
    root = legacy_094_repo(tmp_path)
    proc = run_cli("upgrade", "--dry-run", root=root, stdin="")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _w1(json.loads(proc.stdout)["steps"]) == W1_STEPS
    assert git(root, "status", "--porcelain").stdout.strip() == ""


def test_drop_resolver_keys_keeps_comments_and_other_keys():
    from engine.upgrade_w1 import _strip_resolver_keys
    text = _strip_resolver_keys(LEGACY_CONFIG)
    assert "resolver" not in text and "budget_tokens" not in text
    assert text.startswith("# harness per-repo engine config")
    assert "g3_mode: allow_with_findings      # or: block | radius" in text


def test_drop_resolver_keys_keeps_unknown_resolver_keys():
    from engine.upgrade_w1 import _strip_resolver_keys
    text = _strip_resolver_keys(
        "resolver:\n  budget_tokens: 8000\n  custom: 1\ngates: {}\n")
    assert yaml.safe_load(text) == {"resolver": {"custom": 1}, "gates": {}}


def test_flow_style_resolver_is_removed_through_yaml(tmp_path):
    root = build_toy_repo(tmp_path / "flow")
    cfg = root / ".harness" / "config.yaml"
    cfg.write_text(cfg.read_text() + "resolver: {budget_tokens: 8000, degrade: x}\n")
    out = upgrade_010.run(root, upgrade_010.always_yes, dry_run=False)
    assert _w1(out) == ["w1.drop-resolver-config"]
    assert "resolver" not in yaml.safe_load(cfg.read_text())


INDENTLESS = ("schema: 1\nresolver:\n  budget_tokens: 8000\n  ranking:\n"
              "  - direct_deps\n  - one_hop_types\n  degrade: x\ngates: {}\n")


def test_indentless_list_is_stripped_whole():
    from engine.upgrade_w1 import _strip_resolver_keys
    assert yaml.safe_load(_strip_resolver_keys(INDENTLESS)) == {
        "schema": 1, "gates": {}}


def test_backstop_falls_back_to_yaml_when_the_line_stripper_corrupts(
        tmp_path, monkeypatch):
    from engine import upgrade_w1
    root = build_toy_repo(tmp_path / "bs")
    cfg = root / ".harness" / "config.yaml"
    cfg.write_text(INDENTLESS)
    monkeypatch.setattr(upgrade_w1, "_strip_resolver_keys",
                        lambda text: text.replace("  budget_tokens: 8000\n", ""))
    upgrade_w1._apply_resolver(root, lambda q: True)
    assert yaml.safe_load(cfg.read_text()) == {"schema": 1, "gates": {}}


def test_untrack_shadows_with_harness_root_in_a_subdirectory(tmp_path):
    repo = tmp_path / "mono"
    repo.mkdir()
    git(repo, "init", "-q")
    sub = repo / "app"
    shadows = sub / ".harness" / "shadows"
    shadows.mkdir(parents=True)
    (shadows / "a.json").write_text("{}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "x")
    from engine.upgrade_w1 import _apply_shadows
    _apply_shadows(sub, lambda q: True)
    assert not shadows.exists()
    assert git(repo, "diff", "--cached", "--name-only").stdout.strip() == \
        "app/.harness/shadows/a.json"
