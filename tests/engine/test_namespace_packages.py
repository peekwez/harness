"""ADR-002 / D-008: dotted Python imports + namespace-package module ids.

Shadows keep the whole dotted import (`kente.telemetry.decorators`), module
ids strip the first matching `extractor.src_roots` glob, and G5 + the
resolver match registry entries by longest dotted prefix. Flat repos with no
`src` root are unchanged.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from conftest import loaded_context, make_event
from engine import HarnessError, load_config, read_jsonl, write_jsonl
from engine.events import handle_event
from engine.extractor.engine import (extract_all, extract_path,
                                     match_registry_module, module_id_for,
                                     shadow_path_for)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ns_monorepo"

DATA_SRC = "packages/kente-data/src/kente/data/__init__.py"
CONFIG_SRC = "packages/kente-config/src/kente/config/__init__.py"
CORE_SRC = "packages/kente-core/src/kente/core/__init__.py"


def install_ns_packages(root: Path) -> Path:
    """Copy the namespace-package fixture into a repo and extract it.

    Args:
        root: Repo root carrying a harness substrate (the `toy` fixture).

    Returns:
        The repo root, for chaining.
    """
    shutil.copytree(FIXTURE / "packages", root / "packages")
    extract_all(root, load_config(root))
    return root


def shadow_of(root: Path, rel: str) -> dict:
    """Load the shadow written for a repo-relative source path."""
    return json.loads(shadow_path_for(root, root / rel).read_text())


# ---------------------------------------------------------------- module ids
def test_module_id_strips_packages_src_root(toy):
    install_ns_packages(toy)
    assert shadow_of(toy, DATA_SRC)["module_id"] == "kente.data"
    assert shadow_of(toy, CONFIG_SRC)["module_id"] == "kente.config"
    assert shadow_of(toy, CORE_SRC)["module_id"] == "kente.core"


def test_module_id_for_flat_src_layout(toy):
    src = toy / "src" / "app" / "orders.py"
    src.parent.mkdir(parents=True)
    src.write_text('"""Orders."""\n')
    assert module_id_for(toy, src, load_config(toy)) == "app.orders"


def test_module_id_unchanged_when_no_src_root_matches(toy):
    """A flat repo (no `src` anywhere) keeps the dotted relative path."""
    config = load_config(toy)
    assert module_id_for(toy, toy / "telemetry.py", config) == "telemetry"
    nested = toy / "pkg" / "sub" / "mod.py"
    nested.parent.mkdir(parents=True)
    nested.write_text('"""Mod."""\n')
    assert module_id_for(toy, nested, config) == "pkg.sub.mod"
    # and with no config at all (callers that pass None)
    assert module_id_for(toy, nested) == "pkg.sub.mod"


def test_module_id_honours_configured_src_roots(toy):
    config = load_config(toy)
    config["extractor"]["src_roots"] = ["libs/*/lib"]
    path = toy / "libs" / "alpha" / "lib" / "alpha" / "core.py"
    assert module_id_for(toy, path, config) == "alpha.core"
    # the default globs no longer apply once the key is overridden
    config["extractor"]["src_roots"] = []
    assert module_id_for(toy, toy / "src" / "app.py", config) == "src.app"


@pytest.mark.parametrize("bad", ["src", ["src", 3], {"a": 1}])
def test_malformed_src_roots_fails_loud(toy, bad):
    config = load_config(toy)
    config["extractor"]["src_roots"] = bad
    with pytest.raises(HarnessError) as exc:
        module_id_for(toy, toy / "src" / "app.py", config)
    assert "extractor.src_roots" in str(exc.value)


# ---------------------------------------------------------------- imports
def test_python_imports_keep_the_full_dotted_path(toy):
    install_ns_packages(toy)
    imports = shadow_of(toy, DATA_SRC)["imports"]
    assert imports == ["kente.config", "kente.service"]
    assert "kente" not in imports  # never the top-level segment only
    assert shadow_of(toy, CONFIG_SRC)["imports"] == ["kente.core"]


def test_deep_dotted_import_survives_whole(toy):
    src = toy / "deep.py"
    src.write_text('"""Deep."""\nimport kente.telemetry.decorators\n'
                   "from kente.blob.fsspec import Store\n")
    shadow, _ = extract_path(toy, src, load_config(toy))
    assert shadow["imports"] == ["kente.blob.fsspec",
                                 "kente.telemetry.decorators"]


def test_relative_imports_keep_their_dotted_tail(toy):
    src = toy / "rel.py"
    src.write_text('"""Rel."""\nfrom .base.deep import Thing\n'
                   "from . import sibling\nimport os.path\n")
    shadow, _ = extract_path(toy, src, load_config(toy))
    # leading dots stripped as before; the tail is no longer truncated
    assert shadow["imports"] == ["base.deep", "os.path"]


def test_typescript_imports_unchanged(toy):
    src = toy / "app.ts"
    src.write_text("import {a} from './telemetry';\nimport _ from 'lodash';\n"
                   "export const x = 1;\n")
    shadow, _ = extract_path(toy, src, load_config(toy))
    assert "./telemetry" in shadow["imports"] and "lodash" in shadow["imports"]


# ---------------------------------------------------------------- matching
def _entries():
    return [
        {"id": "kente", "module_id": None},
        {"id": "core", "module_id": "kente.core"},
        {"id": "config", "module_id": "kente.config"},
        {"id": "kente.service", "module_id": None},
        {"id": "telemetry", "module_id": "telemetry"},
    ]


def test_match_registry_module_longest_prefix():
    e = _entries()
    assert match_registry_module("kente.config", e)["id"] == "config"
    assert match_registry_module("kente.config.secrets", e)["id"] == "config"
    assert match_registry_module("kente.service", e)["id"] == "kente.service"
    assert match_registry_module("kente.other.thing", e)["id"] == "kente"
    assert match_registry_module("requests", e) is None


def test_match_registry_module_falls_back_to_ids():
    """Flat repos keep matching on `id` exactly, as before."""
    e = _entries()
    assert match_registry_module("telemetry", e)["id"] == "telemetry"
    assert match_registry_module("telemetry.spans", e)["id"] == "telemetry"


# ---------------------------------------------------------------- G5
def _ns_registry(toy):
    """Registry + slice for the fixture constellation.

    `config` is a built entry whose module_id is `kente.config`; `kente` and
    `kente.service` are planned entries with no module_id. The slice declares
    only `config`, so the `kente.service` import is undeclared.
    """
    install_ns_packages(toy)
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    entry = next(e for e in rows if e["id"] == "config")
    shadow = shadow_of(toy, CONFIG_SRC)
    entry.update({"status": "built", "source": CONFIG_SRC,
                  "source_hash": shadow["source_hash"],
                  "shadow": str(shadow_path_for(toy, toy / CONFIG_SRC)
                                .relative_to(toy)),
                  "module_id": shadow["module_id"]})
    for planned in ("kente", "kente.service"):
        rows.append({"id": planned, "kind": "component", "status": "planned",
                     "module_id": None, "source": None, "source_hash": None,
                     "shadow": None, "guidance_refs": [],
                     "supersedes_guidance": [], "manifest": [],
                     "signature_digest": None})
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    backlog = read_jsonl(toy / ".harness" / "backlog.jsonl")
    backlog[0]["declares_dep"] = ["config"]
    backlog[0]["predicted_files"] = [DATA_SRC]
    write_jsonl(toy / ".harness" / "backlog.jsonl", backlog)


def test_g5_undeclared_use_names_the_dotted_module(toy):
    _ns_registry(toy)
    loaded_context(toy, session="ns5")
    v = handle_event(make_event("post_change", session="ns5",
                                files=[DATA_SRC]), toy)
    hits = [f for f in v["findings"] if f["code"] == "UNDECLARED_USE"]
    msgs = "\n".join(f["message"] for f in hits)
    assert "'kente.service'" in msgs, msgs
    assert "'kente'" not in msgs, msgs      # never collapsed to the top level
    assert "'config'" not in msgs, msgs     # kente.config IS declared


# ---------------------------------------------------------------- resolver
def test_resolver_one_hop_follows_dotted_imports(toy):
    from engine.resolver import resolve
    _ns_registry(toy)
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    data = {"id": "data", "kind": "component", "status": "built",
            "source": DATA_SRC, "guidance_refs": [], "supersedes_guidance": [],
            "manifest": [], "signature_digest": None,
            "source_hash": shadow_of(toy, DATA_SRC)["source_hash"],
            "shadow": str(shadow_path_for(toy, toy / DATA_SRC).relative_to(toy)),
            "module_id": "kente.data"}
    rows.append(data)
    write_jsonl(toy / ".harness" / "registry.jsonl", rows)
    backlog = read_jsonl(toy / ".harness" / "backlog.jsonl")
    backlog[0]["declares_dep"] = ["data"]
    write_jsonl(toy / ".harness" / "backlog.jsonl", backlog)

    out = resolve(toy, "slice-042", load_config(toy))
    assert "shadow:data" in out["context_loaded"]
    assert "shadow:config" in out["context_loaded"]   # one hop via kente.config
    assert "=== shadow:kente.config" in "\n".join(out["injections"])


# ---------------------------------------------------------------- cache stamp
def test_v2_shadow_is_rebuilt_not_served(toy):
    """The FORMAT changed, so the extractor-version half of the cache key must
    invalidate every shadow written before D-008 — otherwise truncated imports
    are served forever while G7's uncached rebuild mismatches forever (W7)."""
    from engine.extractor.engine import EXTRACTOR_VERSION
    assert EXTRACTOR_VERSION >= 3
    config = load_config(toy)
    src = toy / "orders.py"
    src.write_text('"""Orders."""\nimport kente.telemetry.decorators\n')
    extract_path(toy, src, config)
    sp = shadow_path_for(toy, src)

    stale = json.loads(sp.read_text())
    stale["extractor_version"] = 2
    stale["imports"] = ["kente"]            # what v2 would have written
    sp.write_text(json.dumps(stale, sort_keys=True, indent=1) + "\n")

    shadow, _ = extract_path(toy, src, config)  # same source_hash, old stamp
    assert shadow["extractor_version"] == EXTRACTOR_VERSION
    assert shadow["imports"] == ["kente.telemetry.decorators"]
    assert json.loads(sp.read_text())["imports"] == ["kente.telemetry.decorators"]


