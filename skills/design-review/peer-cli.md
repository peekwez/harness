# Running the other provider

First detect the current host and the other CLI/tool. A configured MCP tool
may be used only if it actually runs the other provider's reasoning in a
fresh, read-only session with documented provider identity. Inspect its tool
contract and invocation result, not just its name. `claude mcp serve` exposes tools, not a Claude
reviewer. Otherwise use the CLI. Missing credentials are an availability
failure; use existing provider/model preferences, never silently switch them.

Read the installed CLI's help before using flags. Create a unique temporary
directory **outside the project**, put the review packet there, and run the
peer from that directory. Supply all required design excerpts through stdin.
Start a fresh process with no `resume`, `continue`, session history or builder
memory. Do not load the project as its working directory. Disable hooks,
extensions, remote tools and delegation for this invocation; an OS filesystem
sandbox alone does not restrict MCP or app side effects. Follow local command
wrappers such as RTK. Do not weaken permissions to make a review run.
If required packet preparation, hashing, execution or result-reading operations
are denied, record unavailable with the reason; never reduce isolation to fit
an allowed command pattern. Host permissions remain authoritative.

Use the host tool's process deadline (default 180 seconds unless the task
has another budget). Poll without blocking user updates; on timeout terminate
that process and its children. One live peer per design. Write stdout,
stderr and final output to distinct, newly created paths; a failed run must
never consume a previous run's result.

## Codex lead → Claude Code peer

From the temporary directory, with `packet.md` containing the complete input
and a copy of this skill's `response.schema.json`:

```sh
claude -p --tools '' --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --disable-slash-commands --settings '{"disableAllHooks":true}' \
  --output-format json --json-schema "$(cat response.schema.json)" \
  --no-session-persistence \
  < packet.md > response.json 2> stderr.log
```

This gives the peer the packet without built-in tools, MCP servers or hooks.
Check exit code **and** the JSON envelope: `type` must be `result`, `is_error`
must be false and `subtype` must be `success`. Validate `structured_output`
against `response.schema.json`; `result` may be empty in structured mode.
`subtype: success` alone is insufficient. Reject API/auth errors,
empty/truncated responses, invalid JSON and purported reviews that never
received the design. A useful response may identify insufficient context;
record that limitation instead of treating silence as approval.

## Claude Code lead → Codex peer

Use `codex exec` for design documents; `codex review` targets code changes.
The following invocation requires a CLI supporting `--ignore-user-config`:

```sh
codex exec --ignore-user-config --ephemeral --sandbox read-only \
  --skip-git-repo-check --disable hooks --disable plugins --disable apps \
  --disable multi_agent --disable memories --disable shell_tool \
  --disable unified_exec --disable browser_use --disable computer_use \
  -c 'web_search="disabled"' --output-schema response.schema.json \
  --output-last-message critique.json - \
  < packet.md > events.log 2> stderr.log
```

Check `codex features list` as well as `exec --help`. Ignoring user config
avoids user MCP definitions; disabling plugins also avoids plugin MCPs. Auth
still uses the existing Codex home. If the user's provider/model depends on
that config, supply their already-selected provider, model and reasoning/effort
settings explicitly for this call or
use a configured isolated reviewer; do not switch providers or copy secrets.
Check for managed extensions too. If equivalent restrictions cannot be
established on the installed version, record unavailable with the reason.
Never permanently edit host config or bypass managed policy.

Check process exit status, stderr/events for failure, and the newly written
nonempty `critique.json`. Parse and validate it against `response.schema.json`;
check that it answers the packet with evidence or a reasoned no-findings
result. Do not treat partial
output from a failed process as a completed review. Record the actual model
if the host reports it; do not guess it from a CLI name.

## Peer instruction to include in the packet

> You are the independent design reviewer; the other host is the lead.
> Review only the supplied requirements and design evidence. Identify
> concrete failure modes, missing constraints and a simpler viable option.
> Return the supplied JSON schema with up to five findings: severity, cited evidence, affected
> requirement, consequence, proposed fix and uncertainty. Distinguish missing
> context from a verified defect; use assessment insufficient-context when
> required inputs are missing. Do not edit, use tools, delegate, invoke a
> reciprocal review or approve on the human's behalf. Return your critique
> directly to the lead.

Command semantics: [Claude CLI reference](https://code.claude.com/docs/en/cli-reference),
[Claude hooks](https://code.claude.com/docs/en/hooks-guide),
[Codex noninteractive mode](https://developers.openai.com/codex/noninteractive),
[Codex configuration](https://developers.openai.com/codex/config-reference).
