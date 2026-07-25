# Stage 2 — Red-team protocol

Hand the working document to the red-team agent (`agents/red-team.md`
persona; use a forked session where supported so the builder context stays
clean).

The red-team hunts: unstated assumptions, scale cliffs, security holes,
silent-failure modes (the md-file-bug class: anything that no-ops instead of
erroring when an artifact is missing — see the premortem skill's checklist).

Binding rule: **every risk raised must resolve into either a decision or an
explicit `[accepted-risk]` block** in the working document. Accepted risks
become graph nodes at compile time; silently dropped risks are a defect.

Exit criteria: red-team pass complete, zero unresolved risks. Mark
`<!-- stage: 3 -->`.