# ---------------------------------------------------------------- src roots
def test_src_root_glob_is_anchored_at_the_repo_root(toy):
    """`docs/src/conf.py` is not a source root: only an anchored match strips."""
    config = load_config(toy)
    assert module_id_for(toy, toy / "docs" / "src" / "conf.py",
                         config) == "docs.src.conf"
    assert module_id_for(toy, toy / "vendor" / "packages" / "a" / "src" / "m.py",
                         config) == "vendor.packages.a.src.m"


@pytest.mark.parametrize("bad", [[], 0, "nope"])
def test_malformed_extractor_block_fails_loud(toy, bad):
    """Only a missing `extractor` key defaults; a malformed block is loud."""
    config = load_config(toy)
    config["extractor"] = bad
    with pytest.raises(HarnessError) as exc:
        module_id_for(toy, toy / "src" / "app.py", config)
    assert "extractor.src_roots" in str(exc.value)


def test_absent_extractor_block_uses_the_defaults(toy):
    config = load_config(toy)
    config.pop("extractor")
    assert module_id_for(toy, toy / "src" / "app.py", config) == "app"


# ---------------------------------------------------------------- review L0
def test_layer0_imported_shadows_follow_dotted_prefix(toy):
    """Layer 0 is the fourth consumer of shadow imports: a dotted import must
    still find the registry entry whose id/module_id is its prefix."""
    from engine.review.layer0 import assemble
    (toy / "orders.py").write_text(
        '"""Orders."""\nimport telemetry.spans\n\n'
        "def create_order(sku):\n    return telemetry.spans.emit(sku)\n")
    extract_path(toy, toy / "orders.py", load_config(toy))
    diff = "diff --git a/orders.py b/orders.py\n+++ b/orders.py\n+x = 1\n"
    out = assemble(toy, diff, "slice-042", load_config(toy))
    assert "telemetry.spans" in out["imported_shadows"]
    assert out["imported_shadows"]["telemetry.spans"]["module_id"] == "telemetry"
