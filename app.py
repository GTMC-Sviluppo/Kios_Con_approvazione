"""
Applicazione Web per Generazione Certificati/Adeverințe
Sostituisce la form VBA di Access con un'interfaccia web moderna
"""
from flask import Flask, render_template, request, jsonify, send_file, send_from_directory
from datetime import datetime, timedelta
import logging
import os
import sys
import time
import uuid

# Forza encoding UTF-8 su Windows per gestire caratteri rumeni/Unicode nei log e JSON
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from db_connection import DatabaseConnection
from config_manager import ConfigManager
from certificate_generator import CertificateGenerator
from absence_report import AbsenceReportGenerator
from absence_request import (
    AbsenceRequestManager,
    VACATION_REQUEST_TYPE_ID,
    URGENT_ABSENCE_TYPE_ID,
    SPECIAL_ABSENCE_TYPE_ID,
    URGENT_RECOVERY_PERIODS,
    URGENT_RECOVERY_MONTH,
    URGENT_RECOVERY_YEAR
)
from badge_reader import BadgeReader
from kiosk_request_logger import KioskRequestLogger
from utils import send_email, get_email_recipients
from pdf_printer import print_pdf_silent, get_default_printer
from printer_keepalive import start_printer_keepalive, stop_printer_keepalive
from company_config import EMPLOYER_ID, FALLBACK_EMAIL, LOGO_PATH, COMPANY_NAME

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app_debug.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Secret per-installazione: generato al primo avvio e salvato fuori dal repo git
_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secret_key.key')
try:
    with open(_SECRET_FILE, 'rb') as _f:
        app.config['SECRET_KEY'] = _f.read().strip()
except FileNotFoundError:
    _generated_secret = os.urandom(32)
    with open(_SECRET_FILE, 'wb') as _f:
        _f.write(_generated_secret)
    app.config['SECRET_KEY'] = _generated_secret
    logger.info("Generata nuova SECRET_KEY per-installazione in secret_key.key")

# Inizializza connessione database
config_manager = ConfigManager()
db_connection = DatabaseConnection(config_manager)

# Inizializza Kiosk Request Logger per monitoraggio utilizzo
kiosk_logger = KioskRequestLogger(db_connection)

# Token manager approvazioni: solo memoria del server, non persistente lato browser
manager_auth_tokens = {}
MANAGER_TOKEN_TTL_SECONDS = 3600  # sessione manager valida 60 min dall'ultima attività


@app.after_request
def set_security_headers(response):
    """Header di sicurezza minimi per il kiosk."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


# Rate limiting login manager: max tentativi falliti per IP nella finestra indicata
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 900  # 15 minuti
_login_failures = {}




@app.route('/')
def launcher():
    """Pagina launcher principale con menu servizi"""
    return render_template('launcher.html')




@app.route('/certificati')
def certificati():
    """Pagina applicazione certificati/adeverințe"""
    return render_template('index.html')


@app.route('/absente')
def absente():
    """Pagina raport istoric absențe"""
    return render_template('absence.html')


@app.route('/cerere')
def cerere():
    """Pagina cerere absență"""
    return render_template('request.html')


@app.route('/verifica')
def verifica():
    """Pagina verificare stare cerere"""
    return render_template('check.html')


@app.route('/approvazioni')
def approvazioni():
    """Pagina approvazione/rifiuto richieste assenza (accesso manager)."""
    return render_template('approval.html')


# ─────────────────────────────────────────────────────────────────────────────
# BADGE TIMING CONFIG
# ─────────────────────────────────────────────────────────────────────────────
BADGE_CONFIG_FILE = 'reading_badge_time.json'
BADGE_CONFIG_DEFAULTS = {
    "badge_reading": {
        "rfid_delay_ms": 800,
        "manual_typing_delay_ms": 3000,
        "manual_typing_threshold_ms": 150
    }
}

def _load_badge_config():
    """Legge reading_badge_time.json; se non esiste lo crea con i valori di default."""
    import json
    if not os.path.exists(BADGE_CONFIG_FILE):
        with open(BADGE_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(BADGE_CONFIG_DEFAULTS, f, indent=4)
        logger.info(f"Creato {BADGE_CONFIG_FILE} con valori di default.")
        return BADGE_CONFIG_DEFAULTS
    try:
        with open(BADGE_CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Errore lettura {BADGE_CONFIG_FILE}: {e} — uso valori di default.")
        return BADGE_CONFIG_DEFAULTS


@app.route('/api/badge-config', methods=['GET'])
def get_badge_config():
    """Restituisce la configurazione timing badge dal file reading_badge_time.json."""
    try:
        cfg = _load_badge_config()
        br = cfg.get('badge_reading', BADGE_CONFIG_DEFAULTS['badge_reading'])
        return jsonify({
            'success': True,
            'rfid_delay_ms': br.get('rfid_delay_ms', 800),
            'manual_typing_delay_ms': br.get('manual_typing_delay_ms', 3000),
            'manual_typing_threshold_ms': br.get('manual_typing_threshold_ms', 150)
        })
    except Exception as e:
        logger.error(f"Errore get_badge_config: {e}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


def _get_manager_auth_from_request():
    """Recupera il token manager dalla request e lo valida (scadenza sliding)."""
    auth_header = request.headers.get('Authorization', '')
    token = ''

    if auth_header.lower().startswith('bearer '):
        token = auth_header[7:].strip()
    else:
        token = request.headers.get('X-Manager-Token', '').strip()

    if not token:
        return None, None

    auth_data = manager_auth_tokens.get(token)
    if not auth_data:
        return None, None

    now = time.time()
    if now - auth_data.get('last_seen', 0) > MANAGER_TOKEN_TTL_SECONDS:
        manager_auth_tokens.pop(token, None)
        return None, None

    auth_data['last_seen'] = now
    _purge_expired_manager_tokens(now)

    return token, auth_data


def _purge_expired_manager_tokens(now=None):
    """Rimuove i token manager scaduti dalla memoria."""
    if now is None:
        now = time.time()
    expired = [t for t, d in manager_auth_tokens.items()
               if now - d.get('last_seen', 0) > MANAGER_TOKEN_TTL_SECONDS]
    for expired_token in expired:
        manager_auth_tokens.pop(expired_token, None)


@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.svg',
        mimetype='image/svg+xml'
    )



@app.route('/api/news', methods=['GET'])
def get_news():
    """Recupera messaggi news dal database con priorità per mandatory"""
    conn = None
    try:
        # Crea connessione fresca per evitare "connection broken"
        conn = DatabaseConnection(config_manager).connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        cursor = conn.cursor()
        
        # Data attuale
        current_date = datetime.now()
        
        # Query per recuperare news attive
        # Verifica che current_date sia COMPRESO tra StartNews ed EndNews
        query = """
        SELECT 
            NewId,
            EmployeerId,
            StartNews,
            EndNews,
            News,
            Publisher,
            IsMandatory,
            Printable
        FROM [Employee].[dbo].[News]
        WHERE ? >= StartNews AND ? <= EndNews
        ORDER BY IsMandatory DESC, StartNews ASC
        """
        
        cursor.execute(query, (current_date, current_date))
        rows = cursor.fetchall()
        
        if not rows:
            return jsonify({
                'success': True,
                'has_news': False,
                'news': []
            })
        
        # Separa news mandatory da quelle normali
        mandatory_news = []
        regular_news = []
        
        for row in rows:
            # Usa str() per garantire che nvarchar con caratteri Unicode (rumeni, emoji) sia gestito correttamente
            news_item = {
                'id': row[0],
                'employee_id': row[1],
                'start_date': row[2].isoformat() if row[2] else None,
                'end_date':   row[3].isoformat() if row[3] else None,
                'message':    str(row[4]) if row[4] is not None else '',
                'publisher':  str(row[5]) if row[5] is not None else '',
                'is_mandatory': bool(row[6]) if row[6] is not None else False,
                'printable':    bool(row[7]) if len(row) > 7 and row[7] is not None else False
            }
            
            if news_item['is_mandatory']:
                mandatory_news.append(news_item)
            else:
                regular_news.append(news_item)
        
        # Se ci sono news mandatory, mostra solo quelle
        if mandatory_news:
            return jsonify({
                'success': True,
                'has_news': True,
                'news': mandatory_news,
                'is_mandatory': True
            })
        else:
            return jsonify({
                'success': True,
                'has_news': True,
                'news': regular_news,
                'is_mandatory': False
            })
        
    except Exception as e:
        logger.error(f"Errore recupero news: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500
    finally:
        # Chiudi connessione per liberare risorse
        if conn:
            try:
                conn.close()
            except:
                pass


@app.route('/api/slideshow-images', methods=['GET'])
def get_slideshow_images():
    """Recupera lista immagini disponibili per slideshow (file che iniziano con X o S, ordine random)"""
    try:
        import random
        
        images_dir = os.path.join(app.root_path, 'Images')
        
        if not os.path.exists(images_dir):
            return jsonify({
                'success': True,
                'images': []
            })
        
        # Estensioni immagini supportate
        valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        
        images = []
        for filename in os.listdir(images_dir):
            # Filtra solo file che iniziano con 'X' o 'S' (case-insensitive)
            first_char = filename.upper()[0] if filename else ''
            if first_char not in ['X', 'S']:
                continue
                
            ext = os.path.splitext(filename)[1].lower()
            if ext in valid_extensions:
                # URL relativo per accedere all'immagine
                images.append(f"/images/{filename}")
        
        # Randomizza l'ordine delle immagini
        random.shuffle(images)
        
        return jsonify({
            'success': True,
            'images': images
        })
        
    except Exception as e:
        logger.error(f"Errore recupero immagini slideshow: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve immagini dalla directory Images"""
    try:
        images_dir = os.path.join(app.root_path, 'Images')
        return send_from_directory(images_dir, filename)
    except Exception as e:
        logger.error(f"Errore serving immagine: {str(e)}")
        return jsonify({'success': False, 'error': 'Immagine non trovata'}), 404


