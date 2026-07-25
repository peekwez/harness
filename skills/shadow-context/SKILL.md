---
name: shadow-context
description: How to load module context — shadows, guidance, the supersession rule. Use when reading another module's interface, importing, "what does this module export", "load context", "what's the signature", working with .harness/shadows, resolver output, or before pasting source code into context.
---

# Shadow context

A shadow is the derived interface summary of a module — the `.h` to the
source's `.c`: signatures, docs, imports, exports in a language-neutral
schema, content-hash keyed under `.harness/shadows/`.

Resolution order for any module you need to understand:

1. **Registry entry `built`** -> load the shadow. Never paste source when a
   shadow exists — a shadow diff is the highest-signal review artifact and
   source dumps are what blow context windows.
2. **Registry entry `planned`** -> load its `guidance_refs` (ADR sections).
3. **The supersession rule**: once built, the shadow replaces the guidance
   sections listed in `supersedes_guidance`. Only guidance a signature can't
   express survives alongside — e.g. "never log PII into span attributes".
   Don't reload superseded guidance; it may contradict the built interface.

Freshness: G4 blocks edits when a loaded shadow's hash no longer matches
source. The fix is mechanical: `"${CLAUDE_PLUGIN_ROOT}/bin/harness" extract <path>`, reload, continue.

If you touch a file and its shadow doesn't regenerate (unknown language),
G8 enumerates it — that surface is unenforced, so flag interface changes
there for human review explicitly.
