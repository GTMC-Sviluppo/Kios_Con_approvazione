@echo off
REM ========================================
REM   Mostra IP e URL Accesso Kiosk
REM ========================================

echo.
echo ========================================
echo   INFORMAZIONI ACCESSO KIOSK HR
echo ========================================
echo.

REM Ottieni IP
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set IP=%%a
    goto :found
)

:found
REM Rimuovi spazi
set IP=%IP: =%

echo Nome PC:  %COMPUTERNAME%
echo IP Kiosk: %IP%  (puo' cambiare, DHCP)
echo.
echo ========================================
echo   URL ACCESSO
echo ========================================
echo.
echo Locale (sul kiosk):
echo   http://localhost:3000
echo.
echo Da altri PC sulla rete (consigliato, non cambia):
echo   http://%COMPUTERNAME%:3000
echo.
echo Da altri PC sulla rete (tramite IP attuale):
echo   http://%IP%:3000
if /i not "%COMPUTERNAME%"=="KIOSK-VW" (
    echo.
    echo NOTA: il PC non si chiama KIOSK-VW. Per rinominarlo, da PowerShell
    echo       come Amministratore:  Rename-Computer -NewName "KIOSK-VW" -Restart
)
echo.
echo ========================================
echo   FIREWALL
echo ========================================
echo.

REM Verifica se regola firewall esiste
netsh advfirewall firewall show rule name="Kiosk HR" >nul 2>&1
if %errorlevel% equ 0 (
    echo Status: Porta 3000 APERTA
    echo La regola firewall esiste gia'
) else (
    echo Status: Porta 3000 CHIUSA
    echo.
    echo Per aprire la porta, esegui come Amministratore:
    echo   netsh advfirewall firewall add rule name="Kiosk HR" dir=in action=allow protocol=TCP localport=3000
    echo.
    set /p APRI="Vuoi aprire la porta ora? (S/N): "
    if /i "%APRI%"=="S" (
        echo.
        echo Apertura porta 3000...
        netsh advfirewall firewall add rule name="Kiosk HR" dir=in action=allow protocol=TCP localport=3000
        if %errorlevel% equ 0 (
            echo OK: Porta aperta con successo!
        ) else (
            echo ERRORE: Esegui questo script come Amministratore
        )
    )
)

echo.
echo ========================================
echo   TEST CONNESSIONE
echo ========================================
echo.
echo 1. Apri browser su altro PC
echo 2. Vai a: http://%COMPUTERNAME%:3000  (oppure http://%IP%:3000)
echo 3. Dovresti vedere la pagina launcher
echo.

pause