@app.route('/api/validate-badge', methods=['POST'])
def validate_badge():
    """Valida badge RFID e recupera dati dipendente"""
    try:
        data = request.json
        badge_number = data.get('badgeNumber', '').strip()
        
        if not badge_number:
            return jsonify({
                'success': False, 
                'error': 'Numero badge non fornito'
            }), 400
        
        conn = db_connection.connect()
        badge_reader = BadgeReader(conn)
        
        is_valid, employee_data, error_msg = badge_reader.validate_badge_access(badge_number)
        
        if is_valid:
            return jsonify({
                'success': True,
                'employee': {
                    'id': employee_data['hire_history_id'],
                    'name': employee_data['full_name'],
                    'employeeId': employee_data['employee_id'],
                    'sex': employee_data['sex'],
                    'badgeNumber': employee_data['badge_number']
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': error_msg
            }), 404
    
    except Exception as e:
        logger.error(f"Errore nella validazione badge: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/employees', methods=['GET'])
def get_employees():
    """Recupera lista dipendenti attivi"""
    try:
        conn = db_connection.connect()
        cursor = conn.cursor()
        
        # Query per ottenere dipendenti attivi (dalla form VBA)
        query = f"""
        SELECT 
            H.EmployeeHireHistoryId,
            UPPER(E.EmployeeSurname + ' ' + E.EmployeeName) COLLATE Database_default AS EmployeeName,
            ET.IDEmployee,
            E.EmployeeSex
        FROM Employee.dbo.employees E
        INNER JOIN Employee.dbo.employeeHireHistory H 
            ON E.employeeid = H.employeeid
        INNER JOIN Timeclocking.dbo.Employee AS ET 
            ON E.EmployeeNID COLLATE Database_default = ET.UniqueID 
            AND ET.DataStop IS NULL
        INNER JOIN Timeclocking.dbo.Company C 
            ON ET.IDCompany = C.IDCompany 
            AND C.CompanyCUI = (select EmployeerFiscalCode as cui from employee.dbo.employeers where employeerid={EMPLOYER_ID})
        WHERE H.endWorkDate IS NULL 
            AND H.employeerid = (
                SELECT employeerid 
                FROM employee.dbo.employeers 
                WHERE employeerFiscalCode = (select EmployeerFiscalCode as cui from employee.dbo.employeers where employeerid={EMPLOYER_ID})
            )
        ORDER BY E.employeeSurName
        """
        
        cursor.execute(query)
        employees = []
        for row in cursor.fetchall():
            employees.append({
                'id': row[0],
                'name': row[1],
                'timeclockId': row[2],
                'sex': row[3]
            })
        
        return jsonify({'success': True, 'employees': employees})
    
    except Exception as e:
        logger.error(f"Errore nel recupero dipendenti: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/certificate-reasons', methods=['GET'])
def get_certificate_reasons():
    """Recupera lista motivi certificato"""
    try:
        conn = db_connection.connect()
        cursor = conn.cursor()
        
        query = """
        SELECT 
            CerificateReasonId,
            CerificateReason,
            CanTypeSpecialReason,
            SameIdGroup
        FROM employee.dbo.CertificateReasons 
        ORDER BY CerificateReason
        """
        
        cursor.execute(query)
        reasons = []
        for row in cursor.fetchall():
            reasons.append({
                'id': row[0],
                'reason': row[1],
                'canTypeSpecial': bool(row[2]),
                'groupId': row[3] if row[3] else 0
            })
        
        return jsonify({'success': True, 'reasons': reasons})
    
    except Exception as e:
        logger.error(f"Errore nel recupero motivi: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/add-reason', methods=['POST'])
def add_reason():
    """Aggiunge nuovo motivo certificato (riservato ai manager autenticati)"""
    try:
        _, manager_session = _get_manager_auth_from_request()
        if not manager_session:
            return jsonify({'success': False, 'error': 'Autorizzazione manager richiesta'}), 401

        data = request.json
        reason = (data.get('reason') or '').strip().upper()
        if not reason or len(reason) > 100:
            return jsonify({'success': False, 'error': 'Motivo non valido'}), 400
        can_type_special = data.get('canTypeSpecial', False)
        
        conn = db_connection.connect()
        cursor = conn.cursor()
        
        query = """
        INSERT INTO employee.dbo.CertificateReasons 
        (CerificateReason, CanTypeSpecialReason) 
        VALUES (?, ?)
        """
        
        cursor.execute(query, (reason, 1 if can_type_special else None))
        conn.commit()
        
        return jsonify({'success': True, 'message': 'Motivo aggiunto con successo'})
    
    except Exception as e:
        logger.error(f"Errore nell'aggiunta motivo: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/generate-certificate', methods=['POST'])
def generate_certificate():
    """Genera certificato e lo stampa/invia"""
    badge_number = None  # Per logging kiosk
    try:
        data = request.json
        employee_id = data.get('employeeId')
        reason = data.get('reason')
        typed_reason = data.get('typedReason', '')
        group_id = data.get('groupId', 0)
        badge_number = data.get('badgeNumber', '')  # Recupera badge per logging
        
        # Validazione
        if not employee_id or not reason:
            return jsonify({
                'success': False, 
                'error': 'Dipendente e motivo sono obbligatori'
            }), 400
        
        conn = db_connection.connect()
        
        # Genera il certificato
        generator = CertificateGenerator(conn)
        result = generator.generate_certificate(
            employee_hire_history_id=employee_id,
            reason=reason,
            typed_reason=typed_reason,
            group_id=group_id
        )
        
        if result['success']:
            pdf_path = result.get('pdf_path')

            # Log richiesta kiosk
            if badge_number:
                kiosk_logger.log_certificate_request(badge_number, reason, executed=True)

            # Stampa gestita lato client (tramite bottone Stampa e window.print()).
            # Sul kiosk Chrome è lanciato con --kiosk-printing → stampa silenziosa.
            # Sui PC remoti appare il dialog di stampa del browser del client.

            # Invia email se richiesto
            if result.get('email_required'):
                try:
                    recipients = get_email_recipients(conn, 'Sys_Email_HR')
                    send_email(
                        recipients=recipients,
                        subject=result['email_subject'],
                        body=result['email_body'],
                        is_html=True
                    )
                except Exception as email_error:
                    logger.warning(f"Errore invio email: {str(email_error)}")
            
            return jsonify({
                'success': True,
                'message': 'Certificato generato con successo',
                'documentNumber': result['document_number'],
                'documentDate': result['document_date'],
                'pdfPath': result.get('pdf_path')
            })
        else:
            # Log fallimento
            if badge_number:
                kiosk_logger.log_certificate_request(badge_number, reason, executed=False)
            
            return jsonify({
                'success': False,
                'error': result.get('error', 'Errore sconosciuto')
            }), 500
    
    except Exception as e:
        logger.error(f"Errore nella generazione certificato: {str(e)}")
        
        # Log fallimento
        if badge_number:
            kiosk_logger.log_certificate_request(badge_number, reason or "Unknown", executed=False)
        
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/print-pdf/<path:filename>')
def print_pdf(filename):
    """Invia PDF al browser per stampa"""
    try:
        # Protezione path traversal: solo basename, solo PDF, solo dentro temp/
        safe_name = os.path.basename(filename)
        if not safe_name or safe_name != filename or not safe_name.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'Nome file non valido'}), 400

        pdf_path = os.path.abspath(os.path.join('temp', safe_name))
        temp_dir = os.path.abspath('temp')
        if not pdf_path.startswith(temp_dir + os.sep):
            return jsonify({'success': False, 'error': 'Path non consentito'}), 400

        if os.path.exists(pdf_path):
            return send_file(pdf_path, mimetype='application/pdf')
        else:
            return jsonify({'success': False, 'error': 'File non trovato'}), 404
    except Exception as e:
        logger.error(f"Errore nell'invio PDF: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/generate-absence-report', methods=['POST'])
def generate_absence_report():
    """Genera raport istoric absențe"""
    try:
        logger.info("=== INIZIO GENERAZIONE REPORT ABSENȚE ===")
        data = request.json
        logger.info(f"Dati ricevuti: {data}")
        
        badge_number = data.get('badgeNumber', '').strip()
        year = data.get('year')
        
        logger.info(f"Badge: {badge_number}, Anno: {year}")
        
        if not badge_number:
            logger.error("Badge number non fornito")
            return jsonify({
                'success': False,
                'error': 'Numero badge non fornito'
            }), 400
        
        if not year:
            year = datetime.now().year
        
        # Genera report
        logger.info("Connessione al database...")
        conn = db_connection.connect()
        if not conn:
            logger.error("Errore connessione database")
            return jsonify({
                'success': False,
                'error': 'Errore connessione database'
            }), 500
        
        # Normalizza badge number (padding con zeri a sinistra)
        badge_reader = BadgeReader(conn)
        normalized_badge = badge_reader.normalize_badge_number(badge_number)
        logger.info(f"Badge normalizzato: {normalized_badge}")
        
        logger.info("Creazione AbsenceReportGenerator...")
        report_generator = AbsenceReportGenerator(conn)
        
        logger.info(f"Generazione report per badge {normalized_badge}, anno {year}...")
        pdf_path = report_generator.generate_report(normalized_badge, year)
        logger.info(f"PDF generato: {pdf_path}")
        
        if not pdf_path:
            # Log fallimento
            kiosk_logger.log_absence_report_request(badge_number, year, executed=False)
            return jsonify({
                'success': False,
                'error': 'Errore generazione report'
            }), 500
        
        # Log successo richiesta
        kiosk_logger.log_absence_report_request(badge_number, year, executed=True)

        # Stampa gestita lato client (vedi /api/generate-certificate).

        # Normalizza path per URL
        pdf_filename = os.path.basename(pdf_path)
        pdf_url = f"/api/print-pdf/{pdf_filename}"

        return jsonify({
            'success': True,
            'pdf_path': pdf_path,
            'pdf_url': pdf_url,
            'pdf_filename': pdf_filename
        })
        
    except Exception as e:
        print(f"\n\n!!! ERRORE REPORT ABSENȚE: {str(e)} !!!\n")
        logger.error(f"Errore generazione report absențe: {str(e)}")
        import traceback
        traceback.print_exc()
        logger.error(traceback.format_exc())
        # Log fallimento
        if 'badge_number' in locals() and badge_number:
            kiosk_logger.log_absence_report_request(badge_number, year if 'year' in locals() else datetime.now().year, executed=False)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========================================
# API RICHIESTE ASSENZA
# ========================================

@app.route('/api/request-types', methods=['GET'])
def get_request_types():
    """Recupera tipi di richiesta disponibili"""
    try:
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        request_manager = AbsenceRequestManager(conn)
        request_types = request_manager.get_request_types()
        
        return jsonify({
            'success': True,
            'request_types': request_types
        })
        
    except Exception as e:
        logger.error(f"Errore recupero tipi richiesta: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/special-motives', methods=['GET'])
def get_special_motives():
    """Motivi speciali attivi (SpecialAbsenceMotives) con il limite giorni per evento."""
    try:
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        request_manager = AbsenceRequestManager(conn)
        motives = request_manager.get_special_motives()

        return jsonify({
            'success': True,
            'motives': motives
        })

    except Exception as e:
        logger.error(f"Errore recupero motivi speciali: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/available-vacation-days', methods=['POST'])
def get_available_vacation_days():
    """Calcola giorni ferie disponibili"""
    try:
        data = request.json
        badge_number = data.get('badgeNumber', '').strip()
        year = data.get('year', datetime.now().year)
        
        if not badge_number:
            return jsonify({'success': False, 'error': 'Badge non fornito'}), 400
        
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        # Normalizza badge
        badge_reader = BadgeReader(conn)
        normalized_badge = badge_reader.normalize_badge_number(badge_number)
        
        request_manager = AbsenceRequestManager(conn)
        vacation_data = request_manager.get_available_vacation_days(normalized_badge, year)
        
        if vacation_data:
            return jsonify({
                'success': True,
                'available_days': vacation_data['available_days'],
                'employee_name': f"{vacation_data['employee_surname']} {vacation_data['employee_name']}"
            })
        else:
            return jsonify({'success': False, 'error': 'Dati non trovati'}), 404
        
    except Exception as e:
        logger.error(f"Errore calcolo giorni disponibili: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/calculate-working-days', methods=['POST'])
def calculate_working_days():
    """Calcola giorni lavorativi escludendo weekend e festività"""
    try:
        data = request.json
        date_start_str = data.get('dateStart')
        date_end_str = data.get('dateEnd')
        request_type_id = data.get('requestTypeId')
        
        if not date_start_str or not date_end_str:
            return jsonify({'success': False, 'error': 'Date non fornite'}), 400
        
        date_start = datetime.strptime(date_start_str, '%Y-%m-%d').date()
        date_end = datetime.strptime(date_end_str, '%Y-%m-%d').date()
        
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        request_manager = AbsenceRequestManager(conn)
        
        # Recupera festività per l'anno
        year = date_start.year
        holidays = request_manager.get_holidays(year)
        
        # Se il periodo attraversa più anni, recupera anche festività anno successivo
        if date_end.year > year:
            holidays.extend(request_manager.get_holidays(date_end.year))
        
        # Calcola giorni lavorativi
        working_days = request_manager.calculate_working_days(date_start, date_end, holidays)
        
        return jsonify({
            'success': True,
            'working_days': working_days,
            'total_days': (date_end - date_start).days + 1
        })

    except Exception as e:
        logger.error(f"Errore calcolo giorni lavorativi: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/absence-quota', methods=['POST'])
def absence_quota():
    """Quota annua residua per tipi di assenza con limite per legge (urgenti/speciali)."""
    try:
        data = request.json
        badge_number = data.get('badgeNumber', '').strip()
        request_type_id = data.get('requestTypeId')

        if not badge_number or not request_type_id:
            return jsonify({'success': False, 'error': 'Badge o tipo richiesta non forniti'}), 400

        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        badge_reader = BadgeReader(conn)
        normalized_badge = badge_reader.normalize_badge_number(badge_number)
        employee_data = badge_reader.get_employee_by_badge(normalized_badge)
        if not employee_data:
            return jsonify({'success': False, 'error': 'Dipendente non trovato'}), 404

        request_manager = AbsenceRequestManager(conn)
        quota = request_manager.get_quota_info(
            employee_data['hire_history_id'],
            request_type_id,
            datetime.now().year
        )

        if quota is None:
            return jsonify({'success': False, 'error': 'Tipo di assenza senza quota annua'}), 404

        return jsonify({
            'success': True,
            'request_type_id': request_type_id,
            'max_days': quota['max_days'],
            'used': quota['used'],
            'remaining': quota['remaining'],
            'docs_deadline_days': quota['docs_deadline_days']
        })

    except Exception as e:
        logger.error(f"Errore recupero quota assenza: {str(e)}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/hr/special-docs-sweep', methods=['POST'])
def special_docs_sweep():
    """
    Esegue il controllo delle assenze speciali scadute senza documentazione:
    le annulla e le converte in giorni di congedo ordinario.
    Accessibile ai manager autenticati (stesso token delle approvazioni).
    """
    try:
        _, manager_session = _get_manager_auth_from_request()
        if not manager_session:
            return jsonify({'success': False, 'error': 'Sessione non autenticata'}), 401

        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        request_manager = AbsenceRequestManager(conn)
        conversions = request_manager.convert_expired_special_absences(employeer_id=EMPLOYER_ID)

        # Notifica email HR (best-effort, non blocca l'operazione)
        if conversions:
            try:
                recipients = get_email_recipients(conn, 'Sys_Email_HR') or [FALLBACK_EMAIL]
                rows_html = ''.join(
                    f"<tr>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['employee_name']}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['date_start'].strftime('%d.%m.%Y')} - {c['date_end'].strftime('%d.%m.%Y')}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['special_reason'] or '-'}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['docs_deadline'].strftime('%d.%m.%Y')}</td>"
                    f"</tr>"
                    for c in conversions
                )
                body = f"""
                <html><body style="font-family: Arial, sans-serif;">
                    <h2 style="color: #dc2626;">Conversie automată: absențe speciale fără documentație</h2>
                    <p>Următoarele cerere de absență pentru motive speciale au fost anulate
                    (documentația nu a fost prezentată în termenul stabilit) și transformate
                    în zile de concediu odihnă:</p>
                    <table style="border-collapse: collapse;">
                        <tr>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Angajat</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Perioada</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Motiv</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Scadență documentație</th>
                        </tr>
                        {rows_html}
                    </table>
                    <p style="font-size:12px;color:#718096;">Email generat automat de sistemul Kiosk HR.</p>
                </body></html>
                """
                send_email(
                    recipients=recipients,
                    subject=f"[Kiosk HR] {len(conversions)} absențe speciale convertite în concediu odihnă",
                    body=body,
                    is_html=True
                )
            except Exception as email_error:
                logger.warning(f"[SWEEP SPECIALI] Invio email HR fallito: {email_error}")

        return jsonify({
            'success': True,
            'converted': len(conversions),
            'conversions': [
                {
                    'absence_request_id': c['absence_request_id'],
                    'new_request_id': c['new_request_id'],
                    'employee': c['employee_name'],
                    'date_start': c['date_start'].isoformat(),
                    'date_end': c['date_end'].isoformat(),
                    'docs_deadline': c['docs_deadline'].isoformat() if c['docs_deadline'] else None
                } for c in conversions
            ]
        })

    except Exception as e:
        logger.error(f"Errore sweep assenze speciali: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/submit-absence-request', methods=['POST'])
def submit_absence_request():
    """Invia richiesta assenza"""
    try:
        logger.info("=== INIZIO INVIO RICHIESTA ASSENZA ===")
        data = request.json
        logger.info(f"Dati ricevuti: {data}")
        
        badge_number = data.get('badgeNumber', '').strip()
        request_type_id = data.get('requestTypeId')
        date_start_str = data.get('dateStart')
        date_end_str = data.get('dateEnd')
        from_time = data.get('fromTime')  # Orari per assenze parziali
        to_time = data.get('toTime')
        # Assenze urgenti: scelta del dipendente per il recupero ('MONTH' | 'YEAR')
        urgent_recovery_period = (data.get('urgentRecoveryPeriod') or '').strip().upper() or None
        # Assenze speciali: motivo dall'anagrafica SpecialAbsenceMotives
        # (SpecialReasonId = MotiveId; specialReason resta per compatibilità legacy)
        special_reason_id = data.get('specialReasonId')
        special_reason = (data.get('specialReason') or '').strip() or None
        
        # Validazioni
        if not badge_number:
            return jsonify({'success': False, 'error': 'Badge non fornito'}), 400
        
        if not request_type_id:
            return jsonify({'success': False, 'error': 'Tipo richiesta non fornito'}), 400
        
        if not date_start_str or not date_end_str:
            return jsonify({'success': False, 'error': 'Date non fornite'}), 400
        
        date_start = datetime.strptime(date_start_str, '%Y-%m-%d').date()
        date_end = datetime.strptime(date_end_str, '%Y-%m-%d').date()
        request_date = datetime.now().date()
        year = date_start.year
        
        # Connessione database
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        # Normalizza badge
        badge_reader = BadgeReader(conn)
        normalized_badge = badge_reader.normalize_badge_number(badge_number)
        logger.info(f"Badge normalizzato: {normalized_badge}")
        
        request_manager = AbsenceRequestManager(conn)
        
        # Se è richiesta ferie (IDRequestType = 1), verifica disponibilità
        if request_type_id == 1:
            logger.info("Verifica disponibilità ferie...")
            vacation_data = request_manager.get_available_vacation_days(normalized_badge, year)
            
            if not vacation_data:
                return jsonify({'success': False, 'error': 'Impossibile verificare giorni disponibili'}), 500
            
            # Calcola giorni lavorativi richiesti
            holidays = request_manager.get_holidays(year)
            if date_end.year > year:
                holidays.extend(request_manager.get_holidays(date_end.year))
            
            working_days = request_manager.calculate_working_days(date_start, date_end, holidays)
            logger.info(f"Giorni lavorativi richiesti: {working_days}")
            logger.info(f"Giorni disponibili: {vacation_data['available_days']}")
            
            if working_days > vacation_data['available_days']:
                return jsonify({
                    'success': False,
                    'error': f"Giorni richiesti ({working_days}) > Giorni disponibili ({vacation_data['available_days']})"
                }), 400
            
            hire_history_id = vacation_data['hire_history_id']
            employee_name = f"{vacation_data['employee_surname']} {vacation_data['employee_name']}"
        else:
            # Per altri tipi di richiesta, recupera solo hire_history_id
            employee_data = badge_reader.get_employee_by_badge(normalized_badge)
            if not employee_data:
                return jsonify({'success': False, 'error': 'Dipendente non trovato'}), 404
            
            hire_history_id = employee_data['hire_history_id']
            employee_name = employee_data['full_name']
            
            holidays = request_manager.get_holidays(year)
            if date_end.year > year:
                holidays.extend(request_manager.get_holidays(date_end.year))
            working_days = request_manager.calculate_working_days(date_start, date_end, holidays)
        
        # Verifica richieste duplicate
        logger.info("Verifica richieste duplicate...")
        is_duplicate = request_manager.check_duplicate_request(
            hire_history_id, request_type_id, date_start, date_end
        )
        
        if is_duplicate:
            logger.warning("Richiesta duplicata rilevata")
            return jsonify({
                'success': False,
                'error': 'Există deja o cerere identică pentru această perioadă. Vă rugăm să verificați cererile anterioare.'
            }), 400
        
        # Verifica regole DayNoZone (preavviso minimo richiesto)
        logger.info("Verifica regole DayNoZone...")
        validation_result = request_manager.validate_absence_date_rule(request_type_id, date_start)

        if not validation_result['valid']:
            logger.warning(f"Validazione DayNoZone fallita: {validation_result['message']}")
            return jsonify({
                'success': False,
                'error': validation_result['message']
            }), 400

        # ── Verifiche specifiche assenze urgenti / speciali ──────────────────
        urgent_recovery_deadline = None
        documentation_deadline = None
        special_motive = None

        if request_type_id == URGENT_ABSENCE_TYPE_ID:
            # Quota annua per legge: 10 giorni urgenti (parametro in AbsenceRules)
            logger.info(f"Verifica quota annua per tipo {request_type_id}...")
            quota_result = request_manager.check_quota_availability(
                hire_history_id, request_type_id, date_start, date_end, holidays, year
            )
            if not quota_result['valid']:
                logger.warning(f"Quota annua superata per tipo {request_type_id}")
                return jsonify({
                    'success': False,
                    'error': quota_result['message']
                }), 400

        if request_type_id == URGENT_ABSENCE_TYPE_ID:
            if urgent_recovery_period not in URGENT_RECOVERY_PERIODS:
                return jsonify({
                    'success': False,
                    'error': (
                        'Selecta\u021bi perioada de recuperare a zilelor de absen\u021b\u0103 urgent\u0103:\n'
                        '\u00een luna solicit\u0103rii sau p\u00e2n\u0103 la sf\u00e2r\u0219itul anului lucr\u0103tor.'
                    )
                }), 400
            urgent_recovery_deadline = request_manager.compute_urgent_recovery_deadline(
                urgent_recovery_period, date_start
            )

        if request_type_id == SPECIAL_ABSENCE_TYPE_ID:
            # Motivo speciale dall'anagrafica: limite giorni lavorativi PER EVENTO
            if special_reason_id in (None, ''):
                return jsonify({
                    'success': False,
                    'error': 'Selecta\u021bi motivul special (deces, c\u0103s\u0103torie etc.).'
                }), 400
            try:
                special_reason_id = int(special_reason_id)
            except (TypeError, ValueError):
                return jsonify({
                    'success': False,
                    'error': 'Motiv special invalid.'
                }), 400
            motive_validation = request_manager.validate_special_motive(
                special_reason_id, date_start, date_end, holidays
            )
            if not motive_validation['valid']:
                logger.warning(f"Validazione motivo speciale fallita: {motive_validation['message']}")
                return jsonify({
                    'success': False,
                    'error': motive_validation['message']
                }), 400
            special_motive = motive_validation['motive']
            # Nome motivo testuale (per SpecialReason: approvazioni, PDF, email, monitor)
            special_reason = special_motive['name_ro']
            # Scadenza documenti solo per i motivi che li richiedono (RequiresDocumentation)
            if special_motive['requires_documentation']:
                documentation_deadline = date_start + timedelta(
                    days=special_motive['docs_deadline_days']
                )

        # Crea entry nel registro
        logger.info("Creazione entry registro...")
        registro_id = request_manager.create_registry_entry(year, request_date, employee_name)
        
        if not registro_id:
            return jsonify({'success': False, 'error': 'Errore creazione registro'}), 500
        
        logger.info(f"Registro creato: {registro_id}")
        
        # Recupera nome tipo richiesta (prima di usarlo).
        # Il tipo di congedo DEVE sempre comparire nell'email al superiore e nel PDF:
        # se la lista non fosse disponibile si recupera il nome direttamente dal DB.
        request_types = request_manager.get_request_types()
        request_type_name = next(
            (rt['name'] for rt in request_types if rt['id'] == request_type_id), None
        )
        if not request_type_name:
            request_type_name = request_manager.get_request_type_name(request_type_id)

        # Salva richiesta assenza
        logger.info("Salvataggio richiesta assenza...")
        absence_request_id = request_manager.save_absence_request(
            registro_id, hire_history_id, request_type_id, date_start, date_end,
            from_time=from_time, to_time=to_time,  # Passa orari
            username=employee_name,
            request_type_name=request_type_name,
            urgent_recovery_period=urgent_recovery_period if request_type_id == URGENT_ABSENCE_TYPE_ID else None,
            special_reason=special_reason if request_type_id == SPECIAL_ABSENCE_TYPE_ID else None,
            special_reason_id=special_reason_id if request_type_id == SPECIAL_ABSENCE_TYPE_ID else None
        )
        
        if not absence_request_id:
            return jsonify({'success': False, 'error': 'Errore salvataggio richiesta'}), 500
        
        logger.info(f"Richiesta salvata: {absence_request_id}")
        
        # Recupera info registro
        registry_info = request_manager.get_registry_info(registro_id)
        
        if not registry_info:
            return jsonify({'success': False, 'error': 'Errore recupero info registro'}), 500
        
        # Genera PDF conferma
        logger.info("Generazione PDF conferma...")
        employee_data_pdf = {
            'name': employee_name.split()[-1] if ' ' in employee_name else employee_name,
            'surname': employee_name.split()[0] if ' ' in employee_name else '',
            'badge': normalized_badge
        }
        
        request_data_pdf = {
            'type_name': request_type_name,
            'date_start': date_start,
            'date_end': date_end,
            'working_days': working_days,
            'urgent_recovery_period': urgent_recovery_period if request_type_id == URGENT_ABSENCE_TYPE_ID else None,
            'urgent_recovery_deadline': urgent_recovery_deadline,
            'special_reason': special_reason if request_type_id == SPECIAL_ABSENCE_TYPE_ID else None,
            'documentation_deadline': documentation_deadline,
            'docs_deadline_days': special_motive['docs_deadline_days'] if special_motive else None
        }
        
        pdf_path = request_manager.generate_confirmation_pdf(employee_data_pdf, request_data_pdf, registry_info)
        
        if not pdf_path:
            return jsonify({'success': False, 'error': 'Errore generazione PDF'}), 500
        
        logger.info(f"PDF generato: {pdf_path}")

        # Stampa gestita lato client (vedi /api/generate-certificate).

        # Normalizza path per URL
        pdf_filename = os.path.basename(pdf_path)
        pdf_url = f"/api/print-pdf/{pdf_filename}"
        
        # Invia email notifica ai manager
        try:
            logger.info("[SUBMIT_ABSENCE] Recupero email manager...")
            manager_emails = request_manager.get_manager_emails(hire_history_id)
            
            logger.info(f"[SUBMIT_ABSENCE] Email manager recuperate - tipo: {type(manager_emails)}, numero: {len(manager_emails)}, contenuto: {manager_emails}")
            
            # Se non ci sono manager, usa email fallback
            if not manager_emails:
                logger.warning(f"[SUBMIT_ABSENCE] Nessun manager trovato per hire_history_id {hire_history_id}, uso email fallback")
                manager_emails = [FALLBACK_EMAIL]
            
            logger.info(f"[SUBMIT_ABSENCE] Invio email a: {manager_emails} (numero: {len(manager_emails)})")
            
            # Prepara email HTML
            subject = f"Nouă cerere de absență ({request_type_name}) - {registry_info['doc_name']}"

            # Righe aggiuntive per assenze urgenti / speciali (tipo di congedo sempre ben visibile)
            type_specific_rows = ''
            if request_type_id == URGENT_ABSENCE_TYPE_ID:
                if urgent_recovery_period == URGENT_RECOVERY_MONTH:
                    recovery_label = 'În luna solicitării'
                else:
                    recovery_label = 'Până la sfârșitul anului lucrător'
                recovery_dl = urgent_recovery_deadline.strftime('%d.%m.%Y') if urgent_recovery_deadline else '-'
                type_specific_rows += f'''
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Recuperare zile urgente:</td>
                        <td style="padding: 8px; color: #667eea; font-weight: bold;">{recovery_label} (până la {recovery_dl})</td>
                    </tr>
                '''
            elif request_type_id == SPECIAL_ABSENCE_TYPE_ID:
                docs_dl = documentation_deadline.strftime('%d.%m.%Y') if documentation_deadline else '-'
                docs_days_label = special_motive['docs_deadline_days'] if special_motive else 5
                type_specific_rows += f'''
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Motiv special:</td>
                        <td style="padding: 8px; color: #667eea; font-weight: bold;">{special_reason or '-'}</td>
                    </tr>
                '''
                if documentation_deadline:
                    type_specific_rows += f'''
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Documentație:</td>
                        <td style="padding: 8px; color: #dc2626; font-weight: bold;">⚠️ Obligatorie la HR până la {docs_dl} ({docs_days_label} zile), altfel cererea se anulează și devine concediu odihnă</td>
                    </tr>
                '''

            body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #667eea;">Nouă Cerere de Absență</h2>

                <p>S-a înregistrat o nouă cerere de absență care necesită aprobare:</p>

                <table style="border-collapse: collapse; margin: 20px 0;">
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Număr cerere:</td>
                        <td style="padding: 8px;">{registry_info['doc_name']}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Data cerere:</td>
                        <td style="padding: 8px;">{registry_info['doc_date'].strftime('%d.%m.%Y')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Angajat:</td>
                        <td style="padding: 8px;">{employee_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; font-weight: bold; font-size: 14px;">Tip absență:</td>
                        <td style="padding: 8px; color: #667eea; font-weight: bold; font-size: 14px;">{request_type_name}</td>
                    </tr>
                    {type_specific_rows}
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Perioada:</td>
                        <td style="padding: 8px;">{date_start.strftime('%d.%m.%Y')} - {date_end.strftime('%d.%m.%Y')}</td>
                    </tr>
                    {''.join([f'''
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Orario:</td>
                        <td style="padding: 8px; color: #667eea; font-weight: bold;">Dalle ore {from_time} - Fino alle ore {to_time}</td>
                    </tr>
                    ''' for _ in [1] if from_time and to_time])}
                    <tr>
                        <td style="padding: 8px; font-weight: bold;">Zile lucrătoare:</td>
                        <td style="padding: 8px;">{working_days if working_days else '-'}</td>
                    </tr>
                </table>

                <p style="color: #f59e0b; font-weight: bold;">⚠️ Această cerere este în așteptare de aprobare.</p>

                <p>Vă rugăm să verificați și să aprobați/respingeți cererea în sistemul de management.</p>

                <hr style="margin: 30px 0; border: 1px solid #e5e7eb;">

                <p style="font-size: 12px; color: #718096;">
                    Acest email a fost generat automat de sistemul Kiosk HR.<br>
                    Nu răspundeți la acest email.
                </p>
            </body>
            </html>
            """
            
            # Invia email usando utils.send_email
            logger.info(f"[SUBMIT_ABSENCE] Chiamo send_email con {len(manager_emails)} destinatari")
            send_email(
                recipients=manager_emails,
                subject=subject,
                body=body,
                is_html=True
            )
            
            logger.info("[SUBMIT_ABSENCE] Email notifica inviata con successo")
                
        except Exception as email_error:
            # Non bloccare la richiesta se l'email fallisce
            logger.error(f"[SUBMIT_ABSENCE] Errore invio email notifica: {str(email_error)}")
            import traceback
            logger.error(traceback.format_exc())
        
        # Log richiesta kiosk
        kiosk_logger.log_absence_request_submission(badge_number, request_type_name, executed=True)

        return jsonify({
            'success': True,
            'request_number': registry_info['doc_name'],
            'absence_request_id': absence_request_id,
            'registro_id': registro_id,
            'pdf_path': pdf_path,
            'pdf_url': pdf_url,
            'pdf_filename': pdf_filename,
            'request_type': request_type_name,
            'urgent_recovery_period': urgent_recovery_period if request_type_id == URGENT_ABSENCE_TYPE_ID else None,
            'urgent_recovery_deadline': urgent_recovery_deadline.isoformat() if urgent_recovery_deadline else None,
            'documentation_deadline': documentation_deadline.isoformat() if documentation_deadline else None
        })
        
    except Exception as e:
        logger.error(f"Errore invio richiesta assenza: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/manager/login', methods=['POST'])
def manager_login():
    """Login manager per approvazione richieste assenza."""
    try:
        data = request.json or {}
        user_id = (data.get('userId') or '').strip()
        password = (data.get('password') or '').strip()

        if not user_id or not password:
            return jsonify({
                'success': False,
                'error': 'UserId e Password sono obbligatori'
            }), 400

        # Rate limiting: dopo troppi fallimenti l'IP resta bloccato per la finestra
        client_ip = request.remote_addr or 'unknown'
        now = time.time()
        attempts = [t for t in _login_failures.get(client_ip, []) if now - t < LOGIN_WINDOW_SECONDS]
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            logger.warning(f"Rate limit login manager superato da {client_ip}")
            return jsonify({'success': False, 'error': 'Troppi tentativi, riprovare più tardi'}), 429
        _login_failures[client_ip] = attempts

        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        request_manager = AbsenceRequestManager(conn)
        manager_info = request_manager.authenticate_manager(user_id, password)

        if not manager_info:
            attempts.append(time.time())
            _login_failures[client_ip] = attempts
            return jsonify({
                'success': False,
                'error': 'Credenziali non valide'
            }), 401

        if not manager_info.get('main_cdc_id'):
            return jsonify({
                'success': False,
                'error': 'Manager senza CDC assegnato'
            }), 403

        _login_failures.pop(client_ip, None)

        token = uuid.uuid4().hex
        manager_auth_tokens[token] = {
            'last_seen': time.time(),
            'user_id': manager_info['user_id'],
            'manager_name': manager_info['manager_name'],
            'manager_email': manager_info.get('manager_email'),
            'function_code': manager_info.get('function_code'),
            'main_cdc_id': manager_info.get('main_cdc_id'),
            'main_cdc_description': manager_info.get('main_cdc_description'),
            'employee_hire_history_id': manager_info.get('employee_hire_history_id')
        }

        return jsonify({
            'success': True,
            'token': token,
            'manager': {
                'name': manager_info['manager_name'],
                'email': manager_info.get('manager_email'),
                'function_code': manager_info.get('function_code'),
                'main_cdc_id': manager_info.get('main_cdc_id'),
                'main_cdc_description': manager_info.get('main_cdc_description')
            }
        })

    except Exception as e:
        logger.error(f"Errore manager login: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/manager/logout', methods=['POST'])
def manager_logout():
    """Logout manager approvazioni assenza."""
    token, _ = _get_manager_auth_from_request()
    if token and token in manager_auth_tokens:
        manager_auth_tokens.pop(token, None)
    return jsonify({'success': True})


@app.route('/api/manager/session', methods=['GET'])
def manager_session_status():
    """Stato sessione manager corrente."""
    _, manager_session = _get_manager_auth_from_request()
    if not manager_session:
        return jsonify({'success': True, 'authenticated': False})

    return jsonify({
        'success': True,
        'authenticated': True,
        'manager': {
            'name': manager_session.get('manager_name'),
            'email': manager_session.get('manager_email'),
            'function_code': manager_session.get('function_code'),
            'main_cdc_id': manager_session.get('main_cdc_id'),
            'main_cdc_description': manager_session.get('main_cdc_description')
        }
    })


@app.route('/api/manager/pending-requests', methods=['GET'])
def manager_pending_requests():
    """Lista richieste pending autorizzabili dal manager loggato."""
    try:
        _, manager_session = _get_manager_auth_from_request()
        if not manager_session:
            return jsonify({'success': False, 'error': 'Sessione non autenticata'}), 401

        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        request_manager = AbsenceRequestManager(conn)
        requests = request_manager.get_requests_for_manager(
            main_cdc_id=manager_session['main_cdc_id'],
            manager_function_code=manager_session.get('function_code')
        )

        return jsonify({
            'success': True,
            'requests': requests,
            'total': len(requests)
        })

    except Exception as e:
        logger.error(f"Errore recupero pending requests manager: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/manager/decision', methods=['POST'])
def manager_decision():
    """Approva o rifiuta una richiesta assenza."""
    try:
        _, manager_session = _get_manager_auth_from_request()
        if not manager_session:
            return jsonify({'success': False, 'error': 'Sessione non autenticata'}), 401

        data = request.json or {}
        absence_request_id = data.get('absenceRequestId')
        decision = (data.get('decision') or '').strip().lower()
        refuse_motive = (data.get('refuseMotive') or '').strip()

        if not absence_request_id:
            return jsonify({'success': False, 'error': 'absenceRequestId mancante'}), 400

        if decision not in ['approve', 'reject']:
            return jsonify({'success': False, 'error': 'decision deve essere approve o reject'}), 400

        if decision == 'reject' and not refuse_motive:
            return jsonify({'success': False, 'error': 'Motivo rifiuto obbligatorio'}), 400

        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500

        request_manager = AbsenceRequestManager(conn)

        can_access = request_manager.manager_can_access_request(
            main_cdc_id=manager_session['main_cdc_id'],
            absence_request_id=absence_request_id,
            manager_function_code=manager_session.get('function_code')
        )

        if not can_access:
            return jsonify({
                'success': False,
                'error': 'Non autorizzato a gestire questa richiesta'
            }), 403

        manager_name = manager_session['manager_name']

        if decision == 'approve':
            updated = request_manager.approve_request(absence_request_id, manager_name)
        else:
            updated = request_manager.reject_request(absence_request_id, manager_name, refuse_motive)

        if not updated:
            return jsonify({
                'success': False,
                'error': 'Nessuna riga aggiornata, richiesta non trovata'
            }), 404

        return jsonify({
            'success': True,
            'message': 'Richiesta aggiornata con successo',
            'decision': decision,
            'approved_by': manager_name,
            'approved_at': datetime.now().isoformat() if decision == 'approve' else None,
            'rejected': 1 if decision == 'reject' else 0,
            'refuse_motive': refuse_motive if decision == 'reject' else None
        })

    except Exception as e:
        logger.error(f"Errore decisione manager: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500




@app.route('/api/check-request-status', methods=['POST'])
def check_request_status():
    """Verifica stato richiesta assenza tramite numero richiesta"""
    try:
        data = request.json
        request_number = data.get('requestNumber', '').strip()
        
        if not request_number:
            return jsonify({'success': False, 'error': 'Număr cerere non fornito'}), 400
        
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        cursor = conn.cursor()
        
        # Query per recuperare info richiesta incluso EmployrrHireHistoryId
        query = """
        SELECT 
            R.DocName AS RequestNumber,
            R.DocDate AS RequestDate,
            AR.AbsenceRequestId,
            AR.IDRequestType,
            RT.RequestName AS RequestType,
            AR.DateStart,
            AR.DateEnd,
            AR.Approved,
            AR.Rejected,
            AR.ApprovedBy,
            DATEDIFF(DAY, AR.DateStart, AR.DateEnd) + 1 AS TotalDays,
            AR.EmployrrHireHistoryId
        FROM [Employee].[dbo].[Registry] R
        INNER JOIN [Employee].[dbo].[AbsenceRequestes] AR 
            ON R.RegistroId = AR.RegistroId
        LEFT JOIN [Timeclocking].[dbo].[RequestType] RT
            ON AR.IDRequestType = RT.IDRequestType
        WHERE R.DocName = ?
        """
        
        cursor.execute(query, (request_number,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({
                'success': False,
                'error': f'Cererea cu numărul {request_number} nu a fost găsită'
            }), 404
        
        # Costruisci risposta
        approved_date = row[7]
        rejected_flag = row[8]
        approved_by = row[9]
        date_start = row[5]
        date_end = row[6]
        hire_history_id = row[11]
        
        # Data attuale
        current_date = datetime.now().date()
        
        # Determina stato approvazione
        # Per essere APPROVATA deve:
        # 1. Approved IS NOT NULL
        # 2. Approved != '1900-01-01'
        # 3. Approved >= DateStart AND Approved <= DateEnd
        # 4. ApprovedBy IS NOT NULL
        
        is_approved = False
        if approved_date and approved_by:
            # Verifica che non sia la data placeholder
            if approved_date.year > 1900:
                # Verifica che sia nel range del periodo richiesto
                if date_start and date_end:
                    if date_start <= approved_date.date() <= date_end:
                        is_approved = True
        
        # Determina se la richiesta è rifiutata esplicitamente
        is_rejected = bool(rejected_flag and rejected_flag != 0)
        
        # Determina se la richiesta è scaduta (expired)
        # Una richiesta è scaduta se:
        # - La data attuale è maggiore della data di inizio
        # - NON è stata approvata (Approved è NULL o placeholder o ApprovedBy è NULL)
        # - NON è stata rifiutata esplicitamente
        is_expired = False
        if date_start and current_date > date_start:
            if not is_approved and not is_rejected:
                is_expired = True
        
        # Determina se è veramente pending (in attesa)
        # Una richiesta è pending se:
        # - La data attuale è <= data di inizio
        # - NON è stata approvata
        # - NON è stata rifiutata
        is_pending = False
        if date_start and current_date <= date_start:
            if not is_approved and not is_rejected:
                is_pending = True
        
        # Determina lo stato finale
        if is_approved:
            status = 'approved'
            status_text = 'Aprobată'
        elif is_rejected:
            status = 'rejected'
            status_text = 'Respinsă'
        elif is_expired:
            status = 'expired'
            status_text = 'Expirată (neautorizată la timp)'
        elif is_pending:
            status = 'pending'
            status_text = 'În așteptare'
        else:
            status = 'unknown'
            status_text = 'Necunoscut'
        
        request_info = {
            'request_number': row[0],
            'request_date': row[1].isoformat() if row[1] else None,
            'absence_request_id': row[2],
            'request_type_id': row[3],
            'request_type': row[4] or 'Necunoscut',
            'date_start': row[5].isoformat() if row[5] else None,
            'date_end': row[6].isoformat() if row[6] else None,
            'approved': approved_date.isoformat() if approved_date else None,
            'rejected': rejected_flag,
            'approved_by': approved_by,
            'working_days': row[10],
            'hire_history_id': hire_history_id,
            'is_approved': is_approved,
            'is_rejected': is_rejected,
            'is_expired': is_expired,
            'is_pending': is_pending,
            'status': status,
            'status_text': status_text,
            'can_resend': is_pending  # Può reinviare solo se è ancora pending
        }
        
        return jsonify({
            'success': True,
            'request': request_info
        })
        
    except Exception as e:
        logger.error(f"Errore verifica stato richiesta: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/resend-absence-notification', methods=['POST'])
def resend_absence_notification():
    """Reinvia notifica email ai manager per richiesta assenza pending"""
    try:
        data = request.json
        request_number = data.get('requestNumber', '').strip()
        
        if not request_number:
            return jsonify({'success': False, 'error': 'Număr cerere non fornito'}), 400
        
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        cursor = conn.cursor()
        
        # Query per recuperare tutte le info necessarie
        query = """
        SELECT 
            R.DocName AS RequestNumber,
            R.DocDate AS RequestDate,
            R.RegistroId,
            AR.AbsenceRequestId,
            AR.IDRequestType,
            RT.RequestName AS RequestType,
            AR.DateStart,
            AR.DateEnd,
            AR.EmployrrHireHistoryId,
            UPPER(E.EmployeeSurname + ' ' + E.EmployeeName) AS EmployeeName,
            DATEDIFF(DAY, AR.DateStart, AR.DateEnd) + 1 AS TotalDays
        FROM [Employee].[dbo].[Registry] R
        INNER JOIN [Employee].[dbo].[AbsenceRequestes] AR 
            ON R.RegistroId = AR.RegistroId
        LEFT JOIN [Timeclocking].[dbo].[RequestType] RT
            ON AR.IDRequestType = RT.IDRequestType
        INNER JOIN [Employee].[dbo].[EmployeeHireHistory] H
            ON AR.EmployrrHireHistoryId = H.EmployeeHireHistoryId
        INNER JOIN [Employee].[dbo].[Employees] E
            ON H.EmployeeId = E.EmployeeId
        WHERE R.DocName = ?
        """
        
        cursor.execute(query, (request_number,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({
                'success': False,
                'error': f'Cererea cu numărul {request_number} nu a fost găsită'
            }), 404
        
        # Estrai dati
        doc_name = row[0]
        doc_date = row[1]
        hire_history_id = row[8]
        employee_name = row[9]
        request_type_name = row[5] or 'Sconosciuto'
        date_start = row[6]
        date_end = row[7]
        working_days = row[10]
        
        # Recupera email manager
        request_manager = AbsenceRequestManager(conn)
        manager_emails = request_manager.get_manager_emails(hire_history_id)
        
        # Se non ci sono manager, usa email fallback
        if not manager_emails:
            logger.warning(f"Nessun manager trovato per hire_history_id {hire_history_id}, uso email fallback")
            manager_emails = [FALLBACK_EMAIL]
        
        logger.info(f"Reinvio notifica a: {manager_emails}")
        
        # Prepara email HTML (stesso template di submit_absence_request)
        subject = f"Promemoria: Cerere de absență - {doc_name}"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #667eea;">🔔 Promemoria: Cerere de Absență în Așteptare</h2>
            
            <p>Această cerere de absență este încă în așteptare de aprobare:</p>
            
            <table style="border-collapse: collapse; margin: 20px 0;">
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Număr cerere:</td>
                    <td style="padding: 8px;">{doc_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Data cerere:</td>
                    <td style="padding: 8px;">{doc_date.strftime('%d.%m.%Y')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Angajat:</td>
                    <td style="padding: 8px;">{employee_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Tip absență:</td>
                    <td style="padding: 8px;">{request_type_name}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Perioada:</td>
                    <td style="padding: 8px;">{date_start.strftime('%d.%m.%Y')} - {date_end.strftime('%d.%m.%Y')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: bold;">Zile lucrătoare:</td>
                    <td style="padding: 8px;">{working_days}</td>
                </tr>
            </table>
            
            <p style="color: #f59e0b; font-weight: bold;">⚠️ Această cerere necesită aprobare urgentă.</p>
            
            <p>Vă rugăm să verificați și să aprobați/respingeți cererea în sistemul de management.</p>
            
            <hr style="margin: 30px 0; border: 1px solid #e5e7eb;">
            
            <p style="font-size: 12px; color: #718096;">
                Acest email a fost generat automat de sistemul Kiosk HR.<br>
                Nu răspundeți la acest email.
            </p>
        </body>
        </html>
        """
        
        # Invia email
        send_email(
            recipients=manager_emails,
            subject=subject,
            body=body,
            is_html=True
        )
        
        logger.info("Email promemoria inviata con successo")
        
        return jsonify({
            'success': True,
            'message': 'Notificare retrimisă cu succes',
            'recipients': manager_emails
        })
        
    except Exception as e:
        logger.error(f"Errore reinvio notifica: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/delete-pdf/<filename>', methods=['POST', 'DELETE'])
def delete_pdf_endpoint(filename):
    """Elimina un PDF dalla cartella temp/.

    Usato dal client dopo la stampa (o al timeout del bottone stampa)
    per non lasciare documenti personali nella cartella temporanea.
    """
    try:
        # Protezione path traversal: solo basename, solo in temp/
        safe_name = os.path.basename(filename)
        if not safe_name or safe_name != filename:
            return jsonify({'success': False, 'error': 'Nome file non valido'}), 400

        pdf_path = os.path.abspath(os.path.join('temp', safe_name))
        temp_dir = os.path.abspath('temp')
        if not pdf_path.startswith(temp_dir + os.sep):
            return jsonify({'success': False, 'error': 'Path non consentito'}), 400

        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            logger.info(f"PDF eliminato: {pdf_path}")
            return jsonify({'success': True})
        else:
            return jsonify({'success': True, 'note': 'file già assente'})

    except Exception as e:
        logger.error(f"Errore eliminazione PDF {filename}: {e}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500



# ========================================
# API NETWORK MONITORING
# ========================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check leggero — risponde subito senza query DB.
    Usato dal network-monitor.js per verificare che il server Flask sia attivo.
    """
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/log-offline', methods=['POST'])
def log_offline_event():
    """Registra eventi offline della rete"""
    try:
        from offline_logger import get_offline_logger
        
        data = request.json
        event_type = data.get('event_type')  # 'start' o 'end'
        timestamp = data.get('timestamp')
        duration_seconds = data.get('duration_seconds')
        user_agent = data.get('user_agent')
        page = data.get('page')
        
        offline_logger = get_offline_logger()
        offline_logger.log_event(
            event_type=event_type,
            timestamp=timestamp,
            duration_seconds=duration_seconds,
            user_agent=user_agent,
            page=page
        )
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Errore log offline event: {e}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/offline-statistics', methods=['GET'])
def get_offline_statistics():
    """Recupera statistiche eventi offline"""
    try:
        from offline_logger import get_offline_logger
        
        hours = request.args.get('hours', 24, type=int)
        
        offline_logger = get_offline_logger()
        stats = offline_logger.get_statistics(hours=hours)
        
        return jsonify({
            'success': True,
            'statistics': stats
        })
        
    except Exception as e:
        logger.error(f"Errore recupero statistiche offline: {e}")
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


@app.route('/api/news/print', methods=['POST'])
def print_news():
    """Stampa una news specifica con logo e registrazione in KiosRequestes"""
    conn = None  # Inizializza per evitare UnboundLocalError in finally
    try:
        data = request.json
        news_id = data.get('newsId')
        news_text = data.get('newsText')
        news_date = data.get('newsDate')
        publisher = data.get('publisher', 'Sistema')
        printable = data.get('printable', False)  # Nuovo campo
        
        # Controllo se la news è stampabile
        if not printable:
            logger.warning(f"⚠️ Tentativo stampa news {news_id} NON stampabile (Printable=0)")
            return jsonify({
                'success': False, 
                'error': 'Questa news non può essere stampata'
            }), 403
        
        if not news_id or not news_text:
            return jsonify({'success': False, 'error': 'Dati incompleti'}), 400
        
        logger.info(f"📄 Richiesta stampa news ID: {news_id}")
        
        conn = db_connection.connect()
        if not conn:
            return jsonify({'success': False, 'error': 'Errore connessione database'}), 500
        
        # 1. Registra richiesta in KiosRequestes
        ip_address = request.remote_addr or 'Unknown'
        room_name = 'Kiosk HR'
        
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO [Employee].[dbo].[KiosRequestes] 
                (RequestDate, IpRequest, RequestBy, RequestWhat, Executed)
            VALUES (GETDATE(), ?, ?, ?, 0)
        """, (ip_address, room_name, f'Stampa News {news_id}'))
        conn.commit()
        
        logger.info("✅ Richiesta registrata in KiosRequestes")
        
        # 2. Genera PDF della news
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from datetime import datetime as dt
        
        # Registra font
        try:
            pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
            font_name = 'DejaVuSans'
            font_bold = 'DejaVuSans-Bold'
        except:
            font_name = 'Helvetica'
            font_bold = 'Helvetica-Bold'
        
        # Crea PDF
        pdf_filename = f"news_{news_id}_{dt.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join('temp', pdf_filename)
        
        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4
        
        # Logo
        if os.path.exists(LOGO_PATH):
            try:
                img = ImageReader(LOGO_PATH)
                c.drawImage(img, 30*mm, height - 40*mm, width=40*mm, height=20*mm, preserveAspectRatio=True)
            except:
                pass
        
        # Titolo
        c.setFont(font_bold, 24)
        c.drawString(80*mm, height - 30*mm, "Comunicare Companiei")
        
        # Linea separatore
        c.setStrokeColorRGB(0.2, 0.2, 0.2)
        c.setLineWidth(2)
        c.line(30*mm, height - 45*mm, width - 30*mm, height - 45*mm)
        
        # Metadati
        y_pos = height - 55*mm
        c.setFont(font_bold, 14)
        c.drawString(30*mm, y_pos, "Data:")
        c.setFont(font_name, 14)
        formatted_date = dt.fromisoformat(news_date.replace('Z', '+00:00')).strftime('%d/%m/%Y') if news_date else dt.now().strftime('%d/%m/%Y')
        c.drawString(70*mm, y_pos, formatted_date)
        
        y_pos -= 8*mm
        c.setFont(font_bold, 14)
        c.drawString(30*mm, y_pos, "Publicat de:")
        c.setFont(font_name, 14)
        c.drawString(70*mm, y_pos, publisher)
        
        y_pos -= 8*mm
        c.setFont(font_bold, 14)
        c.drawString(30*mm, y_pos, "ID Știri:")
        c.setFont(font_name, 14)
        c.drawString(70*mm, y_pos, str(news_id))
        
        y_pos -= 5*mm
        c.setLineWidth(1)
        c.line(30*mm, y_pos, width - 30*mm, y_pos)
        
        # Contenuto con font 18 (ridotto leggermente per più spazio)
        y_pos -= 10*mm
        c.setFont(font_name, 18)
        
        # Margini migliorati
        left_margin = 35*mm  # Maggiore margine sinistro
        max_width = width - 70*mm  # Margini bilanciati
        
        # Split testo su punti per paragrafi
        # Ogni frase dopo un punto inizia su nuova riga
        import re
        
        # Split su punteggiatura (.!?) seguita da spazio
        # Mantiene la punteggiatura nella frase
        sentence_endings = re.split(r'([.!?])\s+', news_text)
        
        sentences = []
        for i in range(0, len(sentence_endings)-1, 2):
            if sentence_endings[i].strip():
                sentence = sentence_endings[i].strip() + sentence_endings[i+1]
                sentences.append(sentence)
        
        # Aggiungi ultima parte se non termina con punteggiatura
        if len(sentence_endings) % 2 == 1 and sentence_endings[-1].strip():
            sentences.append(sentence_endings[-1].strip())
        
        logger.info(f"📝 Split testo in {len(sentences)} frasi per formattazione PDF")
        
        # Word wrap per ogni frase
        lines = []
        for idx, sentence in enumerate(sentences):
            words = sentence.split()
            current_line = []
            
            for word in words:
                test_line = ' '.join(current_line + [word])
                if c.stringWidth(test_line, font_name, 18) <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            
            if current_line:
                lines.append(' '.join(current_line))
            
            # Aggiungi spazio extra dopo ogni frase (tranne l'ultima)
            if idx < len(sentences) - 1:
                lines.append('PARAGRAPH_BREAK')  # Marker speciale invece di stringa vuota
        
        logger.info(f"📄 Formattate {len(lines)} righe (inclusi {sentences.__len__()-1} spazi paragrafo)")
        
        # Stampa linee con spaziatura migliorata
        line_height = 6.5*mm
        paragraph_spacing = 3*mm  # Spazio extra tra paragrafi
        
        for line in lines:
            if y_pos < 40*mm:
                c.showPage()
                c.setFont(font_name, 18)
                y_pos = height - 30*mm
            
            if line == 'PARAGRAPH_BREAK':
                # Marker = spazio tra paragrafi
                y_pos -= paragraph_spacing
            else:
                c.drawString(left_margin, y_pos, line)
                y_pos -= line_height
        
        # Footer
        c.setFont(font_name, 10)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        footer = f"Tipărit la {dt.now().strftime('%d/%m/%Y ora %H:%M')} de {room_name}"
        c.drawCentredString(width / 2, 20*mm, footer)
        c.save()
        
        # 3. Stampa
        printer_name = get_default_printer()
        print_success = False
        
        if printer_name and os.path.exists(pdf_path):
            print_success = print_pdf_silent(pdf_path, printer_name)
            if print_success:
                cursor.execute("""
                    UPDATE [Employee].[dbo].[KiosRequestes]
                    SET Executed = 1
                    WHERE RequestWhat = ? AND RequestDate = (
                        SELECT MAX(RequestDate) FROM [Employee].[dbo].[KiosRequestes]
                        WHERE RequestWhat = ?)
                """, (f'Stampa News {news_id}', f'Stampa News {news_id}'))
                conn.commit()
                logger.info("✅ Stampa eseguita e registrata con successo")
            else:
                logger.warning("⚠️ PDF generato ma stampa fallita")
        else:
            if not printer_name:
                logger.warning("⚠️ Nessuna stampante configurata")
            if not os.path.exists(pdf_path):
                logger.error(f"⚠️ PDF non trovato: {pdf_path}")
        
        return jsonify({
            'success': True,
            'message': 'Richiesta processata',
            'printed': print_success,
            'pdf_generated': os.path.exists(pdf_path),
            'printer_available': printer_name is not None
        })
        
    except Exception as e:
        logger.error(f"Errore stampa news: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': 'Errore interno del server'}), 500


if __name__ == '__main__':
    # Crea directory temp se non esiste
    os.makedirs('temp', exist_ok=True)

    # Avvia servizio keep-alive stampante (ogni 5 minuti)
    logger.info("Avvio Printer Keep-Alive service...")
    start_printer_keepalive(interval_seconds=300)

    # Sweep iniziale delle assenze speciali scadute senza documentazione
    # (il controllo giornaliero programmatico è nel kiosk_reports_service)
    try:
        sweep_conn = db_connection.connect()
        if sweep_conn:
            sweep_manager = AbsenceRequestManager(sweep_conn)
            converted = sweep_manager.convert_expired_special_absences(employeer_id=EMPLOYER_ID)
            if converted:
                logger.info(f"[SWEEP SPECIALI] {len(converted)} assenze speciali convertite in congedo ordinario all'avvio")
            sweep_conn.disconnect()
    except Exception as sweep_error:
        logger.warning(f"[SWEEP SPECIALI] Sweep all'avvio fallito (non bloccante): {sweep_error}")
    
    try:
        # Server WSGI di produzione se disponibile, altrimenti server di sviluppo Flask
        try:
            from waitress import serve
        except ImportError:
            serve = None
        if serve is not None:
            logger.info("Avvio server HTTP produzione (waitress) su 0.0.0.0:3000")
            serve(app, host='0.0.0.0', port=3000, threads=8)
        else:
            logger.warning("waitress non installata: uso il server di sviluppo Flask")
            app.run(host='0.0.0.0', port=3000, debug=False, use_reloader=False, threaded=True)
    finally:
        # Arresta keep-alive alla chiusura
        logger.info("Arresto Printer Keep-Alive service...")
        stop_printer_keepalive()
