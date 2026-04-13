#!/usr/bin/env bash
# Rebuild the graphify code graph after edits (Cursor / Claude Code hooks).
# Codex: call with `always` on Stop — Codex PostToolUse currently only fires for Bash, not file writes.
set -euo pipefail

MODE="${1:-code}"

run_rebuild() {
  local root="${1:-.}"
  (cd "$root" && python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))") 2>/dev/null || true
}

git_root_from() {
  local start="${1:-.}"
  git -C "$start" rev-parse --show-toplevel 2>/dev/null || pwd
}

if [[ "$MODE" == "always" ]]; then
  root="${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-}}"
  if [[ -z "$root" ]]; then
    stdin=$(cat 2>/dev/null || true)
    if [[ -n "$stdin" ]] && command -v jq >/dev/null 2>&1; then
      root=$(printf '%s' "$stdin" | jq -r '.cwd // empty' 2>/dev/null || true)
    fi
  fi
  if [[ -z "$root" || "$root" == "null" ]]; then
    root=$(git_root_from ".")
  fi
  run_rebuild "$root"
  exit 0
fi

stdin=$(cat 2>/dev/null || true)
path=""
if [[ -n "$stdin" ]]; then
  if command -v jq >/dev/null 2>&1; then
    path=$(printf '%s' "$stdin" | jq -r '.file_path // .tool_input.file_path // .tool_input.path // empty' 2>/dev/null | head -1 || true)
  fi
  if [[ -z "$path" ]]; then
    path=$(printf '%s' "$stdin" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get('tool_input') or {}
print(d.get('file_path') or ti.get('file_path') or ti.get('path') or '')
" 2>/dev/null || true)
  fi
fi

[[ -z "$path" ]] && exit 0

shopt -s nocasematch 2>/dev/null || true
case "$path" in
  *.py|*.pyi|*.js|*.jsx|*.ts|*.tsx|*.mjs|*.cjs|*.vue|*.go|*.rs|*.java|*.kt|*.kts|*.sql|*.cs|*.fs|*.fsx|*.ex|*.exs|*.rb|*.php|*.swift|*.c|*.h|*.cpp|*.hpp|*.cc|*.cxx)
    ;;
  *)
    exit 0
    ;;
esac

dir=$(dirname "$path")
root=$(git_root_from "$dir")
run_rebuild "$root"
exit 0
