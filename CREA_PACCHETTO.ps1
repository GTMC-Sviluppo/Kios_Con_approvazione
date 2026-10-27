# ========================================
# KIOSK HR - Creazione Pacchetto Deploy
# Versione: 2.4.3
# Data: 2026-10-27
# ========================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  KIOSK HR - Creazione Pacchetto" -ForegroundColor Cyan
Write-Host "  Versione 2.4.3" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Imposta nome pacchetto con timestamp
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$packageName = "Kiosk_HR_v2.4.3_$timestamp.zip"

Write-Host "[1/7] Preparazione directory temporanea..." -ForegroundColor Yellow
if (Test-Path "deploy_temp") {
    Remove-Item -Recurse -Force "deploy_temp"
}
New-Item -ItemType Directory -Path "deploy_temp" | Out-Null
Write-Host "[OK] Directory creata" -ForegroundColor Green

Write-Host ""
Write-Host "[2/7] Copia file applicazione..." -ForegroundColor Yellow
$pythonFiles = @(
    "app.py",
    "absence_report.py",
    "absence_request.py",
    "badge_reader.py",
    "certificate_generator.py",
    "company_config.py",
    "config_manager.py",
    "db_connection.py",
    "digital_signature.py",
    "email_connector.py",
    "kiosk_request_logger.py",
    "kiosk_supervisor.py",
    "kiosk_watchdog.py",
    "offline_logger.py",
    "pdf_digital_signer.py",
    "pdf_printer.py",
    "printer_keepalive.py",
    "rfid_reader.py",
    "service_kiosk_reports.py",
    "service_wrapper.py",
    "setup.py",
    "update_signature.py",
    "utils.py",
    "windows_cert_signer.py",
    "requirements.txt"
)

$copiedPython = 0
foreach ($file in $pythonFiles) {
    if (Test-Path $file) {
        Copy-Item $file "deploy_temp\" -Force
        $copiedPython++
    }
    else {
        Write-Host "  [ATTENZIONE] File mancante: $file" -ForegroundColor Yellow
    }
}
Write-Host "[OK] File Python copiati ($copiedPython/$($pythonFiles.Count) file)" -ForegroundColor Green

Write-Host ""
Write-Host "[3/7] Copia templates e static..." -ForegroundColor Yellow
if (Test-Path "templates") {
    Copy-Item -Recurse "templates" "deploy_temp\templates" -Force
}
if (Test-Path "static") {
    Copy-Item -Recurse "static" "deploy_temp\static" -Force
}
Write-Host "[OK] Templates e static copiati" -ForegroundColor Green

Write-Host ""
Write-Host "[4/7] Copia file configurazione e risorse..." -ForegroundColor Yellow
$resourceFiles = @(
    "DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf",
    "logo.png",
    "GTMC.png",
    "IDReader.dll",
    "print_config.json",
    "encryption_key.key",
    "email_key.key",
    "db_config.enc",
    "email_credentials.enc"
)

$copiedResources = 0
$missingResources = @()
foreach ($file in $resourceFiles) {
    if (Test-Path $file) {
        Copy-Item $file "deploy_temp\" -Force
        $copiedResources++
    }
    else {
        $missingResources += $file
    }
}

Write-Host "[OK] File configurazione copiati ($copiedResources/$($resourceFiles.Count) file)" -ForegroundColor Green

