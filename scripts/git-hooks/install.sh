#!/bin/bash
# One-shot setup for P4 auto-push:
#   1. Activate tracked hooks (core.hooksPath = scripts/git-hooks)
#   2. Register the 'p4' remote pointing at the P4 Git Connector
#
# Usage:
#   ./scripts/git-hooks/install.sh [<p4-remote-url>]
#
#   If <p4-remote-url> is omitted, defaults to:
#     ssh://git@192.168.10.2:2222/ue/post-render-tool
#
#   To override, pass an explicit URL, e.g.:
#     ./scripts/git-hooks/install.sh ssh://git@192.168.10.2:2222/ue/my-repo
#
# Idempotent: safe to re-run. Updates the remote URL if already configured.

set -eu

DEFAULT_P4_URL="ssh://git@192.168.10.2:2222/ue/post-render-tool"
P4_URL="${1:-$DEFAULT_P4_URL}"
REMOTE="p4"

cd "$(git rev-parse --show-toplevel)"

# 1. Activate tracked hooks
git config core.hooksPath scripts/git-hooks
echo "✓ core.hooksPath set to scripts/git-hooks"

# 2. Configure 'p4' remote
if git remote get-url "$REMOTE" >/dev/null 2>&1; then
    CURRENT_URL="$(git remote get-url $REMOTE)"
    if [ "$CURRENT_URL" = "$P4_URL" ]; then
        echo "✓ remote '$REMOTE' already configured: $P4_URL"
    else
        git remote set-url "$REMOTE" "$P4_URL"
        echo "✓ remote '$REMOTE' updated: $CURRENT_URL -> $P4_URL"
    fi
else
    git remote add "$REMOTE" "$P4_URL"
    echo "✓ remote '$REMOTE' added: $P4_URL"
fi

echo ""
echo "P4 auto-push is now active."
echo "Next commit will be pushed to $P4_URL automatically."
