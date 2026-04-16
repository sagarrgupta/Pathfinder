<!-- ## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current (or rely on the hooks below when graphify is installed in your environment)

### Automatic rebuild hooks

Shared script: `scripts/graphify-rebuild-hook.sh` (runs the same Python one-liner; skips non-code paths unless invoked with `always`).

| Tool | Config | When it runs |
| --- | --- | --- |
| **Cursor** | `.cursor/hooks.json` | `afterFileEdit` after agent edits a file (code extensions only) |
| **Claude Code** | `.claude/settings.json` | `PostToolUse` after `Write` or `Edit` (code extensions only) |
| **Codex** | `.codex/hooks.json` | `Stop` at end of each turn with `always` — Codex `PostToolUse` currently only matches **Bash**, not file-write tools, so per-turn `Stop` is the reliable hook |

Enable Codex hooks in config if needed: `[features] codex_hooks = true`. -->
