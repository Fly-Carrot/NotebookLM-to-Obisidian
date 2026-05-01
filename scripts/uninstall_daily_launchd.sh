#!/usr/bin/env bash
set -euo pipefail

AGENT_ID="com.david.notebooklm.obsidian.sync"
PLIST_PATH="${HOME}/Library/LaunchAgents/${AGENT_ID}.plist"

if launchctl list | rg -q "${AGENT_ID}"; then
  launchctl unload "${PLIST_PATH}" || true
fi

if [[ -f "${PLIST_PATH}" ]]; then
  rm -f "${PLIST_PATH}"
fi

echo "[OK] launchd job removed: ${AGENT_ID}"
