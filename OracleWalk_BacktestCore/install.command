#!/bin/bash
#
# BacktestCore installer for macOS.
# Double-click in Finder, or run from Terminal:  bash install.command
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

VENV_DIR=".venv"

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

step() { echo ""; printf "${BOLD}${CYAN}==>${RESET} ${BOLD}%s${RESET}\n" "$1"; }
ok()   { printf "${GREEN}[OK]${RESET} %s\n" "$1"; }
warn() { printf "${YELLOW}[!]${RESET}  %s\n" "$1"; }
fail() { printf "${RED}[X]${RESET}  %s\n" "$1"; }

pause_exit() {
  echo ""
  echo "Pressione Enter para fechar..."
  read -r _
  exit "$1"
}

detect_python() {
  if command -v python3 >/dev/null 2>&1; then
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >/dev/null 2>&1; then
      PY_BIN="python3"
      return 0
    fi
  fi
  PY_BIN=""
  return 1
}

# 1. Detect Python 3.9+
step "Verificando Python 3.9+"
if ! detect_python; then
  warn "Python 3.9+ nao encontrado. Tentando instalar via Homebrew..."

  if ! command -v brew >/dev/null 2>&1; then
    fail "Homebrew nao esta instalado."
    echo ""
    echo "Opcao 1 (recomendada) - instale o Homebrew e rode este script de novo:"
    echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo ""
    echo "Opcao 2 - baixe o Python diretamente do site oficial:"
    echo "  https://www.python.org/downloads/macos/"
    pause_exit 1
  fi

  if ! brew install python@3.12; then
    fail "Falha ao instalar Python via Homebrew."
    echo "Tente manualmente: brew install python@3.12"
    pause_exit 1
  fi

  # brew --prefix differs on Apple Silicon (/opt/homebrew) vs Intel (/usr/local)
  BREW_PREFIX="$(brew --prefix 2>/dev/null)"
  if [ -n "$BREW_PREFIX" ] && [ -x "$BREW_PREFIX/bin/python3" ]; then
    PY_BIN="$BREW_PREFIX/bin/python3"
  elif ! detect_python; then
    fail "Python foi instalado mas nao esta no PATH desta sessao."
    echo "Feche e abra o Terminal de novo, depois rode install.command novamente."
    pause_exit 1
  fi
fi

PY_VERSION="$("$PY_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PY_PATH="$("$PY_BIN" -c 'import sys; print(sys.executable)')"
ok "Python $PY_VERSION em $PY_PATH"

# 2. Create venv
step "Criando ambiente virtual em $VENV_DIR/"
if [ -d "$VENV_DIR" ]; then
  warn "Ambiente virtual ja existe -- vou reaproveitar."
else
  if ! "$PY_BIN" -m venv "$VENV_DIR"; then
    fail "Falha ao criar o ambiente virtual."
    pause_exit 1
  fi
fi

VENV_PY="$SCRIPT_DIR/$VENV_DIR/bin/python"
if [ ! -x "$VENV_PY" ]; then
  fail "venv criado mas $VENV_PY nao existe."
  pause_exit 1
fi
ok "Ambiente virtual em $SCRIPT_DIR/$VENV_DIR"

# 3. Upgrade pip
step "Atualizando pip"
if ! "$VENV_PY" -m pip install --upgrade pip; then
  fail "Falha ao atualizar pip."
  pause_exit 1
fi

# 4. Install project
step "Instalando BacktestCore e dependencias"
if ! "$VENV_PY" -m pip install -e .; then
  fail "Falha ao instalar o pacote."
  pause_exit 1
fi
ok "BacktestCore instalado."

# 5. Smoke test
step "Validando instalacao"
if ! "$VENV_PY" -c "from backtest_core import Backtester, generate_report_bundle; print('  imports OK')"; then
  fail "Smoke test falhou."
  pause_exit 1
fi
if ! "$VENV_PY" -m backtest_core.cli --config configs/mt5_eurusd_h1.json >/dev/null 2>&1; then
  fail "Backtest de validacao falhou."
  echo "O pacote instalou, mas o exemplo EURUSD_H1 nao rodou corretamente."
  pause_exit 1
fi
ok "Tudo certo."

# 6. Final
echo ""
printf "${BOLD}${GREEN}Instalacao concluida.${RESET}\n"
echo ""
echo "Para usar com duplo clique:"
echo "  run_ui.command"
echo ""
echo "Para usar pelo Terminal:"
echo "  source .venv/bin/activate"
echo "  python examples/run_demo.py"
echo "  python -m backtest_core.cli --config configs/mt5_eurusd_h1.json"
echo "  python -m backtest_core.ui.server --config configs/mt5_eurusd_h1.json"
echo ""
pause_exit 0
