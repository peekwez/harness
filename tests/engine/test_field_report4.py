"""Regression tests for parallel-worktree field report round 3 (W7–W11):
extractor version skew, gate chicken-and-egg, shadow merges, bash-edit
touch tracking."""
import json

from conftest import git, loaded_context, make_event, run_cli
from engine import load_config, read_jsonl, sha256_file, write_jsonl
from engine.events import handle_event

GOOD_ORDERS = ("import telemetry\n\n\ndef create_order(sku: str) -> dict:\n"
               "    telemetry.emit_span('create_order', {'sku': sku})\n"
               "    return {'sku': sku}\n")


def codes(verdict):
    return {f["code"] for f in verdict["findings"]}


# ---------------------------------------------------------------- W7
def test_extract_all_rewrites_stale_format_shadows(toy):
    """The G7 <-> cache deadlock: a shadow in an older format has a matching
    source_hash, so extract --all cache-hits forever while G7's uncached
    rebuild mismatches forever. A format/version change must be a cache miss."""
    from engine.gates.g7_derivation import derivation_findings
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    stale = json.loads(sp.read_text())
    stale.pop("extractor_version", None)   # what a 0.3.3-era shadow looks like
    sp.write_text(json.dumps(stale, sort_keys=True, indent=1) + "\n")
    assert any(f["code"] == "DERIVATION_MISMATCH"
               for f in derivation_findings(toy, load_config(toy)))
    proc = run_cli("extract", "--all", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "telemetry.py" in out["written"], \
        "the finding's own named fix must not be a no-op"
    assert json.loads(sp.read_text()).get("extractor_version")
    assert not any(f["code"] == "DERIVATION_MISMATCH"
                   for f in derivation_findings(toy, load_config(toy)))


def test_explicit_extract_reports_cache_hits_as_cached(toy):
    proc = run_cli("extract", str(toy / "telemetry.py"), root=toy)
    out = json.loads(proc.stdout)
    assert "telemetry.py" in out.get("cached", []), out
    assert "telemetry.py" not in out["written"], \
        "a cache hit reported as 'written' lies exactly when debugging W7"


def test_extract_force_bypasses_the_cache(toy):
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    corrupted = json.loads(sp.read_text())
    corrupted["symbols"] = []
    sp.write_text(json.dumps(corrupted, sort_keys=True, indent=1) + "\n")
    proc = run_cli("extract", "--force", str(toy / "telemetry.py"), root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "telemetry.py" in out["written"]
    assert json.loads(sp.read_text())["symbols"], "corruption must be healed"


def test_extract_all_refreshes_existing_extensionless_shadows(toy):
    """--all skips extensionless files when discovering new modules, but a
    shadow that already exists for one (hook-created: Makefile, LICENSE…)
    must still refresh — otherwise G7 mismatches with `extract --all` as a
    no-op fix, the same deadlock class as W7."""
    from engine.extractor.engine import extract_path
    from engine.gates.g7_derivation import derivation_findings
    mk = toy / "Makefile"
    mk.write_text("all:\n\techo hi\n")
    extract_path(toy, mk, load_config(toy))    # the hook path shadows it
    mk.write_text("all:\n\techo changed\n")
    proc = run_cli("extract", "--all", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Makefile" in json.loads(proc.stdout)["written"]
    assert not any(f["code"] == "DERIVATION_MISMATCH"
                   for f in derivation_findings(toy, load_config(toy)))


# ---------------------------------------------------------------- W8
def test_g6_silent_on_extractor_format_skew(toy):
    """Shadow symbols changed but source bytes did not: that is extractor
    version skew, not interface drift — no ack-drift ceremony for non-events."""
    session = "skew"
    loaded_context(toy, session=session)   # baseline snapshot
    sp = toy / ".harness" / "shadows" / "telemetry.py.json"
    shadow = json.loads(sp.read_text())
    shadow["symbols"].append({                      # "new extractor emits more"
        "kind": "field", "name": "Cfg.max_count",
        "signature": "max_count: int = 100", "doc": None,
        "visibility": "public", "span": [1, 1]})
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n")
    v = handle_event(make_event("unit_complete", session=session), toy)
    assert "INTERFACE_DRIFT" not in codes(v), \
        "source unchanged: symbol diff is format skew, not drift"


# ---------------------------------------------------------------- W9
def test_g1_allows_creating_the_slices_own_acceptance_test(toy):
    """The gate demanded a red acceptance test while blocking the very write
    that creates it — builders were bootstrapping via bash heredoc."""
    rows = read_jsonl(toy / ".harness" / "backlog.jsonl")
    rows[0]["acceptance"] = ["tests/slices/042b_fresh.py"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", rows)
    session = "egg"
    loaded_context(toy, session=session)
    # writing anything else while the acceptance test is missing still blocks
    v = handle_event(make_event("pre_change", session=session,
                                files=["orders.py"]), toy)
    assert "MANIFEST_INCOMPLETE" in codes(v) and v["verdict"] == "block"
    # writing the acceptance test itself must pass
    v2 = handle_event(make_event("pre_change", session=session,
                                 files=["tests/slices/042b_fresh.py"]), toy)
    assert "MANIFEST_INCOMPLETE" not in codes(v2), v2["findings"]
    assert v2["verdict"] != "block"


def test_override_records_the_actual_rule_ref(toy):
    from engine.graph import load_edges
    proc = run_cli("gates", "override", "--slice", "slice-042",
                   "--target", "file:weird.py", "--justification", "needed",
                   "--rule-ref", "gate:G1", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    edge = [e for e in load_edges(toy) if e["to"] == "file:weird.py"][-1]
    assert edge["meta"]["rule_ref"] == "gate:G1"
    # default stays G5 when the flag is omitted
    run_cli("gates", "override", "--slice", "slice-042",
            "--target", "file:other.py", "--justification", "needed", root=toy)
    edge = [e for e in load_edges(toy) if e["to"] == "file:other.py"][-1]
    assert edge["meta"]["rule_ref"] == "gate:G5"


# ---------------------------------------------------------------- W10
def test_merge_drivers_never_content_merge_shadows(tmp_path):
    """Shadows are derived: content-merging them is semantically meaningless.
    ours-merge keeps our version; post-merge extract regenerates from the
    merged sources."""
    root = tmp_path / "shad"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ".harness/shadows/** merge=ours" in \
        (root / ".gitattributes").read_text()
    sp = root / ".harness" / "shadows" / "app.py.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text('{"v": "base"}\n')
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    default = git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git(root, "checkout", "-qb", "a")
    sp.write_text('{"v": "ours"}\n')
    git(root, "commit", "-qam", "a")
    git(root, "checkout", "-q", default)
    git(root, "checkout", "-qb", "b")
    sp.write_text('{"v": "theirs"}\n')
    git(root, "commit", "-qam", "b")
    git(root, "checkout", "-q", default)
    assert git(root, "merge", "-q", "--no-edit", "a").returncode == 0
    merged = git(root, "merge", "--no-edit", "b")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert json.loads(sp.read_text())["v"] == "ours"


# ---------------------------------------------------------------- W11
def test_close_uses_git_diff_as_touch_ground_truth(toy):
    """A bash-side edit the hooks never saw must still land in the close
    ceremony's touched set — git is ground truth, hooks an optimization."""
    session = "bash-only"
    run_cli("slice", "--slice", "slice-042", "--session", session, root=toy)
    # every edit happens OUTSIDE the hook path
    (toy / "orders.py").write_text(GOOD_ORDERS)
    (toy / "telemetry.py").write_text(
        (toy / "telemetry.py").read_text() + "\n\ndef _helper():\n    return 1\n")
    run_cli("extract", str(toy / "orders.py"), str(toy / "telemetry.py"),
            root=toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "slice-042 via bash")
    proc = run_cli("close-slice", "--slice", "slice-042", "--session", session,
                   "--commit", "HEAD", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert "orders.py" in out["touched"] and "telemetry.py" in out["touched"]
    assert "orders" in out["registry_flipped"]
    assert "telemetry" in out["registry_refreshed"], \
        "stale registry hash = HASH_MISMATCH in verify after merge"
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 0, proc.stdout


def test_registry_refresh_cli(toy):
    (toy / "telemetry.py").write_text(
        (toy / "telemetry.py").read_text() + "\n\ndef _tweak():\n    return 2\n")
    run_cli("extract", str(toy / "telemetry.py"), root=toy)
    proc = run_cli("registry", "refresh", "telemetry", root=toy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    reg = {e["id"]: e for e in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert reg["telemetry"]["source_hash"] == sha256_file(toy / "telemetry.py")
