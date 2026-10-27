@echo off
REM ========================================
REM KIOSK HR - Sistema Adeverințe
REM Script di Installazione Automatica
REM Versione: 2.2.0
REM Data: 2026-01-09
REM ========================================

REM IMPORTANTE: Imposta la directory corrente a quella dello script
REM Usa pushd per gestire correttamente UAC e admin rights
pushd "%~dp0"

echo.
echo ========================================
echo   KIOSK HR - Installazione Sistema
echo   Versione 2.2.0
echo ========================================
echo.
echo Directory installazione: %CD%
echo.

REM Verifica che NON siamo in System32 (errore comune con UAC)
echo %CD% | findstr /I "System32" >nul
if %errorLevel% equ 0 (
    echo.
    echo [ERRORE CRITICO] Directory corrente non valida!
    echo Lo script e' stato eseguito da: %CD%
    echo.
    echo SOLUZIONE:
    echo 1. Navigare nella cartella del progetto in Esplora Risorse
    echo 2. Tenere premuto SHIFT e fare click destro in uno spazio vuoto
    echo 3. Selezionare "Apri finestra PowerShell qui come amministratore"
    echo 4. Eseguire: .\INSTALLA.bat
    echo.
    echo OPPURE
    echo.
    echo 1. Copiare la cartella del progetto in C:\Temp
    echo 2. Eseguire INSTALLA.bat da li
    echo.
    pause
    exit /b 1
)

REM Verifica che app.py esista (siamo nella directory giusta)
if not exist "app.py" (
    echo.
    echo [ERRORE] File app.py non trovato!
    echo Directory corrente: %CD%
    echo.
    echo Questa NON sembra essere la directory del progetto Kiosk HR.
    echo Assicurarsi di eseguire lo script dalla directory contenente app.py
    echo.
    pause
    exit /b 1
)

REM Verifica privilegi amministratore
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRORE] Questo script richiede privilegi di amministratore.
    echo Fare clic destro e selezionare "Esegui come amministratore"
    pause
    exit /b 1
)

echo [1/8] Verifica Python - 3.11 riferimento, 3.12/3.13 supportati...
set "PY_CMD="
py -3.11 --version >nul 2>&1
if %errorLevel% equ 0 (
    set "PY_CMD=py -3.11"
    echo [OK] Python 3.11 trovato - versione di riferimento
    goto :py_pronto
)
py -3.12 --version >nul 2>&1
if %errorLevel% equ 0 (
    set "PY_CMD=py -3.12"
    echo [AVVISO] Trovato Python 3.12 - supportato, versione di riferimento e' la 3.11
    goto :py_pronto
)
py -3.13 --version >nul 2>&1
if %errorLevel% equ 0 (
    set "PY_CMD=py -3.13"
    echo [AVVISO] Trovato Python 3.13 - supportato, versione di riferimento e' la 3.11
    goto :py_pronto
)
echo [ERRORE] Nessun Python 3.11, 3.12 o 3.13 trovato tramite il py launcher!
echo.
echo Installare Python 3.11 da:
echo   https://www.python.org/downloads/release/python-3119/
echo.
echo IMPORTANTE durante l'installazione:
echo   - selezionare "Add Python to PATH"
echo   - lasciare selezionato "py launcher"
echo.
echo Verifica con: py -3.11 --version
pause
exit /b 1

:py_pronto

echo.
echo [2/8] Creazione ambiente virtuale...
if exist venv (
    echo [INFO] Ambiente virtuale esistente trovato, lo rimuovo...
    rmdir /s /q venv
)
%PY_CMD% -m venv venv
if %errorLevel% neq 0 (
    echo [ERRORE] Impossibile creare ambiente virtuale
    pause
    exit /b 1
)
echo [OK] Ambiente virtuale creato

echo.
echo [3/8] Attivazione ambiente virtuale...
call venv\Scripts\activate.bat
if %errorLevel% neq 0 (
    echo [ERRORE] Impossibile attivare ambiente virtuale
    pause
    exit /b 1
)
echo [OK] Ambiente virtuale attivato

