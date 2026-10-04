"""STEPS keep workstream order whatever module is imported first."""
import subprocess
import sys

from conftest import PLUGIN_ROOT


def test_importing_a_step_module_first_keeps_workstream_order():
    code = ("import engine.upgrade_w3\n"
            "from engine.upgrade_010 import STEPS\n"
            "print(' '.join(s.id.split('.')[0] for s in STEPS))\n")
    out = subprocess.run([sys.executable, "-c", code], cwd=PLUGIN_ROOT,
                         capture_output=True, text=True, check=True).stdout
    heads = out.split()
    assert heads == sorted(heads, key=lambda h: int(h[1:])), heads
