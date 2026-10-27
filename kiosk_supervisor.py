"""
kiosk_supervisor.py
-------------------
Supervisore del kiosk HR: riporta il sistema completo (server Flask + browser
in modalita' kiosk) attivo al logon di Windows, SENZA privilegi di amministratore.

Catena di avvio automatico (tutti componenti per-utente, senza admin):
    Logon di Windows
      -> HKCU\\...\\Run oppure cartella "Esecuzione automatica"   [INSTALLA_AUTOSTART.bat]
        -> wscript.exe AVVIO_KIOSK.vbs                            [finestra nascosta]
          -> pythonw kiosk_supervisor.py                          [questo script]
            -> app.py (server Flask, riavviato se crasha)
            -> Chrome/Edge --kiosk http://localhost:3000          [riaperto se chiuso]

Comportamento:
  - Single-instance garantita da un socket-lock locale (127.0.0.1:39731):
    un secondo supervisore (es. doppia registrazione autostart) esce subito.
  - Se il server Flask e' gia' in salute all'avvio (es. avviato da altri),
    non viene duplicato: il supervisore gestisce solo il browser kiosk.
  - app.py viene avviato con il Python del venv se presente.
  - Il browser viene aperto SOLO dopo che /api/health risponde.
  - Se il processo Flask termina, viene rilanciato (con pausa lunga dopo
    crash ripetuti, come il vecchio kiosk_watchdog).
  - Se la finestra kiosk del browser viene chiusa, viene riaperta.
  - Chrome viene lanciato in --incognito: dopo uno spegnimento improvviso
    non compare il prompt "Ripristinare le pagine?".
  - Log rotante su logs/kiosk_supervisor.log (niente console: gira sotto pythonw).

Fermare il supervisore (Ctrl+C o kill) rilascia il lock; il server Flask
avviato dal supervisore continua a girare finché non viene fermato a parte
(RIMUOVI_AUTOSTART.bat si occupa anche di questo quando richiesto).
"""

import logging
import os
import socket
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
import urllib.request

# ── Configurazione ────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.resolve()
APP_SCRIPT   = BASE_DIR / 'app.py'
LOG_DIR      = BASE_DIR / 'logs'
LOG_FILE     = LOG_DIR / 'kiosk_supervisor.log'
PID_FILE     = BASE_DIR / 'temp' / 'kiosk_supervisor.pid'

VENV_PYTHON  = BASE_DIR / 'venv' / 'Scripts' / 'python.exe'

SERVER_PORT      = 3000
HEALTH_URL       = f'http://127.0.0.1:{SERVER_PORT}/api/health'
HEALTH_TIMEOUT   = 3          # secondi per singola verifica
SERVER_STARTUP_TIMEOUT = 150  # attesa massima perché /api/health risponda
POLL_SEC         = 10         # cadenza del ciclo di monitoraggio
BROWSER_GRACE_SEC = 20        # attesa dopo l'apertura prima di considerarla "chiusa"

RESTART_DELAY_SEC     = 5     # pausa tra un crash e il riavvio
LONG_DELAY_SEC        = 60    # pausa dopo troppi crash ravvicinati
MAX_CRASHES_IN_WINDOW = 5
CRASH_WINDOW_SEC      = 120

# Porta arbitraria usata SOLO come mutex di processo: chi la binda è l'unica
# istanza; il sistema operativo la rilascia automaticamente a processo morto.
LOCK_HOST = '127.0.0.1'
LOCK_PORT = 39731

# Browser in ordine di preferenza (percorsi standard per-utente e di sistema)
CHROME_PATHS = [
    Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
    Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe',
    Path(os.environ.get('LOCALAPPDATA', '')) / 'Google' / 'Chrome' / 'Application' / 'chrome.exe' if os.environ.get('LOCALAPPDATA') else None,
]
EDGE_PATHS = [
    Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe',
    Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Microsoft' / 'Edge' / 'Application' / 'msedge.exe',
]
CHROME_ARGS = [
    '--kiosk', '--kiosk-printing', '--incognito', '--start-fullscreen',
    '--noerrdialogs', '--disable-infobars', '--disable-session-crashed-bubble',
    f'http://localhost:{SERVER_PORT}',
]
EDGE_ARGS = [
    '--kiosk', f'http://localhost:{SERVER_PORT}',
    '--edge-kiosk-type=fullscreen', '--no-first-run',
]
# ─────────────────────────────────────────────────────────────────────────────

