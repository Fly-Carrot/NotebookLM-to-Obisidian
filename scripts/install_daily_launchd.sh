#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_ID="com.david.notebooklm.obsidian.sync"
PLIST_PATH="${HOME}/Library/LaunchAgents/${AGENT_ID}.plist"
LOG_DIR="${ROOT_DIR}/logs"
OUT_LOG="${LOG_DIR}/daily_sync.out.log"
ERR_LOG="${LOG_DIR}/daily_sync.err.log"

mkdir -p "${LOG_DIR}" "${HOME}/Library/LaunchAgents"

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${AGENT_ID}</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd "${ROOT_DIR}" &amp;&amp; ./run_sync.sh --include-source-content --sync-images --skip-unchanged-notebooks --overwrite-changed-notebook --max-source-chars 0</string>
  </array>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>22</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StartInterval</key>
  <integer>3600</integer>

  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>

  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

if launchctl list | rg -q "${AGENT_ID}"; then
  launchctl unload "${PLIST_PATH}" || true
fi

launchctl load "${PLIST_PATH}"
echo "[OK] launchd job installed: ${AGENT_ID}"
echo "[OK] plist: ${PLIST_PATH}"
echo "[OK] logs: ${OUT_LOG} / ${ERR_LOG}"
