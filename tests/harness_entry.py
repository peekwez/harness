"""Test-only entry point: `bin/harness` with the approval store in a temp
file, so no test reads or writes the real `~/.config/harness/`.

The engine has no flag or env var for the store; this file sets the
in-process override that tests use. It refuses to run without one.
"""
import os
import runpy
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from engine import approvals  # noqa: E402

store = os.environ.get("HARNESS_TEST_APPROVALS")
if not store:
    sys.exit("tests/harness_entry.py: set HARNESS_TEST_APPROVALS")
approvals._STORE_OVERRIDE = Path(store)
sys.argv[0] = str(PLUGIN_ROOT / "bin" / "harness")
runpy.run_path(sys.argv[0], run_name="__main__")
