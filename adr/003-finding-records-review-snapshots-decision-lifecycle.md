---
id: "003"
status: proposed        # proposed | accepted | superseded
domains: [review, decisions, backlog, resolver]
supersedes: []
# Decision rows bind on compile whatever `status` says (the compiler warns
# about this). The rows this ADR proposes therefore live in the Decision
# section below as prose until the ADR is accepted, at which point they move
# here verbatim as D-016 … D-021.
decision_table_rows: []
abstractions: []
api_surface: []
---

# ADR-003: Finding records, review snapshots, decision-row lifecycle, follow-ups and cancellation

## Status

Proposed. Gates Codex Astra items E2, E3 (lifecycle), E4 and E5
(cancellation). Nothing in this ADR binds until it is accepted; the
integrity fixes that needed no rule (E1, E5 split safety, E6, the
adjudication duplicate-id guard) shipped in 0.8.6 without it.

## Context

The Codex Astra review (`docs/handoffs/2026-09-05-codex-astra-harness-enhancements.md`, verified
against engine 0.8.5 at b0befcb) found four places where the engine keeps
a *fragment* of an intervention and later behaves as if it kept the whole:

1. **Findings.** `review --record-finding` persists an edge with code,
   severity, rule ref, confidence and session. The message — the part a
   human acts on — is printed and lost. The close ceremony reduces
   recorded findings by *code*, so a later same-code record with advisory
   severity clears an earlier, unrelated blocker (0.8.2's "blockers clear
   by recording the fix" made this a feature; it is also a hole).
2. **Review verdicts.** A fork verdict edge (ADR-001) names the slice and
   the session, not what was reviewed. Any edit after the pass is
   certified by a receipt that never saw it. A naive HEAD-only check would
   invalidate itself: recording the verdict commits substrate.
3. **Decision rows.** Rows have no lifecycle. ADR supersession retires a
   whole ADR; there is no way to retire one row and keep its siblings, to
   revise a row under a new id with lineage, or to tell an active rule
   from a historical one. `adjudicate` now refuses a duplicate id, but the
   supported revision path it points at is this ADR.
4. **Deferred work.** A revisit condition ("once slice X lands, look at
   cursor fencing again") lives only in prose and memory. Sessions roll
   over, memory compacts, the condition comes true and nothing notices.
5. **Unbuilt work.** The only terminal slice status is `closed`, which
   means "acceptance ran green and provenance was written". Using it to
   get a cancelled slice out of the scheduler would fabricate acceptance;
   deleting the row would erase lineage and dangle `depends_on`.

Each of these is a *policy* choice (what counts as the same finding, when
a verdict is stale, who may retire a rule, what a cancelled dependency
means for dependents), so per the review-rubrics contract it needs an
accepted rule before any gate can block on it.

## Decision (proposed rows)

**D-016 — Finding record contract** (domain: review). Every recorded or
parked finding is an append-only *record* in `.harness/findings.jsonl`
carrying: stable `finding_id` (the existing content key), full `message`,
`rule_ref`, `severity`, `layer`, originating `slice`, reviewer `session`,
optional `evidence` refs (paths, line ranges), the `reviewed` snapshot id
(D-017) and a `created` timestamp. Graph edges continue to index records
but are never the only surviving copy. Legacy edges without a record are
reported as `incomplete` by `doctor --substrate`; the engine never
synthesises a message or a snapshot for them.

**D-017 — Review snapshot and staleness** (domain: review). A review
receipt (fork verdict, close review) names the snapshot it reviewed: the
tree hash of the slice's *source* files (the same `reachable_source_keys`
convention provenance already uses) plus the engine version. A receipt is
**stale** when the current source tree hash differs from the reviewed one.
Substrate-only commits (`.harness/**`, notes, telemetry) do not change the
source tree hash, so recording the receipt cannot invalidate it. A stale
`pass` is treated as no verdict: a security-relevant slice blocks again
(rule_ref adr:001) until a fresh receipt is recorded. The engine verifies
*what* was reviewed; it cannot verify that the reviewer session was
independent — that remains the host boundary ADR-001 names, and the
session label is provenance, not proof.

**D-018 — Resolution by identity, not by code** (domain: review). A
finding is resolved, rebutted, superseded or parked by `finding_id`
(`harness review --resolve <id> --how fixed|rebutted|superseded|parked
--note …`). Resolving one finding never changes the state of another,
however similar their codes. The 0.8.2 behaviour ("a later same-code
record with non-block severity clears the blocker") is retired; the close
ceremony blocks while any *unresolved* block-severity record exists for
the slice. Resolution records keep the rationale; nothing is deleted.

**D-019 — Decision-row lifecycle** (domain: decisions). A row has
`lifecycle: active | superseded | retired` (default `active`; old rows
receive the default on load, never rewritten on disk until touched). A
revision is a **new id** carrying `replaces: <old id>` and a `rationale`;
the old row becomes `superseded` with `replaced_by`. `retired` rows have a
`rationale` and no replacement. Only `active` rows resolve for slices, for
the security-row selector and for the author gate; superseded and retired
rows remain readable for audit and for interpreting historical reviews.
The compiler and the doc-section parser carry these fields through both
authoring paths, reject replacement cycles and dangling `replaces`, and
never resurrect a row an adjudication or a revision superseded.
Adjudication accepts structured `--question/--answer/--security` input and
validates everything before its first write; the three writes (row, edge,
queue removal) are ordered so that a retry after interruption is
idempotent (row present → skip, edge present → skip, queue row absent →
skip).

**D-020 — Follow-up records** (domain: backlog). A follow-up is an
authored row in `.harness/followups.jsonl`: `id`, `owner`, `status: open |
waiting | resolved | declined`, `origin` (finding id, decision id, ADR,
free text), `links` (slice / decision / registry ids), a `revisit`
condition that is either deterministic (`slice:<id> closed`,
`decision:<id> superseded`) or opaque prose displayed verbatim and never
evaluated, and `resolution` evidence. `harness status` lists open and
*triggered* follow-ups (deterministic conditions that are now true); the
resolver surfaces follow-ups linked to a slice's declared deps and nothing
else. Follow-ups are advisory: a triggered one never blocks an unrelated
slice and nothing is auto-implemented. Importing prose deferrals into
records is a per-item human action, never a bulk migration.

**D-021 — Cancellation of unbuilt work** (domain: backlog). A new terminal
slice status `cancelled` (with `cancel_reason`, `cancelled_at`, optional
`superseded_by: <slice id>`) is the only way to remove planned or parked
work from the schedule. `closed` keeps its single meaning. A cancelled
slice's acceptance is not part of the closed-slice suite, its predicted
files are not pending manifest work, and it is never schedulable again.
Cancelling a slice that others depend on requires each dependent to name
a replacement (`--repoint <old> <new>`) or an explicit waiver
(`--waive-dep <old>`) in the same command; the engine refuses otherwise.
Every status consumer (campaign selection, dependency readiness,
close/merge, the closed-slice selector, verify, telemetry, the author
gate) treats `cancelled` as terminal-not-accepted.

**Context that cannot fit** (resolver; recorded here, no separate row):
when *binding* material — the decisions block and the guidance of a
declared dep — does not fit the budget even after degradation, `resolve`
returns `context_satisfied: false` naming what was dropped, `start` and
`slice` refuse to bind, and the fix is to split the slice or raise the
budget. Context-loaded evidence (G2) is recorded only for material
actually delivered. Shadows of one-hop deps and memories remain
best-effort.

## Consequences

Easier: a finding survives the session that produced it; a review receipt
means something specific; a rule can be revised without archaeology;
deferred work resurfaces on its own; cancelled slices stop haunting the
scheduler. Harder: two more substrate files (`findings.jsonl`,
`followups.jsonl`) with merge drivers; a schema version bump (new
required semantics on `status`, new lifecycle field); every consumer of
slice status must be audited before `cancelled` ships; legacy findings
and receipts show as `incomplete` rather than being backfilled.

## Considered alternatives

- **Keep findings in edges and widen the edge.** Rejected: edges are an
  index by design and `merge=union` on a wide edge makes conflicts
  invisible. A record file with the keyed merge driver is the existing
  convention for authoritative rows.
- **HEAD-based staleness.** Rejected: the receipt's own commit moves HEAD.
  Source-tree hashing is already how provenance resolves notes after
  squash merges (ADR-002 / D-010).
- **Revise rows in place (same id, `updated`).** Rejected: a historical
  review cited the old answer; rewriting it under the same id changes what
  that review meant. New id + `replaces` keeps both readable.
- **Delete cancelled slices.** Rejected: lineage and `depends_on` audit.
- **Make follow-ups gates.** Rejected: an obligation inferred from prose
  is exactly the silent policy the review-rubrics contract forbids;
  escalation, if ever wanted, is a separate accepted rule.

## Implementation

Pointers, not plans. Each item is its own declared slice after acceptance:

- E2a (D-016, D-018): `engine/cli/review.py`, `engine/cli/ceremony.py`,
  `engine/schema.py`, `engine/graph.py`, merge drivers, `doctor`.
- E2b (D-017): `engine/graph.py` source-tree keys, `ceremony.py`
  fork-verdict check, `review --record-fork` snapshot capture.
- E3 (D-019): `engine/schema.py`, `engine/compiler.py`,
  `engine/docsections.py`, `engine/resolver.py`, adjudication in
  `engine/cli/review.py`, ADR-001's security selector in `ceremony.py`.
- E4 (D-020): new substrate file, `engine/cli/substrate.py` status,
  resolver relevance, `engine/memory.py` links.
- E5 (D-021): `engine/schema.py` SLICE_STATUS, `engine/cli/author.py`
  cancel command, `engine/cli/run.py`, `engine/cli/acceptance.py`
  selector, `engine/cli/verify.py`, author gate.
- Resolver satisfaction: `engine/resolver.py`, `engine/cli/slice.py`.

Non-goals (intent, not G3 boundaries — nothing here names a path to
forbid): a consumer's package policy, dependency layering, CI path filters
or release process, which stay in that consumer's own gates and decisions;
a second reviewer layer or reviewer auto-fix; bulk migration of prose
deferrals into follow-up records.
