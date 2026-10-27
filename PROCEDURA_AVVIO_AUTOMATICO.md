# PROCEDURA AVVIO AUTOMATICO DOPO SHUTDOWN — Kiosk HR

**Versione 2.4.2 · Ottobre 2026 · GTMC — Vandewiele Romania**

Questa procedura rende il kiosk HR **completamente autonomo**: dopo uno shutdown, un black-out o un riavvio di Windows, il sistema torna operativo da solo — server Flask, browser in modalità kiosk e verifica di salute — senza tastiera, mouse o intervento umano.

---

## 1. Prerequisiti (da configurare UNA sola volta per kiosk)

La catena di ripartenza automatica ha tre anelli. Se uno manca, il kiosk si ferma lì.

### 1.1 BIOS — accensione al rientro della corrente

Dopo un black-out il PC non si riaccende da solo se il BIOS non è impostato per farlo.

1. All'avvio del PC entra nel setup BIOS/UEFI (di solito `F2`, `Canc` o `F10`).
2. Cerca l'opzione (il nome varia per produttore):
   - **ASUS**: `Advanced → APM → Restore AC Power Loss → Power On`
   - **Gigabyte**: `Power → AC Back → Always On`
   - **MSI**: `Settings → Advanced → Power → Restore after AC Power Loss → Power On`
   - **ASRock / Dell / HP / Lenovo**: `After Power Loss` / `AC Power Recovery → Power On`
3. Salva ed esci.

**Verifica**: accendi, avvia Windows, poi togli la spina e ricollegala. Il PC deve riaccendersi da solo.

### 1.2 Windows — logon automatico

Dopo il boot Windows si ferma alla schermata di login: senza autologon nessun programma di avvio (nemmeno il nostro) parte.

**Metodo consigliato (account locale):**

1. Premi `Win + R`, digita `netplwiz`, invio.
2. **Windows 11 / Windows 10 con account Microsoft**: se la casella *"Gli utenti devono immettere nome utente e password"* non compare, apri `Impostazioni → Account → Opzioni di accesso` e **disattiva** *"Per una maggiore sicurezza, richiedi l'accesso con Windows Hello"* — poi riapri `netplwiz`: la casella riappare.
3. Spunta la casella, seleziona l'utente del kiosk, `Applica`, inserire la password due volte.

