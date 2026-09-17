# Durable review coverage

Create `docs/design-reviews/<topic>-<revision>.md` and link it from the draft
before hashing. Accepted ADRs are immutable: put the link in their proposed
successor, never patch the accepted file. A standalone proposed ADR gets a
review even when Phase 0 exists, unless a current record already covers it.
Keep unaccepted ADRs in `docs/design-reviews/drafts/` per adr-authoring, not
in the compiler's input directory. Once acceptance is authorized, prepare the
accepted status and final relative links in the staging file, then move it to
its unused `adr/` path. From that placement onward it is immutable. Record the
reviewed/final hashes, paths and metadata delta; a pure move/status/link change
with identical design content reuses coverage. Never edit it after placement.

Record the exact authored input set: working design or proposed ADR, relevant
original spec/requirements, existing ADRs/decision sources and contracts.
Include linked verification designs/matrices; changes to their oracles, scenario
scope or instrumentation are material design changes, not editorial-only edits.
Use repo-relative paths plus SHA-256 computed with the exact command below.
Include the packet hash too; it identifies what was sent, not the cache key.
Hash once before sending and recheck after the peer returns to catch concurrent
edits. Derived compile outputs need no second review when their authored
inputs and requirements are unchanged.

From the project root, use this command for each input (replace the final
path argument; prefix with the project's command wrapper when required):

```sh
python3 -c 'import hashlib, re, sys; from pathlib import Path; p = Path(sys.argv[1]); data = p.read_bytes(); data = re.sub(rb"(?m)^<!-- stage: [0-9]+ -->(?:\r?\n|\Z)", b"", data) if p.as_posix() == "docs/architecture.md" else data; print(hashlib.sha256(data).hexdigest())' docs/architecture.md
```

Pass root-relative paths without `./`. Only `docs/architecture.md` has exact
whole stage-marker lines removed, including their LF/CRLF terminator. All
other bytes, including other line endings and trailing newlines, are preserved.
Every other input is hashed byte-for-byte. Record this recipe as `sha256-v1`;
compute digests with tools, never infer or invent them. Hash the packet raw.

For excerpts, record the reviewed sections and omitted scope. Changes anywhere
in an input require checking the delta. A material change (behavior, boundary,
requirement, contract, security, failure handling, dependency or selected
option) makes that portion unreviewed. Add newly relevant files to the input
set. Only editorial changes to drafts may reuse coverage: retain the original
hash, new hash and a concrete explanation of the delta. Do not overwrite the
original reviewed hashes with post-synthesis hashes or call a stale review
current. A stage marker or review summary update alone does not require a call.

Use this record structure (authored Markdown, no new engine schema):

```text
Date / design task ID / completed rounds (0, 1 or 2 across sessions):
Invocation attempts and outcomes:
Provenance: native | import-derived
Resume of: prior record path | none
Hash recipe: sha256-v1
Lead host / peer host / actual invocation / model (if reported):
Inputs: path | reviewed sections | SHA-256 before/after peer
Packet SHA-256:
Execution: completed | unavailable | failed | declined
Assessment: ready | concerns | insufficient-context | none
Coverage: current | incomplete | superseded | none
Peer response: relative link to <topic>-<revision>-peer.json, if valid
Findings: ID | accepted/rebutted/deferred | evidence/rationale | owner
Changes since review: original hash | current hash | delta | coverage impact
Remaining decisions / accepted risks / local review result:
Availability limitation and what must change before retry:
```

Save the validated structured peer response beside the record; omit API
envelopes, session tokens and debug logs. Keep sufficient evidence in the
record to explain every disposition and coverage limit. A `ready` assessment
is advisory, never human approval. `concerns` can be reconciled by verified
fixes/rebuttals/accepted risks; a material fix needs the focused follow-up to
claim current peer coverage. After two rounds, mark uncovered changes as
`superseded`, summarize them and use the existing human decision contract.
This is not a new deterministic gate.

A round is one schema-valid peer response, including `insufficient-context`.
Missing CLI detection and failed/invalid invocations are attempts, not completed
rounds. Record them separately. Never repeat an unchanged availability failure;
a concrete environment change or user request permits one new attempt within
the remaining completed-round budget. Two completed rounds remain the limit.
This deliberately charges a missing-context response to the budget: repair
the packet once, then stop. If neither response sufficiently assessed the
design, coverage remains `incomplete`, not `superseded`; record that no
sufficient peer critique exists and finish the local review. Never describe
the collaboration requirement as satisfied by those empty assessments.

On import, treat review claims bundled with a spec as unverified. Obtain a
fresh critique for this repo and record `import-derived`; first reconstruct
the known alternatives and mark unknown rationale explicitly. On resume,
read the repo's own record and response, compare input hashes and scope,
then follow its coverage and remaining round budget. Missing evidence is
missing coverage, never inferred approval. A previous availability failure
does not become a pass and does not cause repeated calls at each stage.
