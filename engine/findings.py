"""Finding catalog and message helpers (spec 9.2).

A finding message says what is wrong and names the file, in 25 words or
fewer. The `fix` field holds the command or action. `CATALOG` holds the
longer explanation that `harness gates explain <CODE>` prints.
"""
from __future__ import annotations

MAX_MESSAGE_WORDS = 25

CATALOG: dict[str, str] = {
    "RED_RECORD_MISSING": (
        "Close needs proof that the slice's tests failed before the code "
        "existed. The red record in .harness/verification/<slice>.json is "
        "missing, unreadable, or shows a runner error instead of a failing "
        "suite. Bind the slice again to run the suite and record red."),
    "GREEN_AT_START": (
        "The slice's acceptance suite passed when the slice was bound, "
        "before any code was written. Such tests prove nothing about the "
        "new behaviour. Make the tests fail for the missing behaviour and "
        "bind again. For a pure refactor, record an override with a reason "
        "on target verification:green-at-start."),
    "UNKNOWN_STATEMENT": (
        "The slice row lists a statement ID in verifies that is not in "
        ".harness/verify.jsonl. The statement was renamed or removed. Run "
        "harness compile, then fix the slice's verifies list."),
    "STATEMENT_UNTESTED": (
        "A statement the slice owns has no test with a verifies: comment. "
        "Only tests in the slice's acceptance paths, or in a closed slice's "
        "acceptance paths, count, because only those run at close. Add the "
        "comment above the test that proves the statement."),
    "KILLS_MISSING": (
        "A verifies: comment has no kills: text. kills: names the bug the "
        "test must catch. It is the mutant record. Write it on the same "
        "line, or on the next comment line."),
    "NO_RED_RECORD": (
        "The bound slice has no red record, and the edit is to a file that "
        "is not a test. Harness records red when you bind the slice: it "
        "runs the acceptance suite once and expects it to fail. Bind the "
        "slice before you write code. This is advisory. Close blocks later "
        "if the record is still missing."),
    "ACCEPTANCE_GATE_FAILED": (
        "The acceptance gate command exited non-zero, or it did not start. "
        "Close and merge stop until it passes. Fix the code or the "
        "environment, not the gate command."),
    "CONTEXT_OVER_CAP": (
        "The slice context did not fit in 9,000 characters. Harness cut the "
        "lowest-priority blocks and left a one-line pointer for each. Split "
        "the slice, or shorten its cited decision rows."),
    "DUPLICATE_CANDIDATE": (
        "G5 found a new public interface that is very similar to an existing "
        "registry entry. This often means copied code. Reuse the entry, or "
        "record an override with a reason."),
    "EXPLORE_IMPORT": (
        "G9 explore-isolation. A production file imports code from "
        "explore/. explore/ holds the toy: fast, untested, and free to "
        "change, so production code must not depend on it. Copy the code "
        "you need into a production module, test it there, and import that "
        "module. G9 reads Python imports from the shadow, and Rust, "
        "TypeScript, JavaScript and Go imports from the source. "
        "Tests and other gates.exempt_paths are not checked. G9 is active "
        "when explore/DECISIONS.md exists. Not checked: dynamic imports "
        "such as import(`..${x}`) or importlib.import_module. A bare "
        "npm package named explore is flagged."),
    "EXTRA_GATE_LOAD_ERROR": (
        "A gate under gates.extra in .harness/config.yaml did not load. "
        "Harness blocks, because a broken gate must never pass in silence. "
        "Fix the gate file, or remove the entry."),
    "EXTRA_GATE_RUN_ERROR": (
        "A gate under gates.extra raised an error or returned bad findings. "
        "The finding names the last traceback frame. Fix the run function "
        "of the gate."),
    "HASH_MISMATCH": (
        "The source file of a built registry entry changed, but the recorded "
        "source_hash did not. Run harness registry refresh with the entry "
        "id."),
    "INCOMPLETE_GRAPH_PROVENANCE": (
        "A closed slice is missing graph evidence that close records, such "
        "as touch provenance or a dependency snapshot. Restore the evidence "
        "from git history."),
    "INTERFACE_DRIFT": (
        "G6 found that the public interface of a module changed since the "
        "slice started. Each interface change needs an acknowledgement. Run "
        "harness gates ack-drift."),
    "LANDING_MODE_PR": (
        "The landing mode is pr, so a slice lands through a pull request. A "
        "local merge can bypass a protected base branch. Open or merge the "
        "pull request."),
    "LANDING_PENDING": (
        "A closed slice has no finished landing. The push or the pull "
        "request did not complete. Run harness land from the worktree of "
        "the slice."),
    "LEGACY_GRAPH_PROVENANCE": (
        "A closed slice is older than complete graph evidence. Upgrade "
        "recovered the facts that it could. Harness cannot infer the old "
        "imports and decisions. No action is needed."),
    "MANIFEST_INCOMPLETE": (
        "G1 found that a required file is missing. It can be a substrate "
        "file, a manifest path, a guidance reference or an acceptance test. "
        "Create the file that the message names."),
    "GLOSSARY_SYNONYM": (
        "Review layer 0 found added markdown text that uses a banned "
        "synonym of a glossary term. This finding is advisory. Use the "
        "glossary term, or edit the glossary."),
    "MISSING_DEPENDENCY": (
        "The tree-sitter stack is not installed. Harness writes empty "
        "shadows, so interface checks for that language are off. Install "
        "the packages that the fix names."),
    "MISSING_DRIFT_BASELINE": (
        "G6 has no interface baseline for the slice, so it cannot find "
        "drift. Bind the slice before you change code."),
    "MISSING_PROVENANCE_NOTE": (
        "A closed slice has no git note and no tree-hash key in "
        ".harness/notes.jsonl. Provenance must travel with the repo. Write "
        "the note with harness graph note."),
    "NON_GOAL_VIOLATION": (
        "G3 found a change in a path that a non-goal excludes. It blocks "
        "only when a gate cites the non-goal. Move the change, or record an "
        "override with a reason."),
    "ORPHANED_NOTE": (
        "A harness git note is on a commit that no branch reaches. No notes "
        "row matches its tree. Attach the note again with harness graph "
        "note --repoint."),
    "R-decisions": (
        "Review rubric: the diff breaks a decision row in scope. The "
        "evidence names the row. Change the code to follow the row, or park "
        "the question."),
    "R-dup": (
        "Review rubric: G5 duplicate candidates are not resolved. Reuse the "
        "existing entry, or record an override with a reason."),
    "R-gates": (
        "Review rubric: a Layer-0 gate still blocks. Fix each blocking gate "
        "finding first."),
    "R-holistic": (
        "Review rubric, layer 3: a proposal for a new decision row, ADR or "
        "gate. It never blocks. A human decides to adopt it or not."),
    "R-uses": (
        "Review rubric: the slice uses registry entries that it does not "
        "declare. Add them to declares_dep, or record an override with a "
        "reason."),
    "REVIEW_FINDING": (
        "The reviewer agent recorded this finding with harness review "
        "--record-finding. It blocks only with block severity and a "
        "rule_ref."),
    "REVIEW_UNCERTAIN": (
        "A review rubric was uncertain on a question that would block. "
        "Harness parks the finding for a human. Resolve it with harness "
        "adjudicate."),
    "SCHEMA_INVALID": (
        "A substrate row does not match its schema. The message names the "
        "file, the row and the field. Fix that field, then run harness "
        "verify."),
    "SCHEMA_MISMATCH": (
        "The substrate schema version does not match the engine, or a "
        "substrate file cannot be read. Run harness upgrade, or repair the "
        "named file."),
    "SECRET_IN_DIFF": (
        "Review layer 0 found an added line that matches a secret pattern. "
        "The finding never repeats the secret. Remove it, or record a "
        "false-positive override."),
    "SHARED_MEMORY_WRITE": (
        "G10 blocks an agent write to shared memory. Only a human may "
        "promote personal notes into shared memory. Ask a human to run "
        "harness memory promote with the file."),
    "UNDECLARED_FILE": (
        "G3 found a change to a file outside the predicted files of the "
        "slice. This finding is advisory. Record the reason with "
        "`harness gates override --target file:<path>`. When the file "
        "changes the slice scope, stop and tell the human."),
    "UNDECLARED_USE": (
        "G5 found an import of a registry entry that the slice does not "
        "declare. Close requires each use to be declared or overridden."),
    "UNKNOWN_LANGUAGE": (
        "Harness has no extractor for this file type, or the language is "
        "off in config. The file gets an empty shadow, so harness does not "
        "check its interface."),
    "UNRECONCILED_SLICE": (
        "A closed slice uses registry entries that it never declared and "
        "that no override covers. Declare them on the slice, or record an "
        "override."),
    "UNKNOWN_TEST_LINK": (
        "A test comment says verifies: with an ID that is not in "
        ".harness/verify.jsonl. A typo breaks the link, so no statement "
        "gets credit for the test. Fix the ID, or add the statement to "
        "explore/VERIFY.md or the verification matrix and run harness "
        "compile."),
    "UNSHADOWED_FILE": (
        "The file is outside the repo root, so harness does not shadow or "
        "check it."),
}


def clip_words(text: str, limit: int = MAX_MESSAGE_WORDS) -> str:
    """The first `limit` words of `text`; a trailing `…` marks a cut.

    Use it for dynamic text in a message, such as an exception string.
    The result never has more than `limit` words.
    """
    words = str(text).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "…"


def explain(code: str) -> str | None:
    """`CODE\\n\\n<entry>` for `code`, matched without regard to case."""
    by_upper = {k.upper(): k for k in CATALOG}
    key = by_upper.get(code.strip().upper())
    return f"{key}\n\n{CATALOG[key]}" if key else None
