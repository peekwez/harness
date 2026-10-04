"""Spec 9.2 and 12 step 13: init writes docs/glossary.md; upgrade creates
it when it does not exist."""
from conftest import run_cli
from engine.lint_text import load_glossary


def _fresh(tmp_path):
    target = tmp_path / "fresh"
    target.mkdir()
    (target / "app.py").write_text("x = 1\n")
    return target


def test_init_writes_a_glossary_template(tmp_path):
    target = _fresh(tmp_path)
    proc = run_cli("init", root=target)
    assert proc.returncode == 0, proc.stderr
    assert load_glossary(target / "docs" / "glossary.md")["story"] == "slice"


def test_init_keeps_an_existing_glossary(tmp_path):
    target = _fresh(tmp_path)
    (target / "docs").mkdir()
    (target / "docs" / "glossary.md").write_text("# Our glossary\n")
    assert run_cli("init", root=target).returncode == 0
    assert (target / "docs" / "glossary.md").read_text() == "# Our glossary\n"


def test_glossary_step_is_registered():
    from engine import upgrade_010
    assert "w4.glossary" in [s.id for s in upgrade_010.STEPS]


def test_glossary_step_creates_the_file_once(tmp_path):
    from engine.upgrade_w4 import GLOSSARY_STEP
    assert GLOSSARY_STEP.describe(tmp_path) == [
        "create docs/glossary.md from the glossary template"]
    assert GLOSSARY_STEP.apply(tmp_path, lambda q: False) == [
        "created docs/glossary.md"]
    assert GLOSSARY_STEP.describe(tmp_path) == []
    assert GLOSSARY_STEP.apply(tmp_path, lambda q: False) == []


def test_glossary_step_keeps_an_existing_glossary(tmp_path):
    from engine.upgrade_w4 import GLOSSARY_STEP
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "glossary.md").write_text("mine\n")
    assert GLOSSARY_STEP.describe(tmp_path) == []
    assert (tmp_path / "docs" / "glossary.md").read_text() == "mine\n"


def test_glossary_step_advises_when_docs_is_a_file(tmp_path):
    from engine.upgrade_w4 import GLOSSARY_STEP
    (tmp_path / "docs").write_text("not a directory\n")
    assert GLOSSARY_STEP.describe(tmp_path) == []
    assert GLOSSARY_STEP.apply(tmp_path, lambda q: False) == []
    advice = GLOSSARY_STEP.advise(tmp_path)
    assert len(advice) == 1 and advice[0].startswith("check: ")
    assert "docs" in advice[0]
