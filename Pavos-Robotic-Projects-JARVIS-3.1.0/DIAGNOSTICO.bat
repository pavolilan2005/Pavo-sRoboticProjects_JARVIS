@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0" || (
    echo [ERROR] No se pudo abrir la carpeta del proyecto.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No existe el entorno virtual. Ejecuta INSTALAR.bat.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
".venv\Scripts\python.exe" "diagnostico.py"
pause
