@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist config\secrets.json copy config\secrets.example.json config\secrets.json >nul
echo Instalacion terminada.
pause
