@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call INSTALAR_JARVIS.bat
.venv\Scripts\python.exe -m pip install -r requirements-optional-windows.txt
if errorlevel 1 (
  echo El lector WinRT no esta disponible para esta combinacion de Python/Windows.
  echo El resto de PRP JARVIS funciona normalmente.
)
pause
