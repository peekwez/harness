"""Regression coverage for shadow identity."""
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










