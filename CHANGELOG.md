# Changelog - Kiosk HR Adeverente

Tutte le modifiche rilevanti al progetto saranno documentate in questo file.

## [2.5.0] - 2026-11-06

### Motivi speciali da tabella, con giorni per evento

> **Prima di aggiornare i kiosk** eseguire sul database lo script idempotente
> `sql/MIGRAZIONE_MOTIVI_SPECIALI.sql`: senza la tabella dei motivi l'elenco
> resta vuoto e non si possono inviare richieste per motivi speciali.

- **Nuova tabella `Employee.dbo.SpecialAbsenceMotives`**: nome dell'evento
  (rumeno/italiano), giorni lavorativi massimi **per evento**, etichetta dei
  giorni mostrata nel kiosk, obbligo e scadenza dei documenti, durata libera.
  Nessun numero di giorni è più scritto nel codice. Motivi iniziali:
  - Căsătorie salariat (matrimonio del dipendente) – 5 zile lucrătoare
  - Căsătorie copil (matrimonio di un figlio/a) – 3 zile lucrătoare
  - Deces soț/soție, copil, părinți, socri – 3 zile lucrătoare
  - Deces bunic, frate, soră – 1 zi lucrătoare
  - Donare sânge – 1 zi de permis (în ziua donării)
  - Obligații civice – durată conform documentației (senza tetto)
- **Kiosk (`/cerere`)**: l'elenco dei motivi arriva da `GET /api/special-motives`
  e mostra nome e giorni di ogni evento; tolto "Alt motiv special" (testo libero).
  Il limite per evento è controllato a video e all'invio
  (`validate_special_motive`); il motivo scelto è salvato in
  `AbsenceRequestes.SpecialReasonId` (il nome resta in `SpecialReason`).
- **Tolto il tetto annuo di 5 giorni** per i motivi speciali
  (`AbsenceRules.MaxDaysPerYear = NULL` per il tipo 19): il limite è per evento.
- **Assenze urgenti (tipo 18)**: invariato il limite di **10 giorni
  lavorativi/anno**; l'etichetta "max. X zile/an" ora viene dal database.
- **Documenti**: scadenza presa dal motivo (`DocsDeadlineDays`); niente
  scadenza né avviso per i motivi senza obbligo di documenti. Email, PDF,
  motivazione di annullamento e notifica HR non riportano più "5 zile" fisso.
- `request.js` caricato con `?v=2.5.0` per forzare l'aggiornamento della cache
  nei browser dei kiosk.

---

## [2.4.3] - 2026-10-27

### Richieste assenza solo ai Manager

- **Destinatari email** (`get_manager_emails`): la richiesta arriva solo ai
  **Manager** (`FunctionCode >= 70`) dello stesso centro di costo, con codice
  superiore al richiedente. Prima arrivava a chiunque avesse un FunctionCode
  superiore (es. in PURCHASING a tutti i colleghi Technician/Office). Senza
  Manager nel CDC si usa `FALLBACK_EMAIL`. Soglia nella costante
  `MANAGER_FUNCTION_CODE` in `absence_request.py`.
- **Pagina "Aprobare Cereri"**: login consentito solo con `FunctionCode >= 70`
  (prima `> 61`, includeva ENGINEERING 65); il manager vede le richieste di
  tutti i subordinati del CDC (`FunctionCode` inferiore al suo) invece dei soli
  codici 40-69; stessa verifica prima di approvare/rifiutare.
- **`index.html` (Adeverinte)**: corretta la nota del pannello istruzioni, che
  riportava il testo delle richieste di assenza.

---

## [2.4.2] - 2026-10-27

### 🔒 Sicurezza, pulizia repository e procedura di avvio automatico

#### Sicurezza (app)

- **`/api/print-pdf`**: chiusa la **path traversal** (`<path:filename>` permetteva
  di leggere qualunque file, es. chiavi/`.enc`): ora solo basename, solo `.pdf`,
  solo dentro `temp/` (stessa protezione già presente su `/api/delete-pdf`).
- **Chiavi e credenziali fuori dal repository**: rimosse dal tracking git
  `encryption_key.key`, `email_key.key`, `db_config.enc`, `email_credentials.enc`,
  `certificate_old.pfx`; `.gitignore` ora blocca `*.key`, `*.enc`, `*.pfx`,
  `logs/`, zip di release, `build/`, `dist/`. ⚠️ La history git conserva i file
  storici: **ruotare la password del DB SQL Server e le credenziali SMTP**.
- **SECRET_KEY**: non più placeholder committato — chiave random generata al
  primo avvio e salvata in `secret_key.key` (gitignored).
