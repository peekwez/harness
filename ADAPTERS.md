# Adapter targets — cross-harness compatibility (researched July 2026)

The engine is framework-agnostic by design: `bin/harness event` takes an
EnforcementEvent (JSON, stdin) and returns a verdict (JSON, stdout). Porting
harness to another coding agent = writing one adapter that translates that
harness's hook/plugin events into the five-event contract, then passing
`tests/adapter-conformance/`. Frameworks without pre-change interception run
gates in degraded revert-and-retry mode (T1: gates declare
preferred/fallback events).

Since early 2026 nearly every major harness has adopted Claude-Code-style
lifecycle hooks (stdin JSON → stdout verdict, exit 2 = block), so full
enforcement is available almost everywhere.

## Compatibility matrix

| Harness | Mode | Pre-edit deny binding | Context injection | Adapter effort |
|---|---|---|---|---|
| **Claude Code** | FULL (native) | `PreToolUse` deny | `SessionStart`/`UserPromptSubmit` additionalContext | ships in `hooks/` |
| **OpenAI Codex CLI** (hooks GA 2026-05) | FULL | `PreToolUse`, matcher `apply_patch` (aliases `Edit\|Write`) → `permissionDecision:"deny"` or exit 2 | `SessionStart`/`UserPromptSubmit` additionalContext; `Stop` block forces continuation | near copy of `hooks/adapter.py`; register in `.codex/hooks.json`; needs one-time hook trust |
| **Factory Droid** | FULL | `PreToolUse` (`Edit`,`Create`,`ApplyPatch`,`Execute`) → `permissionDecision:"deny"`/exit 2, `updatedInput` | `SessionStart`/`UserPromptSubmit` additionalContext | near drop-in (same wire shape); org-managed hooks + `allowManagedHooksOnly` make enforcement non-overridable |
| **Gemini CLI** (hooks GA v0.26, 2026-01) | FULL | `BeforeTool`, matcher `write_file\|replace` / `run_shell_command` → `decision:"deny"` | `SessionStart`/`BeforeAgent` additionalContext; `AfterAgent` for unit_complete | event/field rename shim; ship as a gemini-cli extension bundling hooks. Caveat: hooks are fail-open |
| **Cursor (IDE agent)** | FULL | `preToolUse`, matcher `Write`/`Delete`/`Shell` → `permission:"deny"`; set `failClosed:true` | `sessionStart` additional_context; `beforeSubmitPrompt`; `stop` followup | may need none: Cursor natively loads Claude Code hooks configs and maps events/tools automatically |
| **Cursor CLI (headless)** | DEGRADED (post-only for edits) | none yet (`preToolUse` not fired locally as of 2026-04); shell deny works via `beforeShellExecution` | `sessionStart` | `gates.degraded_mode: true` (T1 revert-and-retry via `afterFileEdit`/`postToolUse`); coarse pre-blocks via static `Write()` deny globs in `.cursor/cli.json` |
| **pi** (earendil-works/pi) | FULL | extension `pi.on("tool_call")` → `{block:true, reason}`; `event.input` mutable | `session_start`/`before_agent_start` → injected message + systemPrompt | ~50-line TypeScript extension spawning `bin/harness event` |
| **OpenCode** (anomalyco) | FULL | plugin `tool.execute.before` → throw to deny; `output.args` mutable | AGENTS.md + SDK client; `session.created`/`session.idle` lifecycle | ~50-line JS plugin in `.opencode/plugins/` |
| **Amp** (Sourcegraph) | FULL | plugin `tool.call` → `{action:"reject-and-continue"}` / `modify` / `synthesize` | `agent.start` message return | ~50-line TS plugin (`@ampcode/plugin`); API is descended from pi's, so the two shims are near-identical. Toolboxes/hooks-settings are legacy — plugins only |
| **Aider** | INSTRUCTION-ONLY | none (edits land directly, then auto-commit) | `CONVENTIONS.md` via `--read` | post-hoc only: policy wrapper as `--lint-cmd` + git revert; project dormant since 2025-08 — not recommended |

## Shared foundations that work everywhere

