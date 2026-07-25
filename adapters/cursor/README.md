# harness × Cursor

Two integration routes — pick one:

**A. Native config (this adapter).** Copy `hooks.json` into
`<repo>/.cursor/hooks.json` (or `~/.cursor/hooks.json`), replacing
`${HARNESS_DIR}` with the absolute path of your harness checkout.
`failClosed: true` on `preToolUse` is what makes enforcement real — Cursor
hooks are fail-open by default.

**B. Claude Code compatibility layer.** Cursor can load Claude Code hook
configs directly (Settings -> Features -> Third-party skills): point it at a
`.claude/settings.json` that registers `hooks/adapter.py` from this repo,
and Cursor auto-maps `PreToolUse -> preToolUse`, `Edit/Write -> Write`, etc.

Either way: bind the slice with `export HARNESS_SLICE=<slice-id>` (or
`harness slice`), and note the split:

- **Cursor IDE agent: FULL mode** — `preToolUse` denies edits before they
  land.
- **Cursor CLI / headless: degraded mode** — `preToolUse` doesn't fire
  locally (as of 2026-04); only `afterFileEdit`/`stop` observe. Set
  `gates.degraded_mode: true` in `.harness/config.yaml` there, and consider
  static `Write()` deny globs in `.cursor/cli.json` for the compiled
  non-goal boundaries. `harness verify` in CI backstops both.

**Autonomy (prompt-free slice loop):** merge `cli-permissions.json` into
`<repo>/.cursor/cli.json` (allow git/pytest/python + Write/Read; deny
`Shell(git:push*)`, `Shell(git:remote*)`, `.env` reads — deny always beats
allow). In the IDE set Settings > Cursor Settings > Agents > **Auto-Run**,
mode "Run in Sandbox" recommended over "Run Everything".
