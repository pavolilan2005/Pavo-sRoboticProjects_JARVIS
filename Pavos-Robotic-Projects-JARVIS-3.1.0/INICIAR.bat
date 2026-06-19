@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0" || (
    echo [ERROR] No se pudo abrir la carpeta del proyecto.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No existe el entorno virtual.
    echo Ejecuta INSTALAR.bat primero.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
".venv\Scripts\python.exe" "main.py"
set "APP_EXIT=%ERRORLEVEL%"

if not "%APP_EXIT%"=="0" (
    echo.
    echo [ERROR] JARVIS termino con codigo %APP_EXIT%.
    echo Ejecuta DIAGNOSTICO.bat para obtener mas informacion.
    pause
)
exit /b %APP_EXIT%
