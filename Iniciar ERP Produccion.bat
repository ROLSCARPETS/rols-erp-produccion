@echo off
chcp 65001 >nul
title ERP Produccion - Compras - Rols Carpets

echo ============================================================
echo   ERP Produccion Rols - Modulo de Compras / Materias primas
echo ============================================================
echo.

REM Cambiar al directorio del .bat
cd /d "%~dp0"

REM Verificar que Python esta disponible
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo Instala Python desde https://www.python.org/downloads/
    echo Importante: marcar "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

REM Verificar/instalar Flask
python -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo [Primera vez] Instalando Flask...
    python -m pip install flask --quiet
    if errorlevel 1 (
        echo [ERROR] No se pudo instalar Flask.
        pause
        exit /b 1
    )
    echo Flask instalado.
    echo.
)

REM Verificar/instalar reportlab (PDF del pedido a proveedor)
python -c "import reportlab" >nul 2>nul
if errorlevel 1 (
    echo [Primera vez] Instalando reportlab...
    python -m pip install reportlab --quiet
    echo.
)

REM Abrir el navegador en 3s (en paralelo al arranque del servidor)
start "" /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5060"

echo Arrancando servidor en http://localhost:5060 ...
echo.
echo --- Para DETENER la app, cierra esta ventana o pulsa Ctrl+C ---
echo.

python app.py

echo.
echo Servidor detenido.
pause
