@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" diagnostico.py
) else (
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 diagnostico.py
    ) else (
        python diagnostico.py
    )
)
pause
endlocal
