---
id: "002"
status: accepted
domains: [gates, extractor, landing, compiler, acceptance, skills, cli]
supersedes: []
decision_table_rows:
  - id: D-007
    domain: gates
    question: "How does a consumer repo add its own deterministic gates?"
    answer: "List them in `.harness/config.yaml` under `gates.extra` (repo-relative `.py` path or `module:path`). Each exposes the same `GATE = {id, preferred, fallback}` + `run(ctx) -> list[finding]` contract as G1–G8 and is loaded by `all_gates()` and `harness verify`. A gate that fails to import is a `severity: block` finding `EXTRA_GATE_LOAD_ERROR` citing the path — never a silent skip. Blocking findings from extra gates must cite a `rule_ref` like every other gate."
  - id: D-008
    domain: extractor
    question: "How are Python imports and module ids represented for namespace packages?"
    answer: "Shadows keep the full dotted import (`kente.telemetry.decorators`), never the top-level segment only. `module_id` is derived by stripping any matching `extractor.src_roots` glob (default `[\"src\", \"packages/*/src\"]`) from the source path and dotting the remainder, dropping a trailing `__init__`; `packages/kente-config/src/kente/config/__init__.py` → `kente.config`. G5 and the resolver match registry `module_id`s by longest dotted prefix."
  - id: D-009
    domain: landing
    question: "How does a closed slice reach the main branch?"
    answer: "Per `landing.mode`. `local` (default, unchanged): `merge-slice` merges into the checked-out main. `pr`: `close-slice` regenerates substrate on the slice branch, commits, writes the provenance note, pushes `slice/<id>` to `landing.remote`, and opens a PR via `landing.pr_cmd`; the PR title/body carry the slice's `linear` id when set. `merge-slice` refuses in `pr` mode with a pointer to the PR."
  - id: D-010
    domain: landing
    question: "How do provenance notes survive squash/rebase merges?"
    answer: "Notes are keyed twice: on the commit (as today) and in the derived `.harness/notes.jsonl` by `{slice_id, tree_hash}`. `verify` resolves a slice by tree hash when the noted commit is unreachable and emits no orphan finding; `harness graph note --repoint <slice> <sha>` re-attaches the git note. Only a slice with neither is `MISSING_PROVENANCE_NOTE`."
  - id: D-011
    domain: landing
    question: "Which egress commands may the permit layer auto-approve inside a bound slice?"
    answer: "In `pr` mode only: `git push [-u] <landing.remote> slice/<bound-id>`, `git fetch <landing.remote>`, and `gh pr create|view|checks|status`. Everything else that talks to a remote still falls through to the human. In `local` mode nothing changes."
  - id: D-012
    domain: acceptance
    question: "What command decides that a slice's acceptance is green?"
    answer: "`acceptance.cmd` from config with `{paths}` substituted (default: the historical `<python> -m pytest {paths}` so existing repos are unchanged), run from `acceptance.cwd` with `acceptance.env`. If `acceptance.gate_cmd` is set (e.g. `make check`), it runs once at close and a non-zero exit is the blocking finding `ACCEPTANCE_GATE_FAILED` (rule_ref adr:002). The regression suite at close/merge uses the same runner."
  - id: D-013
    domain: compiler
    question: "Where may decision rows and abstractions be authored besides ADR frontmatter?"
    answer: "In `docs/architecture.md` inside fenced blocks ` ```harness-decisions ` (pipe table `id | domain | question | answer | adr_ref | security`) and ` ```harness-abstractions ` (`id | kind | guidance_ref`). `compile --doc` merges them; an id present in both an ADR and the doc is a hard error naming both sources. `harness architect --from-spec <path>` seeds the doc at `<!-- stage: 3 -->` from an existing spec."
  - id: D-014
    domain: skills
    question: "Which plugin owns what when superpowers is installed alongside harness?"
    answer: "harness owns the outer loop: session start, slice bind/scope/declarations, attempts memory, review contract (`rule_ref`), close and landing. superpowers owns the inner loop: `brainstorming` (as architect stage 1, writing `docs/architecture.md`), `test-driven-development` per unit, `systematic-debugging` on any red test or gate block, `verification-before-completion` before close. `finishing-a-development-branch` and `subagent-driven-development`'s stop-for-side-effects rule are not used inside a bound slice; `using-git-worktrees` must detect and reuse `.worktrees/<slice>`. `requesting-code-review` runs only as review Layer 3 (advisory)."
  - id: D-015
    domain: cli
    question: "How do skills and generated settings reference the engine binary?"
    answer: "Never by absolute plugin path. `allowed-tools` uses `Bash(*/bin/harness *)`; generated `settings.local.json` allows `*/bin/harness` and resolves the engine at runtime; adapters resolve via `__file__`."
