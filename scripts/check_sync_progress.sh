#!/usr/bin/env bash
set -euo pipefail

OUT_ROOT="/Users/david_chen/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Memory/NotebookLM"

echo "== Running Process =="
ps -eo pid,etime,pcpu,pmem,command | rg 'sync_notebooklm_to_obsidian.py|run_sync.sh' | rg -v rg || true

echo
echo "== Notebook Directories =="
if [[ -d "${OUT_ROOT}" ]]; then
  ls -1 "${OUT_ROOT}" | sed -n '1,400p'
  echo
  echo "count_dirs: $(find "${OUT_ROOT}" -maxdepth 1 -type d | wc -l | tr -d ' ')"
  echo "size: $(du -sh "${OUT_ROOT}" | awk '{print $1}')"
else
  echo "output root not found: ${OUT_ROOT}"
fi
