# Git Hooks

Tracked Git hooks for this repository.

## Activation

After cloning the repo, run once from the repo root:

```bash
git config core.hooksPath scripts/git-hooks
```

This points Git at this directory instead of `.git/hooks/`. The setting is
local (stored in `.git/config`), so each clone needs it once.

Alternatively, run the setup script:

```bash
./scripts/git-hooks/install.sh
```

## Hooks

### `post-commit`

Auto-pushes each commit to the `p4` remote (P4 Git Connector), so the PC
running UE can `p4 sync` and receive the latest code without manual steps.

Behavior:

- Pushes the **current branch** (not hardcoded `main`).
- Skips silently if no `p4` remote exists in this clone.
- Skips on detached HEAD.
- Prints `[p4-sync] ✓ <branch> pushed to p4` or `[p4-sync] ✗ ...` to stderr
  so `git commit` output makes sync status obvious.
- Writes a rolling log to `.git/p4-push.log` for history.
- Never blocks the commit itself — if push fails, commit is still saved
  locally and you can retry with `git push p4` manually.
