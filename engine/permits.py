"""Permission policy: the gates ARE the approval layer.

Approval prompts were never the enforcement layer in a harness repo — the
pre-change gates and CI verify are. So inside a bound slice the engine
answers the host's permission question itself: work that the gates would
allow is auto-approved, and nothing else is. Policy lives here (engine),
never in the adapters, which only translate.

Two surfaces:
- `paths_in_scope` — file work inside the slice's declared/predicted set.
- `command_allowed` — the slice loop's command surface (harness, tests,
  local git). Egress (push/remote/fetch/clone) is never auto-approved, and
  neither is anything unrecognized: those fall through to the human. The one
  exception is `landing.mode: pr` (ADR-002 / D-011), where the slice cannot
  finish without pushing its own branch and opening a PR: exactly
  `git push [-u] <landing.remote> slice/<bound-id>`, `git fetch
  <landing.remote>` and `gh pr create|view|checks|status` are auto-approved,
  and nothing else that talks to a remote.
"""
from __future__ import annotations

import re
import shlex
from fnmatch import fnmatch

from .gates.g3_scope import SUBSTRATE_PREFIXES

# git subcommands that stay on this machine
GIT_LOCAL = {
    "status", "diff", "log", "show", "add", "commit", "rev-parse", "notes",
    "worktree", "checkout", "switch", "branch", "merge", "stash", "cat-file",
    "ls-files", "config", "restore", "reset", "rm", "mv", "tag", "apply",
    "cherry-pick", "rebase", "describe", "blame", "grep", "init",
}
# never auto-approved: anything that talks to a remote
GIT_EGRESS = {"push", "remote", "clone", "fetch", "pull", "submodule",
              "request-pull", "send-email"}

# D-011: the egress a pr-mode slice needs to land itself, and no more.
GH_PR_SUBCOMMANDS = ("create", "view", "checks", "status")
PUSH_FLAGS = ("-u", "--set-upstream")
# the only fetch flags that cannot redirect the transport or write a ref
FETCH_FLAGS = ("--prune", "--tags")
# `gh pr` must stay pointed at THIS repo and this terminal: --repo/-R retarget
# it at any repository the token can reach, --web opens a browser
GH_REJECTED = ("--repo", "-R", "--web", "-w")

TEST_RUNNERS = ("pytest", "python -m pytest", "python3 -m pytest",
                ".venv/bin/pytest", ".venv/bin/python -m pytest",
                "make test", "make verify", "make replay")

# splitting on shell operators: EVERY segment must be allowed, mirroring how
# hosts evaluate chained commands
_SPLIT = re.compile(r"&&|\|\||[;\n|]")
# command substitution can hide anything — never auto-approve a command
# carrying it (this is also why the skills use `--commit HEAD`)
_SUBSTITUTION = re.compile(r"\$\(|`|<\(")


def _pr_egress_allowed(parts: list, landing: dict, slice_id: str) -> bool:
    """True for the exact egress a bound slice needs in pr mode (D-011).

    Args:
        parts: The already-split command tokens.
        landing: Resolved landing config.
        slice_id: The slice bound to this session.

    Returns:
        Whether this command is one of the four auto-approved shapes.
    """
    if landing.get("mode") != "pr" or not slice_id:
        return False
    head = _program(parts)
    branch = f"slice/{slice_id}"
    sub, idx, global_opts = (git_subcommand(parts) if head == "git"
                             else (None, -1, False))
    if global_opts:
        # `git -C /elsewhere push origin slice/x` pushes another repo's
        # branch of that name: the allowed shapes are the plain ones only
        return False
    if head == "git" and sub == "push":
        rest = parts[idx + 1:]
        if rest and rest[0] in PUSH_FLAGS:
            rest = rest[1:]
        # exactly `<remote> <branch>`: an extra flag (--force, --delete) or a
        # second refspec is a different operation and stays with the human
        return rest == [landing["remote"], branch] or \
            rest == [landing["remote"], f"HEAD:{branch}"]
    if head == "git" and sub == "fetch":
        rest = parts[idx + 1:]
        if rest[:1] != [landing["remote"]]:
            return False
        # `--upload-pack=<cmd>` executes a command (locally, and server-side
        # on an ssh remote) and a refspec (`main:main`, `+refs/*:refs/*`)
        # writes local refs: the remote, and at most a harmless flag, is all
        return all(f in FETCH_FLAGS for f in rest[1:])
    if head == "gh" and parts[1:2] == ["pr"]:
        if not (len(parts) > 2 and parts[2] in GH_PR_SUBCOMMANDS):
            return False
        # attached forms count too: `-Rowner/repo`, `--repo=owner/repo`
        return not any(tok == flag or tok.startswith(flag + "=")
                       or (flag.startswith("-") and not flag.startswith("--")
                           and tok.startswith(flag))
                       for tok in parts[3:] for flag in GH_REJECTED)
    return False


