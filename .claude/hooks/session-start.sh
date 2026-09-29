#!/bin/bash
# SessionStart hook (web only): install pinned deps, point XT_RAW_DIR at raw/, regenerate STATE.md.
set -euo pipefail
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "$CLAUDE_PROJECT_DIR"

python3 -c "import numpy, pandas, scipy, sklearn, rainflow, statsmodels" 2>/dev/null \
  || python3 -m pip install -q -r requirements.pinned.txt
[ -d node_modules/jsdom ] || npm install --no-audit --no-fund --silent

[ -n "${CLAUDE_ENV_FILE:-}" ] && echo "export XT_RAW_DIR=\"$CLAUDE_PROJECT_DIR/raw\"" >> "$CLAUDE_ENV_FILE"
XT_RAW_DIR="$CLAUDE_PROJECT_DIR/raw" python3 tools/state.py >/dev/null
echo "session-start: deps ready, STATE.md refreshed"
