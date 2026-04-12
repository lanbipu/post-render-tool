#!/bin/bash
# One-shot setup: point Git at tracked hooks in this directory.
set -e

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath scripts/git-hooks
echo "✓ core.hooksPath set to scripts/git-hooks"
echo "  Tracked hooks are now active for this clone."
