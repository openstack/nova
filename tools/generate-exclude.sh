#!/usr/bin/env bash
# Args: <excludes.txt> <output for stestr --exclude-list>
grep -v '^#' "$1" | grep -v '^$' > "$2" || true
