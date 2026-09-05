"""Surfaces the suite never exercised: TypeScript/HCL/YAML shadows, the
scaffolded CI workflow, non-Claude adapter permission parity, and telemetry
retention."""
import json
import subprocess
import sys

from conftest import PLUGIN_ROOT, run_cli
from engine import load_config, read_jsonl


# ---------------------------------------------------------------- TypeScript
TS_SOURCE = """import { emitSpan } from './telemetry';
import lodash from 'lodash';

export interface Order {
  sku: string;
  qty: number;
}

export type OrderResult = { ok: boolean };

export class OrderService {
  create(sku: string): Order {
    return { sku, qty: 1 };
  }
}

export function createOrder(sku: string): Order {
  emitSpan('create_order', { sku });
  return { sku, qty: 1 };
}

function internalHelper(): void {}
"""


def test_typescript_shadow_extracts_the_real_interface(toy):
    from engine.extractor.engine import extract_path
    src = toy / "orders.ts"
    src.write_text(TS_SOURCE)
    shadow, findings = extract_path(toy, src, load_config(toy))
    assert shadow["language"] == "typescript", findings
    names = {s["name"]: s for s in shadow["symbols"]}
    assert {"Order", "OrderService", "createOrder"} <= set(names), names
    assert names["createOrder"]["kind"] == "function"
    assert names["Order"]["kind"] == "interface"
    assert names["OrderService"]["kind"] == "class"
    assert "sku: string" in names["createOrder"]["signature"]
    # exported vs module-private
    assert names["createOrder"]["visibility"] == "public"
    assert names["internalHelper"]["visibility"] == "private"
    assert "internalHelper" not in shadow["exports"]
    # imports: relative kept whole, packages reduced to the package name
    assert "./telemetry" in shadow["imports"] and "lodash" in shadow["imports"]


def test_typescript_shadow_regenerates_identically(toy):
    """G7's guarantee must hold for every enabled language, not just Python."""
    from engine.extractor.engine import extract_path
    from engine.gates.g7_derivation import derivation_findings
    (toy / "orders.ts").write_text(TS_SOURCE)
    extract_path(toy, toy / "orders.ts", load_config(toy))
    assert not [f for f in derivation_findings(toy, load_config(toy))
                if f["severity"] == "block"]


HCL_SOURCE = """variable "region" {
  type    = string
  default = "us-east-1"
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "harness-artifacts"
}

output "bucket_name" {
  value = aws_s3_bucket.artifacts.bucket
}
"""


def test_hcl_shadow_extracts_blocks(toy):
    from engine.extractor.engine import extract_path
    src = toy / "main.tf"
    src.write_text(HCL_SOURCE)
    shadow, findings = extract_path(toy, src, load_config(toy))
    assert shadow["language"] == "hcl", findings
    names = {s["name"] for s in shadow["symbols"]}
    assert "variable.region" in names and "output.bucket_name" in names, names
    assert "resource.aws_s3_bucket.artifacts" in names, names
    # variables and outputs are the public surface of a module
    assert "variable.region" in shadow["exports"]
    assert "resource.aws_s3_bucket.artifacts" not in shadow["exports"]


def test_yaml_shadow_extracts_top_level_keys(toy):
    from engine.extractor.engine import extract_path
    src = toy / "pipeline.yaml"
    src.write_text("name: build\non:\n  push:\n    branches: [main]\njobs:\n"
                   "  test:\n    runs-on: ubuntu-latest\n")
    shadow, _ = extract_path(toy, src, load_config(toy))
    assert shadow["language"] == "yaml"
    names = {s["name"] for s in shadow["symbols"]}
    assert {"name", "on", "jobs"} <= names, names
    assert "branches" not in names, "only top-level keys are the interface"


