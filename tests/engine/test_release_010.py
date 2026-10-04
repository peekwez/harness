"""The 0.10.0 manifests agree with the engine."""
from __future__ import annotations

import json
import re
from pathlib import Path

import engine

ROOT = Path(engine.__file__).resolve().parents[1]


def _json(rel):
    return json.loads((ROOT / rel).read_text())


def test_plugin_manifest_declares_the_engine_schema():
    plugin = _json(".claude-plugin/plugin.json")
    assert plugin["engine"]["substrate_schema_version"] == engine.SCHEMA_VERSION == 2


def test_marketplace_names_only_skills_that_exist():
    market = _json(".claude-plugin/marketplace.json")
    text = " ".join(p["description"] for p in market["plugins"] if p["name"] == "harness")
    named = set(re.findall(r"/harness:([a-z-]+)", text))
    on_disk = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    assert named == on_disk, (named ^ on_disk)
    assert "G1-G8" not in text and "golden replay" not in text


def test_every_manifest_carries_the_engine_version():
    want = engine.ENGINE_VERSION
    assert _json(".claude-plugin/plugin.json")["version"] == want
    assert _json(".codex-plugin/plugin.json")["version"] == want
    plugins = _json(".claude-plugin/marketplace.json")["plugins"]
    assert [p["version"] for p in plugins if p["name"] == "harness"] == [want]
