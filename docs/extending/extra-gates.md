# Repo-local gates

A repo-local gate is a deterministic check that your repo adds to the builtin gates. It runs on the same engine events, and its blocking findings stop an edit or a close in the same way.

## Declare a gate

List each gate under `gates.extra` in `.harness/config.yaml`:

```yaml
gates:
  extra: [".harness/gates/logging.py", "shop_gates.layers:GATE"]
```

An entry has one of two forms:

- A repo-relative `.py` path. The resolved path must stay inside the repo. harness rejects an absolute path, a `../` path and a symbolic link that escapes the repo before any code runs.
- A dotted module name that Python can import.

Either form can end in `:ATTR` to name the attribute that holds the declaration. The default is `GATE`.

A gate module holds a `GATE` dict and a `run(ctx)` function that returns a list of findings:

```python
"""LOG1: production code logs through the logger, not print()."""
from pathlib import Path

from engine.events import make_finding

GATE = {"id": "LOG1", "rule_ref": "adr:002",
        "preferred": ["post_change", "unit_complete"]}


def run(ctx) -> list:
    findings = []
    for path in ctx.touched_files():
        rel = ctx.rel(path)
        if not (rel.startswith("src/") and rel.endswith(".py")):
            continue
        source = Path(ctx.root) / rel
        if source.is_file() and "print(" in source.read_text():
            findings.append(make_finding(
                "LOG1_PRINT", GATE["rule_ref"],
                f"LOG1: {rel} calls print().",
                severity="block", key=rel,
                fix=f"Replace print() with the logger in {rel}."))
    return findings
```

The `GATE` dict has these keys:

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | a string that no other gate uses |
| `preferred` | yes | the engine events that run the gate |
| `fallback` | no | the events that run the gate in degraded mode |
| `rule_ref` | no | the rule that your findings cite, by convention |
| `cites` | no | the non-goals that G3 must block |

These rules apply:

- The module must define `run(ctx)`. harness also accepts `check(ctx)`, the name that the builtin gates use.
- The id must not be a builtin id or a retired id. G2, G4, G7 and G8 were removed in 0.10, and their ids stay reserved so that old overrides keep their meaning.
- Each event name must be one of the five engine events.
- `make_finding(code, rule_ref, message, severity, key=, fix=)` builds a finding. A blocking finding must have a `rule_ref`, such as an ADR of your repo.
- Write the message and the fix in STE-80. Put the command or action that resolves the finding in `fix`.

## The gate context

`ctx` is the `GateContext` from `engine/gates/__init__.py`. Each gate of one event gets the same object.

| Member | What it gives |
|---|---|
| `root` | the repo root, as a `Path` |
| `config` | the loaded `.harness/config.yaml` |
| `event` | the event name, such as `post_change` |
| `session_id` and `work_unit_id` | the session and the bound slice id |
| `payload` | the event payload: `files`, `diff` and `prompt` |
| `touched_files()` | the paths in `payload.files` |
| `rel(path)` | the path relative to the repo root |
| `slice` | the bound slice row, or `None` |
| `registry`, `decisions` and `boundaries` | the substrate rows, loaded on first use |

`ctx` does not skip exempt paths for you. Call `engine.gates.exempt(rel, ctx.config)` when your gate must honor `gates.exempt_paths`.

## Cite a non-goal

A non-goal comes from a `[non-goal]` block in an ADR. G3 blocks an edit to a non-goal path only when a repo-local gate cites that non-goal (spec 4.1).

To cite one, list its boundary id or its rule ref in `GATE["cites"]`:

```python
GATE = {"id": "NG1", "preferred": ["pre_change"], "cites": ["adr:007"]}
```

- A cite of a rule ref covers each non-goal that has that rule ref.
- A boundary id is a hash of the non-goal text. A change to the text makes the old id match nothing.
- `harness compile` warns about each cite that matches no non-goal.
- `harness compile` reports each non-goal that no gate cites as "advisory only".
- G3 writes the blocking finding. The citing gate does not need its own check for the path.

## Failure modes

A broken gate never fails in silence. Two codes report it, and both block:

| Code | When |
|---|---|
| `EXTRA_GATE_LOAD_ERROR` | the path is missing or outside the repo, the import fails, `GATE` is not valid, the id is taken, or no callable `run(ctx)` or `check(ctx)` exists |
| `EXTRA_GATE_RUN_ERROR` | `run(ctx)` raised, returned something that is not a list, or returned a finding that the engine rejects, such as a block with no `rule_ref` |

The builtin gates keep running when a repo-local gate fails. The finding names the entry. Its fix is to repair the entry or to remove it from `gates.extra`.

`harness gates explain` has no catalog entry for a code that your gate emits. Put the whole fix in the finding.

## Gates in CI

`harness verify` runs your gates in CI. For each closed slice, it sends a synthetic `unit_complete` event. The files are the slice's `predicted_files` and `acceptance` paths that exist, with globs expanded.

- A gate without `unit_complete` in `preferred` does not run in CI. A gate that is only for `pre_change` has no edit to check there.
- With `gates.degraded_mode: true`, a gate with `unit_complete` in `fallback` also runs.
- Load errors are always reported, also when no gate runs.
- CI has no session state. The sidecar is a read-only stand-in, so a gate that reads session data gets nothing.

## Exempt paths

`gates.exempt_paths` is a list of path prefixes that most checks skip. The default is `.harness/`, `adr/`, `.github/`, `tests/`, `docs/`, `.claude/` and `explore/`.

- An entry that ends in `/` is a prefix. An entry without it names a whole path segment: `docs` matches `docs/x`, but not `docsite/`.
- G3, G5, G9, the red-record advisory, the scope list at close and the permit layer's scope check skip these paths.
- G10 ignores them. A write to `.claude/memory/shared/` always blocks.
- A value that is not a list of non-empty strings is an engine error. A gate never guesses which files are exempt.
