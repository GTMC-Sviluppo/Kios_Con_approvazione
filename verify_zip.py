"""
Script semplificato per verificare il contenuto del package ZIP
"""
import zipfile
import os
from glob import glob

# Trova l'ultimo ZIP creato
zip_files = glob("Kiosk_HR_v2.2.0_*.zip")
if not zip_files:
    print("Nessun file ZIP trovato!")
    exit(1)

latest_zip = max(zip_files, key=os.path.getmtime)

print("=" * 70)
print("VERIFICA CONTENUTO ZIP: " + os.path.basename(latest_zip))
print("=" * 70)

with zipfile.ZipFile(latest_zip, 'r') as zipf:
    all_files = zipf.namelist()
    
    # File Python nella root
    py_files = [f for f in all_files if f.endswith('.py') and '/' not in f]
    
    print("\nFile Python trovati: " + str(len(py_files)))
    print("-" * 70)
    
    for f in sorted(py_files):
        print("  " + f)
    
    # Verifica file critici
    critical = ['app.py', 'config_manager.py', 'db_connection.py', 'company_config.py',
                'certificate_generator.py', 'absence_report.py', 
                'absence_request.py', 'email_connector.py', 
                'kiosk_request_logger.py', 'utils.py']
    
    print("\n" + "-" * 70)
    print("Verifica file critici:")
    missing = []
    for cf in critical:
        if cf in all_files:
            print("  [OK] " + cf)
        else:
            print("  [MANCANTE] " + cf)
            missing.append(cf)
    
    # Statistiche
    print("\n" + "=" * 70)
    print("Statistiche:")
    print("  Totale file: " + str(len(all_files)))
    print("  File .py: " + str(len([f for f in all_files if f.endswith('.py')])))
    print("  File .md: " + str(len([f for f in all_files if f.endswith('.md')])))
    print("  Dimensione: " + "{:.2f}".format(os.path.getsize(latest_zip) / (1024 * 1024)) + " MB")
    
    if missing:
        print("\nATTENZIONE: " + str(len(missing)) + " file critici mancanti!")
        print("=" * 70)
        exit(1)
    else:
        print("\nTutti i file critici sono presenti!")
        print("=" * 70)
