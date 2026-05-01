#!/bin/bash
cd "$(dirname "$0")/.."
./run_sync.sh
osascript -e 'display notification "Sync completed" with title "NotebookLM → Obsidian"'
