@echo off
REM
REM BacktestCore installer for Windows.
REM Double-click in Explorer, or from cmd:  install.bat
REM
setlocal enableextensions enabledelayedexpansion
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "PY_BIN="

echo.
echo === Verificando Python 3.9+ ===

call :detect_python
if defined PY_BIN goto have_python

echo [!] Python 3.9+ nao encontrado. Tentando instalar via winget...
where winget >nul 2>nul
if errorlevel 1 (
    echo [X] winget nao esta disponivel nesta versao do Windows.
    echo.
    echo Instale o Python manualmente: https://www.python.org/downloads/windows/
    echo Marque "Add Python to PATH" no instalador, depois rode install.bat de novo.
    goto end_fail
)

winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [X] Falha ao instalar Python via winget.
    echo Tente manualmente: https://www.python.org/downloads/windows/
    goto end_fail
)

call :refresh_path
call :detect_python
if not defined PY_BIN (
    echo [X] Python foi instalado, mas o PATH ainda nao foi atualizado nesta sessao.
    echo Feche este terminal, abra um novo e rode install.bat de novo.
    goto end_fail
)

:have_python
for /f "delims=" %%v in ('%PY_BIN% -c "import sys; print(\".\".join(map(str, sys.version_info[:3])))"') do set "PY_VERSION=%%v"
echo [OK] Python %PY_VERSION%

echo.
echo === Criando ambiente virtual em %VENV_DIR%\ ===
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo [!] Ambiente virtual ja existe -- vou reaproveitar.
) else (
    %PY_BIN% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [X] Falha ao criar o ambiente virtual.
        goto end_fail
    )
)

set "VENV_PY=%CD%\%VENV_DIR%\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [X] venv criado mas %VENV_PY% nao existe.
    goto end_fail
)
echo [OK] Ambiente virtual em %CD%\%VENV_DIR%

echo.
echo === Atualizando pip ===
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
    echo [X] Falha ao atualizar pip.
    goto end_fail
)

echo.
echo === Instalando BacktestCore e dependencias ===
"%VENV_PY%" -m pip install -e .
if errorlevel 1 (
    echo [X] Falha ao instalar o pacote.
    goto end_fail
)
echo [OK] BacktestCore instalado.

echo.
echo === Validando instalacao ===
"%VENV_PY%" -c "from backtest_core import Backtester, generate_report_bundle; print('  imports OK')"
if errorlevel 1 (
    echo [X] Smoke test falhou.
    goto end_fail
)
"%VENV_PY%" -m backtest_core.cli --config configs\mt5_eurusd_h1.json >nul 2>nul
if errorlevel 1 (
    echo [X] Backtest de validacao falhou.
    echo O pacote instalou, mas o exemplo EURUSD_H1 nao rodou corretamente.
    goto end_fail
)
echo [OK] Tudo certo.

echo.
echo ========================================
echo  Instalacao concluida.
echo ========================================
echo.
echo Para usar com duplo clique:
echo   run_ui.bat
echo.
echo Para usar pelo cmd:
echo   .venv\Scripts\activate
echo   python examples\run_demo.py
echo   python -m backtest_core.cli --config configs\mt5_eurusd_h1.json
echo   python -m backtest_core.ui.server --config configs\mt5_eurusd_h1.json
echo.
goto end_ok

REM ============================================================
REM Subroutines
REM ============================================================

:detect_python
set "PY_BIN="
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 (
        set "PY_BIN=py -3"
        goto :eof
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_BIN=python"
)
goto :eof

:refresh_path
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYSPATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USRPATH=%%B"
if defined SYSPATH if defined USRPATH set "PATH=%SYSPATH%;%USRPATH%"
goto :eof

:end_fail
echo.
pause
exit /b 1

:end_ok
pause
exit /b 0
