"""W5 (spec 6.3): an edit before the red record gives one advisory line."""
import json

from conftest import build_toy_repo, make_event
from engine.events import handle_event


def _codes(verdict):
    return [f for f in verdict["findings"] if f["code"] == "NO_RED_RECORD"]


def _toy(tmp_path):
    return build_toy_repo(tmp_path / "toy", legacy_verification=False)


def test_source_edit_without_red_record_gives_one_advisory(tmp_path):
    toy = _toy(tmp_path)
    verdict = handle_event(make_event("pre_change",
                                      files=["orders.py", "config.py"]), toy)
    found = _codes(verdict)
    assert len(found) == 1
    finding = found[0]
    assert finding["severity"] == "advisory"
    assert finding["rule_ref"] == "verify:red-record"
    assert "slice-042" in finding["message"]
    assert len(finding["message"].split()) <= 25
    assert "harness slice --slice slice-042" in json.dumps(finding)


def test_test_edits_give_no_advisory(tmp_path):
    toy = _toy(tmp_path)
    for path in ("tests/slices/042_orders.py", "tests/test_new.py",
                 "web/a.test.ts"):
        assert _codes(handle_event(make_event("pre_change", files=[path]),
                                   toy)) == [], path


def test_exempt_paths_give_no_advisory(tmp_path):
    toy = _toy(tmp_path)
    assert _codes(handle_event(make_event("pre_change",
                                          files=["docs/notes.md"]), toy)) == []


def test_no_advisory_once_a_record_exists(tmp_path):
    toy = _toy(tmp_path)
    record = toy / ".harness" / "verification" / "slice-042.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"slice": "slice-042", "red": True}))
    assert _codes(handle_event(make_event("pre_change", files=["orders.py"]),
                               toy)) == []


def test_legacy_slices_give_no_advisory(toy):
    assert _codes(handle_event(make_event("pre_change", files=["orders.py"]),
                               toy)) == []


def test_post_change_gives_no_advisory(tmp_path):
    toy = _toy(tmp_path)
    assert _codes(handle_event(make_event("post_change", files=["orders.py"]),
                               toy)) == []


def test_corrupt_record_does_not_break_the_hook(tmp_path):
    toy = _toy(tmp_path)
    record = toy / ".harness" / "verification" / "slice-042.json"
    record.parent.mkdir(parents=True)
    record.write_text("{not json")
    verdict = handle_event(make_event("pre_change", files=["orders.py"]), toy)
    assert _codes(verdict) == []
