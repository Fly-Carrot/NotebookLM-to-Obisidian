# Walkthrough: NotebookLM -> Obsidian

## Goal

Sync NotebookLM content to Obsidian with one notebook per folder and standard subfolders (`Conversations/`, `Photos/`).

## Delivered

- Sync script: `scripts/sync_notebooklm_to_obsidian.py`
- Runner: `run_sync.sh`
- App launcher: `Launchers/NotebookLM Obsidian Sync.app`
- Documentation: `README.md`

## Design Notes

1. Stable conversation mapping
`Conversations/` is currently based on Notebook Notes for API reliability.

2. Incremental sync
A per-notebook state file (`.sync_state.json`) is used to avoid unnecessary writes.

3. Image strategy
`Photos/` syncs image sources and infographic artifacts when available.

4. Safety controls
Supports `--dry-run`, `--limit`, and notebook filtering before full runs.

## Known Constraints

- Full raw chat-history export depends on upstream NotebookLM API behavior.
