"""Landing: how a closed slice reaches the base branch (ADR-002 / D-009).

Two modes, one config block:

- `local` (the default, and what every existing repo keeps): `merge-slice`
  merges the slice branch into the checked-out base. Nothing leaves the
  machine.
- `pr`: `close-slice` is the landing. After the ceremony's own substrate
  commit and provenance note it pushes `slice/<id>` to `landing.remote` and
  opens a pull request with `landing.pr_cmd`; `merge-slice` refuses.

The pr command is never run through a shell: it is `shlex.split` once and
each `{base}`/`{branch}`/`{title}`/`{body}` placeholder is replaced inside
its own token, so a title with spaces stays one argument and nothing in a
slice row can inject a second command.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile

from engine import HarnessError, get_slice, load_config, save_slice
from engine.cli.common import _print, _root

# every key a repo may set, with the value it has when unset
LANDING_DEFAULTS = {
    "mode": "local",
    "remote": "origin",
    "base": "main",
    "pr_cmd": ("gh pr create --base {base} --head {branch} "
               "--title {title} --body-file {body}"),
}
LANDING_MODES = ("local", "pr")
LINEAR_URL = "https://linear.app/goodwork-ai/issue/{}"
# the only placeholders pr_cmd may name; anything else is a typo that would
# reach the forge verbatim
PLACEHOLDERS = ("{base}", "{branch}", "{title}", "{body}")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
# hosts a pr-mode sandbox must reach when the remote is a plain name
DEFAULT_FORGE_HOSTS = ("github.com", "api.github.com", "ssh.github.com")
_REMOTE_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^@/]+@)?([^/:]+)")
_REMOTE_SCP = re.compile(r"^[^@/]+@([^:/]+):")

# a credential embedded in a remote URL must never reach a log or a finding
_CREDENTIAL = re.compile(r"(?<=://)[^/\s@]+(?=@)")
_URL = re.compile(r"https?://\S+")


def redact(text: str) -> str:
    """Return `text` with any `scheme://user:secret@host` credential masked.

    Args:
        text: Command output that may quote a remote URL.

    Returns:
        The same text with the userinfo component replaced by `***`.
    """
    return _CREDENTIAL.sub("***", text or "")


def landing_config(config) -> dict:
    """Resolve the `landing` block, defaults filled in.

    Args:
        config: The loaded repo config (or None).

    Returns:
        `{mode, remote, base, pr_cmd}`.

    Raises:
        HarnessError: The block is not a mapping, names an unknown key, has
            a non-string value, or sets an unknown `mode`.
    """
    raw = (config or {}).get("landing")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise HarnessError("landing: expected a mapping of "
                           f"{sorted(LANDING_DEFAULTS)}, got "
                           f"{type(raw).__name__}")
    resolved = dict(LANDING_DEFAULTS)
    for key, value in raw.items():
        if key not in LANDING_DEFAULTS:
            raise HarnessError(
                f"landing.{key} is not a landing setting; known keys are "
                f"{sorted(LANDING_DEFAULTS)}")
        if not isinstance(value, str) or not value.strip():
            raise HarnessError(f"landing.{key} must be a non-empty string")
        resolved[key] = value.strip()
    if resolved["mode"] not in LANDING_MODES:
        raise HarnessError(
            f"landing.mode: {resolved['mode']!r} is not a landing mode; "
            f"expected one of {list(LANDING_MODES)}")
    unknown = [ph for ph in _PLACEHOLDER.findall(resolved["pr_cmd"])
               if ph not in PLACEHOLDERS]
    if unknown:
        raise HarnessError(
            f"landing.pr_cmd names unknown placeholder(s) {unknown}; the "
            f"substituted ones are {list(PLACEHOLDERS)} — anything else "
            f"would reach the forge verbatim")
    return resolved


def forge_hosts(remote: str) -> list:
    """Hosts a pr-mode sandbox must be allowed to reach.

    Args:
        remote: `landing.remote` — a git remote NAME (whose URL the engine
            does not resolve for the sandbox profile) or a URL.

    Returns:
        The host parsed out of a URL remote, else the GitHub defaults.
    """
    match = _REMOTE_URL.match(remote) or _REMOTE_SCP.match(remote)
    return [match.group(1)] if match else list(DEFAULT_FORGE_HOSTS)


def slice_branch(slice_id: str) -> str:
    """The branch a slice is built and landed on."""
    return f"slice/{slice_id}"


def pr_title(sl: dict) -> str:
    """Pull-request title for a slice row: `<linear>: <title> (slice <id>)`.

    Args:
        sl: The backlog row.

    Returns:
        The title, prefixed with the row's `linear` id when it has one.
    """
    linear = (sl.get("linear") or "").strip()
    title = (sl.get("title") or sl["id"]).strip()
    return f"{linear + ': ' if linear else ''}{title} (slice {sl['id']})"


def pr_body(root, sl: dict, note_meta=None) -> str:
    """Pull-request body: what a reviewer needs before opening the diff.

    Args:
        root: Substrate root (unused today; keeps the signature stable for
            richer bodies).
        sl: The backlog row.
        note_meta: `{commit, tree_hash}` of the provenance note, if written.

    Returns:
        Markdown body text.
    """
    meta = note_meta or {}
    lines = [f"Slice `{sl['id']}` — {sl.get('title') or sl['id']}", ""]
    linear = (sl.get("linear") or "").strip()
    if linear:
        lines += [f"Linear: {linear} — {LINEAR_URL.format(linear)}", ""]
    if sl.get("spec"):
        lines += [f"Spec: `{sl['spec']}`", ""]
    lines.append("## Acceptance")
    lines += [f"- `{p}`" for p in sl.get("acceptance", [])] or ["- (none)"]
    lines += ["", "## Declares"]
    lines += [f"- `{d}`" for d in sl.get("declares_dep", [])] or ["- (none)"]
    lines += ["", "## Provenance",
              f"- note commit: `{meta.get('commit') or 'n/a'}`",
              f"- tree hash: `{meta.get('tree_hash') or 'n/a'}`",
              "",
              "Landed by `harness close-slice` (`landing.mode: pr`). The "
              "provenance note is keyed twice — on the commit and in "
              "`.harness/notes.jsonl` by tree hash — so a squash merge keeps "
              "`harness verify` green (ADR-002 / D-010).", ""]
    return "\n".join(lines)


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _tail(proc) -> str:
    text = redact((proc.stderr or proc.stdout or "").strip())
    return "\n".join(text.splitlines()[-8:])


def _require_branch(root, branch: str) -> None:
    """Fail loud unless the slice's own branch is checked out.

    Pushing `slice/<id>` from another tree would publish whatever that ref
    happens to point at — a stale branch, silently, under the closed slice's
    name.

    Args:
        root: The tree the landing runs in.
        branch: The branch the slice must be on.

    Raises:
        HarnessError: HEAD is not `branch`.
    """
    current = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if current != branch:
        raise HarnessError(
            f"landing.mode: pr pushes the slice's own branch, but HEAD in "
            f"{root} is {current!r}, not {branch!r} — run the close (or "
            f"`harness land`) from the slice's worktree so the branch that "
            f"reaches the PR is the work that just closed")


def _commit_landing(root, sl: dict) -> str | None:
    """Commit the landing metadata the close ceremony could not know yet.

    `landed_via`/`pr_url` are written after the ceremony's substrate commit,
    so without this the tree is left dirty and the metadata rides into some
    later slice's commit (W4).

    Args:
        root: Substrate root.
        sl: The backlog row that was just updated.

    Returns:
        The commit sha, or None when there was nothing to commit.
    """
    if not _git(root, "status", "--porcelain", "--", ".harness").stdout.strip():
        return None
    _git(root, "add", "-A", "--", ".harness")
    done = _git(root, "commit", "-q", "-m",
                f"harness: close-slice {sl['id']} landing", "--", ".harness")
    if done.returncode != 0:
        return None
    return _git(root, "rev-parse", "HEAD").stdout.strip() or None


def record_pending(root, sl: dict, error: str) -> None:
    """Persist a closed-but-not-landed slice so it is not lost with the shell.

    Args:
        root: Substrate root.
        sl: The backlog row.
        error: The redacted failure tail.
    """
    sl["landed_via"] = "pending"
    sl["landing_error"] = error[:500]
    save_slice(root, sl)
    _commit_landing(root, sl)


def land_pr(root, sl: dict, config, note_meta=None) -> dict:
    """Push the slice branch and open its pull request.

    The close is already recorded when this runs: a push or pr-command
    failure is reported (and surfaces as a non-zero exit) but never rolls
    the close back — the substrate commit exists, the row records
    `landed_via: pending` with the reason, and `harness land` re-runs it.

    Args:
        root: Substrate root (the slice's tree).
        sl: The backlog row, already flipped to closed.
        config: The loaded repo config.
        note_meta: `{commit, tree_hash}` of the provenance note.

    Returns:
        `{landed, pushed, branch, remote, pr_url, error}`.

    Raises:
        HarnessError: The slice's branch is not checked out.
    """
    landing = landing_config(config)
    branch = slice_branch(sl["id"])
    remote = landing["remote"]
    _require_branch(root, branch)
    out = {"landed": False, "pushed": False, "branch": branch,
           "remote": redact(remote), "pr_url": None}
    push = _git(root, "push", "-u", remote, branch)
    if push.returncode != 0:
        out["error"] = (f"git push {redact(remote)} {branch} failed: "
                        f"{_tail(push)}")
        record_pending(root, sl, out["error"])
        return out
    out["pushed"] = True

    # idempotence: a row that already carries a PR url is being RE-landed
    # (a failed metadata push, a fixed remote) — running pr_cmd again would
    # open a second pull request for the same slice
    if sl.get("pr_url"):
        out.update({"landed": True, "pr_url": sl["pr_url"],
                    "pr_cmd_skipped": True})
        return _finish_landing(root, sl, landing, out)

    body = pr_body(root, sl, note_meta)
    fd, body_path = tempfile.mkstemp(prefix=f"harness-pr-{sl['id']}-",
                                     suffix=".md")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        argv = [tok.replace("{base}", landing["base"])
                   .replace("{branch}", branch)
                   .replace("{title}", pr_title(sl))
                   .replace("{body}", body_path)
                for tok in shlex.split(landing["pr_cmd"])]
        if not argv:
            raise HarnessError("landing.pr_cmd is empty — it must name the "
                               "command that opens the pull request")
        proc = subprocess.run(argv, cwd=str(root), capture_output=True,
                              text=True)
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass
    if proc.returncode != 0:
        out["error"] = (f"landing.pr_cmd ({argv[0]}) exited "
                        f"{proc.returncode}: {_tail(proc)}")
        record_pending(root, sl, out["error"])
        return out
    found = _URL.search(proc.stdout or "")
    out["landed"] = True
    out["pr_url"] = found.group(0) if found else None
    return _finish_landing(root, sl, landing, out)


def _finish_landing(root, sl: dict, landing: dict, out: dict) -> dict:
    """Record the landing on the row, commit it, and push it to the branch.

    The metadata is written after the ceremony's substrate commit, so the
    landing owns committing it (W4) and pushing it — the PR is built from
    that branch, and a row claiming `landed_via: pr` that the branch does not
    carry is a false claim. A failed metadata push therefore fails the
    landing (the row goes `pending`, keeping `pr_url` so a re-land never
    opens a second PR).

    Args:
        root: Substrate root.
        sl: The backlog row.
        landing: Resolved landing config.
        out: The result dict being built.

    Returns:
        `out`, updated.
    """
    sl["landed_via"] = "pr"
    sl.pop("landing_error", None)
    if out.get("pr_url"):
        sl["pr_url"] = out["pr_url"]
    save_slice(root, sl)
    out["landing_commit"] = _commit_landing(root, sl)
    if not out["landing_commit"]:
        return out
    # a second push of the same branch is the same permitted shape (D-011)
    again = _git(root, "push", landing["remote"], slice_branch(sl["id"]))
    out["metadata_pushed"] = again.returncode == 0
    if again.returncode != 0:
        out["landed"] = False
        out["error"] = (f"metadata push failed — the pull request is open "
                        f"({out.get('pr_url') or 'no url captured'}) but its "
                        f"branch does not carry landed_via/pr_url: "
                        f"{_tail(again)}")
        record_pending(root, sl, out["error"])
    return out


def cmd_land(args):
    """`harness land` — (re)run the landing for a slice that closed but did
    not land (`landed_via: pending`). Thin on purpose: the close ceremony is
    not repeated, only the push and the pr command."""
    root = _root(args)
    config = load_config(root)
    landing = landing_config(config)
    if landing["mode"] != "pr":
        raise HarnessError("harness land is the landing.mode: pr command; in "
                           "local mode a closed slice lands with merge-slice")
    sl = get_slice(root, args.slice)
    if sl.get("status") != "closed":
        raise HarnessError(f"slice {args.slice} is {sl.get('status')!r} — land "
                           f"runs after close-slice, not instead of it")
    if sl.get("landed_via") == "pr":
        raise HarnessError(
            f"slice {args.slice} already landed via pr"
            f"{' (' + sl['pr_url'] + ')' if sl.get('pr_url') else ''} — "
            f"re-running would open a second pull request; push the branch "
            f"yourself if the open PR needs updating")
    from engine.graph import notes_log
    rows = notes_log(root, args.slice)
    landed = land_pr(root, sl, config, note_meta=rows[-1] if rows else None)
    _print({"slice": args.slice, **landed})
    return 0 if landed["landed"] else 1
