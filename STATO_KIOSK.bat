@echo off
REM ============================================================
REM STATO_KIOSK.bat  (v3 - allineato al flusso v2.4.x)
REM ------------------------------------------------------------
REM Pannello diagnostico dell'avvio automatico del kiosk HR:
REM   1. Registrazione autostart (HKCU Run + cartella Esecuzione automatica)
REM   2. Autologon di Windows (necessario per la ripartenza dopo shutdown)
REM   3. Processo supervisore (kiosk_supervisor.py)
REM   4. Server Flask (health check su porta 3000)
REM   5. Finestra browser kiosk
REM   6. Ultime righe dei log
REM Nessun privilegio di amministratore richiesto.
REM ============================================================

setlocal
set "KIOSK_DIR=%~dp0"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "STARTUP_VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\KioskHR_Autostart.vbs"

echo.
echo ============================================================
echo   KIOSK HR - STATO DEL SISTEMA (flusso v2.4.x)
echo ============================================================
echo.

REM --- 1) Registrazione autostart -------------------------------
echo [1/6] Avvio automatico
reg query "%RUN_KEY%" /v KioskHR_Autostart >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Chiave di registro HKCU\...\Run presente.
) else (
    echo   [MANCA] Chiave HKCU\...\Run assente: eseguire INSTALLA_AUTOSTART.bat
)
if exist "%STARTUP_VBS%" (
    echo   [OK] File in 'Esecuzione automatica' presente.
) else (
    echo   [MANCA] File in 'Esecuzione automatica' assente: eseguire INSTALLA_AUTOSTART.bat
)
echo.

REM --- 2) Autologon ----------------------------------------------
echo [2/6] Logon automatico di Windows
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" /v AutoAdminLogon >nul 2>&1
if %errorLevel% equ 0 (
    echo   [OK] Autologon configurato.
) else (
    echo   [MANCA] Autologon NON configurato: dopo uno shutdown Windows si ferma al login
    echo           e il kiosk non riparte. Vedere PROCEDURA_AVVIO_AUTOMATICO.md, paragrafo 2.
)
echo.

REM --- 3) Supervisore --------------------------------------------
echo [3/6] Supervisore kiosk ^(kiosk_supervisor.py^)
powershell -NoProfile -Command "$n = @(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe' OR Name='python.exe'\" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'kiosk_supervisor' }).Count; if ($n -gt 0) { 'OK - attivo (' + $n + ' processo)' } else { 'MANCA - supervisore non in esecuzione' }"
echo.

REM --- 4) Server Flask -------------------------------------------
echo [4/6] Server Flask ^(porta 3000^)
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri http://127.0.0.1:3000/api/health; 'OK - il server risponde (' + $r.StatusCode + ')' } catch { 'KO - il server NON risponde su http://127.0.0.1:3000' }"
echo.

REM --- 5) Browser kiosk ------------------------------------------
echo [5/6] Finestra browser kiosk
powershell -NoProfile -Command "$n = @(Get-Process -Name chrome,msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }).Count; if ($n -gt 0) { 'OK - finestra browser aperta (' + $n + ')' } else { 'MANCA - nessuna finestra Chrome/Edge aperta' }"
echo.

REM --- 6) Log ------------------------------------------------------
echo [6/6] Ultime righe di logs\kiosk_supervisor.log
powershell -NoProfile -Command "if (Test-Path '%KIOSK_DIR%logs\kiosk_supervisor.log') { Get-Content '%KIOSK_DIR%logs\kiosk_supervisor.log' -Tail 8 } else { 'Nessun log del supervisore presente.' }"
echo.
if exist "%KIOSK_DIR%logs\autostart_error.log" (
    echo [ATTENZIONE] logs\autostart_error.log esiste: errori di avvio registrati.
    powershell -NoProfile -Command "Get-Content '%KIOSK_DIR%logs\autostart_error.log' -Tail 5"
    echo.
)

echo ============================================================
echo   Diagnostica completata
echo ============================================================
echo.
echo Se un punto risulta [MANCA] o [KO]:
echo   - autostart assente  -^> INSTALLA_AUTOSTART.bat
echo   - autologon assente  -^> PROCEDURA_AVVIO_AUTOMATICO.md ^(paragrafo 2^)
echo   - server KO          -^> avvio manuale con START_APP.bat per vedere l'errore
echo.
pause
