# harness × OpenCode (anomalyco/opencode)

1. Copy `harness.js` to `<repo>/.opencode/plugins/harness.js` (project) or
   `~/.config/opencode/plugins/harness.js` (global).
2. `export HARNESS_BIN=/abs/path/to/harness/bin/harness` — the plugin fails
   loud (console error, enforcement disabled) if unset, never silently.
3. Bind the slice: `harness slice --slice <id>` (the repo-default binding
   covers OpenCode's session IDs) or `export HARNESS_SLICE=<id>`.
4. **Autonomy**: merge the `permission` block from
   `opencode-permissions.json` into your `opencode.json` — everything
   allowed except `git push`/`git remote` (denies survive `opencode --auto`).
   Prompts aren't the guardrail; the plugin's `tool.execute.before` deny is.

Semantics:

- `tool.execute.before` throws to deny `edit`/`write`/`patch` (and gates
  `bash`) pre-execution — full enforcement mode.
- `session.idle` maps to unit_complete (shadow regen, edges, G4–G8);
  `session.compacted` records the COMPACTION_REACHED defect signal.
- Context injection: OpenCode has no additionalContext hook, so Phase-1
  context arrives via `AGENTS.md` (read natively; `/init` regenerates) plus
  running `harness resolve --slice <id>` at slice start — the build
  workflow's first step. G2 still verifies at every edit and denies with a
  pointer if the context isn't loaded, so the loop self-corrects.
- AGENTS.md is scaffolded by `harness init`; OpenCode reads it natively.

Verified against the July 2026 plugin API (`@opencode-ai/plugin` types:
`tool.execute.before(input {tool, sessionID, callID}, output {args})`,
throw-to-deny, `event` catch-all). If a version renames events, this file
is the only thing to touch.
