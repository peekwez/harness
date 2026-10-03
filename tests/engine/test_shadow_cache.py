"""Shadow cache and scope (spec §7.1–7.2): lazy, gitignored, scoped."""
from __future__ import annotations

import json
import shutil

import pytest

from conftest import build_toy_repo, git, loaded_context, make_event, run_cli
from engine import HarnessError, get_slice, load_config, read_jsonl, write_jsonl
from engine.events import Sidecar, handle_event
from engine.extractor.engine import (SHADOW_CACHE, EXTRACTOR_VERSION,
                                     in_shadow_scope, scope_files, shadow_for,
                                     shadow_path_for)
from engine.graph import load_edges


def _write(root, rel, text="x = 1\n"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _ignore(root, line):
    gi = root / ".gitignore"
    gi.write_text(gi.read_text() + line + "\n")


def test_cache_lives_under_gitignored_harness_cache(toy):
    sp = shadow_path_for(toy, toy / "telemetry.py")
    assert sp == toy / SHADOW_CACHE / "telemetry.py.json"
    assert sp.exists()
    assert ".harness/cache/" in (toy / ".gitignore").read_text().splitlines()
    assert git(toy, "status", "--porcelain").stdout.strip() == ""
    assert not (toy / ".harness" / "shadows").exists()


def test_default_exclusions(toy):
    config = load_config(toy)
    for rel in ("tests/test_a.py", "pkg/tests/x.py", "pkg/test_b.py",
                "pkg/c_test.py", "cmd/d_test.go", "web/e.test.ts",
                "web/f.spec.ts", "conftest.py", "web/app.js.map",
                "web/vendor.min.js", "assets/logo.png", "dist/site.zip",
                "README.md", ".env.py"):
        _write(toy, rel)
        assert not in_shadow_scope(toy, rel, config), rel
    _write(toy, "pkg/service.py")
    assert in_shadow_scope(toy, "pkg/service.py", config)


def test_large_and_binary_files_are_out_of_scope(toy):
    config = load_config(toy)
    _write(toy, "pkg/huge.py", "x = 1\n" * 200_000)            # 1.2 MB
    (toy / "pkg" / "blob.py").write_bytes(b"x = 1\n\0\0binary")
    assert not in_shadow_scope(toy, "pkg/huge.py", config)
    assert not in_shadow_scope(toy, "pkg/blob.py", config)


def test_gitignored_files_are_out_of_scope(toy):
    _ignore(toy, "site/")
    _write(toy, "site/search.py")
    config = load_config(toy)
    assert not in_shadow_scope(toy, "site/search.py", config)
    assert shadow_for(toy, toy / "site" / "search.py", config) is None


def test_exclude_unless_include(toy):
    config = load_config(toy)
    config["shadows"] = {"exclude": ["*"], "include": ["libs/**/src/**"]}
    _write(toy, "libs/core/src/core/api.py")
    _write(toy, "tools/gen.py")
    assert in_shadow_scope(toy, "libs/core/src/core/api.py", config)
    assert not in_shadow_scope(toy, "tools/gen.py", config)


@pytest.mark.parametrize("bad", ["libs/**", [1], {"a": 1}])
def test_malformed_shadow_globs_fail_loud(toy, bad):
    config = load_config(toy)
    config["shadows"] = {"include": bad}
    with pytest.raises(HarnessError, match="shadows.include"):
        in_shadow_scope(toy, "telemetry.py", config)


def test_shadow_for_rebuilds_a_stale_cache_entry(toy):
    config = load_config(toy)
    src = toy / "telemetry.py"
    src.write_text(src.read_text() + "\n\ndef flush() -> None:\n    return None\n")
    shadow = shadow_for(toy, src, config)
    assert any(s["name"] == "flush" for s in shadow["symbols"])
    stored = json.loads(shadow_path_for(toy, src).read_text())
    assert stored["source_hash"] == shadow["source_hash"]


def test_astralabs_layout_shadows_only_libs_src(tmp_path):
    root = build_toy_repo(tmp_path / "astra")
    _ignore(root, "site/")
    cfg = root / ".harness" / "config.yaml"
    cfg.write_text(cfg.read_text()
                   + 'shadows:\n  exclude: ["*"]\n  include: ["libs/**/src/**"]\n')
    _write(root, "libs/core/src/core/__init__.py", '"""Core."""\n')
    _write(root, "libs/core/src/core/api.py", "def api() -> int:\n    return 1\n")
    _write(root, "libs/web/src/app.ts", "export const A = 1;\n")
    for rel in ("libs/core/tests/test_api.py", "libs/web/src/app.test.ts",
                "libs/web/src/vendor.min.js", "libs/web/src/app.js.map",
                "site/search.py", "site/index.html", "docs/index.md",
                "tools/gen.py", "apps/cli/main.py"):
        _write(root, rel)
    proc = run_cli("extract", "--all", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    cache = root / SHADOW_CACHE
    cached = sorted(p.relative_to(cache).as_posix() for p in cache.rglob("*.json"))
    assert cached == ["libs/core/src/core/__init__.py.json",
                      "libs/core/src/core/api.py.json",
                      "libs/web/src/app.ts.json"]


def test_change_under_ignored_site_changes_no_tracked_file_and_blocks_nothing(toy):
    _ignore(toy, "site/")
    loaded_context(toy, session="site")                  # G6 baseline
    handle_event(make_event("unit_complete", session="site"), toy)
    git(toy, "add", "-A")
    git(toy, "commit", "-qm", "bind slice, ignore site/")
    _write(toy, "site/search.py", "import telemetry\n")
    _write(toy, "site/index.html", "<html></html>\n")
    for event in ("post_change", "unit_complete"):
        v = handle_event(make_event(event, session="site",
                                    files=["site/search.py", "site/index.html"]),
                         toy)
        assert v["verdict"] != "block", v["findings"]
    assert git(toy, "status", "--porcelain").stdout.strip() == ""


def test_scope_without_git_walks_the_tree(tmp_path):
    root = build_toy_repo(tmp_path / "nogit")
    shutil.rmtree(root / ".git")
    _write(root, "pkg/service.py")
    _write(root, "pkg/tests/test_s.py")
    config = load_config(root)
    files = scope_files(root, config)
    assert "pkg/service.py" in files and "pkg/tests/test_s.py" not in files
    assert shadow_for(root, root / "pkg" / "service.py", config) is not None


def test_stop_survives_a_touched_file_deleted_before_it(toy):
    loaded_context(toy, session="gone")
    _write(toy, "scratch.py", "import telemetry\n")
    handle_event(make_event("post_change", session="gone",
                            files=["scratch.py"]), toy)
    (toy / "scratch.py").unlink()
    v = handle_event(make_event("unit_complete", session="gone"), toy)
    assert v["verdict"] != "block", v["findings"]
    assert not any(e["type"] == "touches" and e["to"] == "file:scratch.py"
                   for e in load_edges(toy))


def test_g6_sees_drift_without_a_touch(toy):
    loaded_context(toy, session="g6lazy")
    src = toy / "telemetry.py"
    src.write_text(src.read_text().replace(
        "def emit_span(name: str, attrs: dict) -> dict:",
        "def emit_span(name: str, attrs: dict, level: int = 0) -> dict:"))
    v = handle_event(make_event("unit_complete", session="g6lazy"), toy)
    assert "INTERFACE_DRIFT" in {f["code"] for f in v["findings"]}


def test_registry_rows_carry_no_shadow_field(toy):
    rows = {r["id"]: r for r in read_jsonl(toy / ".harness" / "registry.jsonl")}
    assert rows["telemetry"]["status"] == "built"
    assert all("shadow" not in r for r in rows.values())


def test_flip_refuses_a_source_outside_scope(toy):
    from engine.registry import RegistryError, flip_status
    path = toy / ".harness" / "registry.jsonl"
    rows = read_jsonl(path)
    for r in rows:
        if r["id"] == "orders":
            r["source"] = "orders_test.py"
    write_jsonl(path, rows)
    _write(toy, "orders_test.py", "def create_order(sku):\n    return sku\n")
    with pytest.raises(RegistryError, match="shadows.include"):
        flip_status(toy, "orders")


def test_close_preparation_skips_gitignored_touches(toy):
    from engine.cli.closure_state import prepare_files
    _ignore(toy, "site/")
    _write(toy, "site/search.py")
    sidecar = Sidecar(toy)
    try:
        sidecar.touch("prep", "slice-042", ["site/search.py", "orders.py"])
        files = prepare_files(toy, get_slice(toy, "slice-042"), sidecar,
                              "prep", None, load_config(toy))
    finally:
        sidecar.close()
    assert "site/search.py" not in files and "orders.py" in files


def test_init_ignores_the_cache_and_writes_no_shadow_attribute(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert ".harness/cache/" in (root / ".gitignore").read_text().splitlines()
    assert "shadows" not in (root / ".gitattributes").read_text()
    assert not (root / ".harness" / "shadows").exists()


def test_doctor_reports_the_extractor_stack(toy):
    out = json.loads(run_cli("doctor", root=toy).stdout)
    assert out["extractor"]["version"] == EXTRACTOR_VERSION
    assert set(out["extractor"]["stack"]) == {"tree-sitter",
                                              "tree-sitter-language-pack"}


def test_malformed_shadows_config_fails_loud_on_post_change(toy):
    loaded_context(toy, session="badcfg")
    cfg = toy / ".harness" / "config.yaml"
    cfg.write_text(cfg.read_text() + 'shadows:\n  include: "libs/**"\n')
    with pytest.raises(HarnessError, match="shadows.include"):
        handle_event(make_event("post_change", session="badcfg",
                                files=["telemetry.py"]), toy)


def test_malformed_shadows_config_fails_loud_in_layer0(toy):
    from engine.review.layer0 import assemble
    config = load_config(toy)
    config["shadows"] = {"include": "libs/**"}
    with pytest.raises(HarnessError, match="shadows.include"):
        assemble(toy, "", "slice-042", config)


def test_g5_scans_module_ids_once_per_run(toy, monkeypatch):
    import engine.extractor.engine as ex
    loaded_context(toy, session="cost")
    files = []
    for i in range(4):
        rel = f"pkg/m{i}.py"
        _write(toy, rel, "import telemetry\n")
        files.append(rel)
    calls = []
    real = ex.python_module_ids
    monkeypatch.setattr(ex, "python_module_ids",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    handle_event(make_event("post_change", session="cost", files=files), toy)
    assert len(calls) <= 2, len(calls)     # not one scan per touched file
