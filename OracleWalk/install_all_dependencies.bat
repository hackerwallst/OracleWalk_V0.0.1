@echo off
setlocal EnableExtensions

rem Instalador completo das dependencias do OracleWalk (Python).
rem Execute este arquivo na raiz do projeto.

set ROOT=%~dp0
cd /d "%ROOT%"
set VENV_DIR=.venv

echo ============================================================
echo [INFO] OracleWalk - instalacao de dependencias (verboso)
echo [INFO] Diretorio atual: %CD%
echo ============================================================

rem --- Localiza Python (permite override via PYTHON_CMD) ---
if not "%PYTHON_CMD%"=="" (
    set PY_CMD=%PYTHON_CMD%
    echo [INFO] Override PYTHON_CMD detectado: %PY_CMD%
) else (
    set PY_CMD=
)
echo [STEP] 1/7 - Procurando Python (prefere 'python', depois 'py -3')...
if "%PY_CMD%"=="" (
    where python >nul 2>&1
    if %ERRORLEVEL%==0 (
        set PY_CMD=python
        echo [OK]   Encontrado: python
    )
)
if "%PY_CMD%"=="" (
    where py >nul 2>&1
    if %ERRORLEVEL%==0 (
        set PY_CMD=py -3
        echo [OK]   Encontrado: py -3
    )
)

if "%PY_CMD%"=="" (
    echo [WARN] Python nao encontrado. Tentando instalar via winget...
    where winget >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo [CMD]  winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
        echo [INFO] Rechecando comandos py/python apos instalacao...
        where py >nul 2>&1
        if %ERRORLEVEL%==0 (set PY_CMD=py -3)
        where python >nul 2>&1
        if "%PY_CMD%"=="" if %ERRORLEVEL%==0 (set PY_CMD=python)
    ) else (
        echo [ERRO] winget nao disponivel e Python nao encontrado. Instale Python 3.11 manualmente.
        exit /b 1
    )
)

if "%PY_CMD%"=="" (
    echo [ERRO] Nao foi possivel encontrar ou instalar Python.
    exit /b 1
)

echo [STEP] 2/7 - Testando interpretador: %PY_CMD%
echo [CMD]  %PY_CMD% --version
%PY_CMD% --version
set "PY_TEST_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno Python: %PY_TEST_RC%
if not "%PY_TEST_RC%"=="0" goto :py_fail
echo [OK]   Python respondeu corretamente.
goto :py_ok
:py_fail
echo [ERRO] Python nao respondeu corretamente (%PY_CMD%).
echo [DICA] Defina PYTHON_CMD=python para forcar outro interpretador antes de rodar o .bat.
exit /b 1
:py_ok

echo [STEP] 3/7 - Preparando ambiente virtual: %VENV_DIR%
if exist "%VENV_DIR%\Scripts\activate.bat" goto :venv_ready
echo [CMD]  Criando venv em %VENV_DIR% -> %PY_CMD% -m venv "%VENV_DIR%"
%PY_CMD% -m venv "%VENV_DIR%"
set "VENV_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno criacao venv: %VENV_RC%
if not "%VENV_RC%"=="0" goto :venv_fail
:venv_ready
echo [OK]   Venv disponivel em %VENV_DIR%.
goto :venv_ok
:venv_fail
echo [ERRO] Falha ao criar venv.
exit /b 1
:venv_ok

echo [STEP] 4/7 - Ativando venv...
call "%VENV_DIR%\Scripts\activate.bat"
set "VENV_ACT_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno ativacao venv: %VENV_ACT_RC%
if not "%VENV_ACT_RC%"=="0" goto :venv_act_fail
echo [DEBUG] PATH apos ativacao: %PATH%
goto :venv_act_ok
:venv_act_fail
echo [ERRO] Falha ao ativar venv.
exit /b 1
:venv_act_ok

echo [STEP] 5/7 - Atualizando pip...
echo [CMD]  python -m pip install --upgrade pip
python -m pip install --upgrade pip
set "PIP_UP_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno upgrade pip: %PIP_UP_RC%
if not "%PIP_UP_RC%"=="0" goto :pip_up_fail
echo [OK]   pip atualizado.
goto :pip_up_ok
:pip_up_fail
echo [ERRO] Falha ao atualizar pip.
exit /b 1
:pip_up_ok

echo [STEP] 6/7 - Instalando dependencias Python...
echo [CMD]  python -m pip install -r requirements.txt
python -m pip install -r requirements.txt
set "REQ_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno install requirements: %REQ_RC%
if not "%REQ_RC%"=="0" goto :req_fail
echo [OK]   Dependencias Python instaladas.
goto :req_ok
:req_fail
echo [ERRO] Falha ao instalar requirements.
exit /b 1
:req_ok

echo [STEP] 7/7 - Registrando pacote (pip install -e .)...
echo [CMD]  python -m pip install -e .
python -m pip install -e .
set "PIP_EDIT_RC=%ERRORLEVEL%"
echo [DEBUG] Retorno pip install -e .: %PIP_EDIT_RC%
if not "%PIP_EDIT_RC%"=="0" goto :pip_edit_fail
echo [OK]   Pacote oraclewalk registrado (editable).
goto :pip_edit_ok
:pip_edit_fail
echo [ERRO] Falha ao registrar pacote (pip install -e .). Continue manualmente se preferir.
:pip_edit_ok

echo.
echo [STEP] Finalizacao
echo ✅ Dependencias Python instaladas com sucesso.
echo Ative a venv quando for usar o Python com: %VENV_DIR%\Scripts\activate.bat
echo ============================================================

endlocal