# Su un deploy pulito la cartella logs/ può non esistere ancora: il RotatingFileHandler
# senza directory solleva e, sotto pythonw, l'errore resta invisibile.
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [SUPERVISOR] %(levelname)s %(message)s',
    handlers=[RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding='utf-8')]
)
logger = logging.getLogger('kiosk_supervisor')
# Sotto pythonw stdout/stderr non esistono: aggiungi la console solo se disponibile
if sys.stdout is not None:
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


def acquire_single_instance_lock():
    """Ritorna il socket-lock se questa è l'unica istanza, None altrimenti."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCK_HOST, LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        return None


def health_ok():
    """True se /api/health risponde (il server Flask è vivo)."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=HEALTH_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_browser():
    """(percorso, argomenti, nome-processo) del browser kiosk, oppure None."""
    for p in CHROME_PATHS:
        if p and p.exists():
            return p, CHROME_ARGS, 'chrome'
    for p in EDGE_PATHS:
        if p and p.exists():
            return p, EDGE_ARGS, 'msedge'
    return None


def browser_window_alive(browser_name):
    """
    True se esiste almeno un processo del browser con una finestra principale.
    Distingue la finestra kiosk dai processi in background (es. Edge startup
    boost) che restano attivi anche a finestra chiusa.
    """
    if browser_name is None:
        return False
    ps = (
        "(Get-Process -Name '%s' -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowHandle -ne 0 }).Count" % browser_name
    )
    try:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW
        )
        count = (out.stdout or '').strip()
        return bool(count and int(count.splitlines()[0]) > 0)
    except Exception as e:
        logger.warning(f"Verifica finestra browser fallita ({e}): assumo chiusa")
        return False


def launch_server():
    """Avvia app.py con il Python del venv se disponibile."""
    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    env = os.environ.copy()
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    proc = subprocess.Popen(
        [python_exe, str(APP_SCRIPT)],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        env=env,
        creationflags=CREATE_NO_WINDOW,
    )
    logger.info(f'Server Flask avviato con {python_exe} — PID {proc.pid}')
    return proc


def launch_browser(browser):
    """Apre il browser in modalità kiosk (non blocca: processo indipendente)."""
    if browser is None:
        # Nessun Chrome/Edge installato: senza questo ramo l'unpack qui sotto
        # solleverebbe TypeError e abbatterebbe l'intero supervisore.
        logger.warning('Nessun Chrome/Edge trovato: apro con il browser di default')
        try:
            os.startfile(f'http://localhost:{SERVER_PORT}')
        except Exception as e:
            logger.error(f'Anche il browser di default è fallito: {e}')
        return
    path, args, name = browser
    try:
        subprocess.Popen([str(path)] + args, cwd=str(BASE_DIR))
        logger.info(f'Browser kiosk aperto: {path.name}')
    except Exception as e:
        logger.error(f'Apertura browser fallita ({e}): uso il browser di default')
        try:
            os.startfile(f'http://localhost:{SERVER_PORT}')
        except Exception as e2:
            logger.error(f'Anche il fallback di default è fallito: {e2}')


def write_pid_file():
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding='ascii')
    except Exception as e:
        logger.warning(f'Scrittura PID file fallita: {e}')


