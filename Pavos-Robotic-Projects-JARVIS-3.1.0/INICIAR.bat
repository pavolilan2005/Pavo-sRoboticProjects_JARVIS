@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Falta .venv. Ejecuta INSTALAR.bat primero.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "main.py"
if errorlevel 1 (
  echo.
  echo JARVIS termino con un error. Revisa la salida anterior.
  pause
)
