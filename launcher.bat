@echo off
chcp 65001 > nul
title Super Impersonator app by don24crk - Launcher (C# Core)
cls

echo =======================================================================
echo     SUPER IMPERSONATOR APP ENGINE (C# DSP SYSTEM) - BY DON24CRK
echo =======================================================================
echo.

dotnet --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Das .NET SDK wurde auf diesem System nicht gefunden.
    echo Bitte installiere das .NET SDK 8.0 oder neuer von:
    echo https://dotnet.microsoft.com/download
    echo.
    pause
    exit /b
)

if exist "ffmpeg.exe" (
    echo [INFO] FFmpeg Subsystem bereits betriebsbereit.
    goto :check_dirs
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

:check_dirs
if not exist "models" (
    echo [INFO] Erstelle RVC-Modell-Verzeichnis "\models"...
    mkdir models
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
echo    STARTE ENGINE AUF http://127.0.0.1:8000 - SCHLIESSEN ZUM BEENDEN
echo =======================================================================
echo.

bin\Release\net8.0\SuperImpersonatorEngine.exe
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
