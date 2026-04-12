# Git Hooks

Tracked Git hooks for this repository. Enables automatic push of every
commit to the P4 Git Connector, so the PC running UE can `p4 sync` and
receive the latest code without manual steps.

## Setup (after cloning)

Run once from the repo root:

```bash
./scripts/git-hooks/install.sh
```

This does two things:

1. Activates tracked hooks: `git config core.hooksPath scripts/git-hooks`
2. Registers the `p4` remote pointing at the P4 Git Connector

To override the default remote URL:

```bash
./scripts/git-hooks/install.sh ssh://git@192.168.10.2:2222/ue/my-repo
```

The script is idempotent — safe to re-run. It updates the remote URL
if already configured.

## Hooks

### `post-commit` — P4 auto-push

Automatically pushes each commit to the `p4` remote.

**Behavior:**

- Pushes the **current branch** (not hardcoded `main`).
- Skips silently if no `p4` remote exists in this clone.
- Skips on detached HEAD.
- **Bounded SSH**: `ConnectTimeout=5s` ensures `git commit` never hangs
  when the Git Connector is unreachable (off-LAN, NAS down, etc.) —
  failure reported within 5 seconds, commit itself always succeeds.
- Prints `[p4-sync] ✓ <branch> pushed to p4` or `[p4-sync] ✗ ...` to stderr
  so `git commit` output makes sync status obvious.
- Writes a rolling log to `.git/p4-push.log` for history.
- **Never blocks the commit** — if push fails, commit is still saved
  locally and you can retry with `git push p4` manually.

**Off-LAN workflow:** When working away from the LAN, the hook still
attempts the push, fails fast within 5s, and logs the failure. The
commit succeeds normally. When you're back on LAN, run `git push p4`
once to catch up.
