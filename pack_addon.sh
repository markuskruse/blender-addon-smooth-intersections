#!/usr/bin/env bash
set -euo pipefail

# Script to package the Blender add-on into a distributable zip archive.
# Usage: ./pack_addon.sh [output-zip]
# When no output name is provided, the archive is written to ./dist/<addon_name>.zip

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

ADDON_DIR="t4p_clean"
if [[ ! -d "${ADDON_DIR}" ]]; then
  echo "Error: ${ADDON_DIR} directory not found in ${SCRIPT_DIR}" >&2
  exit 1
fi

DIST_DIR="${SCRIPT_DIR}/dist"
mkdir -p "${DIST_DIR}"

# Default archive name should reflect the user-facing add-on name rather than the
# internal module directory. This ensures the packaged zip aligns with how the
# plug-in is presented in Blender ("T4P clean").
DEFAULT_ZIP_NAME="T4P-Clean.zip"
OUTPUT_NAME="${1:-${DEFAULT_ZIP_NAME}}"
# If the user provided a relative path, place it inside dist for consistency.
if [[ "${OUTPUT_NAME}" != /* ]]; then
  OUTPUT_PATH="${DIST_DIR}/${OUTPUT_NAME}"
else
  OUTPUT_PATH="${OUTPUT_NAME}"
fi

# Ensure the output has a .zip extension.
if [[ "${OUTPUT_PATH}" != *.zip ]]; then
  OUTPUT_PATH="${OUTPUT_PATH}.zip"
fi

# Remove any previous archive with the same name.
rm -f "${OUTPUT_PATH}"

# Create the archive without Python cache files or other temporary artefacts.
if command -v zip >/dev/null 2>&1; then
  zip -r -q "${OUTPUT_PATH}" "${ADDON_DIR}" \
    -x "*/__pycache__/*" "*.pyc" "*.pyo"
else
  if ! command -v git >/dev/null 2>&1; then
    echo "Error: neither zip nor git command is available to create the archive." >&2
    exit 1
  fi

  echo "zip command not found; falling back to git archive."
  git -C "${SCRIPT_DIR}" archive \
    --format=zip \
    --output="${OUTPUT_PATH}" \
    HEAD "${ADDON_DIR}"
fi

echo "Created ${OUTPUT_PATH}"
