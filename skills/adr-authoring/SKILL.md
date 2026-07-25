---
name: adr-authoring
description: Write, record, or amend an architecture decision record (ADR). Use whenever the conversation decides anything architectural — "record this decision", "let's go with", "we decided", "write an ADR", "document why we chose", "architecture decision", "design rationale", "tradeoff", "supersede that decision". Also when compiling decisions into decision tables or registry guidance.
---

# ADR authoring

Format: Nygard sections + machine frontmatter. Use `adr-template.md` in this
skill directory (same schema as `templates/adr.md` scaffolded into repos).
Files are `adr/NNN-kebab-title.md`, numbered sequentially, immutable once
accepted — amendments create a new ADR with `supersedes: [NNN]`.

The split that matters:

- **Prose is for extrapolation.** Context/Consequences teach an agent how to
  act in situations the frontmatter doesn't cover.
- **Frontmatter is what the resolver queries.** `domains[]` routes the ADR to
  slices; `decision_table_rows[]` become atomic lookup rows (see the
  decision-tables skill for when a choice is a row vs a full ADR);
  `abstractions[]` seed the registry; `api_surface[]` seeds contracts.

Rules:

- Every decision row needs `id, domain, question, answer` — the compiler
  fails loud on partial rows.
- Never edit `.harness/decisions.jsonl` directly for phase0 rows; edit the
  ADR frontmatter and re-run `"${CLAUDE_PLUGIN_ROOT}/bin/harness" compile` (compiled form is derived).
- `[non-goal]` lines in the Implementation section become G3 boundaries.
  ENFORCEMENT INTENT MUST BE EXPLICIT: only backticked globs
  (`services/legacy/**`) or `forbid:`-marked paths (forbid: `infra/x.yaml`)
  compile into blocking patterns. A path merely NAMED in prose ("wiring
  lives in `infra/x.yaml`") is descriptive — compile warns and does NOT
  block it. Non-goals are paragraph-scoped; tokens inside code spans are
  prose. Superseded ADRs (status: superseded, or listed in another ADR's
  `supersedes`) compile to nothing — their decisions, refs, and boundaries
  drop on the next compile.
- `contract_mode: generated` in frontmatter declares the contract is
  produced by the build (code-first); compile and author-gate then skip
  api_surface coverage for that ADR.
- Abstraction `kind` must be one of
  `logging|telemetry|config|errors|util|component|other`; anything else is
  coerced to `other` with a warning (decision rows still match by the
  abstraction's id as a domain). Use `replaces: [logging, telemetry]` on an
  abstraction to prune scaffolded planned entries it merges away.
- After writing an ADR, run `"${CLAUDE_PLUGIN_ROOT}/bin/harness" compile` so gates see it this session.
