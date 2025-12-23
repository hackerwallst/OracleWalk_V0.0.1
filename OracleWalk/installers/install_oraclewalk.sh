#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"

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

PROJECT_ROOT="$(detect_project_root "$SCRIPT_DIR")" || {
  echo "[ERRO] Não consegui detectar a raiz do projeto (pyproject.toml/requirements.txt)." >&2
  exit 1
}

# Avoid creating a root-owned venv/config if the user runs with sudo.
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  if [[ -n "${SUDO_USER:-}" ]]; then
    echo "[WARN] Não execute este script com sudo. Ele usa sudo só quando precisa."
    echo "[INFO] Reexecutando como usuário: ${SUDO_USER}"
    exec /usr/bin/su - "${SUDO_USER}" -c "/bin/bash \"$SCRIPT_PATH\""
  fi
  echo "[ERRO] Não execute este script como root."
  exit 1
fi

LOG_DIR="${PROJECT_ROOT}/install_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/install_macos_$(date +%Y%m%d_%H%M%S).log"

exec > >(tee -a "$LOG_FILE") 2>&1

die() { echo "[ERRO] $*" >&2; exit 1; }
info() { echo "[INFO] $*"; }
step() { echo; echo "==> $*"; }

require_file() { [[ -f "$1" ]] || die "Arquivo obrigatório não encontrado: $1"; }

require_file "${PROJECT_ROOT}/requirements.txt"
require_file "${PROJECT_ROOT}/pyproject.toml"

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "Este instalador é para macOS. (uname=$(uname -s))"
fi

PY_MIN_MAJOR=3
PY_MIN_MINOR=10

PYTHON_VERSION_DEFAULT="3.11.8"
PYTHON_VERSION="${PYTHON_VERSION:-$PYTHON_VERSION_DEFAULT}"
PYTHON_MAJOR_MINOR="${PYTHON_VERSION%.*}"
PYTHON_PKG_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-macos11.pkg"

step "OracleWalk - Instalador (macOS)"
info "Pasta do projeto: ${PROJECT_ROOT}"
info "Log: ${LOG_FILE}"
info "macOS: $(sw_vers -productVersion) ($(uname -m))"

find_python3() {
  local candidates=(
    "$(command -v python3 || true)"
    "/usr/local/bin/python3"
    "/opt/homebrew/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/${PYTHON_MAJOR_MINOR}/bin/python3"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -n "$c" && -x "$c" ]]; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

python_ok() {
  local py="$1"
  "$py" -c "import sys; raise SystemExit(0 if sys.version_info >= (${PY_MIN_MAJOR}, ${PY_MIN_MINOR}) else 1)" >/dev/null 2>&1
}

step "Verificando Python (>= ${PY_MIN_MAJOR}.${PY_MIN_MINOR})"
PYTHON_BIN="$(find_python3 || true)"
if [[ -n "${PYTHON_BIN}" ]] && python_ok "$PYTHON_BIN"; then
  info "Python OK: $("$PYTHON_BIN" --version 2>&1) ($PYTHON_BIN)"
else
  step "Python ausente/antigo. Instalando Python ${PYTHON_VERSION} (universal2) via python.org"
  command -v curl >/dev/null 2>&1 || die "curl não encontrado (necessário para download)."

  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  PKG_PATH="${TMP_DIR}/python-${PYTHON_VERSION}-macos11.pkg"

  info "Baixando: ${PYTHON_PKG_URL}"
  curl -fL --retry 3 --retry-delay 2 -o "$PKG_PATH" "$PYTHON_PKG_URL" || die "Falha ao baixar o instalador do Python."

  info "Instalando (vai pedir senha de admin)..."
  sudo -v || die "Sem permissão de administrador (sudo)."
  sudo installer -pkg "$PKG_PATH" -target / || die "Falha ao instalar o Python."

  PYTHON_BIN="$(find_python3 || true)"
  [[ -n "${PYTHON_BIN}" ]] || die "Python não foi encontrado após instalação."
  python_ok "$PYTHON_BIN" || die "Python instalado não atende o mínimo (${PY_MIN_MAJOR}.${PY_MIN_MINOR})."
  info "Python instalado: $("$PYTHON_BIN" --version 2>&1) ($PYTHON_BIN)"
fi

VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/.venv}"
step "Criando/atualizando venv em: ${VENV_DIR}"
"$PYTHON_BIN" -m venv "$VENV_DIR" || die "Falha ao criar venv."

# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

step "Atualizando pip"
python -m pip install --upgrade pip || die "Falha ao atualizar pip."

step "Instalando dependências"
python -m pip install -r "${PROJECT_ROOT}/requirements.txt" || die "Falha ao instalar requirements.txt."
python -m pip install -e "${PROJECT_ROOT}" || die "Falha ao instalar o pacote (pip install -e .)."

step "Configurando config.txt (se necessário)"
if [[ -f "${PROJECT_ROOT}/config.txt" || -f "${PROJECT_ROOT}/.env" ]]; then
  info "Mantendo config existente (.env/config.txt já presentes)."
elif [[ -f "${PROJECT_ROOT}/config.example.txt" ]]; then
  cp "${PROJECT_ROOT}/config.example.txt" "${PROJECT_ROOT}/config.txt"
  # Defaults seguros: backtest + dry_run=true
  if grep -qE '^mode=' "${PROJECT_ROOT}/config.txt"; then
    sed -i '' 's/^mode=.*/mode=backtest/' "${PROJECT_ROOT}/config.txt"
  else
    echo "mode=backtest" >> "${PROJECT_ROOT}/config.txt"
  fi
  if grep -qE '^dry_run=' "${PROJECT_ROOT}/config.txt"; then
    sed -i '' 's/^dry_run=.*/dry_run=true/' "${PROJECT_ROOT}/config.txt"
  else
    echo "dry_run=true" >> "${PROJECT_ROOT}/config.txt"
  fi
  info "Criado: ${PROJECT_ROOT}/config.txt (edite para modo live/keys)."
else
  info "Nenhum config criado automaticamente (config.example.txt ausente)."
fi

step "Sanity-check (import/CLI)"
python -m oraclewalk.backtest --help >/dev/null || die "Sanity-check falhou."

echo
info "✅ Instalação concluída."
info "Para rodar agora: bash \"${PROJECT_ROOT}/installers/run_oraclewalk.sh\""
info "Se quiser operar ao vivo: edite ${PROJECT_ROOT}/config.txt (BINANCE/TELEGRAM) e coloque mode=live."
