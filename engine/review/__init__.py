"""C7 — Review stack: Layer 0 facts, Layer 1 rubrics, Layer 2 ensemble,
Layer 3 holistic (advisory-only). Reviewer context rule: substrate + diff
only — never builder session memory."""
from .layer0 import assemble  # noqa: F401
from .rubrics import run_review  # noqa: F401
from .golden import replay  # noqa: F401
