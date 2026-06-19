@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Ejecuta INSTALAR.bat primero.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "migrar_config.py"
pause
