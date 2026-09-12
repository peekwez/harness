"""Regression coverage for shadow identity and incremental G7 inputs."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

from conftest import run_cli
from engine import load_config, read_jsonl, write_jsonl
from engine.events import Sidecar
from engine.extractor.engine import (RegistryIndex, extract_all, extract_path,
                                     shadow_path_for)
from engine.extractor.modules import python_module_ids
from engine.gates.g7_derivation import (check as check_derivation,
                                        derivation_findings)


def _codes(findings):
    return {finding["code"] for finding in findings}


def _package_source(toy):
    package = toy / "src" / "acme"
    (package / "deep").mkdir(parents=True)
    for rel in ("sibling.py", "base.py", "config.py", "deep/module.py"):
        (package / rel).write_text('"""Local module."""\n')
    source = package / "service.py"
    source.write_text(
        "from . import sibling\n"
        "from .base import Tool\n"
        "from acme import config\n"
        "import acme.deep.module\n"
    )
    return source


def test_python_imports_resolve_relative_and_local_submodules(toy):
    source = _package_source(toy)

    shadow, _ = extract_path(toy, source, load_config(toy))

    assert shadow["module_id"] == "acme.service"
    assert shadow["imports"] == [
        "acme.base",
        "acme.config",
        "acme.deep.module",
        "acme.sibling",
    ]
    index = RegistryIndex([
        {"id": "component_base", "module_id": "acme.base"},
        {"id": "component_config", "module_id": "acme.config"},
        {"id": "component_deep", "module_id": "acme.deep.module"},
        {"id": "component_sibling", "module_id": "acme.sibling"},
    ])
    assert [index.match(name)["id"] for name in shadow["imports"]] == [
        "component_base",
        "component_config",
        "component_deep",
        "component_sibling",
    ]


def test_python_imports_do_not_treat_imported_symbols_as_modules(toy):
    package = toy / "src" / "acme"
    package.mkdir(parents=True)
    (package / "base.py").write_text('"""Base."""\n')
    source = package / "service.py"
    source.write_text("from acme.base import Tool\n")

    shadow, _ = extract_path(toy, source, load_config(toy))

    assert shadow["imports"] == ["acme.base"]


def test_python_imports_recognize_registered_submodule_without_local_file(toy):
    registry_path = toy / ".harness" / "registry.jsonl"
    registry = read_jsonl(registry_path)
    registry.append({"id": "component_config", "module_id": "acme.config"})
    write_jsonl(registry_path, registry)
    source = toy / "src" / "acme" / "service.py"
    source.parent.mkdir(parents=True)
    source.write_text("from acme import config\n")

    shadow, _ = extract_path(toy, source, load_config(toy))

    assert shadow["imports"] == ["acme.config"]


def test_python_imports_recognize_implied_namespace_subpackage(toy):
    package = toy / "src" / "acme"
    (package / "config").mkdir(parents=True)
    (package / "config" / "settings.py").write_text("VALUE = 1\n")
    source = package / "service.py"
    source.write_text("from acme import config\n")

    modules = python_module_ids(toy, load_config(toy))
    shadow, _ = extract_path(toy, source, load_config(toy))

    assert "acme.config" in modules
    assert "src" not in modules
    assert "src.acme" not in modules
    assert shadow["imports"] == ["acme.config"]


def test_shadow_cache_invalidates_when_src_roots_change_module_identity(toy):
    source = _package_source(toy)
    first, _ = extract_path(toy, source, load_config(toy))
    assert first["module_id"] == "acme.service"

    config = load_config(toy)
    config["extractor"]["src_roots"] = []
    result = extract_all(toy, config)
    rebuilt = json.loads(shadow_path_for(toy, source).read_text())

    assert "src/acme/service.py" in result["written"]
    assert rebuilt["module_id"] == "src.acme.service"


def test_incremental_g7_rechecks_when_source_changes_but_shadow_mtime_does_not(
        toy):
    source = toy / "config.py"
    sidecar = Sidecar(toy)
    try:
        ctx = SimpleNamespace(root=toy, config=load_config(toy), sidecar=sidecar)
        assert not check_derivation(ctx)
        shadow = shadow_path_for(toy, source)
        old_mtime = shadow.stat().st_mtime_ns

        source.write_text(source.read_text() + "\nCHANGED = True\n")
        os.utime(shadow, ns=(old_mtime, old_mtime))

        assert "DERIVATION_MISMATCH" in _codes(check_derivation(ctx))
    finally:
        sidecar.close()


def test_incremental_g7_rechecks_when_config_changes_module_identity(toy):
    source = _package_source(toy)
    config = load_config(toy)
    extract_all(toy, config)
    sidecar = Sidecar(toy)
    try:
        ctx = SimpleNamespace(root=toy, config=config, sidecar=sidecar)
        assert not check_derivation(ctx)
        shadow = shadow_path_for(toy, source)
        old_mtime = shadow.stat().st_mtime_ns

        changed_config = load_config(toy)
        changed_config["extractor"]["src_roots"] = []
        changed_ctx = SimpleNamespace(
            root=toy, config=changed_config, sidecar=sidecar)
        os.utime(shadow, ns=(old_mtime, old_mtime))

        assert "DERIVATION_MISMATCH" in _codes(check_derivation(changed_ctx))
    finally:
        sidecar.close()


def test_incremental_g7_rechecks_when_extractor_version_changes(
        toy, monkeypatch):
    from engine.extractor import engine as extractor

    sidecar = Sidecar(toy)
    try:
        ctx = SimpleNamespace(root=toy, config=load_config(toy), sidecar=sidecar)
        assert not check_derivation(ctx)
        shadow = shadow_path_for(toy, toy / "config.py")
        old_mtime = shadow.stat().st_mtime_ns

        monkeypatch.setattr(
            extractor, "EXTRACTOR_VERSION", extractor.EXTRACTOR_VERSION + 1)
        os.utime(shadow, ns=(old_mtime, old_mtime))

        assert "DERIVATION_MISMATCH" in _codes(check_derivation(ctx))
    finally:
        sidecar.close()


def test_g7_rejects_deleted_required_shadow_incrementally_and_exhaustively(toy):
    config = load_config(toy)
    sidecar = Sidecar(toy)
    try:
        ctx = SimpleNamespace(root=toy, config=config, sidecar=sidecar)
        assert not check_derivation(ctx)
        shadow_path_for(toy, toy / "config.py").unlink()

        incremental = check_derivation(ctx)
        exhaustive = derivation_findings(toy, config)
        filtered = derivation_findings(
            toy, config, paths={str((toy / "telemetry.py").resolve())})
        verify = run_cli("verify", root=toy)

        assert "DERIVATION_MISMATCH" in _codes(incremental)
        assert "DERIVATION_MISMATCH" in _codes(exhaustive)
        assert any("config.py" in finding["message"] for finding in exhaustive)
        assert "DERIVATION_MISMATCH" not in _codes(filtered)
        assert verify.returncode == 1
        assert "DERIVATION_MISMATCH" in verify.stdout
    finally:
        sidecar.close()


def test_incremental_g7_rejects_deleted_previously_seen_shadow(toy):
    source = toy / "local_only.py"
    source.write_text("VALUE = 1\n")
    extract_path(toy, source, load_config(toy))
    sidecar = Sidecar(toy)
    try:
        ctx = SimpleNamespace(root=toy, config=load_config(toy), sidecar=sidecar)
        assert not check_derivation(ctx)
        shadow_path_for(toy, source).unlink()

        findings = check_derivation(ctx)

        assert "DERIVATION_MISMATCH" in _codes(findings)
        assert any("local_only.py" in finding["message"] for finding in findings)
    finally:
        sidecar.close()
