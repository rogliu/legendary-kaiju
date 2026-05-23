#!/usr/bin/env bash
# Block Edit/Write/NotebookEdit on rail files. Reason: AGENTS.md danger zones
# must be human-edited only; runtime rail edits can corrupt the safety substrate.
# Fires in ALL Claude Code sessions on this repo (including the main session).
set -euo pipefail

input="$(cat)"
path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.path // ""')"
[ -z "$path" ] && exit 0   # not a path-bearing tool call, allow

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
rel="${path#$repo_root/}"

block() {
  printf 'BLOCKED: %s is a rail file (AGENTS.md danger zone).\nReason: %s\nResolution: Stop & Escalate to a human.\n' "$1" "$2" >&2
  exit 2
}

case "$rel" in
  kaiju/risk/*) block "$rel" "real-money risk gate; must stay fail-closed" ;;
esac

exit 0