echo.
echo [4/8] Aggiornamento pip...
echo [INFO] Questo potrebbe richiedere 30-60 secondi...
REM Usa --no-cache-dir per evitare problemi e mostra output per monitorare
python -m pip install --upgrade pip --no-cache-dir 2>nul
if %errorLevel% neq 0 (
    echo [AVVISO] Aggiornamento pip fallito, procedo con versione attuale
    echo [INFO] Questo non impedisce l'installazione delle dipendenze
) else (
    echo [OK] pip aggiornato
)

echo.
echo [5/8] Installazione dipendenze Python...
echo [INFO] Questo potrebbe richiedere alcuni minuti, attendere...
echo.

REM IMPORTANTE: Installa prima Pillow con wheel pre-compilata
echo [INFO] Fase 1/2: Installazione Pillow 10.4.0 (con wheel pre-compilata)...
pip install Pillow==10.4.0 --only-binary :all:
if %errorLevel% neq 0 (
    echo.
    echo [ERRORE] Installazione Pillow fallita
    echo [INFO] Pillow richiede wheel pre-compilata non disponibile
    echo.
    echo SOLUZIONE ALTERNATIVA:
    echo 1. Aprire PowerShell come amministratore
    echo 2. Attivare venv: .\venv\Scripts\Activate.ps1
    echo 3. Eseguire: pip install Pillow==10.4.0 --only-binary :all:
    echo.
    echo Se persiste, provare versione diversa:
    echo   pip install Pillow==10.3.0 --only-binary :all:
    echo.
    pause
    exit /b 1
)
echo [OK] Pillow installato

echo.
echo [INFO] Fase 2/2: Installazione altre dipendenze...
echo [INFO] Pacchetti: Flask, reportlab, pyodbc, cryptography, ecc.
echo.
pip install -r requirements.txt
if %errorLevel% neq 0 (
    echo.
    echo [ERRORE] Installazione dipendenze fallita
    echo [INFO] Verificare la connessione internet e riprovare
    pause
    exit /b 1
)
echo.
echo [OK] Dipendenze installate

echo.
echo [6/8] Verifica file di configurazione...
if not exist "db_config.enc" (
    echo [AVVISO] File db_config.enc non trovato
    echo [INFO] Sarà necessario configurare la connessione al database
)
if not exist "email_credentials.enc" (
    echo [AVVISO] File email_credentials.enc non trovato
    echo [INFO] Sarà necessario configurare le credenziali email
)
if not exist "encryption_key.key" (
    echo [AVVISO] File encryption_key.key non trovato
    echo [INFO] Sarà necessario generare le chiavi di crittografia
)
if not exist "email_key.key" (
    echo [AVVISO] File email_key.key non trovato
)
echo [OK] Verifica configurazione completata

echo.
echo [7/8] Creazione directory necessarie...
if not exist "temp" mkdir temp
if not exist "Images" mkdir Images
echo [OK] Directory create

echo.
echo [8/8] Verifica componenti aggiuntivi...
if not exist "IDReader.dll" (
    echo [AVVISO] IDReader.dll non trovato - Lettore RFID non disponibile
)
if not exist "DejaVuSans.ttf" (
    echo [AVVISO] Font DejaVuSans.ttf non trovato
)
if not exist "DejaVuSans-Bold.ttf" (
    echo [AVVISO] Font DejaVuSans-Bold.ttf non trovato
)
if not exist "logo.png" (
    echo [AVVISO] logo.png non trovato
)
if not exist "GTMC.png" (
    echo [AVVISO] GTMC.png non trovato
)
echo [OK] Verifica componenti completata

echo.
echo ========================================
echo   INSTALLAZIONE COMPLETATA!
echo ========================================
echo.
echo Prossimi passi:
echo.
echo 1. Configurare la connessione al database (se necessario)
echo    Eseguire: python setup.py
echo.
echo 2. Avviare l'applicazione:
echo    Eseguire: START_APP.bat
echo.
echo 3. Per l'avvio automatico dopo lo shutdown (modalita' kiosk):
echo    Eseguire: INSTALLA_AUTOSTART.bat
echo    Procedura completa: PROCEDURA_AVVIO_AUTOMATICO.md
echo.
echo 4. Diagnostica stato kiosk: STATO_KIOSK.bat
echo.
echo 5. Consultare README.md per maggiori informazioni
echo.
echo ========================================
echo.

pause
