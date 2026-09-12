# Legacy G5 override compatibility hotfix

Kente's upgrade from the 0.8.x engine to 0.9.0 exposes seven landed slices
whose justified G5 registry exceptions use the historical `deps:<id>`
spelling. The graph also contains real dependency-manifest exceptions.

1. Reproduce graph, live-G5 and closed-slice verification failures in tests.
2. Share a conservative target normalizer: explicit G5, recorded reason,
   exact known registry ID, and no manifest/file-path ambiguity. Preserve
   gate and slice scope; leave manifest exceptions in their own namespace.
3. Let readers understand legacy aliases. During upgrade append canonical
   records linked to their originals, retaining all historical bytes,
   justifications, finding IDs and commit references. Make migration
   idempotent and visible in dry-run output. Canonicalize new legacy inputs.
4. Test an isolated copy of Kente's substrate and the full Harness suite;
   regenerate shadows and synchronize 0.9.1 package metadata.
5. Publish the hotfix through the previously authorized primary GitHub
   repository and peekwez mirror. Do not modify the active Kente checkout
   or contact buzz. Give the user the Claude Code upgrade commands.

Validation: 797 tests passed in 177 seconds. Harness verify, doctor, all
11 golden replay cases, plugin validation, compilation and diff checks
passed. Independent review found no blocking defects; its audit-hash test
suggestion was added. An isolated Kente clone reproduced exactly seven
UNRECONCILED_SLICE blocks after a 0.9.0 upgrade. Upgrading that clone to
0.9.1 appended 50 canonical aliases and full verify passed with zero blocks.
A second graph migration added zero rows and preserved all original bytes.
