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


def _changelog_010():
    text = (ROOT / "CHANGELOG.md").read_text()
    heads = re.findall(r"^## 0\.10\.0\b.*$", text, re.M)
    assert heads == ["## 0.10.0 (2026-10-04)"], heads
    entry = re.search(r"^## 0\.10\.0\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return entry.group(1)


def test_changelog_has_the_010_entry():
    body = _changelog_010()
    for needle in ("harness upgrade --dry-run", "harness upgrade --yes",
                   "harness: upgrade to 0.10", "legacy_verification",
                   ".harness/cache/legacy-memory/", "field test",
                   "Closes peekwez/harness#2"):
        assert needle in body, needle
    assert "RELEASE_DATE" not in body
    for issue in range(2, 10):
        assert f"#{issue}" in body, issue


def test_changelog_names_every_upgrade_step():
    from engine import upgrade_010
    body = _changelog_010()
    missing = [s.id for s in upgrade_010.STEPS if f"`{s.id}`" not in body]
    assert not missing, missing
    assert f"{len(upgrade_010.STEPS)} steps" in body


def test_changelog_skill_list_matches_disk():
    body = _changelog_010()
    on_disk = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    assert f"18 to {len(on_disk)}" in body
    kept = re.search(r"^- Kept skills: (.*)$", body, re.M)
    assert kept, "no kept-skills line"
    assert set(re.findall(r"`([a-z-]+)`", kept.group(1))) == on_disk


def test_changelog_010_entry_passes_lint_text(tmp_path):
    import subprocess
    import sys
    section = tmp_path / "changelog-010.md"
    section.write_text("## 0.10.0\n" + _changelog_010())
    proc = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "harness"), "lint-text",
         "--glossary", str(ROOT / "docs" / "glossary.md"), str(section)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
