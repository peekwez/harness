"""Spec 9.2: the hook shows the short message, then the fix."""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, PLUGIN_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HOOK = _load("hook_adapter_render", "hooks/adapter.py")
COMMON = _load("adapters_common_render", "adapters/common.py")

FINDINGS = [
    {"code": "UNDECLARED_FILE", "rule_ref": "gate:G3",
     "message": "rogue.py is outside the declared files of slice slice-042.",
     "fix": "Add rogue.py to predicted_files of slice slice-042.",
     "inject": []},
    {"code": "INTERFACE_DRIFT", "rule_ref": "gate:G6",
     "message": "public interface of 'telemetry' changed since slice start: "
                "1 added, 0 removed.",
     "fix": None, "inject": ["added: ['level']"]},
]

EXPECTED = (
    "[UNDECLARED_FILE gate:G3] rogue.py is outside the declared files of "
    "slice slice-042.\n"
    "  Fix: Add rogue.py to predicted_files of slice slice-042.\n"
    "[INTERFACE_DRIFT gate:G6] public interface of 'telemetry' changed "
    "since slice start: 1 added, 0 removed.\n"
    "added: ['level']\n"
    "Details: harness gates explain <CODE>")


def test_claude_hook_renders_message_then_fix():
    assert HOOK.render_findings(FINDINGS) == EXPECTED


def test_other_hosts_render_the_same_text():
    assert COMMON.render_findings(FINDINGS) == EXPECTED
    assert COMMON.reasons_text({"findings": FINDINGS}) == EXPECTED


def test_no_findings_render_nothing():
    assert HOOK.render_findings([]) == ""
    assert COMMON.reasons_text({"findings": []}) == ""


def test_finding_without_a_fix_key_renders_no_fix_line():
    """A repo-local gate may return a dict with no `fix` key."""
    f = {"code": "NAMESPACE_CAPTURE", "rule_ref": "adr:002",
         "message": "src/kente/__init__.py captures the kente namespace."}
    text = HOOK.render_findings([f])
    assert "Fix:" not in text and "None" not in text
    assert text.splitlines()[0] == (
        "[NAMESPACE_CAPTURE adr:002] src/kente/__init__.py captures the "
        "kente namespace.")


def test_engine_error_still_wins_in_other_hosts():
    out = COMMON.reasons_text({"engine_error": "boom", "findings": FINDINGS})
    assert out == "harness engine error: boom"


def _reasons_source(rel):
    src = (PLUGIN_ROOT / rel).read_text()
    m = re.search(r"^function reasons\(.*?^}\n", src, flags=re.S | re.M)
    assert m, f"no reasons() in {rel}"
    fn = m.group(0)
    fn = re.sub(r"\(v: Verdict\): string", "(v)", fn)
    return fn


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("rel", ["adapters/opencode/harness.js",
                                 "adapters/pi/harness.ts"])
def test_js_and_ts_adapters_render_the_same_text(rel):
    script = (_reasons_source(rel)
              + "\nconst f = JSON.parse(process.argv[1]);\n"
              + "process.stdout.write(reasons({findings: f}) + '\\u0000'"
              + " + reasons({findings: [], engine_error: 'boom'}));\n")
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(FINDINGS)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[:800]
    out, err = proc.stdout.split("\x00")
    assert out == EXPECTED
    assert err == "harness engine error: boom"
