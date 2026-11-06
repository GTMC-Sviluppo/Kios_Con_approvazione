"""
Servizio Invio Report Mensili Utilizzo Kiosk
Background service che invia email mensili con statistiche YTD e mensili
Esegue automaticamente ogni primo del mese
"""
import schedule
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import os
import sys

# Aggiungi directory corrente al path per import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from db_connection import DatabaseConnection
from email_connector import EmailSender
from company_config import REPORT_RECIPIENTS, EMAIL_FROM, COMPANY_NAME, EMPLOYER_ID
from absence_request import AbsenceRequestManager

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('kiosk_reports_service.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class KioskReportsService:
    """
    Servizio per generare e inviare report mensili sull'utilizzo del Kiosk
    """

    def __init__(self):
        """Inizializza il servizio"""
        self.config_manager = ConfigManager()
        self.db_connection = DatabaseConnection(self.config_manager)
        self.email_sender = EmailSender()

        # Destinatari email (letti da print_config.json via company_config)
        self.recipients = list(REPORT_RECIPIENTS)

        # Setup credenziali email (mittente da company_config)
        self.email_sender.save_credentials(EMAIL_FROM, "")

    def get_monthly_statistics(self, year: int, month: int) -> Dict:
        """
        Recupera statistiche per un mese specifico

        Args:
            year: Anno
            month: Mese (1-12)

        Returns:
            Dict con le statistiche del mese
        """
        try:
            conn = self.db_connection.get_connection()

            query = """
            SELECT 
                COUNT(*) AS TotalRequests,
                SUM(CASE WHEN Executed = 1 THEN 1 ELSE 0 END) AS SuccessfulRequests,
                SUM(CASE WHEN Executed = 0 THEN 1 ELSE 0 END) AS FailedRequests,
                COUNT(DISTINCT RequestBy) AS UniqueUsers,
                COUNT(DISTINCT IpRequest) AS UniqueTerminals
            FROM [Employee].[dbo].[KiosRequestes]
            WHERE YEAR(RequestDate) = ? AND MONTH(RequestDate) = ?
            """

            with conn.cursor() as cursor:
                cursor.execute(query, (year, month))
                row = cursor.fetchone()

                if row:
                    return {
                        'total_requests': row[0] or 0,
                        'successful_requests': row[1] or 0,
                        'failed_requests': row[2] or 0,
                        'unique_users': row[3] or 0,
                        'unique_terminals': row[4] or 0
                    }

            return {
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'unique_users': 0,
                'unique_terminals': 0
            }

        except Exception as e:
            logger.error(f"Errore nel recupero statistiche mensili: {e}")
            raise

    def get_ytd_statistics(self, year: int) -> Dict:
        """
        Recupera statistiche Year-To-Date

        Args:
            year: Anno

        Returns:
            Dict con le statistiche YTD
        """
        try:
            conn = self.db_connection.get_connection()

            query = """
            SELECT 
                COUNT(*) AS TotalRequests,
                SUM(CASE WHEN Executed = 1 THEN 1 ELSE 0 END) AS SuccessfulRequests,
                SUM(CASE WHEN Executed = 0 THEN 1 ELSE 0 END) AS FailedRequests,
                COUNT(DISTINCT RequestBy) AS UniqueUsers,
                COUNT(DISTINCT IpRequest) AS UniqueTerminals
            FROM [Employee].[dbo].[KiosRequestes]
            WHERE YEAR(RequestDate) = ?
            """

            with conn.cursor() as cursor:
                cursor.execute(query, (year,))
                row = cursor.fetchone()

                if row:
                    return {
                        'total_requests': row[0] or 0,
                        'successful_requests': row[1] or 0,
                        'failed_requests': row[2] or 0,
                        'unique_users': row[3] or 0,
                        'unique_terminals': row[4] or 0
                    }

            return {
                'total_requests': 0,
                'successful_requests': 0,
                'failed_requests': 0,
                'unique_users': 0,
                'unique_terminals': 0
            }

        except Exception as e:
            logger.error(f"Errore nel recupero statistiche YTD: {e}")
            raise

    def get_top_requests_by_type(self, year: int, month: int = None, limit: int = 10) -> List[Tuple]:
        """
        Recupera top richieste per tipologia

        Args:
            year: Anno
            month: Mese (opzionale, se None considera tutto l'anno)
            limit: Numero massimo di risultati

        Returns:
            List di tuple (RequestWhat, Count)
        """
        try:
            conn = self.db_connection.get_connection()

            if month:
                query = """
                SELECT TOP (?) 
                    RequestWhat, 
                    COUNT(*) AS RequestCount
                FROM [Employee].[dbo].[KiosRequestes]
                WHERE YEAR(RequestDate) = ? AND MONTH(RequestDate) = ?
                GROUP BY RequestWhat
                ORDER BY RequestCount DESC
                """
                params = (limit, year, month)
            else:
                query = """
                SELECT TOP (?) 
                    RequestWhat, 
                    COUNT(*) AS RequestCount
                FROM [Employee].[dbo].[KiosRequestes]
                WHERE YEAR(RequestDate) = ?
                GROUP BY RequestWhat
                ORDER BY RequestCount DESC
                """
                params = (limit, year)

            with conn.cursor() as cursor:
                cursor.execute(query, params)
                results = cursor.fetchall()

                return [(row[0], row[1]) for row in results] if results else []

        except Exception as e:
            logger.error(f"Errore nel recupero top richieste: {e}")
            raise

    def get_top_users(self, year: int, month: int = None, limit: int = 10) -> List[Tuple]:
        """
        Recupera top utenti per numero di richieste

        Args:
            year: Anno
            month: Mese (opzionale)
            limit: Numero massimo di risultati

        Returns:
            List di tuple (RequestBy, Count)
        """
        try:
            conn = self.db_connection.get_connection()

            if month:
                query = """
                SELECT TOP (?) 
                    RequestBy, 
                    COUNT(*) AS RequestCount
                FROM [Employee].[dbo].[KiosRequestes]
                WHERE YEAR(RequestDate) = ? AND MONTH(RequestDate) = ?
                GROUP BY RequestBy
                ORDER BY RequestCount DESC
                """
                params = (limit, year, month)
            else:
                query = """
                SELECT TOP (?) 
                    RequestBy, 
                    COUNT(*) AS RequestCount
                FROM [Employee].[dbo].[KiosRequestes]
                WHERE YEAR(RequestDate) = ?
                GROUP BY RequestBy
                ORDER BY RequestCount DESC
                """
                params = (limit, year)

            with conn.cursor() as cursor:
                cursor.execute(query, params)
                results = cursor.fetchall()

                return [(row[0], row[1]) for row in results] if results else []

        except Exception as e:
            logger.error(f"Errore nel recupero top users: {e}")
            raise

    def generate_html_report(self, ytd_stats: Dict, monthly_stats: Dict, 
                            ytd_top_requests: List, monthly_top_requests: List,
                            ytd_top_users: List, monthly_top_users: List,
                            year: int, month: int) -> str:
        """
        Genera report HTML professionale

        Args:
            ytd_stats: Statistiche YTD
            monthly_stats: Statistiche mensili
            ytd_top_requests: Top richieste YTD
            monthly_top_requests: Top richieste mensili
            ytd_top_users: Top users YTD
            monthly_top_users: Top users mensili
            year: Anno
            month: Mese

        Returns:
            str: HTML formattato
        """
        month_names = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ]
        month_name = month_names[month - 1]

        # Calcola percentuale successo
        ytd_success_rate = 0
        if ytd_stats['total_requests'] > 0:
            ytd_success_rate = (ytd_stats['successful_requests'] / ytd_stats['total_requests']) * 100

        monthly_success_rate = 0
        if monthly_stats['total_requests'] > 0:
            monthly_success_rate = (monthly_stats['successful_requests'] / monthly_stats['total_requests']) * 100

        # Genera tabella top richieste mensili
        monthly_requests_rows = ""
        for idx, (request_type, count) in enumerate(monthly_top_requests, 1):
            monthly_requests_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{idx}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{request_type}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right; font-weight: 600;">{count}</td>
            </tr>
            """

        # Genera tabella top richieste YTD
        ytd_requests_rows = ""
        for idx, (request_type, count) in enumerate(ytd_top_requests, 1):
            ytd_requests_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{idx}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{request_type}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right; font-weight: 600;">{count}</td>
            </tr>
            """

        # Genera tabella top users mensili
        monthly_users_rows = ""
        for idx, (user, count) in enumerate(monthly_top_users, 1):
            monthly_users_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{idx}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{user}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right; font-weight: 600;">{count}</td>
            </tr>
            """

        # Genera tabella top users YTD
        ytd_users_rows = ""
        for idx, (user, count) in enumerate(ytd_top_users, 1):
            ytd_users_rows += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{idx}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{user}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; text-align: right; font-weight: 600;">{count}</td>
            </tr>
            """

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Kiosk HR - Monthly Usage Report</title>
        </head>
        <body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f5f5f5; margin: 0; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;">
                
                <!-- Header con Logo -->
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center;">
                    <img src="cid:logo" alt="{COMPANY_NAME} Logo" style="max-width: 200px; height: auto; margin-bottom: 20px;">
                    <h1 style="color: white; margin: 0; font-size: 28px;">Kiosk HR Usage Report</h1>
                    <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 16px;">{month_name} {year}</p>
                </div>

                <!-- Contenuto -->
                <div style="padding: 30px;">
                    
                    <!-- Sezione Mensile -->
                    <div style="margin-bottom: 40px;">
                        <h2 style="color: #667eea; border-bottom: 2px solid #667eea; padding-bottom: 10px; margin-bottom: 20px;">
                            📊 Monthly Summary - {month_name} {year}
                        </h2>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-bottom: 25px;">
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #667eea;">{monthly_stats['total_requests']}</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Total Requests</div>
                            </div>
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #10b981;">{monthly_stats['unique_users']}</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Unique Users</div>
                            </div>
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #3b82f6;">{monthly_success_rate:.1f}%</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Success Rate</div>
                            </div>
                        </div>

                        <div style="margin-bottom: 25px;">
                            <h3 style="color: #333; font-size: 18px;">Top Request Types</h3>
                            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                                <thead>
                                    <tr style="background-color: #f8f9fa;">
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">#</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">Request Type</th>
                                        <th style="padding: 10px; text-align: right; border-bottom: 2px solid #dee2e6;">Count</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {monthly_requests_rows}
                                </tbody>
                            </table>
                        </div>

                        <div>
                            <h3 style="color: #333; font-size: 18px;">Top Users</h3>
                            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                                <thead>
                                    <tr style="background-color: #f8f9fa;">
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">#</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">User</th>
                                        <th style="padding: 10px; text-align: right; border-bottom: 2px solid #dee2e6;">Requests</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {monthly_users_rows}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Sezione YTD -->
                    <div style="margin-bottom: 20px;">
                        <h2 style="color: #764ba2; border-bottom: 2px solid #764ba2; padding-bottom: 10px; margin-bottom: 20px;">
                            📈 Year-To-Date Summary - {year}
                        </h2>
                        
                        <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-bottom: 25px;">
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #764ba2;">{ytd_stats['total_requests']}</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Total Requests</div>
                            </div>
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #10b981;">{ytd_stats['unique_users']}</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Unique Users</div>
                            </div>
                            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 32px; font-weight: 700; color: #3b82f6;">{ytd_success_rate:.1f}%</div>
                                <div style="font-size: 14px; color: #666; margin-top: 5px;">Success Rate</div>
                            </div>
                        </div>

                        <div style="margin-bottom: 25px;">
                            <h3 style="color: #333; font-size: 18px;">Top Request Types (YTD)</h3>
                            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                                <thead>
                                    <tr style="background-color: #f8f9fa;">
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">#</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">Request Type</th>
                                        <th style="padding: 10px; text-align: right; border-bottom: 2px solid #dee2e6;">Count</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {ytd_requests_rows}
                                </tbody>
                            </table>
                        </div>

                        <div>
                            <h3 style="color: #333; font-size: 18px;">Top Users (YTD)</h3>
                            <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                                <thead>
                                    <tr style="background-color: #f8f9fa;">
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">#</th>
                                        <th style="padding: 10px; text-align: left; border-bottom: 2px solid #dee2e6;">User</th>
                                        <th style="padding: 10px; text-align: right; border-bottom: 2px solid #dee2e6;">Requests</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {ytd_users_rows}
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>

                <!-- Footer -->
                <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #dee2e6;">
                    <p style="margin: 0; font-size: 12px; color: #666;">
                        Automated report generated on {datetime.now().strftime('%B %d, %Y at %H:%M')}
                    </p>
                    <p style="margin: 5px 0 0 0; font-size: 12px; color: #999;">
                        Kiosk HR System - {COMPANY_NAME} © {year}
                    </p>
                </div>

            </div>
        </body>
        </html>
        """

        return html

    def send_monthly_report(self):
        """
        Genera e invia il report mensile
        """
        try:
            # Calcola mese precedente
            today = datetime.now()
            last_month = today.replace(day=1) - timedelta(days=1)
            year = last_month.year
            month = last_month.month

            logger.info(f"Generazione report per {month}/{year}")

            # Ottieni statistiche
            monthly_stats = self.get_monthly_statistics(year, month)
            ytd_stats = self.get_ytd_statistics(year)

            # Top requests
            monthly_top_requests = self.get_top_requests_by_type(year, month, 10)
            ytd_top_requests = self.get_top_requests_by_type(year, None, 10)

            # Top users
            monthly_top_users = self.get_top_users(year, month, 10)
            ytd_top_users = self.get_top_users(year, None, 10)

            # Genera HTML
            html_body = self.generate_html_report(
                ytd_stats, monthly_stats,
                ytd_top_requests, monthly_top_requests,
                ytd_top_users, monthly_top_users,
                year, month
            )

            # Prepara email
            month_names = [
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"
            ]
            subject = f"Kiosk HR Usage Report - {month_names[month - 1]} {year}"

            # Invia email ai destinatari
            for recipient in self.recipients:
                try:
                    self.email_sender.send_email(
                        to_email=recipient,
                        subject=subject,
                        body=html_body,
                        is_html=True
                    )
                    logger.info(f"Report inviato a {recipient}")
                except Exception as e:
                    logger.error(f"Errore nell'invio a {recipient}: {e}")

            logger.info("Report mensile completato con successo")

        except Exception as e:
            logger.error(f"Errore nella generazione del report mensile: {e}")
            raise

    def check_and_send_monthly_report(self):
        """
        Controlla se è il primo del mese e invia il report
        """
        today = datetime.now()
        if today.day == 1:
            logger.info("Primo del mese rilevato - invio report mensile")
            self.send_monthly_report()
        else:
            logger.debug(f"Oggi è il giorno {today.day} - nessun report da inviare")

    def check_and_convert_special_absences(self):
        """
        Controllo giornaliero delle assenze speciali (motivi speciali: deces,
        casatorie etc.): quelle con documentazione non presentata entro la
        scadenza (DocsDeadlineDays del motivo) vengono annullate e convertite in
        giorni di congedo ordinario. Notifica via email agli destinatari HR.
        """
        try:
            logger.info("Controllo assenze speciali scadute senza documentazione...")

            conn = self.db_connection.connect()
            if not conn:
                logger.error("Impossibile connettersi al database per lo sweep assenze speciali")
                return

            request_manager = AbsenceRequestManager(conn)
            conversions = request_manager.convert_expired_special_absences(employeer_id=EMPLOYER_ID)

            if not conversions:
                logger.info("Nessuna assenza speciale da convertire")
                return

            logger.info(f"Convertite {len(conversions)} assenze speciali in congedo ordinario")

            # Notifica email HR (best-effort)
            try:
                rows_html = "".join(
                    f"<tr>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['employee_name']}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['date_start'].strftime('%d.%m.%Y')} - {c['date_end'].strftime('%d.%m.%Y')}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['special_reason'] or '-'}</td>"
                    f"<td style='padding:6px;border:1px solid #e5e7eb;'>{c['docs_deadline'].strftime('%d.%m.%Y') if c['docs_deadline'] else '-'}</td>"
                    f"</tr>"
                    for c in conversions
                )
                body = f"""
                <html><body style="font-family: Arial, sans-serif;">
                    <h2 style="color: #dc2626;">Conversie automat\u0103: absen\u021be speciale f\u0103r\u0103 documenta\u021bie</h2>
                    <p>Urm\u0103toarele cereri de absen\u021b\u0103 pentru motive speciale au fost anulate
                    (documenta\u021bia nu a fost prezentat\u0103 \u00een termenul stabilit pentru motivul ales) \u0219i
                    transformate \u00een zile de concediu odihn\u0103:</p>
                    <table style="border-collapse: collapse;">
                        <tr>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Angajat</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Perioada</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Motiv</th>
                            <th style="padding:6px;border:1px solid #e5e7eb;">Scaden\u021b\u0103 documenta\u021bie</th>
                        </tr>
                        {rows_html}
                    </table>
                    <p style="font-size:12px;color:#718096;">Email generat automat de sistemul Kiosk HR.</p>
                </body></html>
                """
                subject = f"[Kiosk HR] {len(conversions)} absen\u021be speciale convertite \u00een concediu odihn\u0103"
                for recipient in self.recipients:
                    try:
                        self.email_sender.send_email(recipient, subject, body, is_html=True)
                    except Exception as mail_err:
                        logger.error(f"Errore invio notifica conversione a {recipient}: {mail_err}")
            except Exception as mail_err:
                logger.error(f"Errore preparazione email notifica conversioni: {mail_err}")

        except Exception as e:
            logger.error(f"Errore nel controllo assenze speciali: {e}")

    def run_service(self):
        """
        Avvia il servizio schedulato
        """
        logger.info("=" * 60)
        logger.info("KIOSK REPORTS SERVICE - AVVIO")
        logger.info("=" * 60)

        # Schedula controllo giornaliero alle 08:00
        # Il report viene inviato solo il primo giorno del mese
        schedule.every().day.at("08:00").do(self.check_and_send_monthly_report)

        # Sweep giornaliero assenze speciali: conversione in congedo ordinario
        # quando la documentazione non è stata presentata entro la scadenza del motivo
        schedule.every().day.at("06:30").do(self.check_and_convert_special_absences)

        # Per test: esegui subito (commentare in produzione)
        # logger.info("Esecuzione test immediata...")
        # self.send_monthly_report()

        logger.info("Servizio schedulato: controllo giornaliero alle 08:00")
        logger.info("Report inviato automaticamente il 1° di ogni mese")
        logger.info("In attesa del prossimo ciclo...")

        # Loop principale
        while True:
            schedule.run_pending()
            time.sleep(60)  # Controlla ogni minuto


def main():
    """Main entry point"""
    try:
        service = KioskReportsService()
        service.run_service()
    except KeyboardInterrupt:
        logger.info("Servizio interrotto dall'utente")
    except Exception as e:
        logger.error(f"Errore critico nel servizio: {e}")
        raise


if __name__ == "__main__":
    main()
