"""Issue #2: `harness explore` creates explore/ and its three files."""
import json

from conftest import run_cli

FILES = ["explore/DECISIONS.md", "explore/VERIFY.md", "explore/OPEN.md"]


def test_explore_creates_the_folder_and_three_files(toy):
    proc = run_cli("explore", root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["created"] == FILES
    assert out["kept"] == []
    for rel in FILES:
        assert (toy / rel).is_file()
    assert (toy / "explore" / "DECISIONS.md").read_text().startswith(
        "# Decisions")


def test_explore_never_overwrites_a_file(toy):
    run_cli("explore", root=toy)
    (toy / "explore" / "DECISIONS.md").write_text("# mine\n")
    out = json.loads(run_cli("explore", root=toy).stdout)
    assert out["created"] == []
    assert out["kept"] == FILES
    assert (toy / "explore" / "DECISIONS.md").read_text() == "# mine\n"


def test_scaffold_warns_when_explore_held_other_files(toy):
    (toy / "explore").mkdir()
    (toy / "explore" / "service.py").write_text("x = 1\n")
    out = json.loads(run_cli("explore", root=toy).stdout)
    assert "G9" in out["warning"]
    again = json.loads(run_cli("explore", root=toy).stdout)
    assert "warning" not in again


def test_explore_active_needs_decisions_md(toy):
    from engine.explore import explore_active
    assert not explore_active(toy)
    run_cli("explore", root=toy)
    assert explore_active(toy)


def test_explore_is_in_the_command_table():
    from engine.cli import COMMANDS
    assert "explore" in COMMANDS


def test_templates_keep_examples_out_of_live_statements():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "templates" / "explore"
            / "VERIFY.md").read_text()
    import re
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    live = [ln for ln in text.splitlines() if re.match(r"\s*[-*]\s+V-", ln)]
    assert live == []


def test_explore_never_writes_through_a_dangling_symlink(toy, tmp_path):
    (toy / "explore").mkdir()
    outside = tmp_path / "elsewhere.md"
    (toy / "explore" / "OPEN.md").symlink_to(outside)
    proc = run_cli("explore", root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert not outside.exists()
    assert "explore/OPEN.md" not in out["created"]
    assert "explore/OPEN.md" in out["warning"]
    assert len(out["warning"].split()) <= 25
