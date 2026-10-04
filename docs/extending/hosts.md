# Other hosts

Claude Code is the reference host. The engine does not depend on it. Any agent host with lifecycle hooks can run harness through one adapter.

## The five-event contract

`bin/harness event` reads one EnforcementEvent as JSON on stdin. It writes one verdict as JSON on stdout.

```json
{"event": "pre_change", "session_id": "s1", "work_unit_id": "orders-1",
 "payload": {"files": [{"path": "src/orders.py", "proposed_content_hash": null}],
             "context_loaded": [], "diff": null, "prompt": null}}
```

The events are `session_start`, `pre_context`, `pre_change`, `post_change` and `unit_complete`. [Hook events](../reference/hooks.md) maps each Claude Code hook to an engine event.

The verdict has three keys:

- `verdict`: `allow`, `allow_with_findings` or `block`.
- `findings`: each finding, with its code, rule ref, message and fix.
- `injections`: the context text for the host to add.

The exit code tells the adapter what happened:

- Exit 0: the engine wrote a verdict. The verdict holds the decision.
- Exit 2: the input JSON is malformed, or the event is unknown.
- Exit 1: the engine failed, for example because the repo has no `.harness/`.

## Write an adapter

An adapter is one file. It translates the host's hooks to the five events, and the verdict back to the host's answers. The Claude Code adapter is [`hooks/adapter.py`](https://github.com/peekwez/harness/blob/main/hooks/adapter.py), about 350 lines. Most of that file is the permit layer for shell commands and the fallback when the engine is down.

An adapter does these things:

1. It maps each host hook to an engine event, and the host's compaction hook to `harness precompact`.
2. It turns `block` into the host's deny answer, and `injections` into the host's context answer.
3. It obeys the host's loop guards, such as `stop_hook_active` or `loop_count`.
4. It allows everything when the repo has no `.harness/`.
5. It denies an edit when the engine fails in an initialised repo.

The Python adapters share [`adapters/common.py`](https://github.com/peekwez/harness/blob/main/adapters/common.py). It builds the event, calls the engine, finds the edited paths and clips long output.

| Adapter | Host | Form |
|---|---|---|
| `adapters/codex/` | OpenAI Codex CLI | Python adapter and `hooks.json` |
| `adapters/cursor/` | Cursor | Python adapter and `hooks.json` |
| `adapters/gemini/` | Gemini CLI | Python adapter and hook settings |
| `adapters/opencode/` | OpenCode | JavaScript plugin |
| `adapters/pi/` | pi | TypeScript extension, syntax-checked only |

Only the Claude Code hook runs the permit layer on shell commands. [Trade-offs and limits](../trade-offs.md#where-enforcement-depends-on-the-host) lists what that means for each host.

## Conformance tests

Each adapter must pass the tests in `tests/adapter-conformance/`:

- `test_adapter.py` checks the Claude Code adapter.
- `test_multi_adapters.py` checks the Codex, Gemini and Cursor adapters. It checks deny before the slice context loads, injection, a non-goal deny, compaction, the inert repo and the loop guards.
- `test_opencode_adapter.py` runs the OpenCode plugin under node. It skips when node is missing.

`make test` runs them with the rest of the suite, so one run keeps each adapter correct. The [0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#d-010-10-other-host-adapters) gives the reasons. The Claude Code plugin does not load the other adapters, so they cost no tokens.

## Degraded mode

Some hosts have no hook before an edit. Set `gates.degraded_mode: true` in `.harness/config.yaml` for such a host. Each gate then also runs at its `fallback` events. G1, G3 and G10 fall back to `post_change`.

In degraded mode, the edit lands first. The gates report it after the edit, and nothing undoes it.

- On Cursor CLI, `afterFileEdit` only observes. The engine records the touched files.
- At `stop`, a blocking verdict sends a `followup_message` that asks the agent to fix the finding. The adapter sends at most two.
- `harness verify` in CI is the backstop for each degraded host.

## Host matrix

This table is from [`ADAPTERS.md`](https://github.com/peekwez/harness/blob/main/ADAPTERS.md), researched in July 2026. Host features change often, so check the host's own docs.

| Host | Mode | Pre-edit deny | Context injection |
|---|---|---|---|
| Claude Code | full | `PreToolUse` deny | `SessionStart` and `UserPromptSubmit` |
| OpenAI Codex CLI | full | `PreToolUse` on `apply_patch` | `SessionStart` and `UserPromptSubmit` |
| Factory Droid | full, no shipped adapter | `PreToolUse` deny | `SessionStart` and `UserPromptSubmit` |
| Gemini CLI | full; hooks fail open | `BeforeTool` deny | `SessionStart` and `BeforeAgent` |
| Cursor IDE agent | full | `preToolUse` deny, with `failClosed: true` | `sessionStart` and `beforeSubmitPrompt` |
| Cursor CLI | degraded | none for edits; shell deny only | `sessionStart` |
| pi | full | `tool_call` block | `session_start` and `before_agent_start` |
| OpenCode | full | `tool.execute.before` throws | `AGENTS.md` and session events |
| Amp | full, no shipped adapter | `tool.call` reject | `agent.start` |
| Aider | instructions only | none | `CONVENTIONS.md` |

Each host reads `AGENTS.md`, so the instructions work before an adapter exists.

## Codex

The repo holds Codex plugin metadata and a Codex marketplace file. To install harness in Codex:

1. Register this repo as a Codex marketplace.
2. Install `harness@harness-marketplace`.
3. Follow [`adapters/codex/README.md`](https://github.com/peekwez/harness/blob/main/adapters/codex/README.md) to install the project hooks in `.codex/hooks.json`.
4. Approve the hooks once with `/hooks` in Codex. Keep this hook-trust check.

The skills alone install no hooks. Without the hooks, Codex gets instructions only.

`${CLAUDE_PLUGIN_ROOT}` is Claude Code syntax. In Codex, find the plugin root from the installed skill path, and pass `--root` with the project path to each engine command.

`harness upgrade --plugin --host codex` updates the plugin, then upgrades the project. Upgrade points each harness command in `.codex/hooks.json` at the vendored adapter. Approve the hooks again after the upgrade.
