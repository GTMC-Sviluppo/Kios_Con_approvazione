@echo off
REM ============================================================
REM INSTALLA_AUTOSTART.bat  (v2 - SENZA DIRITTI DI AMMINISTRATORE)
REM ------------------------------------------------------------
REM Registra la ripartenza automatica del kiosk HR al logon di
REM Windows, con doppia copertura:
REM   1) chiave di registro HKCU\...\Run  (per-utente, no admin)
REM   2) script nella cartella "Esecuzione automatica" (no admin)
REM Il single-instance lock del supervisore evita doppie partenze.
REM
REM Catena registrata:
REM   Logon -> wscript AVVIO_KIOSK.vbs (nascosto)
REM         -> pythonw kiosk_supervisor.py
REM         -> app.py (Flask, riavviato se crasha)
REM         -> Chrome/Edge --kiosk http://localhost:3000
REM
REM La procedura e' IDEMPOTENTE: rieseguibile senza danni.
REM Tocca SOLO l'hive HKCU dell'utente corrente (sicuro, niente
REM admin, niente modifiche di sistema).
REM ============================================================

setlocal EnableDelayedExpansion
set "INSTALL_LOG=%~dp0logs\autostart_install.log"
if not exist "%~dp0logs" mkdir "%~dp0logs"

echo.
echo ============================================================
echo   KIOSK HR - INSTALLAZIONE AVVIO AUTOMATICO (senza admin)
echo ============================================================
echo.

REM --- Percorsi ---
set "KIOSK_DIR=%~dp0"
if "%KIOSK_DIR:~-1%"=="\" set "KIOSK_DIR=%KIOSK_DIR:~0,-1%"
set "VBS_LAUNCHER=%KIOSK_DIR%\AVVIO_KIOSK.vbs"
set "SUPERVISOR=%KIOSK_DIR%\kiosk_supervisor.py"
set "RUN_KEY=HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
set "RUN_VALUE=KioskHR_Autostart"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_VBS=%STARTUP_DIR%\KioskHR_Autostart.vbs"

echo Directory kiosk   : %KIOSK_DIR%
echo Launcher          : %VBS_LAUNCHER%
echo Supervisore       : %SUPERVISOR%
echo.

REM --- Verifica prerequisiti (NO admin richiesto) ---
set "ERRORS=0"

if not exist "%VBS_LAUNCHER%" (
    echo [ERRORE] AVVIO_KIOSK.vbs non trovato!
    set /a ERRORS+=1
)
if not exist "%SUPERVISOR%" (
    echo [ERRORE] kiosk_supervisor.py non trovato!
    set /a ERRORS+=1
)
if not exist "%KIOSK_DIR%\app.py" (
    echo [ERRORE] app.py non trovato!
    set /a ERRORS+=1
)

where wscript.exe >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] wscript.exe non disponibile!
    set /a ERRORS+=1
)

if %ERRORS% gtr 0 (
    echo.
    echo Installazione annullata: correggere gli errori sopra.
    pause
    exit /b 1
)
echo [OK] Prerequisiti verificati.

REM --- Rimozione del vecchio task amministrativo (se presente) ---
REM Il vecchio sistema usava un task schedulato con privilegi admin:
REM senza admin la rimozione puo' fallire, in tal caso il single-instance
REM lock del supervisore evita comunque doppie partenze del server.
schtasks /query /tn "KioskHR_Watchdog" >nul 2>&1
if %errorLevel% equ 0 (
    echo.
    echo Trovato il vecchio task 'KioskHR_Watchdog' ^(sistema precedente^).
    schtasks /delete /tn "KioskHR_Watchdog" /f >nul 2>&1
    if !errorLevel! equ 0 (
        echo [OK] Vecchio task rimosso.
        echo [%date% %time%] Rimosso vecchio task KioskHR_Watchdog >> "%INSTALL_LOG%"
    ) else (
        echo [AVVISO] Impossibile rimuoverlo senza admin: verra' ignorato,
        echo          ma per una pulizia completa eseguire una volta:
        echo          schtasks /delete /tn KioskHR_Watchdog /f   ^(come admin^)
    )
)

REM --- 1) Registrazione nella chiave HKCU Run (no admin) ---
echo.
echo [1/3] Registrazione in HKCU\...\Run...
reg add "%RUN_KEY%" /v %RUN_VALUE% /t REG_SZ /d "wscript.exe //B //nologo \"%VBS_LAUNCHER%\"" /f >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] Scrittura registro fallita!
    pause
    exit /b 1
)

REM Verifica read-back: il valore deve puntare al nostro VBS
reg query "%RUN_KEY%" /v %RUN_VALUE% 2>nul | findstr /C:"AVVIO_KIOSK.vbs" >nul
if %errorLevel% neq 0 (
    echo [ERRORE] Verifica registro fallita: valore non trovato o errato!
    pause
    exit /b 1
)
echo [OK] Chiave di registro scritta e verificata.

REM --- 2) Copertura nella cartella Esecuzione automatica (no admin) ---
echo [2/3] Copertura cartella 'Esecuzione automatica'...
if not exist "%STARTUP_DIR%" mkdir "%STARTUP_DIR%"