- **AGENTS.md** — `/harness:init` scaffolds it; Codex, Gemini (via context
  files), Cursor, pi, OpenCode, Amp, and Droid all read it. Instruction-level
  guidance is universal even before an adapter exists.
- **`harness verify` in CI** — zero framework involvement; the enforcement
  backstop is identical regardless of which agent produced the commits.
- **The CLI itself** — every harness above can shell out, so the full
  workflow (`resolve`, `gates`, `close-slice`, `review`, `status`) is usable
  from any of them today, adapter or not.

## Shipped adapters

`adapters/` contains ready-to-install adapters for the five full-mode
targets beyond Claude Code, each with its install config and README:

- `adapters/codex/` — adapter.py + hooks.json (`.codex/hooks.json`)
- `adapters/gemini/` — adapter.py + settings-hooks.json (`.gemini/settings.json`)
- `adapters/cursor/` — adapter.py + hooks.json (`.cursor/hooks.json`,
  `failClosed: true`); or use Cursor's Claude Code hooks compatibility layer
- `adapters/pi/` — harness.ts extension (`.pi/extensions/`)
- `adapters/opencode/` — harness.js plugin (`.opencode/plugins/`;
  `tool.execute.before` throw-to-deny, `session.idle` → unit_complete)

The Python adapters share `adapters/common.py` and pass
`tests/adapter-conformance/test_multi_adapters.py` (deny-before-Phase-1 →
inject → allow, non-goal deny, compaction telemetry-only, inert without
substrate, host-specific loop guards); the OpenCode plugin has a live node
conformance test. The pi extension is syntax-checked only — treat it as
beta.

## Autonomy profiles (prompt-free slice loop) per host

Approval prompts are not the enforcement layer in a harness repo — the
pre-change gates and CI verify are — so each host's prompts can be safely
pre-approved, with network-egress commands (`git push`/`git remote`) kept
denied everywhere. Slice worktrees live at `.worktrees/<slice>` INSIDE the
repo precisely so these profiles cover them: acceptEdits (Claude Code),
workspace-write sandboxes (Codex), and workspace-scoped `Write(**)` allows
(Cursor) all stop at the workspace boundary, and an out-of-repo worktree
would prompt — or be blocked — on every edit:

| Host | Profile | Mechanism |
|---|---|---|
| Claude Code | `harness init --autonomy` → `.claude/settings.json` | permissions.allow + acceptEdits; push/remote denied |
| Codex CLI | `adapters/codex/autonomy.toml` + `no-push.rules` | `approval_policy: never`, workspace-write sandbox (network off), Starlark forbidden rules |
| Gemini CLI | `adapters/gemini/autonomy-policy.toml` → `~/.gemini/policies/` | policy engine: allow@50, push/remote deny@900 (user tier; workspace tier broken upstream) |
| Cursor | `adapters/cursor/cli-permissions.json` → `.cursor/cli.json` | permissions allow/deny (deny wins); IDE Auto-Run "Run in Sandbox" |
| OpenCode | `adapters/opencode/opencode-permissions.json` → `opencode.json` | `permission` map, last-match-wins; denies survive `--auto` |
| pi | none needed | no prompts by design; the harness extension IS the permission layer |

## Adapter recipe

1. Map the host's events onto: `session_start`, `pre_context`, `pre_change`,
   `post_change`, `unit_complete` (see `hooks/adapter.py` — the Claude Code
   reference is ~130 lines).
2. Translate verdicts: `block` → the host's deny mechanism; `injections` →
   the host's context-injection mechanism; respect the host's loop guards
   (e.g. Codex/Claude `stop_hook_active`, Cursor `loop_count`).
3. Repos without a `.harness/` substrate must be inert (allow everything).
4. Pass `tests/adapter-conformance/` (event translation, verdict handling,
   injection format, PreCompact semantics).

Field-name cheat sheet: Claude/Codex/Droid use `hookSpecificOutput.permissionDecision`;
Gemini uses `decision`/`reason` with PascalCase events; Cursor uses
`permission`/`agent_message` with camelCase events and abstract tool types;
pi returns `{block}`; OpenCode throws; Amp returns `{action}` objects.
