"""W5 (spec 6.3): binding a slice records that its suite fails first."""
import json
import sys

import pytest
import yaml
from conftest import build_toy_repo, git, run_cli
from engine import HarnessError, load_config

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def _toy(tmp_path):
    return build_toy_repo(tmp_path / "toy", legacy_verification=False)


def _set_config(root, section, **keys):
    path = root / ".harness" / "config.yaml"
    cfg = yaml.safe_load(path.read_text())
    cfg.setdefault(section, {}).update(keys)
    path.write_text(yaml.safe_dump(cfg))


def _bind(root, session="rr"):
    proc = run_cli("slice", "--slice", "slice-042", "--session", session,
                   root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(proc.stdout)


def _record(root):
    return json.loads((root / ".harness" / "verification" /
                       "slice-042.json").read_text())


def _commit(root, msg):
    git(root, "add", "-A")
    git(root, "commit", "-qm", msg)


# ------------------------------------------------------------- command build
def test_default_cmd_appends_junitxml_when_given_a_path(toy):
    from engine.cli.acceptance import _acceptance_cmd
    assert _acceptance_cmd(load_config(toy), ["t.py"], "/py",
                           junit="/tmp/r.xml") == \
        ["/py", "-m", "pytest", "t.py", "-q", "--junitxml=/tmp/r.xml"]


def test_custom_cmd_substitutes_the_junit_placeholder(toy):
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    cfg["acceptance"] = {"cmd": "pytest {paths} --junitxml={junit}"}
    assert _acceptance_cmd(cfg, ["t.py"], "/py", junit="/tmp/r x.xml") == \
        ["pytest", "t.py", "--junitxml=/tmp/r x.xml"]


def test_junit_placeholder_without_a_path_goes_to_devnull(toy):
    import os
    from engine.cli.acceptance import _acceptance_cmd
    cfg = load_config(toy)
    cfg["acceptance"] = {"cmd": "pytest {paths} --junitxml={junit}"}
    assert _acceptance_cmd(cfg, ["t.py"], "/py")[-1] == \
        f"--junitxml={os.devnull}"


def test_junit_must_be_a_boolean(toy):
    from engine.cli.acceptance import junit_enabled
    cfg = load_config(toy)
    cfg["acceptance"] = {"junit": "yes"}
    with pytest.raises(HarnessError) as exc:
        junit_enabled(cfg)
    assert "acceptance.junit" in str(exc.value)


# ------------------------------------------------------------- red record
def test_bind_writes_a_red_record_when_the_suite_fails(tmp_path):
    toy = _toy(tmp_path)
    out = _bind(toy)
    assert out["red_record"]["red"] is True
    assert out["red_record"]["path"] == ".harness/verification/slice-042.json"
    rec = _record(toy)
    assert rec["slice"] == "slice-042"
    assert rec["exit_code"] not in (0, None)
    assert rec["red"] is True and rec["green_at_start"] is False
    assert rec["commit"] == git(toy, "rev-parse", "HEAD").stdout.strip()
    assert rec["ran_at"] and "output_tail" in rec
    assert "per_test" not in rec


def test_a_suite_green_at_start_is_recorded(tmp_path):
    toy = _toy(tmp_path)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    _commit(toy, "orders before the slice")
    out = _bind(toy)
    assert out["red_record"]["green_at_start"] is True
    rec = _record(toy)
    assert rec["exit_code"] == 0
    assert rec["green_at_start"] is True and rec["red"] is False


def test_runner_errors_are_never_red(tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "acceptance", cmd="no-such-binary-w5 {paths}")
    rec_out = _bind(toy)["red_record"]
    assert rec_out["red"] is False and rec_out["green_at_start"] is False
    assert rec_out["runner_error"]

    toy2 = build_toy_repo(tmp_path / "toy2", legacy_verification=False)
    (toy2 / "tests" / "slices" / "042_orders.py").write_text("X = 1\n")
    _commit(toy2, "no tests in the acceptance file")
    rec = _bind(toy2)["red_record"]
    assert rec["red"] is False and "pytest exit 5" in rec["runner_error"]


def test_a_glob_matching_nothing_is_a_runner_error(tmp_path):
    from engine import get_slice, save_slice
    toy = _toy(tmp_path)
    sl = get_slice(toy, "slice-042")
    sl["acceptance"] = ["tests/slices/9*_none.py"]
    save_slice(toy, sl)
    rec = _bind(toy)["red_record"]
    assert rec["red"] is False and "matches no files" in rec["runner_error"]


def test_rebind_keeps_a_red_record_and_reruns_a_green_one(tmp_path):
    toy = _toy(tmp_path)
    _bind(toy)
    first = _record(toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    second = _bind(toy, session="rr2")["red_record"]
    assert second["reused"] is True and second["red"] is True
    assert _record(toy) == first

    toy2 = build_toy_repo(tmp_path / "toy2", legacy_verification=False)
    (toy2 / "orders.py").write_text(GOOD_ORDERS)
    _commit(toy2, "orders before the slice")
    assert _bind(toy2)["red_record"]["green_at_start"] is True
    (toy2 / "tests" / "slices" / "042_orders.py").write_text(
        "def test_orders():\n    import orders\n"
        "    assert orders.create_order('x') == {'sku': 'y'}\n")
    again = _bind(toy2, session="rr3")["red_record"]
    assert again["reused"] is False and again["red"] is True


def test_legacy_slices_get_no_red_record(toy):
    out = _bind(toy)
    assert out["red_record"] is None
    assert not (toy / ".harness" / "verification").exists()


def test_runner_none_skips_the_red_record(tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "gates", acceptance_runner="none")
    out = _bind(toy)
    assert "skipped" in out["red_record"]
    assert not (toy / ".harness" / "verification").exists()


def test_junit_records_each_test_result(tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "acceptance", junit=True)
    _bind(toy)
    rec = _record(toy)
    assert len(rec["per_test"]) == 1
    assert rec["per_test"][0]["test"].endswith("test_orders")
    assert rec["per_test"][0]["outcome"] == "failed"


def test_junit_with_a_custom_cmd_without_the_placeholder_is_reported(tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "acceptance", junit=True,
                cmd=f"{sys.executable} -m pytest {{paths}} -q")
    _bind(toy)
    rec = _record(toy)
    assert rec["red"] is True
    assert "{junit}" in rec["junit_error"]
    assert "per_test" not in rec


def test_start_records_red_in_the_worktree(tmp_path):
    toy = _toy(tmp_path)
    proc = run_cli("start", "--slice", "slice-042", "--session", "st",
                   root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wt = toy / ".worktrees" / "slice-042"
    assert json.loads((wt / ".harness" / "verification" /
                       "slice-042.json").read_text())["red"] is True


# ------------------------------------------------------------- fix round 1
def test_a_corrupt_record_fails_loud_and_is_untouched(tmp_path):
    toy = _toy(tmp_path)
    rec = toy / ".harness" / "verification" / "slice-042.json"
    rec.parent.mkdir(parents=True)
    rec.write_bytes(b"{not json")
    proc = run_cli("slice", "--slice", "slice-042", "--session", "c", root=toy)
    assert proc.returncode != 0
    assert ".harness/verification/slice-042.json" in proc.stdout + proc.stderr
    assert "Repair or delete" in proc.stdout + proc.stderr
    assert rec.read_bytes() == b"{not json"


def test_a_slow_suite_times_out_as_a_runner_error(tmp_path):
    toy = _toy(tmp_path)
    (toy / "tests" / "slices" / "042_orders.py").write_text(
        "import time\n\n\ndef test_slow():\n    time.sleep(30)\n")
    _commit(toy, "slow test")
    _set_config(toy, "acceptance", red_timeout=1)
    out = _bind(toy)["red_record"]
    assert out["red"] is False and out["green_at_start"] is False
    assert "timed out after 1s" in out["runner_error"]


def test_red_timeout_must_be_a_positive_integer_before_any_state_change(
        tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "acceptance", red_timeout=0)
    proc = run_cli("slice", "--slice", "slice-042", "--session", "t", root=toy)
    assert proc.returncode != 0
    assert "red_timeout" in proc.stdout + proc.stderr
    from engine import get_slice
    assert get_slice(toy, "slice-042")["status"] == "planned"


def test_bad_junit_value_leaves_the_slice_unbound(tmp_path):
    toy = _toy(tmp_path)
    _set_config(toy, "acceptance", junit="yes")
    proc = run_cli("slice", "--slice", "slice-042", "--session", "t", root=toy)
    assert proc.returncode != 0
    from engine import get_slice
    assert get_slice(toy, "slice-042")["status"] == "planned"


def test_custom_pytest_command_exit_5_is_a_runner_error(tmp_path):
    toy = _toy(tmp_path)
    (toy / "tests" / "slices" / "042_orders.py").write_text("X = 1\n")
    _commit(toy, "no tests")
    _set_config(toy, "acceptance",
                cmd=f"{sys.executable} -m pytest {{paths}} -q")
    rec = _bind(toy)["red_record"]
    assert rec["red"] is False and "pytest exit 5" in rec["runner_error"]


def test_malformed_junit_xml_is_a_junit_error(tmp_path):
    toy = _toy(tmp_path)
    junit = toy / "fake.py"
    junit.write_text("import sys\nopen(sys.argv[1], 'w').write('<oops')\n"
                     "sys.exit(1)\n")
    _set_config(toy, "acceptance", junit=True,
                cmd=f"{sys.executable} {junit} {{junit}}")
    rec = _bind(toy)["red_record"]
    assert rec["red"] is True
    assert "JUnit XML is not readable" in rec["junit_error"]
    assert not (toy / ".harness" / "cache" / "junit" / "slice-042.xml").exists()
