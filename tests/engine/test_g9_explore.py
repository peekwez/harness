"""Spec 5.6: G9 blocks production imports from explore/ (issue #2)."""
import json

from conftest import make_event, run_cli

from engine import load_config
from engine.events import handle_event
from engine.gates.g9_explore import (_go_specs, _js_specs, _python_specs,
                                     _rust_specs, explore_findings,
                                     file_findings, go_explore_prefix,
                                     resolves_into_explore)

TOY_PY = "def make_order(sku):\n    return {'sku': sku}\n"
BAD_ORDERS = ("from explore.toy import make_order\n\n\n"
              "def create_order(sku):\n    return make_order(sku)\n")
GOOD_ORDERS = "def create_order(sku):\n    return {'sku': sku}\n"


def _explore(toy):
    assert run_cli("explore", root=toy).returncode == 0
    (toy / "explore" / "toy.py").write_text(TOY_PY)


def _codes(verdict):
    return {f["code"] for f in verdict["findings"]}


def test_import_from_explore_in_production_code_fails_g9(toy):
    _explore(toy)
    (toy / "orders.py").write_text(BAD_ORDERS)
    v = handle_event(make_event("post_change", files=["orders.py"]), toy)
    assert v["verdict"] == "block"
    g9 = [f for f in v["findings"] if f["code"] == "EXPLORE_IMPORT"]
    assert len(g9) == 1
    assert g9[0]["rule_ref"] == "gate:G9"
    assert g9[0]["severity"] == "block"
    assert "orders.py imports explore.toy" in g9[0]["message"]
    assert len(g9[0]["message"].split()) <= 25
    assert g9[0]["fix"]


def test_g9_also_runs_at_unit_complete(toy):
    _explore(toy)
    (toy / "orders.py").write_text(BAD_ORDERS)
    v = handle_event(make_event("unit_complete", files=["orders.py"]), toy)
    assert "EXPLORE_IMPORT" in _codes(v)


def test_production_code_without_the_import_passes(toy):
    _explore(toy)
    (toy / "orders.py").write_text(GOOD_ORDERS)
    v = handle_event(make_event("post_change", files=["orders.py"]), toy)
    assert "EXPLORE_IMPORT" not in _codes(v)


def test_an_edit_under_explore_gives_no_g3_g5_or_g9_finding(toy):
    _explore(toy)
    (toy / "explore" / "more.py").write_text("import explore.toy\n")
    for event in ("pre_change", "post_change", "unit_complete"):
        v = handle_event(make_event(event, files=["explore/more.py"]), toy)
        about = [f for f in v["findings"]
                 if "explore/more.py" in f["message"]]
        assert about == [], (event, about)


def test_g9_is_silent_without_explore_decisions(toy):
    (toy / "explore").mkdir()
    (toy / "explore" / "toy.py").write_text(TOY_PY)
    (toy / "orders.py").write_text(BAD_ORDERS)
    v = handle_event(make_event("post_change", files=["orders.py"]), toy)
    assert "EXPLORE_IMPORT" not in _codes(v)
    assert explore_findings(toy, load_config(toy)) == []


def test_tests_may_import_explore(toy):
    _explore(toy)
    (toy / "tests" / "test_toy.py").write_text("import explore.toy\n")
    assert file_findings(toy, "tests/test_toy.py", load_config(toy)) == []


def test_typescript_javascript_and_go_files(toy):
    _explore(toy)
    config = load_config(toy)
    (toy / "web" / "src").mkdir(parents=True)
    (toy / "web" / "src" / "a.ts").write_text(
        'import { t } from "../../explore/toy";\n')
    (toy / "web" / "src" / "b.js").write_text(
        "const t = require('../../explore/toy');\n")
    (toy / "go.mod").write_text("module github.com/acme/app\n\ngo 1.22\n")
    (toy / "svc").mkdir()
    (toy / "svc" / "main.go").write_text(
        'package main\n\nimport (\n\t"fmt"\n'
        '\tt "github.com/acme/app/explore/toy"\n)\n')
    for rel in ("web/src/a.ts", "web/src/b.js", "svc/main.go"):
        codes = [f["code"] for f in file_findings(toy, rel, config)]
        assert codes == ["EXPLORE_IMPORT"], rel


def test_rust_use_of_the_explore_module(toy):
    _explore(toy)
    (toy / "src").mkdir()
    (toy / "src" / "lib.rs").write_text("use crate::explore::toy;\n")
    codes = [f["code"] for f in
             file_findings(toy, "src/lib.rs", load_config(toy))]
    assert codes == ["EXPLORE_IMPORT"]


def test_readers():
    py = _python_specs("import os, explore.toy as t\nfrom explore import x\n")
    assert {"os", "explore.toy", "explore"} <= set(py)
    assert _rust_specs("use crate::explore::toy;\npub use super::orders;\n"
                       "extern crate explore;\n") == [
        "explore", "orders", "explore"]
    assert _rust_specs("use crate::{explore::toy, x};\n"
                       "use {self::a, explore};\n") == [
        "explore", "x", "a", "explore"]
    assert _js_specs('import x from "../explore/a";\nimport "./explore/b";\n'
                     "const c = require('../explore/c');\n"
                     'await import("explore/d");\n'
                     'export { e } from "/explore/e";\n'
                     'import type { T } from "react";\n') == [
        "../explore/a", "./explore/b", "../explore/c", "explore/d",
        "/explore/e", "react"]
    assert _go_specs('package x\n// import "github.com/no/explore"\n'
                     'import "fmt"\nimport (\n  t "github.com/a/explore/toy"\n'
                     '  "strings"\n)\n') == [
        "fmt", "github.com/a/explore/toy", "strings"]


