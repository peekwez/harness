"""W7: design history lives in docs/internal/ and no file points at the old
paths. Skills and templates may still name docs/design-reviews/ and
docs/superpowers/specs/ — those are paths in a CONSUMER repo, not links."""
import subprocess

from conftest import PLUGIN_ROOT

GONE = ("docs/SPEC.md", "CODEX-ASTRA-HARNESS-ENHANCEMENTS.md",
        "docs/handoffs/")
# Paths that only harness's own code and tests used. Skills, templates,
# agents and the public docs pages name them as consumer-repo conventions,
# and docs.yml / mkdocs.yml name them to exclude them, so only these
# locations are checked for them.
OWN_ONLY = ("docs/design-reviews/", "docs/superpowers/")
OWN_SCOPE = ("tests/", "engine/", "bin/", "hooks/", "adr/", ".harness/")
OWN_FILES = ("README.md", "CHANGELOG.md", "Makefile")
SELF = "tests/engine/test_internal_paths.py"
# Frozen copies of old releases name paths as they were then.
FROZEN = "tests/fixtures/legacy/"


def _tracked():
    out = subprocess.run(["git", "-C", str(PLUGIN_ROOT), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines()
            if not p.startswith("docs/internal/") and p != SELF]


def test_moved_files_exist_at_their_new_paths():
    internal = PLUGIN_ROOT / "docs" / "internal"
    assert (internal / "SPEC.md").is_file()
    assert (internal / "handoffs"
            / "2026-09-05-codex-astra-harness-enhancements.md").is_file()
    assert (internal / "design-reviews").is_dir()
    assert (internal / "superpowers" / "specs"
            / "2026-10-02-harness-0.10-design.md").is_file()
    for old in ("docs/SPEC.md", "docs/design-reviews", "docs/superpowers",
                "CODEX-ASTRA-HARNESS-ENHANCEMENTS.md"):
        assert not (PLUGIN_ROOT / old).exists(), old


def test_no_tracked_file_points_at_a_moved_path():
    stale = []
    for rel in _tracked():
        path = PLUGIN_ROOT / rel
        if path.suffix not in {".md", ".py", ".yml", ".yaml", ".json",
                               ".toml", ".txt", ".sh"}:
            continue
        text = path.read_text(errors="replace")
        for needle in GONE:
            if needle in text:
                stale.append(f"{rel}: {needle}")
        if (rel.startswith(OWN_SCOPE) or rel in OWN_FILES) and not rel.startswith(FROZEN):
            for needle in OWN_ONLY:
                if needle in text:
                    stale.append(f"{rel}: {needle}")
    assert not stale, "stale paths:\n" + "\n".join(stale)


def test_changelog_has_an_empty_0_10_heading_first():
    text = (PLUGIN_ROOT / "CHANGELOG.md").read_text()
    lines = text.splitlines()
    assert lines[0] == "# Changelog"
    headings = [ln for ln in lines if ln.startswith("## ")]
    assert headings[0] == "## 0.10.0 (unreleased)"
    assert headings[1].startswith("## 0.9.4")
    assert headings[-1] == "## 0.8.0"
    assert not any(ln.startswith("### 0.") for ln in lines)