**Metodo alternativo (password cifrata, consigliato se il PC è fisicamente accessibile):**
usa lo strumento [Sysinternals Autologon](https://learn.microsoft.com/sysinternals/downloads/autologon): salva le credenziali cifrate in LSA invece che nel registro in chiaro.

**Nota BitLocker**: se il disco è cifrato con BitLocker + PIN, al boot serve il PIN a mano. Per il kiosk impostare sblocco automatico (TPM-only) o nessun PIN.

### 1.3 Progetto — registrazione autostart

Sulla cartella del kiosk (nessun diritto di amministratore richiesto):

```
INSTALLA_AUTOSTART.bat
```

Lo script:
- registra `AVVIO_KIOSK.vbs` nella chiave `HKCU\...\Run` (valore `KioskHR_Autostart`);
- genera un secondo launcher nella cartella *Esecuzione automatica* dell'utente (doppia copertura);
- rimuove il vecchio task amministrativo `KioskHR_Watchdog` dell'era v2.3.9c, se presente;
- verifica venv, `kiosk_supervisor.py` e `app.py`;
- fa un **avvio di prova** e attende fino a 60 s che `http://127.0.0.1:3000/api/health` risponda;
- scrive un log in `logs\autostart_install.log`.

---

## 2. Come funziona la catena di ripartenza

```
Black-out / shutdown
  └─ Rientro corrente ──► BIOS: Power On
       └─ Boot Windows ──► Autologon
            └─ Logon utente
                 ├─ HKCU\...\Run  "KioskHR_Autostart"          ┐
                 └─ %APPDATA%\...\Startup\KioskHR_Autostart.vbs ┘ (una delle due basta)
                      └─ wscript AVVIO_KIOSK.vbs (nascosto)
                           └─ venv\Scripts\pythonw.exe kiosk_supervisor.py
                                ├─ avvia app.py (Flask, porta 3000)
                                ├─ attende /api/health (fino a 150 s)
                                ├─ apre Chrome/Edge --kiosk --incognito
                                └─ ciclo ogni 10 s:
                                     · Flask non risponde? kill + riavvio (backoff 5 s;
                                       dopo 5 crash in 120 s → pausa 60 s)
                                     · finestra kiosk chiusa? riapre il browser
```

Garanzie del supervisore (`kiosk_supervisor.py`):

- **Istanza unica**: socket-lock locale; un secondo supervisore esce subito.
- **Mai schermo nero silenzioso**: se il browser non viene trovato usa il browser di default; qualunque eccezione imprevista viene loggata e il ciclo riprende dopo 30 s invece di terminare.
- **Avvio senza `logs/`**: la cartella log viene creata all'occorrenza.
- **Venv mancante**: `AVVIO_KIOSK.vbs` NON ripiega su un Python globale (potrebbe non avere Flask): scrive la causa in `logs\autostart_error.log` ed esce. Diagnosi immediata invece di un loop invisibile.
- **`/api/health` non tocca il database**: il kiosk si apre anche se SQL Server è ancora giù; l'overlay offline in pagina copre l'attesa.

---

## 3. Checklist di verifica (dopo installazione o manutenzione)

1. **Pannello di stato** — doppio clic su:
   ```
   STATO_KIOSK.bat
   ```
   Tutte le voci devono risultare `[OK]`. Il pannello controlla: chiave Run, file Startup, autologon, processo supervisore, health del server su porta 3000, finestra browser, ultime righe di log.

2. **Prova di shutdown reale** (una volta):
   - Spegni Windows dal menu Start (`Arresta il sistema`).
   - Riaccendi il PC.
   - Entro ~2 minuti dal logon il kiosk deve essere a schermo intero sulla pagina iniziale.

3. **Prova di black-out** (se il BIOS è impostato, paragrafo 1.1):
   - Togli la spina con il PC acceso, poi ricollegalo.
   - Il PC deve riaccendersi da solo e completare la catena.

---

## 4. Risoluzione problemi

| Sintomo | Causa probabile | Rimedio |
|---|---|---|
| Il PC resta spento dopo il black-out | BIOS `Restore AC Power Loss` su `Power Off` | Paragrafo 1.1 |
| Schermata di login al boot, nessuno la digita | Autologon non configurato o disattivato dal toggle Windows Hello | Paragrafo 1.2 |
| Al logon non parte nulla | Autostart non registrato | `INSTALLA_AUTOSTART.bat`, poi `STATO_KIOSK.bat` |
| `logs\autostart_error.log` dice "venv non trovato" | Ambiente Python non creato su quella macchina | Rieseguire `INSTALLA.bat` o `SETUP_PYTHON311.bat` |
| Il supervisore logga "Nessun Chrome/Edge trovato" | Browser non installato o percorso non standard | Installare Chrome/Edge, oppure continuare: verrà usato il browser di default |
| Il browser si apre ma mostra errore di connessione | Flask non ancora su (attesa normale fino a 150 s) oppure crash ripetuti | Vedere `logs\kiosk_supervisor.log`; avvio manuale `START_APP.bat` per leggere l'errore a console |
| Overlay "offline" persistente a schermo | SQL Server non raggiungibile | Il kiosk è vivo: controllare rete/SQL; il server non è la causa |
| Doppio browser / due finestre | Registrazione duplicata (es. Run + Startup su utenze diverse) | `RIMUOVI_AUTOSTART.bat` e reinstallare pulito |

File di log utili:

| File | Contenuto |
|---|---|
| `logs\kiosk_supervisor.log` | attività del supervisore: avvii, crash, riaperture browser (ruota a 2 MB ×3) |
| `logs\autostart_install.log` | esito dell'installazione autostart |
| `logs\autostart_error.log` | presente SOLO se l'avvio al logon è fallito (venv mancante) |
| `app_debug.log` | log dell'applicazione Flask |

---

## 5. Gestione quotidiana

| Operazione | Comando |
|---|---|
| Disattivare l'avvio automatico | `RIMUOVI_AUTOSTART.bat` |
| Riattivarlo | `INSTALLA_AUTOSTART.bat` |
| Vedere lo stato completo | `STATO_KIOSK.bat` |
| Avvio manuale (solo server, con console) | `START_APP.bat` |

**Nota**: il servizio Windows `KioskReportsService` (report mensili e job ore alle 06:30) è un sottosistema separato, gestito con `INSTALL_SERVICE.bat` / `UNINSTALL_SERVICE.bat`: non viene toccato da questa procedura né da `RIMUOVI_AUTOSTART.bat`.
