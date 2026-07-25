"""C2 acceptance: deterministic shadows; docstring vs body edits; unknown
extension -> degenerate + finding; 500-file perf."""
import json
import time

from engine import load_config
from engine.extractor.engine import extract_all, extract_path, shadow_path_for

TS_SRC = 'export function render(p: string): string { return p; }\n'
YAML_SRC = 'name: x\njobs:\n  a: 1\n'
HCL_SRC = 'variable "region" {\n  type = string\n}\n'


def test_byte_identical_across_two_runs(toy):
    config = load_config(toy)
    for name, src in (("a.ts", TS_SRC), ("b.yaml", YAML_SRC), ("c.tf", HCL_SRC)):
        (toy / name).write_text(src)
    extract_all(toy, config)
    first = {p: p.read_bytes()
             for p in (toy / ".harness" / "shadows").rglob("*.json")}
    # force re-extract from scratch (kill the cache by deleting shadows)
    for p in first:
        p.unlink()
    extract_all(toy, config)
    second = {p: p.read_bytes()
              for p in (toy / ".harness" / "shadows").rglob("*.json")}
    assert first == second


def test_docstring_changes_shadow_body_does_not_change_symbols(toy):
    config = load_config(toy)
    src = toy / "telemetry.py"
    before = json.loads(shadow_path_for(toy, src).read_text())

    # body edit, same line count: symbols must be unchanged, hash must change
    body_edit = src.read_text().replace(
        'return {"name": name, "attrs": attrs}',
        'return {"attrs": attrs, "name": name}')
    src.write_text(body_edit)
    shadow, _ = extract_path(toy, src, config)
    assert shadow["symbols"] == before["symbols"]
    assert shadow["source_hash"] != before["source_hash"]

    # docstring edit: the shadow (symbols.doc) must change
    doc_edit = src.read_text().replace("Emit a span with", "Emit one span with")
    src.write_text(doc_edit)
    shadow2, _ = extract_path(toy, src, config)
    assert shadow2["symbols"] != shadow["symbols"]
    docs = [s["doc"] for s in shadow2["symbols"] if s["name"] == "emit_span"]
    assert docs and "Emit one span" in docs[0]


def test_unknown_extension_degenerate_shadow_plus_finding(toy):
    config = load_config(toy)
    (toy / "main.go").write_text("package main\nfunc main() {}\n")
    shadow, findings = extract_path(toy, toy / "main.go", config)
    assert shadow["exports"] == "unknown"
    assert shadow["symbols"] == []
    assert "raw_head" in shadow and "package main" in shadow["raw_head"]
    codes = [f["code"] for f in findings]
    assert "UNKNOWN_LANGUAGE" in codes  # never silence
    assert all(f["rule_ref"] == "gate:G8" for f in findings)


def test_cache_hit_no_work(toy):
    config = load_config(toy)
    sp = shadow_path_for(toy, toy / "telemetry.py")
    mtime = sp.stat().st_mtime_ns
    extract_path(toy, toy / "telemetry.py", config)
    assert sp.stat().st_mtime_ns == mtime  # unchanged source -> no rewrite


def test_500_file_repo_perf(tmp_path):
    from conftest import build_toy_repo
    root = build_toy_repo(tmp_path / "big")
    config = load_config(root)
    pkg = root / "pkg"
    pkg.mkdir()
    for i in range(500):
        (pkg / f"m{i:03d}.py").write_text(
            f'"""Module {i}."""\n\ndef f{i}(x: int) -> int:\n'
            f'    """Fn {i}."""\n    return x + {i}\n')
    t0 = time.perf_counter()
    out = extract_all(root, config)
    cold = time.perf_counter() - t0
    assert len(out["written"]) >= 500
    t0 = time.perf_counter()
    out2 = extract_all(root, config)
    warm = time.perf_counter() - t0
    assert not out2["written"], "warm run must be all cache hits"
    assert cold < 10.0, f"cold extract took {cold:.1f}s"
    assert warm < 1.0, f"warm extract took {warm:.1f}s"


def test_visibility_mapping_per_language(toy):
    config = load_config(toy)
    (toy / "vis.ts").write_text(
        "export const A = 1;\nconst b = 2;\nexport function pub() {}\n"
        "function priv() {}\n")
    shadow, _ = extract_path(toy, toy / "vis.ts", config)
    vis = {s["name"]: s["visibility"] for s in shadow["symbols"]}
    assert vis["A"] == "public" and vis["b"] == "private"
    assert vis["pub"] == "public" and vis["priv"] == "private"

    (toy / "vis.tf").write_text(
        'variable "v" {}\noutput "o" {}\nresource "r" "x" {}\n')
    shadow, _ = extract_path(toy, toy / "vis.tf", config)
    vis = {s["name"]: s["visibility"] for s in shadow["symbols"]}
    assert vis["variable.v"] == "public"
    assert vis["output.o"] == "public"
    assert vis["resource.r.x"] == "private"
