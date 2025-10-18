#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"


if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip
pip install -r "${ROOT_DIR}/requirements.txt"
pip install -e "${ROOT_DIR}"

if [[ $# -eq 0 ]]; then
  set -- menu
fi

exec fileops-toolkit "$@"
