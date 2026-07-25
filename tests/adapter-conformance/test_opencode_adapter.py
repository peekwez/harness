"""Live conformance for the OpenCode plugin (harness.js), run under node:
throw-to-deny before Phase 1, allow after, session.idle -> unit_complete,
inert without HARNESS_BIN/substrate. Plus validity checks for every
autonomy profile shipped in adapters/."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PLUGIN_ROOT / "tests"))
sys.path.insert(0, str(PLUGIN_ROOT))

NODE = shutil.which("node")

DRIVER = """
import { HarnessPlugin } from '%(plugin)s';
import { writeFileSync } from 'node:fs';
const results = [];
const hooks = await HarnessPlugin({ directory: '%(root)s', worktree: '%(root)s' });

// 1. pre-change before Phase 1 -> must throw (G2)
try {
  await hooks['tool.execute.before'](
    { tool: 'edit', sessionID: 'oc-1', callID: 'c1' },
    { args: { filePath: 'orders.py' } });
  results.push(['deny-before-phase1', 'NO-THROW']);
} catch (e) { results.push(['deny-before-phase1', e.message]); }

// 2. session.created -> session_start (Phase 1 side effects + injection state)
await hooks.event({ event: { type: 'session.created',
                             properties: { sessionID: 'oc-1' } } });

// 3. same edit now allowed
try {
  await hooks['tool.execute.before'](
    { tool: 'edit', sessionID: 'oc-1', callID: 'c2' },
    { args: { filePath: 'orders.py' } });
  results.push(['allow-after-inject', 'ok']);
} catch (e) { results.push(['allow-after-inject', 'THREW: ' + e.message]); }

// 4. non-goal boundary still denies
try {
  await hooks['tool.execute.before'](
    { tool: 'write', sessionID: 'oc-1', callID: 'c3' },
    { args: { filePath: 'legacy/exporter.py' } });
  results.push(['non-goal', 'NO-THROW']);
} catch (e) { results.push(['non-goal', e.message]); }

// 5. the edit actually lands (what the real tool would have done),
// then after + idle: touch recording and unit_complete side effects
writeFileSync('%(root)s/orders.py',
  "import telemetry\\n\\ndef create_order(sku):\\n" +
  "    return telemetry.emit_span('create_order', {'sku': sku})\\n");
await hooks['tool.execute.after'](
  { tool: 'edit', sessionID: 'oc-1', callID: 'c2',
    args: { filePath: 'orders.py' } }, {});
await hooks.event({ event: { type: 'session.idle',
                             properties: { sessionID: 'oc-1' } } });
results.push(['idle', 'ok']);

// 6. non-edit tools pass through untouched
await hooks['tool.execute.before'](
  { tool: 'grep', sessionID: 'oc-1', callID: 'c4' },
  { args: { pattern: 'x' } });
results.push(['non-edit-passthrough', 'ok']);

console.log(JSON.stringify(results));
"""


def run_driver(toy, env_extra=None):
    env = dict(os.environ)
    env["HARNESS_BIN"] = str(PLUGIN_ROOT / "bin" / "harness")
    env["HARNESS_SLICE"] = "slice-042"
    if env_extra:
        env.update(env_extra)
    code = DRIVER % {
        "plugin": (PLUGIN_ROOT / "adapters" / "opencode" / "harness.js").as_posix(),
        "root": str(toy),
    }
    proc = subprocess.run([NODE, "--input-type=module", "-"],
                          input=code, capture_output=True, text=True,
                          cwd=str(toy), env=env)
    assert proc.returncode == 0, proc.stderr[:1500]
    return dict(json.loads(proc.stdout.strip().splitlines()[-1]))


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_opencode_plugin_full_flow(toy):
    r = run_driver(toy)
    assert "gate:G2" in r["deny-before-phase1"]
    assert r["allow-after-inject"] == "ok"
    assert "NON_GOAL" in r["non-goal"]
    assert r["idle"] == "ok"
    assert r["non-edit-passthrough"] == "ok"
    # idle regenerated the touched file's shadow
    assert (toy / ".harness" / "shadows" / "orders.py.json").exists()


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_opencode_plugin_inert_without_bin(toy):
    env = dict(os.environ)
    env.pop("HARNESS_BIN", None)
    code = ("import { HarnessPlugin } from '"
            + (PLUGIN_ROOT / "adapters" / "opencode" / "harness.js").as_posix()
            + f"';\nconst hooks = await HarnessPlugin({{ directory: '{toy}', "
            "worktree: null });\n"
            "await hooks['tool.execute.before']("
            "{ tool: 'edit', sessionID: 's', callID: 'c' },"
            "{ args: { filePath: 'a.py' } });\nconsole.log('INERT-OK');")
    proc = subprocess.run([NODE, "--input-type=module", "-"],
                          input=code, capture_output=True, text=True, env=env)
    assert proc.returncode == 0 and "INERT-OK" in proc.stdout
    assert "HARNESS_BIN is not set" in proc.stderr  # loud, never silent


# ---------------- autonomy profile files are valid and deny egress ----------
def test_autonomy_profiles_parse_and_deny_push():
    oc = json.loads((PLUGIN_ROOT / "adapters" / "opencode" /
                     "opencode-permissions.json").read_text())
    assert oc["permission"]["bash"]["git push *"] == "deny"
    assert list(oc["permission"]["bash"])[0] == "*", \
        "last-match-wins: the blanket allow must come first"

    cur = json.loads((PLUGIN_ROOT / "adapters" / "cursor" /
                      "cli-permissions.json").read_text())
    assert "Shell(git:push*)" in cur["permissions"]["deny"]

    cc = json.loads((PLUGIN_ROOT / "templates" /
                     "claude-settings.json").read_text())
    assert "Bash(git push:*)" in cc["permissions"]["deny"]

    codex = (PLUGIN_ROOT / "adapters" / "codex" / "autonomy.toml").read_text()
    assert 'approval_policy = "never"' in codex
    assert "network_access = false" in codex
    rules = (PLUGIN_ROOT / "adapters" / "codex" / "no-push.rules").read_text()
    assert '"forbidden"' in rules and '["git", "push"]' in rules

    gem = (PLUGIN_ROOT / "adapters" / "gemini" /
           "autonomy-policy.toml").read_text()
    assert 'commandPrefix = "git push"' in gem and 'decision = "deny"' in gem
    try:
        import tomllib  # py3.11+
        parsed = tomllib.loads(gem)
        assert any(r["decision"] == "deny" for r in parsed["rule"])
        tomllib.loads((PLUGIN_ROOT / "adapters" / "codex" /
                       "autonomy.toml").read_text())
    except ImportError:
        pass  # syntax spot-checked above on 3.10
