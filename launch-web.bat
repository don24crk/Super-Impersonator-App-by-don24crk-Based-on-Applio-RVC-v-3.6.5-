@echo off
title Super Impersonator app - Engine v3.0 Web Launcher
set "PYTHON_PATH=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
set "APPLIO_CORE=C:\Users\User\Downloads\ApplioV3.7.1"

cd /d "C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine"

:: Erweitert den Python-Suchpfad, damit infer-web.py alle Applio-Module findet
set "PYTHONPATH=%APPLIO_CORE%;%APPLIO_CORE%\runtime\Lib\site-packages;%PYTHONPATH%"

echo ================================================================
echo   SUPER IMPERSONATOR APP // LAUNCHER WINDOW
echo   Engine v3.0 DYNAMICS FX // Coded by don24crk
echo ================================================================
echo.
echo [SYSTEM] Initialisiere Runtime...

if exist "%PYTHON_PATH%" (
    echo [OK] Python 3.12 - Global - erkannt.
    
    :: Automatische Abfrage der wichtigsten Plugins vor dem Start
    "%PYTHON_PATH%" -c "import pedalboard, pydub, gradio" 2>nul
    if errorlevel 1 (
        echo [INFO] Installiere fehlende Studio-Abhaengigkeiten...
        "%PYTHON_PATH%" -m pip install gradio pedalboard pydub
    )
    
    echo [INFO] Starte Cyberpunk Web-UI unter http://127.0.0.1:6969 ...
    echo [SYSTEM] Warte kurz auf Server-Initialisierung...
    
    :: Startet ein paralleles, unsichtbares Timeout, das nach 5 Sekunden Firefox oeffnet
    start /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:6969"
    
    echo.
    "%PYTHON_PATH%" infer-web.py
) else (
    echo [WARNUNG] Globales Python 3.12 nicht gefunden!
    echo [INFO] Versuche isolierte Applio-Runtime als Fallback zu laden...
    echo.
    
    if exist "%APPLIO_CORE%\runtime\python.exe" (
        start /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:6969"
        "%APPLIO_CORE%\runtime\python.exe" infer-web.py
    ) else (
        echo [FEHLER] Start abgebrochen. Keine Python-Umgebung gefunden!
        echo Bitte ueberpruefe deine Pfade in den Installationsordnern.
    )
)

echo.
echo [SYSTEM] Webserver-Instanz wurde geschlossen.
pause
