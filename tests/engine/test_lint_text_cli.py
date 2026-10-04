"""`harness lint-text` (spec 9.3): file:line output, non-zero exit."""
import json

from conftest import run_cli


def test_cli_prints_file_line_rule_text_and_exits_1(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Intro.\n\nWe utilize it.\n")
    proc = run_cli("lint-text", f)
    assert proc.returncode == 1, proc.stderr
    assert proc.stdout.splitlines() == [
        f"{f}:3: banned-word: 'utilize': write a plain word"]


def test_cli_exits_0_on_clean_text(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Plain text.\n")
    proc = run_cli("lint-text", f)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout == ""


def test_cli_walks_directories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("It is robust.\n")
    proc = run_cli("lint-text", tmp_path)
    assert proc.returncode == 1
    assert "b.md:1: banned-word: 'robust'" in proc.stdout


def test_cli_reads_docs_glossary_under_root_by_default(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "glossary.md").write_text(
        "- **slice** — the unit of work (not: story)\n")
    f = tmp_path / "guide.md"
    f.write_text("One story.\n")
    proc = run_cli("lint-text", f, root=tmp_path)
    assert proc.returncode == 1
    assert "glossary-synonym: 'story': use 'slice'" in proc.stdout


def test_cli_missing_glossary_is_an_error(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("Plain.\n")
    proc = run_cli("lint-text", f, "--glossary", tmp_path / "nope.md")
    assert proc.returncode == 2
    assert "nope.md" in proc.stderr


def test_cli_missing_path_is_an_error(tmp_path):
    proc = run_cli("lint-text", tmp_path / "missing.md")
    assert proc.returncode == 2
    assert "missing.md" in proc.stderr


def test_cli_json_output(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("We leverage it.\n")
    proc = run_cli("lint-text", f, "--json")
    assert proc.returncode == 1
    rows = json.loads(proc.stdout)
    assert rows == [{"path": str(f), "line": 1, "rule": "banned-word",
                     "text": "'leverage': write a plain word"}]


def test_cli_skips_a_directory_named_like_markdown(tmp_path):
    (tmp_path / "dir.md").mkdir()
    (tmp_path / "ok.md").write_text("It is robust.\n")
    proc = run_cli("lint-text", tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "ok.md:1: banned-word" in proc.stdout


def test_cli_reports_an_unreadable_file_and_continues(tmp_path):
    import os
    import pytest
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("permissions are not enforced here")
    bad = tmp_path / "bad.md"
    bad.write_text("Plain.\n")
    bad.chmod(0)
    (tmp_path / "ok.md").write_text("It is robust.\n")
    try:
        proc = run_cli("lint-text", tmp_path)
    finally:
        bad.chmod(0o644)
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr
    assert "bad.md:1: unreadable:" in proc.stdout
    assert "ok.md:1: banned-word" in proc.stdout


def test_cli_skips_a_dangling_symlink_in_a_walked_directory(tmp_path):
    import os
    import pytest
    if os.name == "nt":
        pytest.skip("symlinks need privileges here")
    (tmp_path / "gone.md").symlink_to(tmp_path / "missing-target.md")
    (tmp_path / "ok.md").write_text("It is robust.\n")
    proc = run_cli("lint-text", tmp_path)
    assert proc.returncode == 1, proc.stderr
    assert "does not exist" not in proc.stderr
    assert "ok.md:1: banned-word" in proc.stdout