REM Genera la copia con percorso assoluto risolto in fase di installazione.
REM Nota: Chr(34) = virgoletta; evita qualunque ambiguita' di quoting VBS/batch.
> "%STARTUP_VBS%" (
    echo ' KioskHR_Autostart - generato da INSTALLA_AUTOSTART.bat
    echo ' Copia per-utente per la cartella Esecuzione automatica ^(no admin^)
    echo Option Explicit
    echo Dim fso, sh, py, cmd
    echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
    echo Set sh  = CreateObject^("WScript.Shell"^)
    echo If Not fso.FileExists^("%SUPERVISOR%"^) Then WScript.Quit 1
    echo py = "%KIOSK_DIR%\venv\Scripts\pythonw.exe"
    echo If fso.FileExists^(py^) Then
    echo     sh.CurrentDirectory = "%KIOSK_DIR%"
    echo     cmd = Chr^(34^) ^& py ^& Chr^(34^) ^& " " ^& Chr^(34^) ^& "%SUPERVISOR%" ^& Chr^(34^)
    echo     sh.Run cmd, 0, False
    echo Else
    echo     On Error Resume Next
    echo     If Not fso.FolderExists^("%KIOSK_DIR%logs"^) Then fso.CreateFolder^("%KIOSK_DIR%logs"^)
    echo     Set ts = fso.OpenTextFile^("%KIOSK_DIR%logs\autostart_error.log", 8, True^)
    echo     ts.WriteLine Now ^& " - Startup: venv\Scripts\pythonw.exe non trovato, avvio annullato"
    echo     ts.Close
    echo     On Error Goto 0
    echo End If
)

if not exist "%STARTUP_VBS%" (
    echo [ERRORE] Creazione file in Esecuzione automatica fallita!
    pause
    exit /b 1
)
echo [OK] Copia creata: %STARTUP_VBS%

REM --- 3) Controllo autologon di Windows (sola lettura, informativo) ---
echo [3/3] Controllo autologon di Windows...
set "AUTOLOGON="
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command "(Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name AutoAdminLogon -ErrorAction SilentlyContinue).AutoAdminLogon" 2^>nul`) do set "AUTOLOGON=%%v"

if "%AUTOLOGON%"=="1" (
    echo [OK] Autologon ATTIVO: dopo uno spegnimento il kiosk riparte da solo.
) else (
    echo.
    echo ***********************************************************
    echo  [AVVISO] L'accesso automatico di Windows NON risulta attivo.
    echo  Dopo uno spegnimento, Windows si ferma sulla schermata di
    echo  login: l'autostart parte solo DOPO l'accesso dell'utente.
    echo.
    echo  Per il ripristino completamente automatico attivare una
    echo  volta l'accesso automatico ^(richiede admin, operazione di
    echo  sistema standard e non parte di questo installer^):
    echo    netplwiz -^> utente kiosk -^> deseleziona
    echo    'Gli utenti devono inserire un nome utente e una password'
    echo ***********************************************************
)

REM --- Avvio immediato con verifica funzionale (opzionale) ---
echo.
choice /C SN /M "Avviare subito il kiosk per una verifica completa (S/N)"
if errorlevel 2 goto :registro_log
if errorlevel 1 goto :avvio_subito
goto :registro_log

:avvio_subito
echo Avvio del supervisore in corso...
wscript.exe //B //nologo "%VBS_LAUNCHER%"
echo Attesa risposta del server (max 60 secondi)...
set "HEALTH_OK=0"
for /l %%i in (1,1,30) do (
    if !HEALTH_OK!==0 (
        powershell -NoProfile -Command "try { if ((Invoke-WebRequest -Uri 'http://127.0.0.1:3000/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { exit 0 } } catch { exit 1 }" >nul 2>&1
        if !errorLevel! equ 0 (
            set "HEALTH_OK=1"
        ) else (
            timeout /t 2 /nobreak >nul
        )
    )
)
if %HEALTH_OK%==1 (
    echo [OK] Server attivo su http://localhost:3000 — il browser kiosk si
    echo      apre entro pochi secondi ^(il supervisore attende /api/health^).
) else (
    echo [AVVISO] Il server non ha ancora risposto entro 60s.
    echo         Controllare logs\kiosk_supervisor.log e app_debug.log.
)

:registro_log
echo [%date% %time%] INSTALL autostart: Run=%RUN_VALUE% VBS=%VBS_LAUNCHER% STARTUP=%STARTUP_VBS% AUTOLOGON=%AUTOLOGON% >> "%INSTALL_LOG%"

echo.
echo ============================================================
echo   INSTALLAZIONE COMPLETATA
echo ============================================================
echo.
echo Il kiosk HR riparte automaticamente a ogni accesso di Windows:
echo   - registro HKCU Run    : %RUN_VALUE%
echo   - Esecuzione automatica : KioskHR_Autostart.vbs
echo   - se il server crasha  : riavviato dal supervisore
echo   - se il browser chiuso : riaperto in modalita' kiosk
echo.
echo Log supervisore     : logs\kiosk_supervisor.log
echo Log installazione   : logs\autostart_install.log
echo.
echo Per disinstallare: RIMUOVI_AUTOSTART.bat
echo.
pause
