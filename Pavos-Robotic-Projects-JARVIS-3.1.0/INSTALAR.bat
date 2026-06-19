@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0" || (
    echo [ERROR] No se pudo abrir la carpeta del proyecto.
    pause
    exit /b 1
)

echo ================================================
echo  Pavo's Robotic Projects - JARVIS Installer
echo ================================================
echo.

set "PYTHON_CMD="
py -3.11 --version >nul 2>&1 && set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD (
    python --version >nul 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo [ERROR] No se encontro Python 3.11 o compatible.
    echo Instala Python y activa la opcion Add Python to PATH.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creando entorno virtual...
    %PYTHON_CMD% -m venv ".venv"
    if errorlevel 1 goto :install_error
) else (
    echo [1/4] Entorno virtual existente.
)

echo [2/4] Actualizando pip dentro del entorno virtual...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :install_error

echo [3/4] Instalando dependencias...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto :install_error

echo [4/4] Preparando configuracion...
if not exist "config\secrets.json" (
    copy /Y "config\secrets.example.json" "config\secrets.json" >nul
)

echo.
echo [OK] Instalacion terminada correctamente.
echo Ya puedes ejecutar INICIAR.bat.
pause
exit /b 0

:install_error
echo.
echo [ERROR] La instalacion no termino correctamente.
echo Revisa el mensaje mostrado arriba.
pause
exit /b 1