def run():
    logger.info('=' * 60)
    logger.info('KIOSK HR SUPERVISOR - AVVIO')
    logger.info(f'Cartella     : {BASE_DIR}')
    logger.info(f'Python       : {sys.executable}')
    logger.info(f'Health check : {HEALTH_URL} (timeout avvio {SERVER_STARTUP_TIMEOUT}s)')
    browser = find_browser()
    logger.info(f'Browser      : {browser[0].name if browser else "nessuno (fallback default)"}')
    logger.info(f'Poll         : ogni {POLL_SEC}s, grazia browser {BROWSER_GRACE_SEC}s')
    logger.info('=' * 60)
    write_pid_file()

    app_proc = None             # processo Flask avviato da noi (None se esterno)
    crash_times = []            # timestamp degli ultimi crash
    server_bad_since = None     # da quando il processo è vivo ma non risponde
    browser_opened_at = None    # ultima apertura del browser

    while True:
        # ── 1. Server Flask ──────────────────────────────────────────────
        healthy = health_ok()

        if healthy:
            if app_proc is None:
                logger.info('Server Flask già in salute (avviato esternamente): '
                            'il supervisore gestisce solo il browser')
            server_bad_since = None
        else:
            proc_alive = app_proc is not None and app_proc.poll() is None

            if proc_alive:
                # processo vivo ma non ancora in salute: concedi la grazia di avvio
                if server_bad_since is None:
                    server_bad_since = time.time()
                    logger.info('Attesa risposta /api/health...')
                elif time.time() - server_bad_since > SERVER_STARTUP_TIMEOUT:
                    logger.error(f'Nessuna risposta da /api/health dopo '
                                 f'{SERVER_STARTUP_TIMEOUT}s: kill e riavvio')
                    try:
                        app_proc.kill()
                    except Exception:
                        pass
                    app_proc = None
                    server_bad_since = None
            else:
                # processo assente o morto: (ri)parti con backoff
                now = time.time()
                if app_proc is not None:
                    crash_times.append(now)
                    crash_times = [t for t in crash_times if now - t <= CRASH_WINDOW_SEC]
                    logger.warning(f'Server terminato — exit code {app_proc.returncode}')
                    app_proc = None

                if len(crash_times) >= MAX_CRASHES_IN_WINDOW:
                    logger.error(f'{len(crash_times)} crash in {CRASH_WINDOW_SEC}s: '
                                 f'pausa lunga di {LONG_DELAY_SEC}s')
                    time.sleep(LONG_DELAY_SEC)
                    crash_times.clear()

                if app_proc is None:
                    if crash_times:
                        time.sleep(RESTART_DELAY_SEC)
                    app_proc = launch_server()
                    server_bad_since = None

        # ── 2. Browser kiosk ─────────────────────────────────────────────
        if health_ok():
            if browser_opened_at is None:
                launch_browser(browser)
                browser_opened_at = time.time()
            elif time.time() - browser_opened_at > BROWSER_GRACE_SEC:
                if not browser_window_alive(browser[2] if browser else None):
                    logger.warning('Finestra kiosk chiusa: riapertura browser')
                    launch_browser(browser)
                    browser_opened_at = time.time()

        # ── 3. Ciclo successivo ──────────────────────────────────────────
        time.sleep(POLL_SEC)


def main():
    lock = acquire_single_instance_lock()
    if lock is None:
        # Nessun log: un'altra istanza è già in funzione, esci in silenzio
        print('kiosk_supervisor: un\'altra istanza è già in esecuzione, esco.')
        sys.exit(0)

    if not APP_SCRIPT.exists():
        logger.error(f'app.py non trovato in {BASE_DIR}: supervisore arrestato')
        sys.exit(1)

    try:
        while True:
            try:
                run()
            except KeyboardInterrupt:
                raise
            except Exception:
                # Un'eccezione non gestita non deve lasciare il kiosk nero fino
                # al prossimo logon: log, pausa e ripresa del ciclo di sorveglianza.
                logger.exception('Eccezione non gestita nel supervisore: ripresa tra 30s')
                time.sleep(30)
    except KeyboardInterrupt:
        logger.info('Interruzione da tastiera: arresto supervisore')
    finally:
        lock.close()
        try:
            if PID_FILE.exists():
                PID_FILE.unlink()
        except Exception:
            pass


if __name__ == '__main__':
    main()
