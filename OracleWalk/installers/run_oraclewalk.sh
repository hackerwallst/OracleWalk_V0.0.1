#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

detect_project_root() {
  local dir="$1"
  while [[ -n "$dir" && "$dir" != "/" ]]; do
    if [[ -f "$dir/pyproject.toml" && -f "$dir/requirements.txt" ]]; then
      echo "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

ROOT_DIR="$(detect_project_root "$SCRIPT_DIR")" || {
  echo "[ERRO] Não consegui detectar a raiz do projeto (pyproject.toml/requirements.txt)." >&2
  exit 1
}

cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-${ROOT_DIR}/.venv}"
PY="${VENV_DIR}/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[ERRO] Venv não encontrada em: ${VENV_DIR}"
  echo "[DICA] Rode primeiro: bash \"${ROOT_DIR}/installers/install_oraclewalk.sh\""
  exit 1
fi

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"
python -m oraclewalk.main
