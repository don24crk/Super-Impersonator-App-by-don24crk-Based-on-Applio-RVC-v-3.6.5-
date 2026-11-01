@echo off
:: =======================================================================
:: SPRENGKOPF-SCHUTZ: Fängt eventuelle BOM-Verschiebungen ab
:: =======================================================================
goto studio_start
:studio_start
setlocal enabledelayedexpansion
chcp 65001 > nul
title Super Impersonator App Launcher (Applio v3.6.5 Interop)
cls

echo =======================================================================
echo   SUPER IMPERSONATOR APP - WORKSTATION LAUNCHER // by don24crk
echo =======================================================================
echo.

echo [INFO] Bereinige Studio-Netzwerkports...
C:\Windows\System32\netstat.exe -aon | findstr :6969 > nul
if not %errorlevel% == 0 goto skip_kill

for /f "tokens=5" %%a in ('C:\Windows\System32\netstat.exe -aon ^| findstr :6969') do taskkill /f /pid %%a >nul 2>&1
echo [OK] Restaktivitaet auf Port 6969 erfolgreich beendet.

:skip_kill

:: Statische Pfade fuer die Python 3.12 Studioumgebung
set "RUN_CMD=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
set "PRESETS_DIR=C:\Users\User\Downloads\Super Impersonator app by don24crk\Engine\presets"

echo.
echo [INFO] Ueberpruefe Systemkomponenten...

if exist "%RUN_CMD%" goto python_ok
echo [FEHLER] Python 3.12 wurde unter %RUN_CMD% nicht gefunden.
goto error_exit

:python_ok
echo [OK] Python 3.12 Laufzeitumgebung direkt verifiziert.

where ffmpeg >nul 2>&1
if %errorlevel% == 0 echo [OK] FFmpeg Master-Exporter einsatzbereit.
if not %errorlevel% == 0 echo [WARNUNG] ffmpeg ist nicht im System-PATH registriert. Export eingeschraenkt.

where ffprobe >nul 2>&1
if %errorlevel% == 0 echo [OK] FFprobe Stream-Analyse einsatzbereit.
if not %errorlevel% == 0 echo [WARNUNG] ffprobe ist nicht im System-PATH registriert. Analyse eingeschraenkt.

echo.
echo [INFO] Ueberpruefe Verzeichnisstrukturen...
if not exist "models" mkdir "models"
if exist "models" echo [OK] Lokaler RVC 'models' Ordner wurde verifiziert.

if not exist "%PRESETS_DIR%" mkdir "%PRESETS_DIR%"
if exist "%PRESETS_DIR%" echo [OK] Globaler Preset-Speicherort wurde verifiziert.

echo.
echo [INFO] Starte native DSP Python Engine mit hoher Prioritaet...
start "Super Impersonator Engine" /high "%RUN_CMD%" app.py

echo [INFO] Initialisiere HTTP-Server-Schnittstelle (127.0.0.1:6969)...
C:\Windows\System32\timeout.exe /t 2 /nobreak >nul

echo.
echo [INFO] Starte Studio-Benutzeroberflaeche...
if exist "index.html" start "" "index.html"
if exist "index.html" echo [OK] Lokale index.html geladen.
if not exist "index.html" start "" "http://127.0.0.1:6969"
if not exist "index.html" echo [OK] HTTP Web-Stream geoeffnet.

echo.
echo =======================================================================
echo   [OK] ENGINE ERFOLGREICH GESTARTET // WORKSTATION ONLINE
echo   Schließen Sie dieses Konsolenfenster nicht waehrend der Nutzung.
echo =======================================================================
echo.
pause
exit /b

:error_exit
echo.
echo [FEHLER] Startvorgang abgebrochen. Bitte ueberpruefen Sie die Python-Installation.
pause
exit /b