if ($missingResources.Count -gt 0) {
    Write-Host ""
    Write-Host "AVVISO: File di configurazione mancanti nel deploy:" -ForegroundColor Red
    foreach ($file in $missingResources) {
        Write-Host "  - $file" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Questi file sono CRITICI per il funzionamento:" -ForegroundColor Yellow
    Write-Host "  encryption_key.key   -> Generato da setup.py (NECESSARIO)" -ForegroundColor Yellow
    Write-Host "  email_key.key        -> Generato da setup.py (NECESSARIO)" -ForegroundColor Yellow
    Write-Host "  db_config.enc        -> Generato da setup.py (NECESSARIO)" -ForegroundColor Yellow
    Write-Host "  email_credentials.enc -> Generato da setup.py (NECESSARIO)" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""
Write-Host "[5/7] Copia script e documentazione..." -ForegroundColor Yellow
$scriptFiles = @(
    "INSTALLA.bat",
    "START_APP.bat",
    "START_KIOSK_REPORTS_SERVICE.bat",
    "AGGIORNA_FIRMA.bat",
    "MOSTRA_IP_KIOSK.bat",
    "STATO_KIOSK.bat",
    "INSTALLA_AUTOSTART.bat",
    "RIMUOVI_AUTOSTART.bat",
    "AVVIO_KIOSK.vbs"
)

$docFiles = @(
    "README.md",
    "CHANGELOG.md",
    "GUIDA_INSTALLAZIONE.md",
    "INSTALLAZIONE_MANUALE.md",
    "DEPLOYMENT.md",
    "GUIDA_RAPIDA.md",
    "GUIDA_RFID.md",
    "GUIDA_KIOSK_FULLSCREEN.md",
    "GUIDA_NEWS_SLIDESHOW.md",
    "CONFIGURAZIONE_RETE.md",
    "STAMPA_AUTOMATICA.md",
    "PROCEDURA_AVVIO_AUTOMATICO.md",
    "IMPLEMENTAZIONE_ASSENZE_URGENTI_SPECIALI.md"
)

# Copia la migrazione SQL (assenze urgenti/speciali: Employee + Employees)
if (Test-Path "sql") {
    New-Item -ItemType Directory -Path "deploy_temp\sql" -Force | Out-Null
    Copy-Item "sql\*" "deploy_temp\sql\" -Force
    Write-Host "[OK] Migrazioni SQL copiate (sql/)" -ForegroundColor Green
}

$copiedDocs = 0
foreach ($file in ($scriptFiles + $docFiles)) {
    if (Test-Path $file) {
        Copy-Item $file "deploy_temp\" -Force
        $copiedDocs++
    }
}
Write-Host "[OK] Script e documentazione copiati ($copiedDocs file)" -ForegroundColor Green

Write-Host ""
Write-Host "[6/7] Creazione directory e copia immagini..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path "deploy_temp\temp" -Force | Out-Null
New-Item -ItemType Directory -Path "deploy_temp\Images" -Force | Out-Null

if (Test-Path "Images") {
    $imagesCopied = 0
    Get-ChildItem "Images" -File | Where-Object { 
        $_.Name -match '^[xXsS]' 
    } | ForEach-Object {
        Copy-Item $_.FullName "deploy_temp\Images\" -Force
        $imagesCopied++
    }
    Write-Host "[OK] Immagini slideshow copiate ($imagesCopied immagini X* e S*)" -ForegroundColor Green
}
else {
    Write-Host "[INFO] Directory Images non trovata" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[7/7] Creazione archivio ZIP..." -ForegroundColor Yellow

# Rimuovi vecchio pacchetto se esiste
if (Test-Path $packageName) {
    Remove-Item $packageName -Force
}

try {
    # Crea ZIP usando Compress-Archive
    Compress-Archive -Path "deploy_temp\*" -DestinationPath $packageName -CompressionLevel Optimal -Force
    
    if (Test-Path $packageName) {
        $packageInfo = Get-Item $packageName
        $sizeMB = [math]::Round($packageInfo.Length / 1MB, 2)
        
        Write-Host "[OK] Pacchetto creato: $packageName" -ForegroundColor Green
        
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "  PACCHETTO CREATO CON SUCCESSO!" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host ""
        Write-Host "File: " -NoNewline -ForegroundColor Cyan
        Write-Host $packageName -ForegroundColor White
        Write-Host "Dimensione: " -NoNewline -ForegroundColor Cyan
        Write-Host "$sizeMB MB" -ForegroundColor White
        Write-Host "Percorso: " -NoNewline -ForegroundColor Cyan
        Write-Host $packageInfo.FullName -ForegroundColor Gray
        Write-Host ""
        
        # Conta file nel pacchetto
        $totalFiles = (Get-ChildItem -Path "deploy_temp" -Recurse -File).Count
        Write-Host "Contenuto del pacchetto:" -ForegroundColor Yellow
        Write-Host "  - File totali: $totalFiles" -ForegroundColor White
        Write-Host "  - Applicazione Python completa" -ForegroundColor White
        Write-Host "  - Templates HTML e CSS" -ForegroundColor White
        Write-Host "  - Script di installazione" -ForegroundColor White
        Write-Host "  - Documentazione completa" -ForegroundColor White
        Write-Host "  - Immagini slideshow (X* e S*)" -ForegroundColor White
        Write-Host "  - Font e loghi" -ForegroundColor White
        Write-Host ""
        
        Write-Host "PROSSIMI PASSI:" -ForegroundColor Magenta
        Write-Host "  1. Trasferire il file ZIP sulla macchina target" -ForegroundColor White
        Write-Host "  2. Estrarre il contenuto" -ForegroundColor White
        Write-Host "  3. Eseguire INSTALLA.bat come Amministratore" -ForegroundColor White
        Write-Host "  4. Configurare database e email: python setup.py" -ForegroundColor White
        Write-Host "  5. Avvio manuale: START_APP.bat - Autostart: INSTALLA_AUTOSTART.bat" -ForegroundColor White
        Write-Host "     (procedura completa: PROCEDURA_AVVIO_AUTOMATICO.md)" -ForegroundColor White
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        
    }
    else {
        throw "File ZIP non creato"
    }
    
}
catch {
    Write-Host "[ERRORE] Impossibile creare pacchetto ZIP" -ForegroundColor Red
    Write-Host "Dettagli errore: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Prova a:" -ForegroundColor Yellow
    Write-Host "  1. Chiudere tutti i file aperti nella directory" -ForegroundColor White
    Write-Host "  2. Eseguire PowerShell come Amministratore" -ForegroundColor White
    Write-Host "  3. Verificare permessi sulla directory" -ForegroundColor White
    exit 1
}

# Pulizia
Write-Host ""
Write-Host "Pulizia file temporanei..." -ForegroundColor Yellow
Remove-Item -Recurse -Force "deploy_temp"
Write-Host "[OK] Pulizia completata" -ForegroundColor Green

Write-Host ""
Write-Host "Premere un tasto per continuare..." -ForegroundColor Gray
if (-not [Console]::IsInputRedirected) {
    # Pausa solo quando lanciato interattivamente con un doppio clic
    try { $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown") } catch {}
}
