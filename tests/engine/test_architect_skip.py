"""Spec 5.5 / D-0.10-12: architect needs explore, a spec, or a skip reason."""
import json

from conftest import PLUGIN_ROOT, run_cli
from explore_samples import DECISIONS, OPEN, VERIFY

from engine.explore import (SKIP_MARKER, explore_summary_extra, record_skip,
                            skip_reason)

DOC = "docs/architecture.md"


def test_architect_with_no_source_refuses_to_start(toy):
    proc = run_cli("architect", root=toy)
    assert proc.returncode == 1
    err = json.loads(proc.stderr)["error"]
    assert err.startswith("architect: no frozen explore/")
    assert "harness explore" in err and "--skip-explore" in err
    assert not (toy / DOC).exists()


def test_unfrozen_explore_names_the_freeze_command(toy):
    run_cli("explore", root=toy)
    proc = run_cli("architect", root=toy)
    assert proc.returncode == 1
    assert "harness explore --freeze" in json.loads(proc.stderr)["error"]


def test_frozen_explore_is_a_source_without_a_flag(toy):
    run_cli("explore", root=toy)
    (toy / "explore" / "DECISIONS.md").write_text(DECISIONS)
    (toy / "explore" / "VERIFY.md").write_text(VERIFY)
    (toy / "explore" / "OPEN.md").write_text(OPEN)
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    proc = run_cli("architect", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["rows"] == ["D-E1"]


def test_skip_explore_seeds_a_stage_1_doc_with_the_reason(toy):
    proc = run_cli("architect", "--skip-explore", "one endpoint, no stores",
                   root=toy)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["doc"].endswith(DOC)          # the CLI resolves symlinks
    assert out["stage"] == 1
    assert out["explore_skipped"] == "one endpoint, no stores"
    text = (toy / DOC).read_text()
    assert "<!-- stage: 1 -->" in text
    assert "<!-- explore-skipped: one endpoint, no stores -->" in text
    assert "[assumption] Explore was skipped: one endpoint, no stores" in text


def test_skip_explore_on_an_existing_doc_keeps_its_content(toy):
    doc = toy / DOC
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("# Arch\n\n<!-- stage: 3 -->\nbody\n")
    proc = run_cli("architect", "--skip-explore", "spike", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["stage"] == 3
    assert doc.read_text() == ("# Arch\n\n<!-- explore-skipped: spike -->\n\n"
                               "<!-- stage: 3 -->\nbody\n")


def test_skip_explore_with_blank_reason_refuses(toy):
    proc = run_cli("architect", "--skip-explore", "   ", root=toy)
    assert proc.returncode == 1
    assert "needs a reason" in json.loads(proc.stderr)["error"]
    assert not (toy / DOC).exists()


def test_skip_reason_is_one_line_and_cannot_close_the_comment():
    text = record_skip(None, "  spike\n only -->  ")
    assert SKIP_MARKER.search(text).group(1) == "spike only ->"
    again = record_skip(text, "second")
    assert again.count("explore-skipped") == 1
    assert SKIP_MARKER.search(again).group(1) == "second"


def test_skip_reason_is_found_in_a_non_default_doc(toy):
    run_cli("architect", "--skip-explore", "spike", "--doc", "docs/design.md",
            root=toy)
    assert skip_reason(toy) == "spike"


def test_skip_reason_ignores_markers_in_fenced_code(toy):
    doc = toy / DOC
    doc.parent.mkdir(exist_ok=True)
    doc.write_text("# Arch\n\n```\n<!-- explore-skipped: example -->\n```\n")
    assert skip_reason(toy) is None


def test_summary_extra_carries_the_skip_reason(toy):
    assert explore_summary_extra(toy) == {}
    run_cli("architect", "--skip-explore", "spike", root=toy)
    assert explore_summary_extra(toy) == {"explore_skipped": "spike"}


def test_summary_extra_is_empty_once_explore_is_frozen(toy):
    run_cli("architect", "--skip-explore", "spike", root=toy)
    run_cli("explore", root=toy)
    (toy / "explore" / "DECISIONS.md").write_text(DECISIONS)
    (toy / "explore" / "VERIFY.md").write_text(VERIFY)
    (toy / "explore" / "OPEN.md").write_text(OPEN)
    assert run_cli("explore", "--freeze", root=toy).returncode == 0
    assert explore_summary_extra(toy) == {}


def test_slice_summary_row_records_explore_skipped(toy):
    from engine.telemetry import record_slice_summary
    run_cli("architect", "--skip-explore", "spike", root=toy)
    row = record_slice_summary(toy, "slice-042",
                               extra=explore_summary_extra(toy))
    assert row["explore_skipped"] == "spike"
    last = (toy / ".harness" / "slice-metrics.jsonl").read_text() \
        .strip().splitlines()[-1]
    assert json.loads(last)["explore_skipped"] == "spike"


def test_close_ceremony_passes_the_explore_extra():
    body = (PLUGIN_ROOT / "engine" / "cli" / "ceremony.py").read_text()
    assert "explore_summary_extra(root)" in body
