"""Pre-0.9 G5 dependency exceptions survive strict namespace enforcement."""
import json

import pytest

from conftest import git, make_event, run_cli
from engine import load_config, read_jsonl, sha256_text, write_jsonl
from engine.events import handle_event
from engine.graph import append_edge, load_edges, override_targets, uses_vs_declares


def legacy_override(root, target="deps:telemetry", rule="gate:G5", reason="Existing dependency approved"):
    return append_edge(root, "override", "slice:slice-042", target,
                       commit=git(root, "rev-parse", "HEAD").stdout.strip(),
                       meta={"rule_ref": rule, "justification": reason,
                             "finding_id": "F-historical"})


def undeclared_use(root):
    rows = read_jsonl(root / ".harness/backlog.jsonl")
    rows[0]["declares_dep"] = ["config"]
    write_jsonl(root / ".harness/backlog.jsonl", rows)
    append_edge(root, "uses", "slice:slice-042", "module:telemetry")
    (root / "orders.py").write_text("import telemetry\n")
    from engine.extractor.engine import extract_path
    extract_path(root, root / "orders.py", load_config(root))


def test_legacy_registry_override_applies_to_graph_and_live_g5(toy):
    undeclared_use(toy)
    legacy_override(toy)
    assert uses_vs_declares(toy, "slice-042")["unresolved"] == []
    result = handle_event(make_event("post_change", files=["orders.py"]), toy)
    assert "UNDECLARED_USE" not in {f["code"] for f in result["findings"]}
    assert override_targets(toy, "slice-042", "gate:G5", {"deps"}) == set()


def test_legacy_landed_slice_verifies_without_reopening_or_new_overrides(toy):
    from engine.graph import write_note
    undeclared_use(toy)
    legacy_override(toy)
    rows = read_jsonl(toy / ".harness/backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness/backlog.jsonl", rows)
    write_note(toy, "HEAD", {"slice_id": "slice-042", "modules_touched": [],
                             "registry_used": ["config"], "memory_ids": []})
    before = (toy / ".harness/edges.jsonl").read_bytes()
    proc = run_cli("verify", root=toy)
    report = json.loads(proc.stdout)
    assert proc.returncode == 0, report
    assert (toy / ".harness/edges.jsonl").read_bytes() == before


@pytest.mark.parametrize("rule,reason", [("gate:G3", "approved"),
                                       ("gate:G6", "approved"),
                                       (None, "approved"),
                                       ("gate:G5", " "),
                                       ("gate:G5", None)])
def test_legacy_alias_requires_its_own_g5_justification(toy, rule, reason):
    undeclared_use(toy)
    legacy_override(toy, rule=rule, reason=reason)
    assert uses_vs_declares(toy, "slice-042")["unresolved"] == ["module:telemetry"]


@pytest.mark.parametrize("target", ["pyproject.toml", "packages/core/pyproject.toml",
                                   "requirements.txt", "package.json", "go.mod",
                                   "folder\\telemetry", "unknown"])
def test_manifest_paths_and_unknown_ids_cannot_become_registry_exceptions(toy, target):
    if target != "unknown":
        rows = read_jsonl(toy / ".harness/registry.jsonl")
        rows.append({**rows[1], "id": target})
        write_jsonl(toy / ".harness/registry.jsonl", rows)
    legacy_override(toy, target="deps:" + target)
    assert override_targets(toy, "slice-042", "gate:G5", {"module", "registry"}) == set()
    assert override_targets(toy, "slice-042", "gate:G5", {"deps"}) == {target}


def test_legacy_alias_supports_dotted_registry_ids_and_stays_slice_scoped(toy):
    rows = read_jsonl(toy / ".harness/registry.jsonl")
    rows.append({**rows[1], "id": "acme.telemetry"})
    write_jsonl(toy / ".harness/registry.jsonl", rows)
    legacy_override(toy, target="deps:acme.telemetry")
    assert override_targets(toy, "slice-042", "gate:G5", {"registry"}) == {"acme.telemetry"}
    assert override_targets(toy, "other-slice", "gate:G5", {"registry"}) == set()


def test_existing_file_named_like_a_registry_id_is_not_aliased(toy):
    (toy / "telemetry").write_text("a manifest without an extension\n")
    legacy_override(toy)
    assert override_targets(toy, "slice-042", "gate:G5", {"registry"}) == set()
    assert override_targets(toy, "slice-042", "gate:G5", {"deps"}) == {"telemetry"}


def test_upgrade_appends_auditable_aliases_once_and_preserves_authored_rows(toy):
    from engine.telemetry import aggregate
    undeclared_use(toy)
    original = legacy_override(toy)
    legacy_override(toy, target="deps:pyproject.toml")
    legacy_override(toy, target="deps:config", rule="gate:G6")
    edges_path = toy / ".harness/edges.jsonl"
    before = edges_path.read_bytes()
    override_counts = aggregate(toy)["override_counts"]
    authored = {name: (toy / ".harness" / name).read_bytes()
                for name in ("backlog.jsonl", "decisions.jsonl", "config.yaml")}

    preview = run_cli("upgrade", "--dry-run", root=toy)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["legacy_overrides"]["would_add"] == 1
    assert edges_path.read_bytes() == before

    proc = run_cli("upgrade", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["legacy_overrides"]["edges_added"] == 1
    assert edges_path.read_bytes().startswith(before)
    canonical = [e for e in load_edges(toy) if e["type"] == "override" and e["to"] == "registry:telemetry"]
    assert len(canonical) == 1
    alias = canonical[0]
    assert alias["commit"] == original["commit"]
    for key in ("justification", "rule_ref", "finding_id"):
        assert alias["meta"][key] == original["meta"][key]
    assert alias["meta"]["legacy_override"]["target"] == "deps:telemetry"
    assert alias["meta"]["legacy_override"]["source_hash"] == sha256_text(
        json.dumps(original, sort_keys=True))
    assert alias["meta"]["legacy_override"]["ts"] == original["ts"]
    after = edges_path.read_bytes()
    again = run_cli("upgrade", root=toy)
    assert again.returncode == 0, again.stdout + again.stderr
    assert json.loads(again.stdout)["legacy_overrides"]["edges_added"] == 0
    assert edges_path.read_bytes() == after
    assert aggregate(toy)["override_counts"] == override_counts
    assert {name: (toy / ".harness" / name).read_bytes() for name in authored} == authored


def test_override_writer_canonicalizes_only_unambiguous_legacy_registry_targets(toy):
    from engine.gates.g5_conformance import record_override
    canonical = record_override(toy, "slice-042", "deps:telemetry", "approved")
    assert canonical["to"] == "registry:telemetry"
    assert canonical["meta"]["requested_target"] == "deps:telemetry"
    manifest = record_override(toy, "slice-042", "deps:pyproject.toml", "approved")
    assert manifest["to"] == "deps:pyproject.toml"
    wrong_gate = record_override(toy, "slice-042", "deps:telemetry", "approved", rule_ref="gate:G6")
    assert wrong_gate["to"] == "deps:telemetry"
