# harness × pi (earendil-works/pi)

1. Copy `harness.ts` to `.pi/extensions/harness.ts` (project) or
   `~/.pi/agent/extensions/harness.ts` (global); pi hot-loads TypeScript via
   jiti — no build step. Reload with `/reload`, smoke-test with `pi -e`.
2. `export HARNESS_BIN=/abs/path/to/harness/bin/harness` (or keep the
   adapter inside the harness checkout and the relative default resolves).
3. Bind the slice: `export HARNESS_SLICE=<slice-id>` or `harness slice`.

Semantics:

- `tool_call` returning `{ block: true, reason }` denies edits pre-execution
  — full enforcement mode.
- Context injects each turn via `before_agent_start`; the engine dedupes so
  the transcript doesn't bloat.
- pi has no stop-block verdict, so `unit_complete` blocks surface as
  injected findings on the NEXT turn plus a console warning — close-slice
  remains the hard gate (`harness close-slice` refuses regardless of host).
- pi reads AGENTS.md natively; `/harness:init`'s scaffold covers the
  instruction layer.

**Autonomy:** nothing to configure — pi has no permission prompts by design
("no permission popups; run in a container, or build your own confirmation
flow with extensions"). The harness `tool_call` extension IS the permission
layer here: it denies out-of-policy edits pre-execution. For a stricter
posture, run pi in a container and/or restrict with `--tools`.

The event names above track pi's extensions API as of v0.80 (July 2026);
the handler reads `event.name`/`event.tool` and `session_id`/`sessionId`
defensively. If a pi upgrade renames events, this file is the only thing
to touch.
