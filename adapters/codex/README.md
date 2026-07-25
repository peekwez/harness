# harness × OpenAI Codex CLI

1. Copy `hooks.json` into `<repo>/.codex/hooks.json` (or merge into
   `~/.codex/hooks.json`), replacing `${HARNESS_DIR}` with the absolute path
   of your harness checkout — Codex hook commands don't expand custom env
   vars, so inline the real path.
2. Approve the hooks once via `/hooks` in the Codex TUI (hash-pinned trust);
   enterprise setups can pre-trust via `requirements.toml`.
3. `export HARNESS_SLICE=<slice-id>` (or run `harness slice --slice <id>
   --session <session>`) to bind the active slice.
4. Codex reads `AGENTS.md` natively — `/harness:init`'s scaffold covers the
   instruction layer with zero extra setup.

Enforcement notes: PreToolUse intercepts `apply_patch`, shell, and MCP
calls, but OpenAI documents it as a guardrail, not a complete boundary
(streaming `unified_exec` paths are not yet intercepted). Keep
`harness verify` in CI as the fail-closed backstop.

**Autonomy (prompt-free slice loop):** merge `autonomy.toml` into
`~/.codex/config.toml` (`approval_policy = "never"` + workspace-write
sandbox, network off) and install `no-push.rules` to `~/.codex/rules/` —
a Starlark `prefix_rule` marking `git push`/`git remote` forbidden even if
network access is later enabled. Prompts aren't the guardrail; the hook is.
