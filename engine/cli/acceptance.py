"""The configurable acceptance runner (ADR-002, decision row D-012).

One command decides that a slice's acceptance is green: `acceptance.cmd`
from config with `{paths}` substituted — defaulting to the historical
`<python> -m pytest {paths} -q` so a repo without an `acceptance:` block
runs exactly what it always ran — executed from `acceptance.cwd` with
`acceptance.env` overlaid on the environment. `acceptance.gate_cmd` (e.g.
`make check`) is the repo's own whole-tree gate: it runs ONCE per ceremony,
at close and at merge, and a non-zero exit is the blocking finding
`ACCEPTANCE_GATE_FAILED`.

The close ceremony and `merge-slice` call this module; nothing here knows
about ceremonies, so the same runner decides acceptance, the cumulative
regression suite and the gate.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from engine import HarnessError, load_backlog
from engine.cli.common import _acceptance_python

GATE_RULE_REF = "adr:002"
GATE_REASON = "acceptance gate command failed"
SPAWN_FAILED_RC = 127          # the shell's "command not found"
GATE_CODE = "ACCEPTANCE_GATE_FAILED"


def _acceptance_block(config) -> dict:
    """The `acceptance:` config block, always a mapping.

    Args:
        config: The merged engine config.

    Returns:
        The block, or an empty mapping when the repo declares none.

    Raises:
        HarnessError: If `acceptance` is present but not a mapping.
    """
    block = config.get("acceptance")
    if block is None:
        return {}
    if not isinstance(block, dict):
        raise HarnessError(
            f"config `acceptance` must be a mapping, got {type(block).__name__}"
            f" — see ADR-002 (D-012)")
    return block


def _acceptance_cmd(config, paths, interpreter) -> list[str]:
    """The argv that decides acceptance for the given paths.

    `{paths}` is substituted with the shell-quoted paths and the result
    split with `shlex`; a custom command that never names `{paths}` gets
    them appended, so a bare `uv run pytest -q` still receives its targets.

    Args:
        config: The merged engine config.
        paths: Repo-relative acceptance paths, already glob-expanded.
        interpreter: Python used by the default command.

    Returns:
        The argv list to execute (no shell is involved).
    """
    cmd = _acceptance_block(config).get("cmd")
    paths = [str(p) for p in paths]
    if not cmd:
        return [interpreter, "-m", "pytest", *paths, "-q"]
    if "{paths}" in cmd:
        quoted = " ".join(shlex.quote(p) for p in paths)
        return shlex.split(cmd.replace("{paths}", quoted))
    return [*shlex.split(cmd), *paths]


def _acceptance_cwd(root, config) -> str:
    """The directory acceptance runs from: `root / acceptance.cwd`.

    Args:
        root: Repo root.
        config: The merged engine config.

    Returns:
        The absolute working directory for acceptance and gate commands.

    Raises:
        HarnessError: If `acceptance.cwd` is not a string, is absolute, or
            escapes the repo — the same containment rule `gates.extra`
            applies to code the engine executes.
    """
    raw = _acceptance_block(config).get("cwd", ".")
    if not isinstance(raw, str):
        raise HarnessError(
            f"config `acceptance.cwd` must be a string, got "
            f"{type(raw).__name__} — quote it in harness.yaml")
    path = Path(root) / raw
    resolved = Path(os.path.realpath(path))
    if Path(raw).is_absolute() or not resolved.is_relative_to(
            Path(os.path.realpath(root))):
        raise HarnessError(
            f"config `acceptance.cwd` must be repo-relative and stay inside "
            f"the repo: {raw!r} resolves to {resolved}")
    return str(path)


def _acceptance_env(root, config, base=None) -> dict:
    """`os.environ | acceptance.env`, with the repo root on PYTHONPATH.

    Args:
        root: Repo root.
        config: The merged engine config.
        base: Environment to overlay onto (default: a fresh `os.environ`
            copy with the repo root prepended to PYTHONPATH).

    Returns:
        The environment mapping for the acceptance/gate subprocess.

    Raises:
        HarnessError: If any `acceptance.env` value is not a string — a
            YAML `true`/`3` would crash `subprocess` far from its cause.
    """
    if base is None:
        base = dict(os.environ)
        base["PYTHONPATH"] = str(root) + os.pathsep + base.get("PYTHONPATH", "")
    else:
        base = dict(base)
    extra = _acceptance_block(config).get("env") or {}
    if not isinstance(extra, dict):
        raise HarnessError("config `acceptance.env` must be a mapping of "
                           "string environment values")
    for key, value in extra.items():
        if not isinstance(value, str):
            raise HarnessError(
                f"config `acceptance.env` value for {key!r} must be a string, "
                f"got {type(value).__name__} — quote it in harness.yaml")
        base[str(key)] = value
    return base


def _run(argv, root, config, env=None):
    """Run `argv` under the acceptance cwd/env; returns a CompletedProcess.

    stderr is folded into stdout so evidence tails read in the order the
    command actually printed them. A command that cannot even be SPAWNED
    (missing binary, typo, nonexistent `acceptance.cwd`) comes back as an
    ordinary non-zero result rather than an exception: callers roll merges
    back and raise blocking findings on a red result, and an escaping
    `OSError` would sail past that and leave a merged-but-unvalidated tree.
    """
    cwd = None
    try:
        cwd = _acceptance_cwd(root, config)
        return subprocess.run(argv, cwd=cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=_acceptance_env(root, config, env))
    except OSError as exc:
        return subprocess.CompletedProcess(
            argv, SPAWN_FAILED_RC,
            f"cannot run {shlex.join(str(a) for a in argv)} from "
            f"{cwd or _acceptance_block(config).get('cwd', '.')}: {exc}")


def _expand(root, patterns):
    """(paths, error): glob patterns expanded against the repo root.

    Globs are expanded here rather than by the runner so a pattern matching
    nothing fails loud instead of arriving as a "no tests ran" ambiguity.
    """
    paths = []
    for pat in patterns:
        if "*" in pat:
            matches = sorted(str(p.relative_to(root))
                             for p in Path(root).glob(pat))
            if not matches:
                return None, (f"acceptance pattern {pat!r} matches no files "
                              f"— red-test-first requires at least one")
            paths.extend(matches)
        else:
            paths.append(pat)
    return paths, None


def run_acceptance(root, sl, config):
    """(ok, evidence): the §7.5 precondition, engine-enforced.

    Runs the slice's acceptance command and then — unless
    `gates.regression_at_close` is off — the cumulative regression suite,
    so a slice cannot close green while breaking an earlier slice's tests.

    Args:
        root: Repo root.
        sl: The slice row (its `acceptance` patterns and `id`).
        config: The merged engine config.

    Returns:
        A `(ok, evidence)` pair; evidence is the output tail or the reason.
    """
    runner = config["gates"].get("acceptance_runner", "pytest")
    declared = sl.get("acceptance", [])
    if runner == "none" or not declared:
        return True, "acceptance runner disabled or no acceptance paths"
    paths, error = _expand(root, declared)
    if error:
        return False, error
    interpreter = _acceptance_python(root, config)
    if not _acceptance_block(config).get("cmd") \
            and not Path(interpreter).exists():
        return False, (f"acceptance interpreter {interpreter!r} does not exist "
                       f"(gates.acceptance_python) — fail loud, not skip")
    env = _acceptance_env(root, config)
    proc = _run(_acceptance_cmd(config, paths, interpreter), root, config, env)
    tail = (proc.stdout or "").strip().splitlines()[-5:]
    if proc.returncode != 0:
        return False, "\n".join(tail)
    if config["gates"].get("regression_at_close", True):
        ok, detail = run_regression(root, config, exclude=sl.get("id"),
                                    interpreter=interpreter, env=env)
        if not ok:
            return False, detail
    return True, "\n".join(tail)


def run_regression(root, config, exclude=None, interpreter=None, env=None):
    """(ok, detail): every CLOSED slice's acceptance paths, one run.

    Shared by close (pre-close, in the slice tree) and `merge-slice`
    (post-merge, with rollback) — the merged tree is what ships.

    Args:
        root: Repo root.
        config: The merged engine config.
        exclude: Slice id to leave out (the one being closed).
        interpreter: Python for the default command; discovered if omitted.
        env: Prepared environment; built from config if omitted.

    Returns:
        A `(ok, detail)` pair.
    """
    regression = []
    for s in load_backlog(root):
        if s.get("status") != "closed" or s.get("id") == exclude:
            continue
        for pat in s.get("acceptance", []):
            if "*" in pat:
                regression.extend(sorted(str(p.relative_to(root))
                                         for p in Path(root).glob(pat)))
            elif (Path(root) / pat).exists():
                regression.append(pat)
    regression = sorted(set(regression))
    if not regression:
        return True, "no closed-slice acceptance tests to protect"
    if interpreter is None:
        interpreter = _acceptance_python(root, config)
    proc = _run(_acceptance_cmd(config, regression, interpreter), root, config,
                env)
    if proc.returncode == 0:
        return True, f"regression suite green ({len(regression)} paths)"
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-6:])
    return False, (f"cumulative regression: earlier slices' acceptance tests "
                   f"are now red ({regression}) — this change breaks closed "
                   f"work.\n{tail}")


def run_gate_cmd(root, config):
    """(ok, output_tail): the repo's whole-tree gate, once per ceremony.

    Args:
        root: Repo root.
        config: The merged engine config.

    Returns:
        `(True, "")` when no `acceptance.gate_cmd` is configured, otherwise
        `(exit == 0, last 20 lines of combined stdout/stderr)`.
    """
    cmd = _acceptance_block(config).get("gate_cmd")
    if not cmd:
        return True, ""
    proc = _run(shlex.split(cmd), root, config)
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-20:])
    return proc.returncode == 0, tail


def gate_configured(config) -> bool:
    """Whether the repo declares an `acceptance.gate_cmd` at all.

    Args:
        config: The merged engine config.

    Returns:
        True when a gate command is configured, so a ceremony can report
        `passed` versus `skipped` instead of leaving the reader guessing.
    """
    return bool(_acceptance_block(config).get("gate_cmd"))


def gate_finding(root, config):
    """(finding, tail): the blocking gate finding, or `(None, "")` when green.

    Args:
        root: Repo root.
        config: The merged engine config.

    Returns:
        A `(finding, output_tail)` pair. The finding is a blocking
        `ACCEPTANCE_GATE_FAILED` (rule_ref `adr:002`) when the configured
        gate command exits non-zero — or could not be spawned at all — and
        None otherwise. The tail is returned separately so callers report
        it as `evidence`: the ceremony's `reason` is persisted into
        `parked_reason`, and raw command output does not belong there.
    """
    ok, tail = run_gate_cmd(root, config)
    if ok:
        return None, ""
    from engine.events import make_finding
    cmd = _acceptance_block(config)["gate_cmd"]
    finding = make_finding(
        GATE_CODE, GATE_RULE_REF,
        f"{GATE_REASON}: {cmd!r} (run from "
        f"{_acceptance_block(config).get('cwd', '.')!r}) — fix the tree, not "
        f"the gate.\n{tail}",
        severity="block", layer=0, key=f"{cmd}")
    return finding, tail
