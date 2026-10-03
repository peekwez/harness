"""The CLI is a package of modules, not a 2,500-line shebang script.

`bin/harness` is the portability boundary and must stay a thin dispatcher;
the subcommand implementations live in `engine/cli/`, one module per command
family, each small enough to load into an agent's context whole.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_bin_is_thin_dispatcher():
    assert len((ROOT / "bin" / "harness").read_text().splitlines()) <= 40


def test_every_subcommand_has_a_cli_module():
    from engine.cli import COMMANDS
    for name in ("init", "verify", "close-slice", "start", "review",
                 "compile"):
        assert name in COMMANDS


def test_cli_modules_under_500_lines():
    for p in (ROOT / "engine" / "cli").glob("*.py"):
        assert len(p.read_text().splitlines()) <= 500, p


def test_help_still_lists_all_subcommands():
    out = subprocess.run([sys.executable, str(ROOT / "bin" / "harness"),
                          "--help"], capture_output=True, text=True).stdout
    for name in ("init", "verify", "close-slice", "merge-slice", "permit"):
        assert name in out


def test_run_is_removed():
    """0.10 (spec 10.2): campaign mode had 0 dispatches in the field."""
    from engine.cli import COMMANDS
    assert "run" not in COMMANDS
    assert not (ROOT / "engine" / "cli" / "run.py").exists()
    proc = subprocess.run([sys.executable, str(ROOT / "bin" / "harness"),
                           "run"], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "invalid choice: 'run'" in proc.stderr


def test_run_builder_templates_are_removed():
    for name in ("claude-builder.sh", "claude-builder-sdk.py"):
        assert not (ROOT / "templates" / name).exists(), name
