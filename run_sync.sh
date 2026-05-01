#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${ROOT_DIR}/Obsidian_Transfer_venv/bin/python"
SCRIPT_PATH="${ROOT_DIR}/scripts/sync_notebooklm_to_obsidian.py"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[ERROR] Python venv not found: ${PYTHON_BIN}" >&2
  echo "Please create env first: python3.14 -m venv Obsidian_Transfer_venv" >&2
  exit 1
fi

exec "${PYTHON_BIN}" -u "${SCRIPT_PATH}" "$@"
