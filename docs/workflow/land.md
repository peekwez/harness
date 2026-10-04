# Land

Land moves a closed slice onto the base branch. The `landing:` block in `.harness/config.yaml` picks one of two modes: `local` or `pr`.

## Local mode

Local mode is the default. Nothing leaves the machine. Run this from the main tree, not from the slice worktree:

```bash
harness merge-slice --slice orders-1
```

`harness merge-slice` does these things:

1. It checks that the slice is closed on `slice/<id>`, and that your tracked files and index are clean.
2. It merges `slice/<id>` into the checked-out branch.
3. It runs the acceptance suite of every closed slice on the merged tree, then `acceptance.gate_cmd`, then the `unit_complete` gates.
4. On any red result, it rolls the merge back with a hard reset to the commit it started from. The branch and the worktree stay for a fix.
5. On green, it commits the substrate as `harness: merge-slice <id> substrate`.
6. It removes the worktree and deletes the branch.

## Pull request mode

Use pull request mode when the base branch is protected. Set the `landing:` block:

```yaml
landing:
  mode: pr
  remote: origin
  base: main
  pr_cmd: "gh pr create --base {base} --head {branch} --title {title} --body-file {body}"
```

In this mode, close is the landing. After its substrate commit and its git note, `harness close-slice` does these things:

1. It pushes `slice/<id>` to `landing.remote`.
2. It runs `pr_cmd` without a shell. It splits the command with `shlex` and replaces `{base}`, `{branch}`, `{title}` and `{body}` inside their own words. `{body}` is a temporary file that holds the pull request body.
3. It records the first URL that `pr_cmd` prints as `pr_url`, and `landed_via: pr`.
4. It commits that metadata and pushes the branch again.

A slice row with a `linear` id puts that id in the pull request title and links it in the body.

`harness merge-slice` refuses in this mode with `LANDING_MODE_PR`, because a local merge would go around the protected branch. `harness start --no-worktree` also refuses, because close pushes from the slice worktree.

## Re-land after a failure

A failed push or a failed `pr_cmd` does not undo the close. The slice stays closed, and close exits 1. The row records `landed_via: pending` and `landing_error`. `harness verify` reports the advisory finding `LANDING_PENDING`.

Fix the cause, then run this from the slice worktree:

```bash
harness land --slice orders-1
```

`harness land` re-runs only the landing. It writes a new git note when the branch moved, then pushes. It runs `pr_cmd` only when the row has no `pr_url` yet, so it never opens a second pull request. Never run `harness close-slice` again for a closed slice.

## Update a slice branch

When the base branch moves while the pull request is open, update the branch on your machine, in the slice worktree:

```bash
git fetch origin && git merge origin/main
harness land --slice orders-1
```

Never use GitHub's "Update branch" button. Its server-side merge cannot run the `harness-substrate` merge driver, so it conflicts inside `.harness/backlog.jsonl`.

## Egress permits

In local mode, the sandbox profile denies `git push`, `git remote`, `git clone`, `git fetch` and `git pull`.

In pull request mode, the permit layer approves exactly these commands:

- `git push [-u] <remote> slice/<bound-slice>`, for the bound slice only;
- `git fetch <remote>`, with `--prune` or `--tags` only;
- `gh pr create`, `gh pr view`, `gh pr checks` and `gh pr status`.

The permit layer denies every other command that talks to a remote. These are some examples:

- a push of another branch, a second refspec, or `--force`;
- a fetch with a refspec or `--upload-pack`;
- `gh` with `--repo` or `-R`, which points it at another repository;
- `gh` with `--web` or `-w`, which opens a browser.

It also denies a `git config` write that could open a later egress, such as an alias, a hook path, a credential helper or a URL rewrite.

The permit layer approves `gh pr create --body-file` with any path. An agent could point the body file at a secret, so read each pull request body. [Trade-offs and limits](../trade-offs.md#where-enforcement-depends-on-the-host) lists this limit.
