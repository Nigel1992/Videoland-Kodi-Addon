#!/usr/bin/env bash
# Run the Kodi add-on checker locally against a copy of this repository with the
# same filtered layout as the CI workflow (.github/workflows/addonchecker.yml).
#
# Usage:
#   scripts/run-addon-check-local.sh            # default: omega branch
#   scripts/run-addon-check-local.sh --branch nexus
#   scripts/run-addon-check-local.sh piers
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BRANCH="omega"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    *)
      BRANCH="$1"
      shift
      ;;
  esac
done

case "${BRANCH}" in
  nexus|omega|piers) ;;
  *) echo "Unsupported kodi-addon-checker branch '${BRANCH}' (use nexus, omega or piers)." >&2; exit 2 ;;
esac

ADDON_ID="$(python3 - "${REPO_ROOT}/addon.xml" <<'PY'
from xml.etree import ElementTree as ET
import sys
print(ET.parse(sys.argv[1]).getroot().attrib["id"])
PY
)"

if ! command -v kodi-addon-checker >/dev/null 2>&1; then
  echo "kodi-addon-checker is not installed. Install it with:" >&2
  echo "  python -m pip install kodi-addon-checker" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT

TARGET="${WORKDIR}/${ADDON_ID}"
mkdir -p "${TARGET}"
rsync -a "${REPO_ROOT}/" "${TARGET}/" \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '.env/' \
  --exclude '.vscode/' \
  --exclude '.idea/' \
  --exclude '.cache/' \
  --exclude 'cache/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.tox/' \
  --exclude '.nox/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '.DS_Store' \
  --exclude 'tests/' \
  --exclude 'scripts/' \
  --exclude 'package_build/' \
  --exclude '*.zip' \
  --exclude '.gitignore'

echo "Running kodi-addon-checker (${BRANCH}) on ${ADDON_ID}..."
kodi-addon-checker "${TARGET}" --branch "${BRANCH}"