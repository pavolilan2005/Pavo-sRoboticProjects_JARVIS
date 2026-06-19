@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" MIGRAR_DESDE_ANTERIOR.py
) else (
  py -3.11 MIGRAR_DESDE_ANTERIOR.py 2>nul || python MIGRAR_DESDE_ANTERIOR.py
)
