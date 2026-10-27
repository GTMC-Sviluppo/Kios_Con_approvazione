# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Dipendenti di stabilimento** (Vandewiele Romania, fabbrica): usano il kiosk touch in hall per autoservizi HR, senza formazione e senza login personale — si identificano solo con badge RFID o numero badge.
- **Manager / HR**: approvano le richieste di assenza via pagina di approvazione web protetta da login manager (badge utente + password) e ricevono email di notifica.
- **Manutentore del sistema** (GTMC): installa e diagnostica il kiosk via script bat/vbs e pannello di stato; gli strumenti devono funzionare senza competenze Python.

## Product Purpose

Kiosk orario HR ("Kiosk HR – Sistema Adeverințe"): generazione automatica di certificati lavorativi (adeverințe) con firma digitale e stampa silenziosa, richieste di assenza (ferie, permessi, malattia, assenze urgenti e motivi speciali), verifica stato richieste, report storico annuale assenze, e display news con auto-refresh. Esiste per togliere l'ufficio HR dal flusso: il dipendente ottiene il documento firmato in autonomia in pochi secondi. Success = documento corretto, in rumeno, stampato, senza intervento umano.

## Positioning

Integrazione verticale su un unico impianto: badge RFID lettura diretta via `IDReader.dll`, scrittura nei database aziendali SQL Server `Employee` e `Timeclocking`, PDF firmato digitalmente e inviato alla stampante di rete senza dialoghi. Un portale HR generico non può copiare né il legame diretto col Timeclocking né la catena badge→PDF firmato→stampa silenziosa.

## Operating Context

- **Deposito**: fabbrica Vandewiele Romania; PC Windows 10/11 in modalità kiosk, browser Chrome/Edge `--kiosk --incognito`, monitor touch.
- **Rete**: intranet di fabbrica; il server Flask ascolta su `0.0.0.0:3000`; il DB SQL Server può essere momentaneamente non raggiungibile — l'app deve degradare con overlay offline, non crashare.
- **Riavvii**: il kiosk deve ripartire da solo dopo black-out/shutdown (BIOS Restore on AC Power Loss → autologon → Run key/Startup → `kiosk_supervisor.py` sorveglia Flask + browser).
- **Documenti**: tutti i PDF generati sono in **rumeno** (localizzazione obbligatoria); l'interfaccia è trilingua IT/RO/EN.
- **Stampa**: silenziosa via `PDFtoPrinter.exe`; le firme amministratore sono immagini in `Images/`.
- **Sottosistema report separato**: `KioskReportsService` (servizio Windows, pywin32) genera report mensili il 1° del mese e job ore alle 06:30 — indipendente dal supervisor del kiosk.
- **Deploy**: pacchetti ZIP costruiti da `CREA_PACCHETTO.ps1`, installati sul target con `INSTALLA.bat` come admin; le credenziali (DB, SMTP) arrivano cifrate per-macchina e NON vivono nel repo git.

## Capabilities and Constraints

- Endpoint kiosk (validazione badge, generazione certificato, richiesta assenza, verifica stato, report, news) sono **volutamente senza autenticazione** — la sicurezza è delegata al perimetro di rete della fabbrica; gli endpoint `/api/manager/*` e `/api/hr/*` usano token emessi dal login manager.
- `/api/health` non deve mai toccare il DB: è la sonda del supervisor.
- Il server deve restare avviabile con `python app.py` (il supervisor lancia esattamente questo); un eventuale server WSGI di produzione deve restare dietro lo stesso entrypoint.
- Porta server: **3000** (non 5000 — i tool diagnostici più vecchi la sbagliano).
- Log in `logs/` (supervisor, autostart install), `app_debug.log` per Flask; `temp/` per i PDF volatili.
- Non deciso: eventuale ACL di rete oltre il firewall; eventuale hash delle password manager (oggi in chiaro su `ResetServices.dbo.tbuserkey`, schema condiviso non modificabile unilateramente).

## Brand Commitments

- Nome prodotto: **Kiosk HR**; proprietario **Vandewiele Romania**, sviluppato da **GTMC** (Gianluca Testa).
- Logo GTMC (`GTMC.png`) e `logo.png` aziendali su documenti e UI; font DejaVu per i PDF (supporto rumeno: ș/ț/ă/â/î).
- Codice sorgente proprietario, repo privato `glctesta/kiosk-hr-adeverente`.

## Evidence on Hand

- README.md, CHANGELOG.md (v2.1.0 → v2.4.1), RELEASE_NOTES_v2.1.0–v2.3.7.
- Pacchetti deploy storici (zip v2.3.6 → v2.4.1) come riferimento di contenuto spedito.
- Nessun caso studio, testimonianza o metrica d'uso: non inventarli.

## Product Principles

1. **Zero formazione**: ogni flusso si completa con badge + tocchi; niente login per il dipendente.
2. **Degrada, non muore**: DB o stampante assenti → overlay offline e coda, il kiosk resta in piedi; il supervisor riporta tutto su da solo.
3. **Il documento è il prodotto**: rumeno corretto, firmato, stampato — un PDF a video non è successo.
4. **Gestibile da remoto con strumenti semplici**: script bat/vbs autolocanti, un pannello di stato, log leggibili; niente dipendenze esoteriche.

## Accessibility & Inclusion

Nessuno standard formale richiesto a oggi. Vincolo di fatto: uso touch da parte di utenti in piedi, a volte con guanti; testi in tre lingue.
