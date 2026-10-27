# Kiosk HR - Sistema Adeverințe

Sistema web per la generazione automatica di certificati e gestione richieste di assenza per dipendenti.

## 📋 Caratteristiche Principali

- **Generazione Certificati**: Creazione automatica di certificati/adeverințe con firma digitale
- **Richieste Assenza**: Sistema completo per richieste ferie, permessi, malattia
- **Report Storico**: Generazione report annuali delle assenze
- **Sistema News**: Display dinamico con auto-refresh e stampa silenziosa (NEW v2.3.0)
- **Lettore RFID**: Integrazione con lettore badge per identificazione rapida
- **Stampa Automatica**: Invio automatico documenti alla stampante configurata
- **Notifiche Email**: Notifiche automatiche ai manager per approvazioni
- **Multilingua**: Supporto IT/RO/EN

## 🚀 Installazione Rapida

### Prerequisiti

- **Windows 10/11**
- **Python 3.11** ([Download](https://www.python.org/downloads/))
- **SQL Server** (accesso al database Employee)
- **Stampante** configurata (opzionale)
- **Lettore RFID** (opzionale)

### Installazione

1. **Clona o scarica il repository**
   ```bash
   git clone https://github.com/glctesta/kiosk-hr-adeverente.git
   cd kiosk-hr-adeverente
   ```

2. **Esegui lo script di installazione** (come Amministratore)
   ```bash
   INSTALLA.bat
   ```

3. **Configura la connessione al database**
   ```bash
   python setup.py
   ```
   Inserisci i parametri di connessione SQL Server quando richiesto.

4. **Avvia l'applicazione**
   ```bash
   START_APP.bat
   ```

5. **Accedi all'interfaccia web**
   - Locale: `http://localhost:5000`
   - Rete: `http://<IP-MACCHINA>:5000`

## 📁 Struttura Progetto

```
kiosk-hr-adeverente/
├── app.py                      # Applicazione Flask principale
├── absence_report.py           # Generazione report assenze
├── absence_request.py          # Gestione richieste assenza
├── certificate_generator.py    # Generazione certificati
├── badge_reader.py             # Lettore badge RFID
├── digital_signature.py        # Firma digitale PDF
├── pdf_printer.py              # Gestione stampa PDF
├── printer_keepalive.py        # Servizio keep-alive stampante
├── email_connector.py          # Invio email notifiche
├── db_connection.py            # Connessione database
├── config_manager.py           # Gestione configurazioni
├── kiosk_supervisor.py         # Supervisore kiosk (riavvio automatico server+browser)
├── utils.py                    # Utility varie
├── setup.py                    # Script configurazione iniziale
├── requirements.txt            # Dipendenze Python
├── templates/                  # Template HTML
│   ├── launcher.html          # Menu principale
│   ├── certificati.html       # Generazione certificati
│   ├── absente.html           # Report assenze
│   ├── cerere.html            # Richiesta assenza
│   └── verifica.html          # Verifica stato richiesta
├── static/                     # Risorse statiche
│   ├── css/
│   ├── js/
│   └── images/
├── sql/                        # Migrazioni SQL
├── temp/                       # PDF temporanei
├── Images/                     # Immagini firme
├── INSTALLA.bat               # Script installazione
├── START_APP.bat              # Avvio manuale applicazione
├── INSTALLA_AUTOSTART.bat     # Avvio automatico dopo shutdown (senza admin)
├── RIMUOVI_AUTOSTART.bat      # Disattivazione avvio automatico
├── STATO_KIOSK.bat            # Pannello diagnostico kiosk
└── AVVIO_KIOSK.vbs            # Launcher nascosto al logon

```

## 🔧 Configurazione

### Database

Il sistema richiede accesso a SQL Server con i seguenti database:
- `Employee` - Dati dipendenti e richieste
- `Timeclocking` - Gestione presenze e assenze

### File di Configurazione

- **db_config.enc**: Credenziali database (crittografate)
- **email_credentials.enc**: Credenziali email (crittografate)
- **encryption_key.key**: Chiave crittografia database
- **email_key.key**: Chiave crittografia email
- **print_config.json**: Configurazione stampante

### Configurazione Iniziale

Eseguire `python setup.py` per configurare:
1. Connessione database SQL Server
2. Credenziali email SMTP
3. Stampante predefinita

## 📖 Guide Dettagliate

- **[PROCEDURA_AVVIO_AUTOMATICO.md](PROCEDURA_AVVIO_AUTOMATICO.md)** - Avvio automatico dopo shutdown (BIOS, autologon, checklist)
- **[INSTALLAZIONE_MANUALE.md](INSTALLAZIONE_MANUALE.md)** - Installazione passo-passo
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deployment in produzione
- **[GUIDA_RAPIDA.md](GUIDA_RAPIDA.md)** - Guida utente rapida
- **[GUIDA_RFID.md](GUIDA_RFID.md)** - Configurazione lettore RFID
- **[GUIDA_KIOSK_FULLSCREEN.md](GUIDA_KIOSK_FULLSCREEN.md)** - Modalità kiosk
- **[CONFIGURAZIONE_RETE.md](CONFIGURAZIONE_RETE.md)** - Accesso da rete
- **[STAMPA_AUTOMATICA.md](STAMPA_AUTOMATICA.md)** - Configurazione stampa

## 🎯 Utilizzo

### 1. Generazione Certificati

1. Scansiona badge RFID o inserisci numero badge
2. Seleziona motivo certificato
3. Clicca "Genera Certificato"
4. Il PDF viene generato e stampato automaticamente

### 2. Richiesta Assenza

1. Scansiona badge RFID
2. Seleziona tipo assenza (Ferie, Permesso, Malattia, ecc.)
3. Seleziona date inizio/fine
4. Il sistema calcola automaticamente i giorni lavorativi
5. Invia richiesta - viene notificato il manager via email

### 3. Verifica Stato Richiesta

1. Inserisci numero richiesta (es. ABS/001/2026)
2. Visualizza stato: In Attesa / Approvata / Respinta / Scaduta
3. Possibilità di reinviare notifica se in attesa

### 4. Report Storico Assenze

1. Scansiona badge RFID
2. Seleziona anno
3. Genera report PDF con tutte le assenze dell'anno

## 🔐 Sicurezza

- **Crittografia**: Tutte le credenziali sono crittografate con Fernet
- **Chiavi fuori dal repository**: `*.key`, `*.enc`, `*.pfx` NON sono tracciati in git; si distribuiscono solo col pacchetto deploy generato da `CREA_PACCHETTO.ps1`
- **Server di produzione**: in produzione `app.py` usa waitress (WSGI) al posto del server di sviluppo Flask
- **Hardening v2.4.2**: protezione path traversal su `/api/print-pdf`, header di sicurezza, rate-limit sul login manager, scadenza token manager, messaggi d'errore generici verso il client
- **Firma Digitale**: I certificati possono essere firmati digitalmente
- **Logging**: Tutte le operazioni sono registrate nel database
- **Validazione**: Controlli di validità su badge, date, disponibilità ferie

## 🖨️ Stampa Automatica

Il sistema supporta la stampa automatica silenziosa su:
- Stampanti di rete
- Stampanti locali
- Stampanti PDF virtuali

Configurazione in `print_config.json`

## 📧 Notifiche Email

Le richieste di assenza inviano automaticamente email ai manager con:
- Dettagli richiesta
- Nome dipendente
- Periodo richiesto
- Giorni lavorativi
- Link per approvazione (se configurato)

## 🔄 Aggiornamenti

### Versione 2.3.0 (2026-01-21)
- ✨ **Sistema News Completo**: Integrazione display news nel launcher
- 🔄 **Auto-refresh**: News si aggiornano automaticamente ogni 30-60 secondi
- 📜 **Scorrimento Verticale**: Per testi lunghi con animazione automatica
- 🖨️ **Stampa Silenziosa**: Click su news → stampa immediata (NO popup Adobe)
- 🇷🇴 **Localizzazione Rumena**: Tutti i campi PDF in rumeno
- ⚡ **Performance**: pdf_printer.py ottimizzato (-60% codice)
- 📊 **Audit Trail**: Tracking completo stampe in KiosRequestes

### Versione 2.1.1 (2026-01-03)
- ✅ Fix errore `UnboundLocalError` in submit_absence_request
- ✅ Pulizia file inutili
- ✅ Script installazione migliorato

### Versione 2.1.0 (2025-12-31)
- ✅ Sistema richieste assenza completo
- ✅ Verifica stato richieste
- ✅ Reinvio notifiche manager
- ✅ Logging operazioni servizio
- ✅ Disclaimer Romanian su report
- ✅ Branding GTMC

## 🆘 Troubleshooting

### L'applicazione non si avvia
- Verificare che Python 3.11 sia installato
- Verificare che l'ambiente virtuale sia attivato
- Controllare i log in `app_debug.log`

### Errore connessione database
- Verificare credenziali in `db_config.enc`
- Testare connessione con `python setup.py`
- Verificare firewall SQL Server

### Stampa non funziona
- Verificare stampante predefinita in Windows
- Controllare `print_config.json`
- Verificare driver stampante

### Lettore RFID non funziona
- Verificare presenza `IDReader.dll`
- Consultare `GUIDA_RFID.md`
- Verificare driver lettore

## 📞 Supporto

Per problemi o domande:
- **Email**: gianluca.testa@vandewiele.com
- **GitHub Issues**: [Apri una issue](https://github.com/glctesta/kiosk-hr-adeverente/issues)

## 📄 Licenza

Proprietario: Vandewiele Romania  
Sviluppato da: GTMC (Gianluca Testa)

---

**© 2026 GTMC - Vandewiele Romania**