abstractions:
  - id: cli
    kind: component
    source: engine/cli/__init__.py
    section: s1
    replaces: []
api_surface: []
---

# ADR-002: Make harness kente-capable and superpowers-composable

## Status

Accepted (2026-08-16). Tracked as Linear GOO-72 with one sub-issue per
section below (GOO-73…GOO-80).

## Context

Three independent reviews of harness 0.7.1 (engine vs spec, skills/hooks
vs superpowers 6.3.0, tests/history/maturity) before using it to build the
kente platform constellation (~15 PEP 420 namespace packages, uv workspace,
`main` PR-protected with linear history, two humans + Claude + Codex)
found the gates real and the pilot (`rt`, 19 slices) genuine, but seven
concrete blockers for this shape of repo:

1. `all_gates()` is a hardcoded list — a repo cannot add its own
   deterministic gates, so kente's core invariants (no `kente/__init__.py`,
   import DAG, telemetry-null-not-conditional, `__all__` ↔ skill-node
   parity) would live in CI scripts harness never sees.
2. `_python_imports` keeps `split(".")[0]` and `module_id_for` dots the
   whole path: G5 uses⊆declares, one-hop resolution and any DAG check are
   blind for namespace packages.
3. `merge-slice`/`run` merge locally into `main`; the sandbox denies
   `git push`; `gh` is never permitted; provenance notes are written on the
   pre-squash SHA so `verify` reports `ORPHANED_NOTE` after every squash.
4. `compile` reads only ADR frontmatter plus `[non-goal]`/`[open-question]`
   from `--doc`; an existing 1000-line spec would be re-derived Socratically.
5. Acceptance runs `python -m pytest` under `sys.executable`; kente's gate
   is `make check` (ruff, ty, pytest `--import-mode=importlib`).
6. With superpowers installed, agents receive contradictory instructions at
   session start (architect vs brainstorming), mid-build (run-to-close vs
   stop-for-side-effects), and at close (silent merge vs menu).
7. `${CLAUDE_PLUGIN_ROOT}` is baked into allow-rules and settings (breaks
   on plugin bump); the CI template cannot clone a private engine repo;
   `bin/harness` is a 2,489-line monolith.

## Decision

Ship harness **0.8.0** with exactly the changes in the decision rows above,
one PR per row group, and nothing else. Explicitly deferred: `harness run`
campaign mode hardening, non-Claude adapters, embeddings, new language
packs. Kente adopts 0.8 (GOO-80) before any package code lands, and keeps
a tripwire: if after three kente slices the gates have caught nothing that
CI + superpowers would not have, harness is cut back to `verify` +
`decisions.jsonl` + ADRs.

### Config additions (all optional; absent = 0.7.1 behaviour)

```yaml
gates:
  extra: [".harness/gates/namespace.py", "kente_gates.dag:GATE"]
registry:
  kinds_extra: [package, protocol]
extractor:
  src_roots: ["src", "packages/*/src"]
landing:
  mode: pr              # local | pr
  remote: origin
  base: main
  pr_cmd: "gh pr create --base {base} --head {branch} --title {title} --body-file {body}"
acceptance:
  cmd: "uv run pytest --import-mode=importlib {paths}"
  cwd: "."
  env: {}
  gate_cmd: "make check"
```

Backlog slice rows gain an optional `linear: "GOO-NN"` field (schema §5.6);
with `landing.mode: pr` in `.harness/config.yaml`, the close includes it in
the PR title and body.

## Consequences

Easier: kente's invariants become first-class gates with `rule_ref`s and
run in CI `verify` (so Codex diffs are covered too); slices land through
the same PR path humans use; the existing spec is compiled, not re-typed;
one working agreement tells both plugins who owns what.

Harder: two landing modes to test; `notes.jsonl` is one more derived file
(G7 covers it); the CLI split is a large mechanical diff that must keep all
307 tests and the README subcommand test green.
