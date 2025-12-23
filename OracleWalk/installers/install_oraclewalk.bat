@echo off
setlocal EnableExtensions

rem OracleWalk - Instalador Windows (wrapper para PowerShell)
rem Recomendado: clique com botão direito > "Executar como administrador"

set "INSTALL_DIR=%~dp0"
set "ROOT=%INSTALL_DIR%.."
cd /d "%ROOT%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%install_oraclewalk.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERRO] Instalacao falhou (codigo=%RC%). Veja install_logs\ para detalhes.
  exit /b %RC%
)

echo.
echo [OK] Instalacao finalizada. Para rodar: installers\\run_oraclewalk.bat
exit /b 0
