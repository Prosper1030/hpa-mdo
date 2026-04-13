#!/usr/bin/env bash
# Clean temporary output directories that accumulate at repo root.
# These match the .gitignore pattern *_out/ and are never committed.
# Safe to run at any time.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

count=0
total_size=0

for d in *_out; do
    [ -d "$d" ] || continue
    size=$(du -sm "$d" 2>/dev/null | cut -f1)
    total_size=$((total_size + size))
    count=$((count + 1))
    rm -rf "$d"
done

# Also clean __pycache__ outside .venv
find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true

echo "Cleaned $count temp directories (${total_size} MB) + __pycache__"
