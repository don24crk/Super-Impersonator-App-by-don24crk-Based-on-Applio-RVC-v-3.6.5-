@echo off
chcp 65001 > nul
title Super Impersonator app by don24crk - Modern RVC Launcher
cls

echo =======================================================================
echo     SUPER IMPERSONATOR APP ENGINE (RVC CORE & DSP) - BY DON24CRK
echo =======================================================================
echo.

dotnet --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Das .NET SDK wurde auf diesem System nicht gefunden.
    echo Bitte installiere das .NET SDK 8.0/9.0 oder neuer von:
    echo https://dotnet.microsoft.com/download
    echo.
    pause
    exit /b
)

if exist "ffmpeg.exe" (
    echo [INFO] FFmpeg Subsystem bereits betriebsbereit.
    goto :check_rvc_models
)

echo [INFO] FFmpeg fehlt. Starte automatischen Download der Core-Binaries...
powershell -Command "& {Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg.zip'}"
if %errorlevel% neq 0 goto :download_failed

echo [INFO] Entpacke Audio-Codecs...
powershell -Command "& {Expand-Archive -Path 'ffmpeg.zip' -DestinationPath 'ffmpeg_temp' -Force}"
for /r "ffmpeg_temp" %%i in (ffmpeg.exe) do move "%%i" "." >nul 2>&1

del ffmpeg.zip
rmdir /s /q ffmpeg_temp
if not exist "ffmpeg.exe" goto :ffmpeg_failed
echo [INFO] FFmpeg erfolgreich in Studio-Matrix integriert.

:check_rvc_models
if not exist "models" (
    echo [INFO] Erstelle RVC-Modell-Verzeichnis "\models"...
    mkdir models
)

echo [INFO] Scanne RVC-Bibliothek nach .pth und .index Dateien...
set "found_models=0"
for /R models %%f in (*.pth) do (
    set /a found_models+=1
    echo   -^> RVC-Modell geladen: %%~nxf
)
for /R models %%f in (*.index) do (
    echo   -^> RVC-Index geladen: %%~nxf
)

if %found_models%==0 (
    echo [WARNUNG] Keine lokalen .pth-Modelle im Ordner "\models" gefunden.
    echo           Bitte füge deine Applio/RVC-Modelle dort ein.
) else (
    echo [INFO] %found_models% RVC-Modell^(e^) erfolgreich für Inferenz indiziert.
)

echo [INFO] Starte automatischen Build der C# Advanced DSP Engine...
if not exist "SuperImpersonatorEngine.csproj" (
    dotnet new console --force --name SuperImpersonatorEngine --output . >nul 2>&1
)

dotnet build -c Release >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Die Kompilierung der C# Codebasis ist fehlgeschlagen.
    goto :end
)
echo [INFO] Build-Vorgang erfolgreich. Alle Windows Subsysteme bereit.

echo.
echo =======================================================================
echo    STARTE ENGINE AUF https://127.0.0.1:6969 - SCHLIESSEN ZUM BEENDEN
echo =======================================================================
echo.

if exist "bin\Release\net9.0\SuperImpersonatorEngine.exe" (
    start /high "" bin\Release\net9.0\SuperImpersonatorEngine.exe
) else if exist "bin\Release\net8.0\SuperImpersonatorEngine.exe" (
    start /high "" bin\Release\net8.0\SuperImpersonatorEngine.exe
) else (
    dotnet run -c Release
)
goto :end

:download_failed
echo [FEHLER] Der Download von FFmpeg ist fehlgeschlagen.
goto :end

:ffmpeg_failed
echo [FEHLER] FFmpeg-Extraktion fehlgeschlagen.
goto :end

:end
echo.
echo [INFO] Engine wurde beendet.
pause