- **Server di produzione**: `app.py` usa **waitress** (WSGI) se installata
  (aggiunta a `requirements.txt`), con fallback sul server di sviluppo Flask.
- **Rate limiting** sul login manager (5 tentativi falliti per IP / 15 min).
- **Token manager con scadenza**: TTL 60 min sliding con pulizia periodica.
- **XSS stored rimosso**: `showToast` in `app.js` usa `textContent`;
  `approval.js` escapa i campi dal DB (`escapeHtml`) e sanifica la classe CSS
  dello stato.
- **Errori generici verso il client**: le 24 risposte `500` non espongono più
  `str(e)` (dettagli solo nei log).
- **`/api/add-reason`** richiede ora autenticazione manager (non era usato dal
  frontend); validazione lunghezza motivo.
- **Header di sicurezza**: `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy` su ogni risposta.

#### Pulizia repository

- Rimossi **7 script legacy**: `AVVIA_TUTTO.BAT`, `INSTALLA_KIOSK.bat`,
  `START_KIOSK.bat`, `START_KIOSK_EDGE.bat`, `START_KIOSK_FULLSCREEN.bat`,
  `START_SISTEMA_KIOSK.bat`, `Lancia_come_adm.vbs` (percorso rotto
  `C:\Users\gtesta\...`). Riferimenti aggiornati in `CREA_PACCHETTO.ps1`,
  `INSTALLA.bat` e README.
- Fuori dal repo anche zip di release storici, PDF/artefatti di test, log e
  file runtime (`reading_badge_time.json`, `logs/offline_events.json`).

#### Avvio automatico dopo shutdown (procedura v2)

- **`kiosk_supervisor.py`**: corretto il crash che abbatteva l'intero
  supervisore quando Chrome/Edge non risultano installati (`launch_browser(None)`);
  creazione di `logs/` all'avvio; qualunque eccezione imprevista viene loggata
  e il ciclo riprende invece di terminare.
