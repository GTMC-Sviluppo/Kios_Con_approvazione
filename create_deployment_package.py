"""
Script per creare il package di deployment del Kiosk HR System
Include tutti i file necessari per l'installazione
"""
import os
import zipfile
from datetime import datetime
import shutil

def create_deployment_package():
    """Crea il file ZIP con tutti i componenti necessari"""
    
    # Nome del package con timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version = "2.2.0"
    zip_filename = f"Kiosk_HR_v{version}_{timestamp}.zip"
    
    print("=" * 80)
    print(f"CREAZIONE PACKAGE DEPLOYMENT - Kiosk HR v{version}")
    print("=" * 80)
    print(f"File di output: {zip_filename}")
    print()
    
    # File e directory da includere
    include_files = [
        # Core application
        'app.py',
        'config_manager.py',
        'db_connection.py',
        'company_config.py',  # parametri aziendali (importato da app.py: senza, il kiosk non si avvia)
        'utils.py',
        
        # Generatori e report
        'certificate_generator.py',
        'absence_report.py',
        'absence_request.py',
        
        # Gestione firma digitale e PDF
        'digital_signature.py',
        'pdf_printer.py',
        'pdf_signature_powershell.py',
        'pdf_digital_signer.py',  # NUOVO! - Firma digitale con certificati
        'windows_cert_signer.py',  # NUOVO! - Firma con Windows Store
        'update_signature.py',
        
        # Connettori e logger
        'email_connector.py',
        'kiosk_request_logger.py',
        'offline_logger.py',  # NUOVO! - Logging eventi disconnessione rete
        
        # Hardware e RFID
        'badge_reader.py',
        'rfid_reader.py',
        'printer_keepalive.py',
        
        # Servizi background
        'service_kiosk_reports.py',
        
        # Script di utilità e diagnostici
        'check_news.py',
        'diagnose_news.py',
        'test_api_news.py',
        'insert_test_news.py',
        'test_news.py',
        'test_kiosk_logger.py',
        
        # Setup e deployment
        'setup.py',
        'create_deployment_package.py',
        
        # Configurazione
        'config.ini',
        'requirements.txt',
        
        # Script batch
        'START_APP.bat',
        'INSTALLA.bat',
        'INSTALLA_RAPIDA.bat',  # NUOVO! - Per installazioni problematiche
        'AGGIORNA_FIRMA.bat',
        
        # Documentazione
        'README.md',
        'FIX_NEWS_SISTEMA.md',
        'NEWS_SISTEMA_COMPLETO.md',
        'GUIDA_SQL_NEWS.md',
        'GUIDA_INSTALLAZIONE.md',
        'GUIDA_NEWS_SLIDESHOW.md',
        'GUIDA_FIRMA_DIGITALE.md',  # NUOVO! - Setup firma digitale
        'SETUP_FIRMA_PRODUZIONE.md',  # NUOVO! - Deploy firma produzione
        'RELEASE_NOTES_v2.2.0.md',
        'QUICK_START_KIOSK_MONITORING.md',
        'QUICK_START_CONFIGURAZIONE.md',  # NUOVO! - Prima config DB
        'CONFIGURAZIONE_RETE.md',
        'STAMPA_AUTOMATICA.md',
        'RIEPILOGO_INTERVENTO_2026-01-09.md',
        'RISOLUZIONE_PROBLEMI_INSTALLAZIONE.md',  # NUOVO! - Troubleshooting installazione
    ]
    
    include_dirs = [
        'templates',
        'static',
        'Images',
        'Fonts',
        'sql',  # migrazioni DB idempotenti da applicare nelle nuove sedi
    ]
    
    # Crea il file ZIP
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        file_count = 0
        
        # Aggiungi file singoli
        print("Aggiunta file singoli...")
        for filename in include_files:
            if os.path.exists(filename):
                zipf.write(filename)
                file_count += 1
                print(f"  ✓ {filename}")
            else:
                print(f"  ⚠ SKIP: {filename} (non trovato)")
        
        print()
        
        # Aggiungi directory
        print("Aggiunta directory...")
        for dirname in include_dirs:
            if os.path.exists(dirname):
                dir_file_count = 0
                for root, dirs, files in os.walk(dirname):
                    # Escludi __pycache__
                    if '__pycache__' in root:
                        continue
                    
                    for file in files:
                        # Escludi file temporanei
                        if file.endswith(('.pyc', '.pyo', '.log', '.tmp')):
                            continue
                        
                        filepath = os.path.join(root, file)
                        zipf.write(filepath)
                        file_count += 1
                        dir_file_count += 1
                
                print(f"  ✓ {dirname}/ ({dir_file_count} file)")
            else:
                print(f"  ⚠ SKIP: {dirname}/ (non trovato)")
        
        print()
    
    # Verifica dimensione
    size_mb = os.path.getsize(zip_filename) / (1024 * 1024)
    
    print("=" * 80)
    print("✓ PACKAGE CREATO CON SUCCESSO!")
    print("=" * 80)
    print(f"File: {zip_filename}")
    print(f"Dimensione: {size_mb:.2f} MB")
    print(f"File inclusi: {file_count}")
    print()
    print("Il package è pronto per la distribuzione!")
    print("=" * 80)
    
    return zip_filename

if __name__ == '__main__':
    try:
        zip_file = create_deployment_package()
        print(f"\nPer installare su un altro PC:")
        print(f"1. Copiare {zip_file}")
        print(f"2. Estrarre il contenuto")
        print(f"3. Eseguire INSTALLA.bat come amministratore")
    except Exception as e:
        print(f"\n✗ ERRORE: {str(e)}")
        import traceback
        traceback.print_exc()
