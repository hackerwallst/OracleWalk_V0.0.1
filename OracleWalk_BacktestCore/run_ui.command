#!/bin/bash
#
# Starts the OracleWalk BacktestCore web UI on macOS.
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

VENV_PY="$SCRIPT_DIR/.venv/bin/python"
URL="http://127.0.0.1:8765"

if [ ! -x "$VENV_PY" ]; then
  echo "Ambiente virtual nao encontrado."
  echo "Rode install.command primeiro."
  echo ""
  echo "Pressione Enter para fechar..."
  read -r _
  exit 1
fi

echo "Abrindo OracleWalk BacktestCore UI..."
echo "$URL"
open "$URL" >/dev/null 2>&1 &
"$VENV_PY" -m backtest_core.ui.server --config configs/mt5_eurusd_h1.json --host 127.0.0.1 --port 8765