def test_resolution_rules_per_language(tmp_path):
    r = tmp_path
    assert resolves_into_explore(r, "a.py", "python", "explore.toy")
    assert resolves_into_explore(r, "a.py", "python", "explore")
    assert not resolves_into_explore(r, "a.py", "python", "explorer.toy")
    assert resolves_into_explore(r, "web/src/a.ts", "typescript",
                                 "../../explore/x")
    assert not resolves_into_explore(r, "web/src/a.ts", "typescript",
                                     "../explore/x")
    assert resolves_into_explore(r, "a.js", "javascript", "/explore/x")
    assert resolves_into_explore(r, "a.js", "javascript",
                                 str(r / "explore" / "x"))
    assert resolves_into_explore(r, "a.ts", "typescript", "explore/x")
    assert not resolves_into_explore(r, "a.ts", "typescript", "explore-utils")
    assert not resolves_into_explore(r, "a.ts", "typescript", "./explorer/x")
    assert resolves_into_explore(r, "src/lib.rs", "rust", "explore")
    assert not resolves_into_explore(r, "src/lib.rs", "rust", "explorer")
    (r / "go.mod").write_text("module github.com/acme/app\n")
    (r / "svc").mkdir()
    prefix = go_explore_prefix(r, "svc/main.go")
    assert prefix == "github.com/acme/app/explore"
    assert resolves_into_explore(r, "svc/main.go", "go",
                                 "github.com/acme/app/explore/toy", prefix)
    assert not resolves_into_explore(r, "svc/main.go", "go",
                                     "github.com/acme/app/explorer", prefix)
    assert not resolves_into_explore(r, "svc/main.go", "go",
                                     "github.com/other/explore", prefix)


def test_go_module_below_explore_has_no_prefix(tmp_path):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "go.mod").write_text("module example.com/svc\n")
    assert go_explore_prefix(tmp_path, "svc/main.go") is None


def test_verify_runs_g9_over_the_repo(toy):
    _explore(toy)
    (toy / "orders.py").write_text(BAD_ORDERS)
    proc = run_cli("verify", root=toy)
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert "EXPLORE_IMPORT" in {f["code"] for f in report["findings"]}
    (toy / "orders.py").write_text(GOOD_ORDERS)
    assert "EXPLORE_IMPORT" not in run_cli("verify", root=toy).stdout


def test_g9_is_a_builtin_gate_with_a_catalog_entry():
    from engine.findings import CATALOG
    from engine.gates import builtin_gates
    assert "G9" in [g.GATE["id"] for g in builtin_gates()]
    assert "EXPLORE_IMPORT" in CATALOG


def test_rust_brace_group_resolves_into_explore(toy):
    _explore(toy)
    (toy / "src").mkdir()
    (toy / "src" / "lib.rs").write_text("use crate::{explore::toy, x};\n")
    codes = [f["code"] for f in
             file_findings(toy, "src/lib.rs", load_config(toy))]
    assert codes == ["EXPLORE_IMPORT"]
    (toy / "src" / "lib.rs").write_text("use crate::{orders, x};\n")
    assert file_findings(toy, "src/lib.rs", load_config(toy)) == []


def test_verify_computes_python_module_ids_once(toy, monkeypatch):
    _explore(toy)
    for i in range(5):
        (toy / f"m{i}.py").write_text("x = 1\n")
    (toy / "orders.py").write_text(BAD_ORDERS)
    from engine.extractor import modules
    calls = []
    real = modules.python_module_ids
    monkeypatch.setattr(modules, "python_module_ids",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    found = explore_findings(toy, load_config(toy))
    assert [f["code"] for f in found] == ["EXPLORE_IMPORT"]
    assert len(calls) == 1


def test_root_aliases_comments_and_rust_path_attribute(toy):
    _explore(toy)
    config = load_config(toy)
    (toy / "web").mkdir()
    (toy / "web" / "a.ts").write_text('import t from "@/explore/toy";\n')
    (toy / "web" / "b.ts").write_text('import t from "~/explore/toy";\n')
    (toy / "web" / "c.ts").write_text(
        '// import t from "../explore/toy";\n'
        '/* import u from "../explore/u"; */\n'
        'import v from "https://x.dev/v";\n')
    (toy / "src").mkdir()
    (toy / "src" / "lib.rs").write_text(
        '#[path = "../explore/toy.rs"]\nmod toy;\n')
    for rel, n in (("web/a.ts", 1), ("web/b.ts", 1), ("web/c.ts", 0),
                   ("src/lib.rs", 1)):
        assert len(file_findings(toy, rel, config)) == n, rel


def test_g9_check_asks_git_for_ignored_files_once(toy, monkeypatch):
    from engine.extractor import engine as ex
    from engine.gates import GateContext
    from engine.gates.extra import _NullSidecar
    from engine.gates.g9_explore import check
    _explore(toy)
    files = [f"m{i}.py" for i in range(4)] + ["orders.py"]
    for rel in files[:-1]:
        (toy / rel).write_text("x = 1\n")
    (toy / "orders.py").write_text(BAD_ORDERS)
    single, batch = [], []
    real_set = ex.git_ignored_set
    monkeypatch.setattr(ex, "git_ignored",
                        lambda *a, **k: single.append(a) or False)
    monkeypatch.setattr(ex, "git_ignored_set",
                        lambda *a, **k: batch.append(a) or real_set(*a, **k))
    ctx = GateContext(toy, make_event("post_change", files=files),
                      load_config(toy), _NullSidecar())
    found = check(ctx)
    assert [f["code"] for f in found] == ["EXPLORE_IMPORT"]
    assert single == []
    assert len(batch) == 1
