#!/usr/bin/env bash
# Installs version-controlled git hooks from scripts/hooks/ into .git/hooks/
# by symlinking them. Safe to run multiple times (idempotent).
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_SRC_DIR="$REPO_ROOT/scripts/hooks"
HOOKS_DST_DIR="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_SRC_DIR" ]; then
    echo "install-hooks: no hooks directory found at $HOOKS_SRC_DIR" >&2
    exit 1
fi

mkdir -p "$HOOKS_DST_DIR"

installed=0
for hook_path in "$HOOKS_SRC_DIR"/*; do
    [ -f "$hook_path" ] || continue
    hook_name="$(basename "$hook_path")"
    dst_path="$HOOKS_DST_DIR/$hook_name"

    chmod +x "$hook_path"

    if [ -L "$dst_path" ]; then
        # Already a symlink -- replace it in case the target changed.
        rm -f "$dst_path"
    elif [ -e "$dst_path" ]; then
        # A real file exists where the hook should go; back it up rather
        # than clobbering it silently.
        backup_path="$dst_path.bak.$(date +%s)"
        echo "install-hooks: backing up existing $dst_path -> $backup_path" >&2
        mv "$dst_path" "$backup_path"
    fi

    ln -s "../../scripts/hooks/$hook_name" "$dst_path"
    echo "install-hooks: installed $hook_name -> $dst_path"
    installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
    echo "install-hooks: no hook files found in $HOOKS_SRC_DIR" >&2
    exit 1
fi

echo "install-hooks: done ($installed hook(s) installed)"
