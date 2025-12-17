#!/usr/bin/env bash
# Helper para gerar um executável standalone do OracleWalk usando PyInstaller.
# Deve ser executado na máquina/OS de destino (ex.: sua VPS Linux) para evitar problemas de compatibilidade.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR="${VENV_DIR:-.venv-build}"

echo ">> Criando/ativando venv em ${VENV_DIR}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo ">> Instalando dependências do projeto"
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo ">> Instalando PyInstaller para empacotar"
pip install pyinstaller

# Em sistemas Windows o separador de --add-data é ';'. Ajuste automático aqui:
ADD_DATA_SEP=":"
case "${OSTYPE:-}" in
  msys*|cygwin*|win32*|win64*)
    ADD_DATA_SEP=";"
    ;;
esac

echo ">> Gerando executável (dist/oraclewalk)"
pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --name oraclewalk \
  --add-data "src/oraclewalk/dashboard/static${ADD_DATA_SEP}oraclewalk/dashboard/static" \
  src/oraclewalk/main.py

echo
echo "✅ Executável criado em dist/oraclewalk (ou dist/oraclewalk.exe no Windows)."
echo "   Coloque o arquivo dist gerado na mesma pasta que seu config.txt/trades.csv para rodar."
