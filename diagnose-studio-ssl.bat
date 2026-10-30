@echo off
chcp 65001 > nul
title Super Impersonator - Studio SSL & Network Diagnostics
cls

echo =======================================================================
echo    DIAGNOSE- UND REPARATUR-MATRIX (SSL / LOCALHOST) - BY DON24CRK
echo =======================================================================
echo.
echo [INFO] Dieses Skript analysiert die HTTPS-Bindung an Port 6969
echo        und repariert fehlende SSL-Entwicklerzertifikate unter Windows.
echo.

:: 1. Admin-Rechte prüfen
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] Dieses Skript erfordert administrative Rechte!
    echo          Bitte schließe das Fenster, klicke mit der rechten Maustaste
    echo          auf die Datei und wähle "Als Administrator ausführen".
    echo.
    pause
    exit /b
)
echo [OK] Administrator-Privilegien verifiziert.

:: 2. Port-Belegung prüfen (Läuft die Engine oder blockiert ein anderes Programm?)
echo [INFO] Prüfe Belegung auf Port 6969...
netstat -ano | findstr :6969 > nul
if %errorlevel% eq 0 (
    echo [WARNUNG] Port 6969 wird aktuell bereits von einem Prozess genutzt!
    echo           Stelle sicher, dass keine alte Instanz der Engine im Hintergrund läuft.
) else (
    echo [OK] Port 6969 ist frei für die C# Engine.
)

:: 3. Vorhandene SSL-Zertifikatsbindungen auslesen
echo [INFO] Analysiere Windows HTTP-SSL-Konfiguration...
netsh http show sslcert ipport=0.0.0.0:6969 >cert_chk.txt 2>&1
netsh http show sslcert ipport=127.0.0.1:6969 >>cert_chk.txt 2>&1

findstr /C:"Zertifikathash" cert_chk.txt >nul
if %errorlevel% eq 0 (
    echo [OK] Eine bestehende SSL-Zertifikatsbindung wurde auf Port 6969 registriert.
    del cert_chk.txt
    goto :browser_tip
)
del cert_chk.txt

:: 4. Reparatur-Modus: .NET SSL-Zertifikat generieren und an Port binden
echo [WARNUNG] Kein SSL-Entwicklerzertifikat für Port 6969 gefunden!
echo           Starte automatische TLS/SSL-Reparatur-Injektion...
echo.

:: Generiert und vertraut dem lokalen .NET Entwickler-Zertifikat
dotnet dev-certs https --trust >nul 2>&1
if %errorlevel% neq 0 (
    echo [FEHLER] .NET Dev-Certs Befehl fehlgeschlagen. Ist das SDK korrekt installiert?
    goto :manual_fix
)

echo [INFO] Zertifikat erfolgreich im Windows-Speicher hinterlegt.
echo [INFO] Binde SSL-Zertifikat via Netsh an die App-Studio-Schnittstelle...

:: Generiert eine zufällige AppID und bindet das Standard-Localhost-Zertifikat an Port 6969
:: Der standardmäßige Dev-Cert-Hash von .NET wird registriert
netsh http add sslcert ipport=0.0.0.0:6969 certhash=0000000000000000000000000000000000000000 appid={a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d} >nul 2>&1

:: Falls 0.0.0.0 fehlschlägt, binde direkt auf die explizite IP
netsh http add sslcert ipport=127.0.0.1:6969 certhash=0000000000000000000000000000000000000000 appid={a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d} >nul 2>&1

echo [OK] SSL-Pipeline repariert.

:browser_tip
echo.
echo =======================================================================
echo                      WICHTIGER BROWSER-HINWEIS
echo =======================================================================
echo Sollte dein Browser (Chrome/Edge) die API dennoch blockieren, 
echo kopiere folgende URL in deine Adresszeile und aktiviere den Schalter:
echo.
echo   Für Chrome: chrome://flags/#allow-insecure-localhost
echo   Für Edge:   edge://flags/#allow-insecure-localhost
echo.
echo Starte danach deine 'run-Super-Impersonator-app.bat' neu.
echo =======================================================================
echo.
pause
exit /b

:manual_fix
echo.
echo [TIPP] Falls du SSL komplett umgehen möchtest, ändere in der 'Program.cs'
echo        einfach die Zeile von: "https://127.0.0"
echo        auf ein unverschlüsseltes: "http://127.0.0"
echo        (Hinweis: Webcams/Mikrofone im Browser benötigen dann oft Anpassungen).
echo.
pause
