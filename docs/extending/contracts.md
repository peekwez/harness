# Contracts recipe

harness 0.10 does not check API contracts. This page shows two ways to add the check back in your own repo.

## Why contracts left core

Decision D-0.10-09 removed contracts from core. Many repos had an unused `contracts/api.yaml`, and few used the stub generation or the contract lint.

- `harness init` no longer writes `contracts/`. `harness compile` generates no stubs. `harness verify` does not lint contracts.
- The `contract-first` skill was removed.
- "Use a contract as the seam" is now a decision card in architect.

`harness upgrade` keeps your `contracts/` files. It prints a `check:` line that says harness no longer checks them. When `contracts/` is not in `gates.exempt_paths`, the line also tells you to add it, so G3 gives no scope findings for it.

A team that wants OpenAPI checks adds a repo-local gate or a CI linter.

## A contract gate

This gate blocks an OpenAPI operation in `contracts/` that has no `operationId`. Copy it to `.harness/gates/contracts.py`:

```python
"""API1: each OpenAPI operation in contracts/ has an operationId."""
from pathlib import Path

import yaml

from engine.events import make_finding

GATE = {"id": "API1", "rule_ref": "adr:004",
        "preferred": ["post_change", "unit_complete"]}
METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}


def run(ctx) -> list:
    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if not (rel.startswith("contracts/") and rel.endswith(".yaml")):
            continue
        spec = yaml.safe_load((Path(ctx.root) / rel).read_text()) or {}
        for route, ops in (spec.get("paths") or {}).items():
            for method, op in (ops or {}).items():
                if method in METHODS and not (op or {}).get("operationId"):
                    findings.append(make_finding(
                        "CONTRACT_NO_OPERATION_ID", GATE["rule_ref"],
                        f"API1: {method.upper()} {route} has no operationId "
                        f"in {rel}.",
                        severity="block", key=f"{rel}|{method}|{route}",
                        fix=f"Add operationId to {method.upper()} {route}."))
    return findings
```

Then declare it in `.harness/config.yaml`:

```yaml
gates: {extra: [".harness/gates/contracts.py"]}
```

- `adr:004` stands for your repo's ADR for the contract rule. A blocking finding must cite one.
- The gate runs after each edit and at `unit_complete`, so `harness verify` also runs it in CI.
- The harness catalog lists only builtin codes. Describe `CONTRACT_NO_OPERATION_ID` in your own docs.

[Repo-local gates](extra-gates.md) gives the full gate contract.

## A CI linter instead

Use an OpenAPI linter when you want more than one rule, or a linter that your team already knows. Run it in one of two places:

- In a workflow file of your own, such as `.github/workflows/openapi-lint.yml`, on each pull request.
- In `acceptance.gate_cmd` in `.harness/config.yaml`. That command runs once at close and once at merge.

Do not add the step to `.github/workflows/harness-verify.yml` while its first line is the harness marker. `harness upgrade` rewrites a workflow that has the marker. It keeps a workflow without the marker, and prints a note that names the engine step to check.

A linter in CI does not run on each edit. The agent learns about a problem at close, or when CI fails.
