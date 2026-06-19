@echo off
cd /d "%~dp0"
py -3.11 -m venv .venv
call .venv\Scriptsctivate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config\secrets.json copy config\secrets.example.json config\secrets.json
pause
