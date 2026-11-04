@echo off
title Super Impersonator v3.0 DYNAMICS - Gradio Interface
echo ========================================================
echo   LAUNCHING GRADIO CORE
echo ========================================================

:: Schließt alte, hängengebliebene Python-Instanzen zur Port-Freigabe
taskkill /f /im python.exe >nul 2>&1

:: Wartet im Hintergrund 5 Sekunden und oeffnet dann den Browser
    start /b cmd /c "timeout /t 5 /nobreak >nul && start http://127.0.0.1:7860"

:: Automatische Installation/Prüfung der benötigten Live-Bibliotheken
echo [INFO] Pruefe Live-Audio Abhaengigkeiten...
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m pip install sounddevice numpy --quiet

:: Den Dateinamen deines Python-Skripts definieren
set "PYTHON_SCRIPT=infer-web.py"

:: Falls das Skript eine Ebene höher liegt (falls die .bat im Engine-Ordner ausgeführt wird):
if not exist "%PYTHON_SCRIPT%" if exist "..\%PYTHON_SCRIPT%" set "PYTHON_SCRIPT=..\%PYTHON_SCRIPT%"

echo [RUN] Starte Webserver via Python 3.12...
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" "%PYTHON_SCRIPT%"

if %errorlevel% neq 0 (
    echo.
    echo [FEHLER] Die App wurde unerwartet mit Fehlercode %errorlevel% beendet.
)

echo ========================================================
echo   Session beendet.
echo ========================================================
