#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${ROOT_DIR}/Launchers/NotebookLM Obsidian Sync.app"

mkdir -p "${APP_DIR}/Contents/MacOS" "${APP_DIR}/Contents/Resources"

swiftc -parse-as-library "${ROOT_DIR}/mac_app_build/NotebookSyncApp.swift" -o "${ROOT_DIR}/mac_app_build/NotebookSyncApp"
cp -f "${ROOT_DIR}/mac_app_build/NotebookSyncApp" "${APP_DIR}/Contents/MacOS/NotebookSyncApp"
chmod +x "${APP_DIR}/Contents/MacOS/NotebookSyncApp"
cp -f "${ROOT_DIR}/mac_app_build/AppIcon.icns" "${APP_DIR}/Contents/Resources/AppIcon.icns"

# Re-sign the full app bundle so Gatekeeper does not treat it as damaged.
rm -rf "${APP_DIR}/Contents/_CodeSignature"
codesign --force --deep --sign - "${APP_DIR}"
codesign --verify --deep --strict --verbose=2 "${APP_DIR}"

echo "[OK] App rebuilt at: ${APP_DIR}"
