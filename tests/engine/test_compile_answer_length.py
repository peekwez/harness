"""Spec 9.2 and 14 "#7": compile warns on a decision answer over 150 words."""
from engine.compiler import DECISION_ANSWER_WORDS, compile_substrate


def _adr(toy, words):
    answer = " ".join(["word"] * words)
    (toy / "adr" / "010-long.md").write_text(
        '---\nid: "010"\nstatus: accepted\ndomains: [config]\n'
        "decision_table_rows:\n  - id: D-500\n    domain: config\n"
        '    question: "How is config loaded?"\n'
        f'    answer: "{answer}"\n---\nbody\n')


def _warnings_for(report, rid):
    return [w for w in report["warnings"] if w.startswith(f"decision {rid}:")]


def test_compile_warns_on_an_answer_over_150_words(toy):
    _adr(toy, DECISION_ANSWER_WORDS + 1)
    report = compile_substrate(toy)
    assert _warnings_for(report, "D-500") == [
        "decision D-500: the answer has 151 words; the limit is 150. Move "
        "the detail into the ADR that the row cites."]


def test_compile_is_quiet_at_150_words(toy):
    _adr(toy, DECISION_ANSWER_WORDS)
    assert _warnings_for(compile_substrate(toy), "D-500") == []


def test_the_warning_reaches_the_cli_output(toy):
    import json
    from conftest import run_cli
    _adr(toy, 200)
    proc = run_cli("compile", root=toy)
    assert proc.returncode == 0, proc.stderr
    assert any("D-500" in w and "200 words" in w
               for w in json.loads(proc.stdout)["warnings"])
