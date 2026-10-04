# Glossary

One name for each concept. Each line has this form:
`term — definition (not: synonym, synonym)`.

`harness lint-text` and review layer 0 flag each synonym from a `not:` list.
Add a line when a new concept needs a name. Remove a synonym that causes
false findings.

- **slice** — the smallest unit of autonomous work, one row in `.harness/backlog.jsonl` (not: story, ticket)
- **decision row** — one recorded answer to a recurring question, in `.harness/decisions.jsonl` (not: decision entry, rule row)
- **finding** — one result from a gate or a review, with a code, a rule and a fix (not: violation report, issue report)
- **gate** — a deterministic check that runs on an engine event (not: guard check, hook check)
- **override** — a recorded reason to accept one finding (not: waiver, exception record)
- **acknowledgement** — a recorded acceptance of one public interface change (not: drift approval)
- **statement** — one testable sentence with an ID such as `V-orders-3` (not: requirement line, check item)
- **substrate** — the committed harness files under `.harness/` and `adr/` (not: harness state)
- **close** — the ceremony that finishes a slice and records its provenance (not: finalize, wrap-up)
