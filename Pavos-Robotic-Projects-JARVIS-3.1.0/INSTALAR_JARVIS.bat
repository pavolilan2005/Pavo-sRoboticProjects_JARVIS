@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8:replace

where py >nul 2>&1
if not errorlevel 1 (
    set "BASEPY=py -3.11"
) else (
    set "BASEPY=python"
)

%BASEPY% -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info < (3,13) else 1)"
if errorlevel 1 (
    echo Pavo's Robotic Projects // JARVIS recomienda Python 3.11 o 3.12 de python.org.
    echo La version de Microsoft Store puede funcionar, pero Python 3.13 todavia rompe algunas dependencias de audio.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual PRP...
    %BASEPY% -m venv .venv || goto :error
)

set "PY=.venv\Scripts\python.exe"
%PY% -m pip install --upgrade pip setuptools wheel || goto :error
%PY% -m pip install -r requirements.txt || goto :error
%PY% -m playwright install chromium

if not exist "config\api_keys.json" copy /y "config\api_keys.example.json" "config\api_keys.json" >nul

echo.
echo Instalacion completada.
echo 1. Ejecuta INICIAR_JARVIS.bat

echo 2. Abre CENTRO DE CONTROL para configurar ESP32, OBS, Spotify y Gmail.
pause
exit /b 0

:error
echo.
echo La instalacion fallo. Revisa el mensaje anterior.
pause
exit /b 1
