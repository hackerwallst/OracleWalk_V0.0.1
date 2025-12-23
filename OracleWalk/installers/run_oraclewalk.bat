@echo off
setlocal EnableExtensions

set "INSTALL_DIR=%~dp0"
set "ROOT=%INSTALL_DIR%.."
cd /d "%ROOT%"

if not exist ".venv\\Scripts\\python.exe" (
  echo [ERRO] Ambiente .venv nao encontrado.
  echo [DICA] Rode primeiro: installers\\install_oraclewalk.bat
  exit /b 1
)

call ".venv\\Scripts\\activate.bat"
python -m oraclewalk.main

endlocal
