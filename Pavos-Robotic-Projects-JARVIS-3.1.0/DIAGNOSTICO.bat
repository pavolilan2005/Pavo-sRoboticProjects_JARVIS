@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Falta .venv. Ejecuta INSTALAR.bat.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "diagnostico.py"
pause
