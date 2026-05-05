#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_SCRIPT="${ROOT_DIR}/run_sync.sh"
EXPORT_SCRIPT="${ROOT_DIR}/scripts/export_antigravity_chats.py"
PYTHON_BIN="${ROOT_DIR}/Obsidian_Transfer_venv/bin/python"

VAULT_ROOT=""
DRY_RUN=false
BUNDLE_DIR="N2O Export"
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vault-root)
      VAULT_ROOT="$2"
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      ARGS+=("$1")
      shift
      ;;
    --bundle-dir)
      BUNDLE_DIR="$2"
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${VAULT_ROOT}" ]]; then
  echo "[ERROR] --vault-root is required" >&2
  exit 1
fi

NOTEBOOKLM_OUT="${BUNDLE_DIR}/NotebookLM"
ANTIGRAVITY_OUT="${BUNDLE_DIR}/Antigravity"

echo "[INFO] Unified output root: ${VAULT_ROOT}/${BUNDLE_DIR}"

echo "[PHASE] sync-start"
"${SYNC_SCRIPT}" "${ARGS[@]}" --output-dir "${NOTEBOOKLM_OUT}"
echo "[PHASE] sync-end"

echo "[PHASE] export-start"
EXPORT_ARGS=(--vault-root "${VAULT_ROOT}" --output-dir "${ANTIGRAVITY_OUT}")
if [[ "${DRY_RUN}" == "true" ]]; then
  EXPORT_ARGS+=(--dry-run)
fi
"${PYTHON_BIN}" -u "${EXPORT_SCRIPT}" "${EXPORT_ARGS[@]}"
echo "[PHASE] export-end"

echo "[DONE] 100%"
