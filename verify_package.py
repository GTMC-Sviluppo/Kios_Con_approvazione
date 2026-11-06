"""
Script per verificare il contenuto del package ZIP
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import zipfile
import os
from glob import glob

# Trova l'ultimo ZIP creato
zip_files = glob("Kiosk_HR_v2.2.0_*.zip")
if not zip_files:
    print("Nessun file ZIP trovato!")
    exit(1)

# Ordina per data di modifica (più recente prima)
latest_zip = max(zip_files, key=os.path.getmtime)

print("=" * 80)
print(f"VERIFICA CONTENUTO: {latest_zip}")
print("=" * 80)

with zipfile.ZipFile(latest_zip, 'r') as zipf:
    all_files = zipf.namelist()
    
    # Filtra solo file .py nella root
    py_files = [f for f in all_files if f.endswith('.py') and '/' not in f and '\\' not in f]
    
    print(f"\nFile Python (.py) nella root: {len(py_files)}")
    print("-" * 80)
    
    for f in sorted(py_files):
        print(f"  ✓ {f}")
    
    print()
    print("-" * 80)
    print(f"Totale file nel ZIP: {len(all_files)}")
    
    # Statistiche per tipo
    md_files = [f for f in all_files if f.endswith('.md')]
    bat_files = [f for f in all_files if f.endswith('.bat')]
    html_files = [f for f in all_files if f.endswith('.html')]
    css_files = [f for f in all_files if f.endswith('.css')]
    js_files = [f for f in all_files if f.endswith('.js')]
    
    print(f"\nStatistiche:")
    print(f"  - File .py: {len(py_files)}")
    print(f"  - File .md: {len(md_files)}")
    print(f"  - File .bat: {len(bat_files)}")
    print(f"  - File .html: {len(html_files)}")
    print(f"  - File .css: {len(css_files)}")
    print(f"  - File .js: {len(js_files)}")
    
    # Dimensione ZIP
    size_mb = os.path.getsize(latest_zip) / (1024 * 1024)
    print(f"\nDimensione ZIP: {size_mb:.2f} MB")
    
    print()
    print("=" * 80)
    
    # Verifica file critici
    critical_files = [
        'app.py',
        'config_manager.py',
        'db_connection.py',
        'company_config.py',
        'certificate_generator.py',
        'absence_report.py',
        'absence_request.py',
        'email_connector.py',
        'kiosk_request_logger.py',
        'utils.py',
    ]
    
    print("\nVerifica file critici:")
    missing = []
    for cf in critical_files:
        if cf in all_files:
            print(f"  ✓ {cf}")
        else:
            print(f"  ✗ MANCANTE: {cf}")
            missing.append(cf)
    
    if missing:
        print(f"\n⚠ ATTENZIONE: {len(missing)} file critici mancanti!")
        print("=" * 80)
        exit(1)
    else:
        print("\n✓ Tutti i file critici sono presenti!")
        print("=" * 80)
