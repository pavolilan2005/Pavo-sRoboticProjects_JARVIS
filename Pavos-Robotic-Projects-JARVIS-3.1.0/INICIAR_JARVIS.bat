@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8:replace
set JARVIS_SUBPROCESS_ENCODING=mbcs

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    echo No existe el entorno virtual. Ejecutando INSTALAR_JARVIS.bat...
    call INSTALAR_JARVIS.bat
    if not exist ".venv\Scripts\python.exe" exit /b 1
    set "PY=.venv\Scripts\python.exe"
)

%PY% main.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo JARVIS termino con codigo %EXIT_CODE%.
    echo Ejecuta DIAGNOSTICO_JARVIS.bat para revisar el entorno.
    pause
)
endlocal
