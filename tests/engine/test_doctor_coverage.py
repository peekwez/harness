"""Spec 4.1: G8 is removed; `doctor` reports unshadowed source files."""
import json

from conftest import PLUGIN_ROOT, make_event, run_cli
from engine.events import handle_event


def test_g8_is_not_a_gate():
    from engine.gates import builtin_gates
    assert "G8" not in [g.GATE["id"] for g in builtin_gates()]
    assert not (PLUGIN_ROOT / "engine" / "gates" / "g8_coverage.py").exists()


def test_post_change_on_an_unknown_language_raises_no_gate_finding(toy):
    (toy / "main.rb").write_text("puts 1\n")
    v = handle_event(make_event("post_change", session="g8",
                                files=["main.rb"]), toy)
    assert "UNSHADOWED_FILE" not in {f["code"] for f in v["findings"]}


def test_doctor_lists_unshadowed_source_files(toy):
    (toy / "main.rb").write_text("puts 1\n")
    (toy / "docs").mkdir()
    (toy / "docs" / "example.rb").write_text("puts 2\n")   # exempt prefix
    (toy / "README.md").write_text("# toy\n")              # ignored ext
    proc = run_cli("doctor", "--substrate", root=toy)
    out = json.loads(proc.stdout)
    assert "main.rb" in out["unshadowed_files"]
    assert "telemetry.py" not in out["unshadowed_files"]
    assert "docs/example.rb" not in out["unshadowed_files"]
    assert "README.md" not in out["unshadowed_files"]
