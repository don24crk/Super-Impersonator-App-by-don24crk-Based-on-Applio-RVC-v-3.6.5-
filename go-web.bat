@echo off
title Super Impersonator app - Engine v3.0 Launcher
set "PYTHON_PATH=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
set "APPLIO_CORE=C:\Users\User\Downloads\ApplioV3.7.1"

cd /d "C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine"

:: Bindet die Bibliotheken und Site-Packages von Applio in deine Python 3.12 Runtime ein
set "PYTHONPATH=%APPLIO_CORE%;%APPLIO_CORE%\runtime\Lib\site-packages;%PYTHONPATH%"

echo ================================================================
echo   Super Impersonator app // Engine v3.0 DYNAMICS FX
echo   by don24crk
echo ================================================================
echo.
echo [SYSTEM] Initialisierung der Runtime gestartet

if exist "%PYTHON_PATH%" (
    echo [OK] Python 3.12 - Global - erkannt
    
    :: Ueberpruefung und automatische Installation von pedalboard
    echo [INFO] Ueberpruefe Studio FX Engine pedalboard
    "%PYTHON_PATH%" -c "import pedalboard" 2>nul
    if errorlevel 1 (
        echo [WARNUNG] pedalboard fehlt - Starte Installation
        "%PYTHON_PATH%" -m pip install pedalboard
        echo [OK] Studio FX Engine eingerichtet
    ) else (
        echo [OK] Studio FX Engine betriebsbereit
    )
    
    :: Ueberpruefung und automatische Installation von pydub
    echo [INFO] Ueberpruefe Master Export Router pydub
    "%PYTHON_PATH%" -c "import pydub" 2>nul
    if errorlevel 1 (
        echo [WARNUNG] pydub fehlt - Starte Installation
        "%PYTHON_PATH%" -m pip install pydub
        echo [OK] Export Router eingerichtet
    ) else (
        echo [OK] Export Router betriebsbereit
    )
    
    echo.
    echo [INFO] Starte infer-web.py unter http://127.0.0.1:6969
    echo [SYSTEM] Warte kurz auf Server Initialisierung
    
    :: Wartet im Hintergrund 5 Sekunden und oeffnet dann den Browser
    start /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:6969"
    
    echo.
    "%PYTHON_PATH%" infer-web.py
) else (
    echo [WARNUNG] Python 3.12 wurde nicht gefunden
    echo [INFO] Versuche als Fallback die Applio eigene Runtime zu nutzen
    echo.
    
    if exist "%APPLIO_CORE%\runtime\python.exe" (
        start /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:6969"
        "%APPLIO_CORE%\runtime\python.exe" infer-web.py
    ) else (
        echo [FEHLER] Keine kompatible Python Umgebung gefunden
        echo Bitte ueberpruefe die Pfade
    )
)

echo.
echo Anwendung beendet
pause