def _segment_allowed(seg: str, harness_bin: str | None, landing=None,
                     slice_id=None) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    try:
        parts = shlex.split(seg)
    except ValueError:
        return False          # unbalanced quotes: not something to auto-approve
    if not parts:
        return True
    head = parts[0]
    if head in ("cd", "true", "echo", "ls", "pwd"):
        return True
    base = head.rsplit("/", 1)[-1]
    if base == "harness" or (harness_bin and head.strip('"\'') == harness_bin):
        return True
    if base in ("python", "python3") and parts[1:3] == ["-m", "pytest"]:
        return True
    if base in ("pytest",):
        return True
    if base == "make" and len(parts) > 1 and parts[1] in ("test", "verify", "replay"):
        return True
    if landing and _pr_egress_allowed(parts, landing, slice_id):
        return True
    if base == "git":
        sub = next((p for p in parts[1:] if not p.startswith("-")), None)
        return sub in GIT_LOCAL and sub not in GIT_EGRESS
    return any(seg.startswith(pfx) for pfx in TEST_RUNNERS)


# --------------------------------------------------------------- classifier
# Egress classification decides whether a refusal becomes a DENY, so it must
# see through every spelling of the same command: `git -C . push`,
# `GIT_DIR=x git push`, `/usr/bin/git push`, `bash -c "git push"`,
# `timeout 5 git push`. Unrecognised or unparseable shapes fail CLOSED.
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git global options that consume the NEXT token
GIT_OPT_WITH_ARG = ("-C", "-c", "--git-dir", "--work-tree", "--exec-path",
                    "--namespace", "--super-prefix")
