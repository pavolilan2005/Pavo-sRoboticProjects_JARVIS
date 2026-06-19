@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

echo ================================================
echo  PAVO'S ROBOTIC PROJECTS - JARVIS 3.0.0
echo  Instalacion limpia
echo ================================================

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro el lanzador de Python "py".
  echo Instala Python 3.11 o 3.12 desde python.org y activa "Add Python to PATH".
  pause
  exit /b 1
)

if exist ".venv" (
  echo [INFO] Entorno virtual existente detectado.
) else (
  echo [1/4] Creando entorno virtual...
  py -3.11 -m venv ".venv"
  if errorlevel 1 py -3 -m venv ".venv"
  if errorlevel 1 (
    echo [ERROR] No pude crear .venv.
    pause
    exit /b 1
  )
)

echo [2/4] Actualizando pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [3/4] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto :fail

echo [4/4] Preparando configuracion...
if not exist "config\api_keys.json" copy /Y "config\api_keys.example.json" "config\api_keys.json" >nul
if not exist "logs" mkdir "logs"

echo.
echo [OK] Instalacion terminada.
echo Ejecuta INICIAR.bat
pause
exit /b 0

:fail
echo.
echo [ERROR] La instalacion no termino correctamente.
pause
exit /b 1
