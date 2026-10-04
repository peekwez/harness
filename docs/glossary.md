# Glossary

harness uses one name for each concept. This page lists the names. `harness lint-text` flags a word from a `not:` list in the docs.

- acceptance suite — the tests that a slice declares. Close needs them green.
- adjudication — a human decision on a parked finding. It writes a decision row or a shared fact.
- ADR — an architecture decision record: one file in `adr/` with one decision, its context and the rejected options.
- author gate — the completeness check that ends architect. A human signs it.
- binding — the link between one session and one slice.
- close — the ceremony that checks the proof of a slice and records it.
- decision card — the format for one big decision: options, trade-offs, effects, undo cost and evidence. (not: option sheet, decision template)
- decision row — one row in `.harness/decisions.jsonl` that answers one recurring question. (not: rule row, decision entry)
- drift acknowledgement — a recorded edge that accepts a public interface change that G6 found. (not: drift approval, drift waiver)
- event — one of the five engine events, such as `pre_change`.
- explore — the first design step: a toy, decision cards and statements, then a human freeze. (not: spike, discovery phase)
- finding — one result from a gate or a reviewer: code, severity, rule reference, message and fix. (not: violation, lint error)
- gate — a deterministic check in the engine that runs on an event and returns findings. (not: policy check, enforcer)
- injection — the text that the resolver adds to the agent context for a bound slice.
- kills text — the `kills:` text of a test link. It names the bug that the test must catch. (not: mutant spec)
- landing — how a closed slice reaches the base branch: a local merge or a pull request.
- non-goal — a design boundary that a slice must not cross. It blocks only when a gate cites it. (not: anti-goal, out-of-scope rule)
- override — a recorded edge with a justification that lets one finding pass. (not: waiver)
- park — to move an uncertain finding to the adjudication queue.
- permit — the engine answer to a host question: may this tool call run without a prompt?
- red record — the file that proves the acceptance suite of a slice failed at slice start. (not: red proof, failing baseline)
- regression suite — the acceptance suites of all closed slices, run again at close and at merge.
- rule reference — the `rule_ref` of a finding: the gate, decision row or ADR that it cites.
- shadow — the cached interface summary of one source file: symbols, imports and exports. (not: interface file, signature dump)
- shared memory — facts in `.claude/memory/shared/` that a human promoted for the team. (not: durable memory, team memory)
- slice — the smallest unit of autonomous work: one goal, its tests, its declared dependencies and predicted files. (not: ticket, user story)
- statement — one claim about a feature that a test must prove, with an id such as `V-orders-3`. (not: verify item, spec line)
- STE-80 — the writing rules of harness: short sentences, one action per step, active voice, one name per concept.
- substrate — the harness files committed in a repo: `.harness/`, `adr/`, `AGENTS.md`, the CI workflow and git notes. (not: harness state, metadata store)
- toy — quick code in `explore/` that tests an idea. It never becomes production code. (not: throwaway prototype)
- verdict — the engine answer to an event: allow or block, with findings.
