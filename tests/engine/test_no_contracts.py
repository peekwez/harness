"""D-0.10-09: contracts leave core. No scaffold, stubs, lint or skill."""
from conftest import PLUGIN_ROOT, git, run_cli
from engine.compiler import author_gate, compile_substrate


def test_init_creates_no_contracts(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n")
    git(root, "init", "-q")
    assert run_cli("init", root=root).returncode == 0
    assert not (root / "contracts").exists()


def test_contract_template_and_skill_are_gone():
    assert not (PLUGIN_ROOT / "templates" / "contract.stub.yaml").exists()
    assert not (PLUGIN_ROOT / "skills" / "contract-first").exists()


def test_compile_ignores_api_surface(toy):
    (toy / "adr" / "012-api.md").write_text(
        '---\nid: "012"\nstatus: accepted\ncontract: billing\n'
        'api_surface:\n  - "POST /invoices"\n---\nbody\n')
    report = compile_substrate(toy)
    assert "contracts" not in report and "contract_gaps" not in report
    assert not (toy / "contracts" / "billing.yaml").exists()
    assert not any("api_surface" in g for g in author_gate(toy)["gaps"])


def test_verify_does_not_lint_contracts(toy):
    (toy / "contracts").mkdir(exist_ok=True)
    (toy / "contracts" / "api.yaml").write_text("openapi: 3.0.3\n[broken")
    proc = run_cli("verify", root=toy)
    assert "CONTRACT_INVALID" not in proc.stdout


def test_no_skill_or_template_describes_the_contract_scaffold():
    offenders = []
    for sub in ("skills", "templates", "agents"):
        for path in sorted((PLUGIN_ROOT / sub).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(errors="replace")
            for needle in ("contracts/", "contract_gaps", "contract_mode",
                           "api_surface", "contract-first"):
                if needle in text:
                    offenders.append(f"{path.relative_to(PLUGIN_ROOT)}: {needle}")
    assert not offenders, offenders
