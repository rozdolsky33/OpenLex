#!/usr/bin/env bash
# PostToolUse hook: after Claude edits/writes a file, auto-run ruff format + ruff check --fix
# on it if it's a *.py file. No-ops silently on everything else so it's safe to register with
# a blanket Edit|Write|MultiEdit matcher -- Claude Code's hook matcher only matches on tool
# name, not file glob, so filtering by extension has to happen inside this script, via the
# tool_input JSON piped to stdin.
set -euo pipefail

input="$(cat)"
file_path="$(echo "$input" | jq -r '.tool_input.file_path // empty')"

[[ "$file_path" == *.py ]] || exit 0
[[ -f "$file_path" ]] || exit 0

cd "$CLAUDE_PROJECT_DIR"
uv run ruff format "$file_path" >/dev/null 2>&1 || true
uv run ruff check --fix "$file_path" >/dev/null 2>&1 || true

exit 0
