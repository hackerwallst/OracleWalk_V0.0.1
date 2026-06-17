@echo off
REM Starts the OracleWalk BacktestCore web UI on Windows.
setlocal enableextensions
cd /d "%~dp0"

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:8765"

if not exist "%VENV_PY%" (
    echo Ambiente virtual nao encontrado.
    echo Rode install.bat primeiro.
    echo.
    pause
    exit /b 1
)

echo Abrindo OracleWalk BacktestCore UI...
echo %URL%
start "" "%URL%"
"%VENV_PY%" -m backtest_core.ui.server --config configs\mt5_eurusd_h1.json --host 127.0.0.1 --port 8765

pause