- **`AVVIO_KIOSK.vbs`** (e VBS generato dall'installer): niente più fallback
  silenzioso a un `pythonw` globale senza Flask — scrive la causa in
  `logs/autostart_error.log` ed esce.
- **`STATO_KIOSK.bat`** (riscritto): pannello diagnostico del flusso v2.4.x
  (chiave Run, file Startup, autologon, supervisore, health su porta 3000,
  finestra browser, log) — la versione precedente controllava il sistema
  deprecato (task `KioskHR_Watchdog`, porta 5000, `wmic`).
- **`PROCEDURA_AVVIO_AUTOMATICO.md`** (nuova, sostituisce
  `GUIDA_RIAVVIO_AUTOMATICO_KIOSK.md`): prerequisiti BIOS (Restore AC Power
  Loss), autologon con caveat Windows Hello/BitLocker, catena di ripartenza,
  checklist di verifica (incluso `STATO_KIOSK.bat`) e matrice di risoluzione
  problemi.

#### Connessione database e accesso in rete

- **`db_connection.py`**: connessione resiliente all'istanza nominata
  `roghipsql01.vandewiele.local\emsreset`. Se SQL Browser (UDP 1434) non
  risponde, ritenta su `host,1434`; se il nome DNS non e' risolvibile, ritenta
  su `10.140.1.4,1434`. Porta e IP sovrascrivibili con `port`/`server_ip` in
  config o con le variabili d'ambiente `DB_PORT`/`DB_SERVER_IP`.
- Rimosso l'attributo non valido `Connection Timeout` dalla connection string
  (avviso "Invalid connection string attribute"); il timeout resta su
  `pyodbc.connect(timeout=8)`.
- **`MOSTRA_IP_KIOSK.bat`**: mostra il nome PC e l'URL `http://NOMEPC:3000`
  (stabile anche con IP DHCP), con promemoria per rinominare il PC in `KIOSK-VW`.

---

## [2.4.1] - 2026-10-16

### 🔄 Ripartenza automatica del kiosk dopo spegnimento — SENZA admin

Ricostruito il sistema di avvio automatico: dopo uno spegnimento (anche per
interruzione di corrente) il kiosk HR riparte da solo **in modalità kiosk**,
con registrazione **senza privilegi di amministratore**.

- **`kiosk_supervisor.py`** (nuovo): supervisore che mantiene in vita l'intero
  kiosk — avvia `app.py` (Python del venv se presente), attende `/api/health`,
  apre Chrome/Edge `--kiosk --incognito` (niente prompt "ripristina pagine?"
  dopo un blackout), riavvia il server se crasha (backoff dopo crash ripetuti),
  riapre la finestra kiosk se viene chiusa. Single-instance tramite socket-lock
  locale 127.0.0.1:39731. Log rotante su `logs/kiosk_supervisor.log`.
- **`AVVIO_KIOSK.vbs`** (nuovo): launcher nascosto auto-locante (venv prima,
  PATH poi) — nessuna finestra console.
- **`INSTALLA_AUTOSTART.bat`** (riscritto): registrazione **doppia e senza
  admin** — valore `KioskHR_Autostart` in `HKCU\...\Run` + script generato nella
  cartella *Esecuzione automatica*. Verifica con read-back del registro,
  controllo informativo dell'autologon di Windows, avvio di prova con health
  check, log su `logs/autostart_install.log`. Idempotente; rimuove il vecchio
  task `KioskHR_Watchdog` quando possibile.
- **`RIMUOVI_AUTOSTART.bat`** (riscritto): rimozione pulita senza admin
  (registro + Startup + vecchio task), arresto processi su conferma; usa
  PowerShell CIM al posto di `wmic` (non più disponibile su Windows 11 recenti).
- Guida operativa: **`GUIDA_RIAVVIO_AUTOMATICO_KIOSK.md`**.
- Test eseguiti: py_compile, lock single-instance, scoperta browser, health
  check, VBS statico e generato (comando corretto e quotato), round-trip
  `reg add`/`reg query`.

---

## [2.4.0] - 2026-10-16

### 🚨 Nuovi tipi di assenza: urgenti (recuperabili) e motivi speciali

**Assenze urgenti** (`Invoire urgenta (recuperabila)`, IDRequestType 18):
- Diritto per legge a **10 giorni/anno** per dipendente (parametro `AbsenceRules.MaxDaysPerYear`)
- I giorni devono essere recuperati **nel mese della richiesta** oppure **entro l'anno
  lavorativo**: la scelta del dipendente è un parametro salvato nella tabella
  (`AbsenceRequestes.UrgentRecoveryPeriod` = `MONTH`/`YEAR`) insieme alla scadenza
  calcolata (`UrgentRecoveryDeadline`)

**Motivi speciali** (`Motive speciale (deces, casatorie)`, IDRequestType 19):
- **Massimo 5 giorni/anno** per dipendente (decesso, matrimonio, naștere, ...)
- Documentazione giustificativa da presentare **fisicamente al dep. HR entro 5 giorni**
  dalla richiesta (parametro `AbsenceRules.DocsDeadlineDays`), pena **annullamento e
  conversione automatica in giorni di congedo ordinario** (`ConvertToIDRequestType = 1`)

### 🗄️ Migrazione database (applicata con `sql/MIGRAZIONE_ASSENZE_URGENTI_SPECIALI.sql`)
- `[Timeclocking].[dbo].[RequestType]`: inseriti tipi 18 e 19
- `[Employee].[dbo].[AbsenceRules]`: + colonne `MaxDaysPerYear`, `DocsDeadlineDays`, `ConvertToIDRequestType` + righe regole per i due tipi
- `[Employee].[dbo].[AbsenceRequestes]`: + colonne `UrgentRecoveryPeriod`, `UrgentRecoveryDeadline`, `SpecialReason`, `DocumentationDeadline`, `DocumentationReceived`, `DocumentationReceivedDate`, `ConvertedToOrdinary`, `ConvertedToOrdinaryDate`, `ConvertedAbsenceRequestId`
- `[Employees]` (nuovo programma gestione dipendenti): `app.LeaveTypes` + colonne `RequiresDocumentation`, `DocsDeadlineDays`, `ConvertToLeaveTypeId`, `IsRecoverable` + tipi `AU`/`MS`; `app.LeaveRequests` + stesse colonne di tracciatura

### 🖥️ Kiosk
- Form cerere absență: selettore **perioada de recuperare** (assenze urgenti),
  selettore **motiv special** + dettaglio + avviso documentazione obbligatoria
- Card quota residua (X din 10 / X din 5) e blocco invio se quota superata
- PDF di conferma: righe recupero/motivo speciale + avviso scadenza documenti
- Email al superiore: **tip absență sempre in evidenza** (fallback recupero nome da DB)
  + righe recupero urgente / motivo speciale / scadenza documentazione
- Nuovi endpoint: `POST /api/absence-quota` (quota residua),
  `POST /api/hr/special-docs-sweep` (conversione manuale, riservata ai manager)

### ⏰ Conversione automatica (documentazione mancante)
- `service_kiosk_reports.py`: job giornaliero alle 06:30 → annulla le assenze speciali
  scadute senza documenti e le converte in congedo ordinario + email HR
- Sweep aggiuntivo all'avvio di `app.py` (best-effort)

### 📰 News
- Inserito annuncio dei nuovi tipi di assenza con scadenza **03.01.2027**
  (`Employee.dbo.News` NewId 783 + `Employees.app.News` NewsId 656)

---

## [2.3.7] - 2026-07-20

### ⌨️ Timeout adattivo per inserimento badge manuale
- Rilevamento automatico scansione RFID vs digitazione manuale tramite intervallo tra caratteri
- Digitazione manuale (>150ms tra caratteri): attesa **2000ms** (era 500ms per tutti)
- Scansione RFID (burst veloce): attesa **500ms** invariata

### 💾 Badge persistente durante la sessione
- Badge salvato in `sessionStorage` dopo validazione
- "Generează altă adeverință" mantiene il badge, resetta solo il form
- "Resetează" e timeout inattività cancellano la sessione e tornano alla home
- Home page (`launcher.html`) pulisce automaticamente la sessione al caricamento

---

## [2.3.5] - 2026-04-17


### 🖨️ Stampa client-side (fix accesso da rete locale)

- La stampa dei documenti (certificato, cerere di assenza, raport istoric absențe)
  ora avviene sul browser del client che ha fatto la richiesta, non più sul PC
  dove gira il server.
- Nuovo flusso: al termine della generazione appare il bottone
  **"Printează (15)"** con countdown. Click → stampa client-side via iframe
  nascosto (kiosk silenzioso grazie a `--kiosk-printing`, PC remoti con dialog
  standard del browser). Se non cliccato entro 15s il PDF viene eliminato.

### 🔧 Modifiche tecniche

- `app.py`: rimossa stampa server-side da `/api/generate-certificate`,
  `/api/generate-absence-report`, `/api/submit-absence-request`.
- `app.py`: sostituito endpoint `/api/do-print` con `/api/delete-pdf/<filename>`
  (cleanup PDF con protezione path traversal).
- `static/js/app.js`, `request.js`, `absence.js`: riscritto `handlePrint` con
  stampa via iframe + countdown 15s.
- `/api/news/print` e `printer_keepalive.py` invariati (funzioni kiosk-interne).

## [2.3.0] - 2026-01-21

### ✨ Novità
- **Sistema News Completo**: Integrazione totale del sistema news nel launcher
  - Display dinamico con auto-refresh ogni 30-60 secondi (basato su lunghezza testo)
  - Scorrimento verticale automatico per testi lunghi
  - Click sul frame news per stampa immediata
  
### 🖨️ Stampa News
- **Stampa silenziosa completamente funzionante**:
  - Metodo Windows `printto` nativo (NO popup Adobe)
  - Generazione PDF con logo aziendale
  - Metadati completi in **rumeno**:
    - "Comunicare Companiei" (titolo)
    - "Data:", "Publicat de:", "ID Știri:" (campi)
    - "Tipărit la ... ora ... de ..." (footer)
  - Spaziatura migliorata tra etichette e valori (70mm)
  - Font dimensione 20 per contenuto
  - Registrazione automatica in `KiosRequestes` con flag `Executed`
  - Stampante target: "Color Birou" (configurabile)

### 🔧 Miglioramenti Tecnici
- **pdf_printer.py**: 
  - Codice semplificato da ~300 a ~130 righe
  - Rimosso doppio escape backslash (bugfix)
  - Eliminati metodi complessi (GhostScript, Out-Printer, .NET)
  - Metodo unico robusto: `ProcessStartInfo` con verbo `printto`
  
- **app.py** (`/api/news/print`):
  - PDF generato con formato A4, word-wrap automatico
  - Gestione multi-pagina se necessario
  - Logo aziendale in header
  - Footer con timestamp e nome kiosk

### 🌐 Localizzazione
- Tutti i campi PDF news tradotti in rumeno
- Mantenuta compatibilità con sistema esistente

### 📊 API
- `GET /api/news` - Recupera news attive ordinate per priorità/data
- `POST /api/news/print` - Stampa news specifica (JSON: `newsId`, `newsText`, `newsDate`, `publisher`)
- Response JSON completo: `{pdf_generated, printed, printer_available, success, message}`

### 🐛 Bug Fix
- Risolto errore "filename, directory name, or volume label syntax is incorrect"
- Eliminati problemi con path Windows contenenti backslash
- Stampa funziona anche senza GhostScript o SumatraPDF installati

## [2.2.0] - 2026-01-20

### Modifiche Precedenti
- Sistema richieste assenze
- Gestione adeverințe
- Firma digitale con CertSign
- Sistema email notifiche
- Printer keep-alive service

---

## Formato
Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it/1.0.0/),
e questo progetto aderisce al [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
