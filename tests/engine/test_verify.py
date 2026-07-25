"""C9 acceptance: each seeded defect fails CI with a named finding code;
runs with no plugin (pure CLI)."""
import json

from conftest import git, run_cli


def verify(toy):
    proc = run_cli("verify", root=toy)
    return proc.returncode, json.loads(proc.stdout)


def test_clean_repo_passes(toy):
    code, out = verify(toy)
    assert code == 0 and out["passed"], out["findings"]


def test_stale_shadow_fails_with_derivation_mismatch(toy):
    (toy / "telemetry.py").write_text(
        open(toy / "telemetry.py").read() + "\ndef added(x):\n    return x\n")
    code, out = verify(toy)
    assert code == 1
    codes = {f["code"] for f in out["findings"]}
    assert "DERIVATION_MISMATCH" in codes
    assert "HASH_MISMATCH" in codes  # built entry's recorded hash is stale too


def test_missing_manifest_file_fails(toy):
    (toy / "config.py").unlink()
    code, out = verify(toy)
    assert code == 1
    hits = [f for f in out["findings"] if f["code"] == "MANIFEST_INCOMPLETE"]
    assert hits and "config" in hits[0]["message"]


def test_manifest_checked_against_built_artifact(toy, tmp_path):
    """CI validates the built/installed tree, not just the source tree."""
    built = tmp_path / "built"
    built.mkdir()
    (built / "telemetry.py").write_text("x")  # config.py missing from the artifact
    proc = run_cli("verify", "--built-artifact", built, root=toy)
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert any(f["code"] == "MANIFEST_INCOMPLETE" and "config" in f["message"]
               for f in out["findings"])


def test_orphaned_note_fails(toy):
    (toy / "tmp.txt").write_text("x")
    git(toy, "add", "tmp.txt")
    git(toy, "commit", "-qm", "doomed")
    doomed = git(toy, "rev-parse", "HEAD").stdout.strip()
    from engine.graph import write_note
    write_note(toy, doomed, {"slice_id": "slice-042"})
    git(toy, "reset", "--hard", "-q", "HEAD~1")
    git(toy, "reflog", "expire", "--expire=now", "--all")
    git(toy, "prune")
    code, out = verify(toy)
    assert code == 1
    assert any(f["code"] == "ORPHANED_NOTE" for f in out["findings"])


def test_unreconciled_closed_slice_fails(toy):
    from engine import read_jsonl, write_jsonl
    from engine.graph import append_edge
    append_edge(toy, "uses", "slice:slice-042", "module:ghost")
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["status"] = "closed"
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    code, out = verify(toy)
    assert code == 1
    hits = [f for f in out["findings"] if f["code"] == "UNRECONCILED_SLICE"]
    assert hits and "ghost" in hits[0]["message"]


def test_deleted_built_shadow_fails(toy):
    """The md-file-bug limit case: a missing derived artifact must fail CI."""
    (toy / ".harness" / "shadows" / "telemetry.py.json").unlink()
    code, out = verify(toy)
    assert code == 1
    hits = [f for f in out["findings"] if f["code"] == "MISSING_SHADOW"]
    assert hits and "telemetry" in hits[0]["message"]


def test_corrupt_backlog_fails_loud(toy):
    (toy / ".harness" / "backlog.jsonl").write_text("{not json\n")
    code, out = verify(toy)
    assert code == 1
    assert any(f["code"] == "SCHEMA_MISMATCH" for f in out["findings"])


def test_reformatted_shadow_fails_derivation(toy):
    """'Regenerates identically' is byte-level: reformatting a derived file
    is still a hand-edit."""
    import json as j
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    sp.write_text(j.dumps(j.loads(sp.read_text()), indent=4))
    code, out = verify(toy)
    assert code == 1
    assert any(f["code"] == "DERIVATION_MISMATCH" for f in out["findings"])


def test_schema_mismatch_fails(toy):
    (toy / ".harness" / "schema_version").write_text("99\n")
    code, out = verify(toy)
    assert code == 1
    assert any(f["code"] == "SCHEMA_MISMATCH" for f in out["findings"])


def test_verify_green_on_harness_repo_itself(plugin_root):
    """The v0.1 ship gate: self-hosting substrate validates with its own
    engine (skills and query packs carry manifests)."""
    proc = run_cli("verify", root=plugin_root)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["passed"], out["findings"]