# remote-talking git subcommands beyond the push/fetch family
GIT_REMOTE_EXTRA = {"ls-remote", "archive"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
# programs that run another command; the real head is somewhere after them
WRAPPERS = {"env", "nohup", "timeout", "time", "nice", "command", "exec",
            "sudo", "doas", "script", "caffeinate", "xargs", "eval",
            "stdbuf", "setsid"}
_MAX_NESTING = 5


def _strip_env(parts: list) -> list:
    """Drop leading `NAME=value` assignments (`GIT_DIR=x git push …`)."""
    i = 0
    while i < len(parts) and _ENV_ASSIGN.match(parts[i]):
        i += 1
    return parts[i:]


def _program(parts: list) -> str:
    """The program a segment runs, by basename (`/usr/bin/git` -> `git`)."""
    return parts[0].rsplit("/", 1)[-1].strip("\"'") if parts else ""


def git_subcommand(parts: list) -> tuple:
    """Split a `git` invocation into its global options and subcommand.

    The subcommand is the first token that neither starts with `-` nor is the
    argument of an option that takes one — so `git -C /x -c a=b push` is a
    push, however it is spelled.

    Args:
        parts: Tokens of one segment, env assignments already stripped.

    Returns:
        `(subcommand or None, index or -1, saw_global_option)`.
    """
    i, saw = 1, False
    while i < len(parts):
        tok = parts[i]
        if tok in GIT_OPT_WITH_ARG:
            i, saw = i + 2, True
            continue
        if tok.startswith("--") and tok.split("=", 1)[0] in GIT_OPT_WITH_ARG:
            i, saw = i + 1, True
            continue
        if tok.startswith("-"):
            i, saw = i + 1, True
            continue
        return tok, i, saw
    return None, -1, saw


# long shell options that may precede `-c`: the first set takes no argument,
# the second consumes the next token. Anything else long is unknown to us.
SHELL_LONG_FLAGS = {"--norc", "--noprofile", "--login", "--posix", "--noediting",
                    "--restricted", "--verbose", "--debugger", "--dump-strings",
                    "--dump-po-strings", "--help", "--version"}
SHELL_LONG_WITH_ARG = {"--rcfile", "--init-file"}
# short letters that take no argument (bash/sh `set` flags plus -i -l -r -s -D);
# `-o optname` and `-O shopt` each consume the NEXT token, wherever they sit
# in a cluster (`-co pipefail X` and `-oc pipefail X` both run X)
SHELL_SHORT_FLAGS = set("abefhkmnptuvxBCEHPTilrsDc")
SHELL_SHORT_WITH_ARG = set("oO")


def _shell_script(args: list):
    """The `-c` script of a shell invocation, or None when there is none.

    None is the fail-closed sentinel: a script FILE, an interactive shell, a
    `-c` with no script, or an unknown long option are all opaque to us.
    Only SHORT clusters (`-c`, `-lc`, `-xc`) carry `-c` — long options such
    as `--norc` contain the letter but are not it.
    """
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            return None
        if tok in SHELL_LONG_FLAGS:
            i += 1
            continue
        if tok in SHELL_LONG_WITH_ARG:
            i += 2
            continue
        if tok.startswith("--"):
            return None                   # unknown long option: opaque
        if tok.startswith("-"):
            cluster = tok[1:]
            if not all(ch in SHELL_SHORT_FLAGS or ch in SHELL_SHORT_WITH_ARG
                       for ch in cluster):
                return None               # unknown short letter: opaque
            # each -o/-O in the cluster eats one following token
            i += 1 + sum(ch in SHELL_SHORT_WITH_ARG for ch in cluster)
            if "c" in cluster:
                return args[i] if i < len(args) else None
            continue
        return None
    return None


def _wrapper_egress(args: list, depth: int) -> bool:
    """Classify what a wrapper (`env`, `timeout`, `xargs`, `eval`, …) runs.

    The wrapped program can sit behind flags and their arguments, or inside a
    single quoted token (`eval "git push"`), so both are tried.
    """
    for i, tok in enumerate(args):
        base = tok.rsplit("/", 1)[-1]
        if base in ("git", "gh") or base in SHELLS or base in WRAPPERS:
            return _segment_egress(args[i:], depth + 1)
        if any(ch.isspace() for ch in tok) and _text_egress(tok, depth + 1):
            return True
    return False


def _segment_egress(parts: list, depth: int = 0) -> bool:
    """Whether one already-split command segment talks to a remote."""
    if depth > _MAX_NESTING:
        return True                       # nesting this deep is not a slice loop
    parts = _strip_env(parts)
    if not parts:
        return False
    base = _program(parts)
    if base in SHELLS:
        script = _shell_script(parts[1:])
        # a script FILE (or a bare shell) hides its commands from every check
        # here — in pr mode that is exactly the hole, so it fails closed
        return True if script is None else _text_egress(script, depth + 1)
    if base in WRAPPERS:
        return _wrapper_egress(parts[1:], depth)
    if base == "gh":
        return True
    if base == "git":
        sub, _idx, _opts = git_subcommand(parts)
        if sub in GIT_EGRESS or sub in GIT_REMOTE_EXTRA:
            # `git archive` only reaches a remote with --remote
            if sub != "archive":
                return True
            return any(tok.split("=", 1)[0] == "--remote" for tok in parts)
    return False


def _text_egress(command: str, depth: int = 0) -> bool:
    for seg in _SPLIT.split(command or ""):
        seg = seg.strip()
        if not seg:
            continue
        try:
            parts = shlex.split(seg)
        except ValueError:
            return True          # unparseable: treat as the dangerous case
        if _segment_egress(parts, depth):
            return True
    return False


def is_egress(command: str) -> bool:
    """True when any segment of the command talks to a remote.

    The permit layer only auto-approves; for these commands a refusal has to
    become an actual DENY (D-011), because no host permission rule can
    express "this slice's own branch" — a prefix rule that opens
    `git push origin slice/` also opens `slice/x:main` — and a sandboxed
    host auto-runs whatever the harness leaves silent.

    Args:
        command: The command line the host is asking about.

    Returns:
        Whether it is egress-shaped. Unknown/opaque shapes count as egress.
    """
    return _text_egress(command, 0)


def command_decision(command: str, harness_bin: str | None = None,
                     config=None, slice_id=None) -> tuple:
    """The host-facing verdict: `allow`, `deny` or `defer`.

    `allow` and `defer` are the historical answers (auto-approve, or leave it
    to the human). `deny` exists only for `landing.mode: pr`, where the
    profile has to drop its blanket `git push`/`git fetch` denies so the
    slice can land itself: there, an egress command the permit refuses is
    denied outright rather than handed to a coarse prefix rule.

    Args:
        command: The command line.
        harness_bin: Absolute path of the engine binary, when known.
        config: The loaded repo config (supplies `landing`).
        slice_id: The slice bound to this session.

    Returns:
        `(decision, allow, reason)`.
    """
    from engine.cli.landing import landing_config
    allow, reason = command_allowed(command, harness_bin, config, slice_id)
    if allow:
        return "allow", True, reason
    if landing_config(config)["mode"] == "pr" and is_egress(command):
        return "deny", False, (
            "landing.mode: pr auto-approves only `git push [-u] <remote> "
            "slice/<bound-slice>`, `git fetch <remote>` and `gh pr "
            "create|view|checks|status` (ADR-002 / D-011) — this command is "
            f"outside that surface: {reason}")
    return "defer", False, reason


def command_allowed(command: str, harness_bin: str | None = None,
                    config=None, slice_id=None) -> tuple:
    """Would the harness auto-approve this command?

    Conservative by construction: unknown commands are NOT denied here —
    they simply are not auto-approved, so the host's normal permission flow
    (and the user) decides.

    Args:
        command: The command line the host is asking about.
        harness_bin: Absolute path of the engine binary, when known.
        config: The loaded repo config; supplies `landing` (D-011). Omitted
            (or `landing.mode: local`) keeps the historical surface, with no
            egress at all.
        slice_id: The slice bound to this session — pr-mode egress is scoped
            to that slice's own branch.

    Returns:
        `(allow, reason)`.
    """
    if not command or not command.strip():
        return False, "empty command"
    if _SUBSTITUTION.search(command):
        return False, ("command substitution is never auto-approved — use "
                       "plain commands (e.g. `--commit HEAD`)")
    from engine.cli.landing import landing_config
    landing = landing_config(config)
    segments = _SPLIT.split(command)
    for seg in segments:
        if not _segment_allowed(seg, harness_bin, landing, slice_id):
            return False, f"segment not in the slice loop's command surface: {seg.strip()!r}"
    return True, "slice loop command surface"


def declared_set(slice_row: dict, registry: list) -> set:
    declared = set(slice_row.get("predicted_files", []))
    declared.update(slice_row.get("acceptance", []))
    by_id = {e["id"]: e for e in registry}
    for did in slice_row.get("declares_dep", []):
        entry = by_id.get(did)
        if entry and entry.get("source"):
            declared.add(entry["source"])
    return declared


def paths_in_scope(slice_row: dict, registry: list, rels) -> bool:
    """True when every path is substrate or inside the slice's declaration.
    Wandering keeps its prompt — auto-approval is scoped to what the slice
    said it would touch, which is exactly what G3 reconciles at close."""
    declared = declared_set(slice_row, registry)
    globs = [d for d in declared if "*" in d]
    for rel in rels:
        if rel.startswith(SUBSTRATE_PREFIXES):
            continue
        if rel in declared or any(fnmatch(rel, g) for g in globs):
            continue
        return False
    return True
