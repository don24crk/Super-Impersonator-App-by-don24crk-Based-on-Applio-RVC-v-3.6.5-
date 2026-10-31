@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul
title Super Impersonator Launcher
cls

echo Startvorgang laeuft
echo.

set "MINGW_PATH=C:\Program Files\mingw-w64\x86_64-8.1.0-win32-seh-rt_v6-rev0\mingw64\bin"

if exist "%MINGW_PATH%" goto :path_ok
echo FEHLER Compiler Pfad wurde nicht gefunden
pause
exit /b

:path_ok
set "PATH=%MINGW_PATH%;%PATH%"
echo Compiler Pfad geladen

where g++ >nul 2>&1
if %errorlevel% neq 0 goto :compiler_error
echo C++ Compiler verifiziert
goto :check_cmake

:compiler_error
echo FEHLER C++ Compiler konnte im Pfad nicht verifiziert werden
pause
exit /b

:check_cmake
where cmake >nul 2>&1
if %errorlevel% neq 0 goto :cmake_error
echo CMake verifiziert
goto :check_ffmpeg

:cmake_error
echo FEHLER CMake wurde im System nicht gefunden
pause
exit /b

:check_ffmpeg
if exist "ffmpeg.exe" goto :ffmpeg_ok
echo FFmpeg fehlt. Starte Download
powershell -Command "& {Invoke-WebRequest -Uri 'https://gyan.dev' -OutFile 'ffmpeg.zip'}"
if %errorlevel% neq 0 goto :ffmpeg_fail

echo Entpacke Audio Codecs
powershell -Command "& {Expand-Archive -Path 'ffmpeg.zip' -DestinationPath 'ffmpeg_temp' -Force}"
for /r "ffmpeg_temp" %%i in (ffmpeg.exe) do move "%%i" "." >nul 2>&1
if exist "ffmpeg.zip" del "ffmpeg.zip"
if exist "ffmpeg_temp" rmdir /s /q "ffmpeg_temp"
goto :ffmpeg_ok

:ffmpeg_fail
echo WARNUNG Download fehlgeschlagen

:ffmpeg_ok
if not exist "models" mkdir "models"

echo Saubere altes Build Verzeichnis
if exist "build" rmdir /s /q "build"
mkdir "build"
cd build

echo Konfiguriere Build mit MinGW-w64
cmake -G "MinGW Makefiles" -DCMAKE_CXX_COMPILER="C:/Program Files/mingw-w64/x86_64-8.1.0-win32-seh-rt_v6-rev0/mingw64/bin/g++.exe" -DCMAKE_C_COMPILER="C:/Program Files/mingw-w64/x86_64-8.1.0-win32-seh-rt_v6-rev0/mingw64/bin/gcc.exe" -DCMAKE_BUILD_TYPE=Release ..
if %errorlevel% neq 0 goto :cmake_fail

echo Kompiliere Anwendung
cmake --build . --config Release
if %errorlevel% neq 0 goto :build_fail

cd ..
echo Build erfolgreich abgeschlossen
goto :start_engine

:cmake_fail
echo FEHLER CMake Konfiguration fehlgeschlagen
cd ..
pause
exit /b

:build_fail
echo FEHLER Kompilierung fehlgeschlagen
cd ..
pause
exit /b

echo Befreie Port 6969 von alten Prozessen...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :6969') do taskkill /f /pid %%a >nul 2>&1

:start_engine
echo STARTE C++ ENGINE PORT 6969
echo.

if exist "build\SuperImpersonatorEngine.exe" goto :run_exe
echo FEHLER Anwendung wurde gebaut aber die exe wurde nicht gefunden
pause
exit /b

:run_exe
start /high "" "build\SuperImpersonatorEngine.exe"
pause