# ---------------------------------------------------------------- CI workflow
def test_scaffolded_ci_workflow_is_valid_yaml_with_the_engine_step(tmp_path):
    import yaml
    root = tmp_path / "ci"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    assert run_cli("init", root=root).returncode == 0
    wf = yaml.safe_load((root / ".github" / "workflows" /
                         "harness-verify.yml").read_text())
    triggers = wf.get(True) or wf.get("on")     # yaml parses bare `on:` as True
    assert "pull_request" in triggers and "workflow_dispatch" in triggers, triggers
    steps = wf["jobs"]["verify"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert any("harness engine" in n for n in names), names
    assert any("harness verify" in n for n in names), names
    # the verify step must not assume a vendored ./bin/harness (X5)
    verify_step = next(s for s in steps if s.get("name") == "harness verify")
    assert "$HARNESS_BIN" in verify_step["run"]


def test_this_repo_actually_runs_its_own_ship_gate():
    """README: "`harness verify` runs in this repo's CI ... the ship gate for
    every release." That claim needs a workflow to exist."""
    import yaml
    wf_path = PLUGIN_ROOT / ".github" / "workflows" / "harness-verify.yml"
    assert wf_path.exists(), "the self-hosting claim needs a real workflow"
    wf = yaml.safe_load(wf_path.read_text())
    assert "verify" in wf["jobs"]


def test_ci_engine_resolution_step_runs(tmp_path):
    """Exercise the locate-or-fetch shell logic itself: vendored engine wins,
    and a repo with neither vendor nor variable fails with the named fix."""
    import yaml
    root = tmp_path / "ci2"
    (root / ".github").mkdir(parents=True)
    run_cli("init", root=root)
    wf = yaml.safe_load((root / ".github" / "workflows" /
                         "harness-verify.yml").read_text())
    script = next(s for s in wf["jobs"]["verify"]["steps"]
                  if "harness engine" in s.get("name", ""))["run"]
    env_file = root / "gh_env"

    # (a0) init vendored the engine under .harness/engine -> chosen first
    proc = subprocess.run(["bash", "-c", script], cwd=root, capture_output=True,
                          text=True, env={"GITHUB_ENV": str(env_file),
                                          "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    assert "HARNESS_BIN=.harness/engine/bin/harness" in env_file.read_text()
    import shutil
    shutil.rmtree(root / ".harness" / "engine")
    env_file.write_text("")

    # (a) root-level engine present (self-hosted) -> chosen, no clone attempted
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "harness").write_text("#!/bin/sh\n")
    (root / "bin" / "harness").chmod(0o755)
    proc = subprocess.run(["bash", "-c", script], cwd=root, capture_output=True,
                          text=True, env={"GITHUB_ENV": str(env_file),
                                          "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    assert "HARNESS_BIN=./bin/harness" in env_file.read_text()

    # (b) nothing to go on -> fails with the setup instruction
    (root / "bin" / "harness").unlink()
    env_file.write_text("")
    proc = subprocess.run(["bash", "-c", script], cwd=root, capture_output=True,
                          text=True, env={"GITHUB_ENV": str(env_file),
                                          "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 1
    assert "HARNESS_REPO" in proc.stdout + proc.stderr


# ---------------------------------------------------------------- adapters
def test_non_claude_adapters_auto_approve_declared_work(toy):
    """Permission parity: the gates answer the approval question on every
    host that has a pre-change hook, not just Claude Code."""
    run_cli("start", "--slice", "slice-042", "--session", "ac", "--no-worktree",
            root=toy)
    for name, hook in (
        ("codex", {"hook_event_name": "PreToolUse", "session_id": "ac",
                   "tool_name": "apply_patch",
                   "tool_input": {"input": "*** Update File: orders.py\n@@"}}),
        ("cursor", {"hook_event_name": "preToolUse", "session_id": "ac",
                    "tool_input": {"file_path": "orders.py"}}),
    ):
        adapter = PLUGIN_ROOT / "adapters" / name / "adapter.py"
        proc = subprocess.run(
            [sys.executable, str(adapter)], input=json.dumps(hook),
            capture_output=True, text=True, cwd=str(toy),
            env={"HARNESS_BIN": str(PLUGIN_ROOT / "bin" / "harness"),
                 "PATH": "/usr/bin:/bin", "HOME": str(toy)})
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
        blob = json.dumps(out)
        assert "allow" in blob, f"{name} should auto-approve declared work: {blob}"


# ---------------------------------------------------------------- retention
def test_telemetry_rotates_into_an_archive(toy):
    from engine import telemetry
    cap = 25
    import yaml
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg.setdefault("telemetry", {})["max_rows"] = cap
    cfg_path.write_text(yaml.safe_dump(cfg))
    for i in range(cap + 10):
        telemetry.emit(toy, "slice_closed", {"slice": f"s-{i}"})
    moved = telemetry.rotate(toy, load_config(toy))
    assert moved > 0
    live = read_jsonl(toy / ".harness" / "telemetry.jsonl")
    archive = read_jsonl(toy / ".harness" / "telemetry.archive.jsonl")
    assert len(live) <= cap and archive, (len(live), len(archive))
    # nothing is lost, only moved
    assert len(live) + len(archive) == cap + 10
    # the newest rows stay live
    assert live[-1]["meta"]["slice"] == f"s-{cap + 9}"


def test_status_since_filters_the_window(toy):
    from engine import telemetry
    telemetry.emit(toy, "slice_closed", {"slice": "old"})
    rows = read_jsonl(toy / ".harness" / "telemetry.jsonl")
    rows[0]["ts"] = "2020-01-01T00:00:00+00:00"
    from engine import write_jsonl
    write_jsonl(toy / ".harness" / "telemetry.jsonl", rows)
    telemetry.emit(toy, "slice_closed", {"slice": "new"})
    out = json.loads(run_cli("status", "--since", "2021-01-01", root=toy).stdout)
    assert out["window"]["since"] == "2021-01-01"
    assert out["window"]["rows"] == 1
