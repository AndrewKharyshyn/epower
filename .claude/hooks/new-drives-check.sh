#!/bin/bash
# SessionStart hook (M508): report raw drive CSVs that are not yet in raw_manifest.json and tell the session to start the `ingest-drive` skill.
# Silent when there are none. Read-only; never fails a session.
cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || exit 0
PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
"$PY" tools/new_raw_files.py 2>/dev/null || true
exit 0
