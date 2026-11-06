"""
Modulo Richiesta Assenza
Gestisce le richieste di assenza (ferie, permessi, ecc.)
"""

import logging
import os
from company_config import EMPLOYER_ID, LOGO_PATH
from datetime import datetime, timedelta, date
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from utils import log_service_operation
import pyodbc

logger = logging.getLogger(__name__)

# FunctionCode minimo del ruolo 'MANAGER' (employee.dbo.Functions).
# Solo i Manager (>= 70) del centro di costo ricevono le richieste di assenza,
# possono accedere alla pagina 'Aprobare Cereri' e approvarle/rifiutarle.
MANAGER_FUNCTION_CODE = 70

# ── ID dei tipi di richiesta gestiti dal kiosk ([Timeclocking].[dbo].[RequestType]) ──
VACATION_REQUEST_TYPE_ID = 1    # Concediu odihna (ferie / congedo ordinario)
URGENT_ABSENCE_TYPE_ID = 18     # Invoire urgenta (recuperabila) - max 10 giorni/anno
SPECIAL_ABSENCE_TYPE_ID = 19    # Motive speciale - limite giorni PER EVENTO da SpecialAbsenceMotives
KIOSK_REQUEST_TYPE_IDS = (1, 7, 10, 12, URGENT_ABSENCE_TYPE_ID, SPECIAL_ABSENCE_TYPE_ID)

# Scelta del dipendente per il recupero delle assenze urgenti (parametro in tabella)
URGENT_RECOVERY_MONTH = 'MONTH'   # recupero entro la fine del mese della richiesta
URGENT_RECOVERY_YEAR = 'YEAR'     # recupero entro la fine dell'anno lavorativo
URGENT_RECOVERY_PERIODS = (URGENT_RECOVERY_MONTH, URGENT_RECOVERY_YEAR)

# Fallback se la regola in AbsenceRules.DocsDeadlineDays non è presente
DEFAULT_DOCS_DEADLINE_DAYS = 5


class AbsenceRequestManager:
    def __init__(self, db_connection):
        self.conn = db_connection
        self.logo_path = LOGO_PATH  # Configurabile in print_config.json → company.logo_path
        
        # Registra font DejaVuSans per caratteri rumeni
        try:
            pdfmetrics.registerFont(TTFont('DejaVuSans', 'DejaVuSans.ttf'))
            pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', 'DejaVuSans-Bold.ttf'))
            self.font_name = 'DejaVuSans'
            self.font_bold = 'DejaVuSans-Bold'
        except Exception as e:
            logger.warning(f"Font DejaVuSans non disponibili: {e}")
            self.font_name = 'Helvetica'
            self.font_bold = 'Helvetica-Bold'
    
    def get_request_types(self):
        """Recupera tipi di richiesta disponibili"""
        try:
            cursor = self.conn.cursor()

            id_list = ','.join(str(i) for i in KIOSK_REQUEST_TYPE_IDS)
            query = f"""
            SELECT
                rt.IDRequestType,
                rt.RequestName,
                rt.IsConsideredEntireDay,
                ISNULL(ar.DayNoZone, 1) AS DayNoZone,
                ar.MaxDaysPerYear,
                ar.DocsDeadlineDays,
                ar.ConvertToIDRequestType
            FROM [Timeclocking].[dbo].[RequestType] rt
            LEFT JOIN [Employee].[dbo].[AbsenceRules] ar
                ON ar.IDRequestType = rt.IDRequestType
                AND ar.DateOut IS NULL
            WHERE rt.IDRequestType IN ({id_list})
            ORDER BY rt.RequestName
            """

            cursor.execute(query)
            rows = cursor.fetchall()

            request_types = []
            for row in rows:
                request_types.append({
                    'id': row[0],
                    'name': row[1],
                    'entire_day': row[2],
                    'day_no_zone': row[3] if row[3] is not None else 1,
                    'max_days_per_year': int(row[4]) if row[4] is not None else None,
                    'docs_deadline_days': int(row[5]) if row[5] is not None else None,
                    'convert_to_request_type': int(row[6]) if row[6] is not None else None
                })

            return request_types

        except Exception as e:
            logger.error(f"Errore recupero tipi richiesta: {str(e)}")
            return []
    
    def get_holidays(self, year):
        """Recupera giorni festivi per un anno"""
        try:
            cursor = self.conn.cursor()
            
            query = """
            SELECT DISTINCT
                DATEFROMPARTS(YearPublicHoliday, MonthPublicHoliday, DayPublicHoliday) AS DataFestivo
            FROM [Timeclocking].[dbo].[PublicHoliday]
            WHERE YearPublicHoliday = ?
            """
            
            cursor.execute(query, (year,))
            rows = cursor.fetchall()
            
            holidays = [row[0] for row in rows]
            return holidays
            
        except Exception as e:
            logger.error(f"Errore recupero festività: {str(e)}")
            return []
    
    def calculate_working_days(self, start_date, end_date, holidays):
        """Calcola giorni lavorativi escludendo weekend e festività"""
        working_days = 0
        current_date = start_date
        
        while current_date <= end_date:
            # Verifica se è weekend (sabato=5, domenica=6)
            if current_date.weekday() < 5:  # Lunedì=0, Venerdì=4
                # Verifica se non è festivo
                if current_date not in holidays:
                    working_days += 1
            
            current_date += timedelta(days=1)

        return working_days

    def get_absence_days_used(self, hire_history_id, request_type_id, year):
        """
        Giorni lavorativi già utilizzati nell'anno per un tipo di assenza
        con quota annua (assenze urgenti / speciali).

        Esclude le richieste rifiutate e quelle annullate per mancanza di
        documentazione (convertite in congedo ordinario).
        """
        try:
            cursor = self.conn.cursor()

            query = """
            DECLARE @HireHistoryId INT = ?
            DECLARE @RequestTypeId INT = ?
            DECLARE @Anno INT = ?

            ;WITH Numbers AS (
                SELECT a.n + b.n + c.n AS n
                FROM (
                    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
                    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
                ) a
                CROSS JOIN (
                    SELECT 0 AS n UNION ALL SELECT 10 UNION ALL SELECT 20 UNION ALL SELECT 30
                ) b
                CROSS JOIN (
                    SELECT 0 AS n UNION ALL SELECT 100 UNION ALL SELECT 200 UNION ALL SELECT 300
                ) c
                WHERE a.n + b.n + c.n <= 366
            ),
            FestiviCTE AS (
                SELECT DISTINCT
                    DATEFROMPARTS(YearPublicHoliday, MonthPublicHoliday, DayPublicHoliday) AS DataFestivo
                FROM [Timeclocking].[dbo].[PublicHoliday]
                WHERE YearPublicHoliday = @Anno
            ),
            GiorniEspansi AS (
                SELECT
                    DATEADD(DAY, N.n, AR.DateStart) AS DataCorrente,
                    CASE
                        WHEN DATEPART(WEEKDAY, DATEADD(DAY, N.n, AR.DateStart)) IN (1, 7) THEN 0
                        WHEN EXISTS (
                            SELECT 1 FROM FestiviCTE F
                            WHERE F.DataFestivo = DATEADD(DAY, N.n, AR.DateStart)
                        ) THEN 0
                        ELSE 1
                    END AS IsGiornoLavorativo
                FROM [Employee].[dbo].[AbsenceRequestes] AR
                CROSS JOIN Numbers N
                WHERE AR.EmployrrHireHistoryId = @HireHistoryId
                  AND AR.IDRequestType = @RequestTypeId
                  AND DATEADD(DAY, N.n, AR.DateStart) <= AR.DateEnd
                  AND (AR.Rejected IS NULL OR AR.Rejected = 0)
                  AND (AR.ConvertedToOrdinary IS NULL OR AR.ConvertedToOrdinary = 0)
            )
            SELECT ISNULL(SUM(IsGiornoLavorativo), 0) AS GiorniUsati
            FROM GiorniEspansi
            WHERE YEAR(DataCorrente) = @Anno
            """

            cursor.execute(query, (hire_history_id, request_type_id, year))
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

        except Exception as e:
            logger.error(f"Errore calcolo giorni usati (tipo {request_type_id}): {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def get_quota_info(self, hire_history_id, request_type_id, year):
        """
        Info sulla quota annua di un tipo di assenza (assenze urgenti/speciali):
        limite per legge (AbsenceRules.MaxDaysPerYear), giorni usati e residui.
        """
        try:
            cursor = self.conn.cursor()

            query = """
            SELECT MaxDaysPerYear, DocsDeadlineDays, ConvertToIDRequestType
            FROM [Employee].[dbo].[AbsenceRules]
            WHERE IDRequestType = ?
                AND DateOut IS NULL
            """
            cursor.execute(query, (request_type_id,))
            row = cursor.fetchone()

            if not row or row[0] is None:
                return None  # tipo senza quota annua: non soggetto a limite

            max_days = int(row[0])
            used = self.get_absence_days_used(hire_history_id, request_type_id, year)
            if used is None:
                used = 0

            return {
                'max_days': max_days,
                'used': used,
                'remaining': max(0, max_days - used),
                'docs_deadline_days': int(row[1]) if row[1] is not None else None,
                'convert_to_request_type': int(row[2]) if row[2] is not None else None
            }

        except Exception as e:
            logger.error(f"Errore recupero quota (tipo {request_type_id}): {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def check_quota_availability(self, hire_history_id, request_type_id, date_start, date_end, holidays, year):
        """
        Verifica che la richiesta rispetti la quota annua del tipo di assenza.

        Returns:
            dict: {'valid', 'message', 'used', 'requested', 'max_days', 'remaining'}
        """
        quota = self.get_quota_info(hire_history_id, request_type_id, year)
        if quota is None:
            return {'valid': True, 'message': '', 'used': None, 'requested': None,
                    'max_days': None, 'remaining': None}

        requested = self.calculate_working_days(date_start, date_end, holidays)

        if requested > quota['remaining']:
            message = (
                f"ATEN\u021aIE: Nu mai ave\u021bi zile disponibile pentru acest tip de absen\u021b\u0103!\n\n"
                f"Zile utilizate \u00een {year}: {quota['used']} din {quota['max_days']}.\n"
                f"Zile r\u0103mase: {quota['remaining']}.\n"
                f"A\u021bi solicitat {requested} zile."
            )
            logger.warning(
                f"Quota superata per tipo {request_type_id}: richiesti {requested} > residui {quota['remaining']}"
            )
            return {
                'valid': False,
                'message': message,
                'used': quota['used'],
                'requested': requested,
                'max_days': quota['max_days'],
                'remaining': quota['remaining']
            }

        return {
            'valid': True,
            'message': '',
            'used': quota['used'],
            'requested': requested,
            'max_days': quota['max_days'],
            'remaining': quota['remaining']
        }

    def get_docs_deadline_days(self, request_type_id):
        """Giorni concessi per presentare la documentazione (AbsenceRules.DocsDeadlineDays)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT DocsDeadlineDays
                FROM [Employee].[dbo].[AbsenceRules]
                WHERE IDRequestType = ? AND DateOut IS NULL
            """, (request_type_id,))
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        except Exception as e:
            logger.error(f"Errore lettura DocsDeadlineDays (tipo {request_type_id}): {e}")
        return DEFAULT_DOCS_DEADLINE_DAYS

    def get_special_motives(self):
        """
        Catalogo dei motivi speciali attivi (Employee.dbo.SpecialAbsenceMotives).

        Ogni motivo porta il proprio limite di giorni lavorativi PER EVENTO
        (MaxDays; NULL = durata in base alla documentazione, es. obblighi civici).
        Sostituisce la lista hardcoded dell'interfaccia kiosk.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT MotiveId, NameRo, NameIt, MaxDays, DaysLabelRo,
                       RequiresDocumentation, DocsDeadlineDays, AllowCustomDuration
                FROM [Employee].[dbo].[SpecialAbsenceMotives]
                WHERE IsActive = 1 AND DateOut IS NULL
                ORDER BY SortOrder, MotiveId
            """)
            motives = []
            for row in cursor.fetchall():
                motives.append({
                    'id': int(row[0]),
                    'name_ro': str(row[1]),
                    'name_it': str(row[2]),
                    'max_days': float(row[3]) if row[3] is not None else None,
                    'days_label_ro': str(row[4]) if row[4] is not None else None,
                    'requires_documentation': bool(row[5]),
                    'docs_deadline_days': int(row[6]) if row[6] is not None else DEFAULT_DOCS_DEADLINE_DAYS,
                    'allow_custom_duration': bool(row[7])
                })
            return motives

        except Exception as e:
            logger.error(f"Errore recupero motivi speciali: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def get_special_motive(self, motive_id):
        """Singolo motivo speciale attivo per MotiveId (None se inesistente o disattivo)."""
        if motive_id is None:
            return None
        for motive in self.get_special_motives():
            if motive['id'] == motive_id:
                return motive
        return None

    def validate_special_motive(self, motive_id, date_start, date_end, holidays):
        """
        Valida il motivo speciale scelto rispetto ai giorni lavorativi richiesti.

        Il limite (SpecialAbsenceMotives.MaxDays) è PER EVENTO: i giorni
        lavorativi della richiesta non possono superarlo, salvo i motivi con
        durata libera (AllowCustomDuration / MaxDays NULL, es. obblighi civici).

        Returns:
            dict: {'valid', 'message', 'motive', 'requested_days'}
        """
        motive = self.get_special_motive(motive_id)
        if not motive:
            return {
                'valid': False,
                'message': 'Selecta\u021bi un motiv special valid din list\u0103.',
                'motive': None,
                'requested_days': None
            }

        requested_days = self.calculate_working_days(date_start, date_end, holidays)
        max_days = motive['max_days']

        if max_days is not None and requested_days > max_days:
            max_label = int(max_days) if float(max_days).is_integer() else max_days
            message = (
                f"ATEN\u021aIE: Motivul special selectat prevede maxim {max_label} "
                f"zile lucr\u0103toare.\n\n"
                f"A\u021bi solicitat {requested_days} zile lucr\u0103toare."
            )
            logger.warning(
                f"Motivo speciale {motive_id}: richiesti {requested_days} gg > "
                f"limite {max_days} gg/evento"
            )
            return {
                'valid': False,
                'message': message,
                'motive': motive,
                'requested_days': requested_days
            }

        return {
            'valid': True,
            'message': '',
            'motive': motive,
            'requested_days': requested_days
        }

    def compute_urgent_recovery_deadline(self, recovery_period, date_start):
        """
        Data limite entro cui recuperare i giorni di assenza urgente:
        - MONTH: fine del mese della data di inizio assenza
        - YEAR:  fine dell'anno lavorativo (31.12 dell'anno della data di inizio)
        """
        if isinstance(date_start, datetime):
            date_start = date_start.date()

        if recovery_period == URGENT_RECOVERY_MONTH:
            # ultimo giorno del mese della data di inizio
            if date_start.month == 12:
                return date_start.replace(day=31)
            return date_start.replace(month=date_start.month + 1, day=1) - timedelta(days=1)

        # YEAR: fine anno lavorativo
        return date(date_start.year, 12, 31)

    def get_available_vacation_days(self, badge_number, year):
        """Calcola giorni di ferie disponibili per un dipendente"""
        try:
            cursor = self.conn.cursor()
            
            # Query complessa per calcolare ferie disponibili
            query = f"""
            DECLARE @NoBadge VARCHAR(50) = ?
            DECLARE @Anno INT = ?
            DECLARE @DataRiferimento DATE = GETDATE()
            DECLARE @InizioAnno DATE = DATEFROMPARTS(@Anno, 1, 1)
            DECLARE @FineAnno DATE = DATEFROMPARTS(@Anno, 12, 31)

            ;WITH 
            Numbers AS (
                SELECT a.n + b.n + c.n AS n 
                FROM (
                    SELECT 0 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 
                    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9
                ) a
                CROSS JOIN (
                    SELECT 0 AS n UNION ALL SELECT 10 UNION ALL SELECT 20 UNION ALL SELECT 30 UNION ALL SELECT 40 
                    UNION ALL SELECT 50 UNION ALL SELECT 60 UNION ALL SELECT 70 UNION ALL SELECT 80 UNION ALL SELECT 90
                ) b
                CROSS JOIN (
                    SELECT 0 AS n UNION ALL SELECT 100 UNION ALL SELECT 200 UNION ALL SELECT 300
                ) c
                WHERE a.n + b.n + c.n <= 365
            ),
            BonusAnzianitaCTE AS (
                SELECT 
                    noYears,
                    FixValueOnBrutSalary AS GiorniBonus
                FROM 
                    [Employee].[dbo].[BonusTypeSeniotiry]
                WHERE 
                    BonusTypeValueId = 4 
                    AND dateout IS NULL
            ),
            FestiviCTE AS (
                SELECT DISTINCT
                    DATEFROMPARTS(YearPublicHoliday, MonthPublicHoliday, DayPublicHoliday) AS DataFestivo
                FROM 
                    [Timeclocking].[dbo].[PublicHoliday]
                WHERE 
                    YearPublicHoliday BETWEEN @Anno - 50 AND @Anno + 1
            ),
            CalcoloAnzianitaCTE AS (
                SELECT 
                    te.IDEmployee,
                    h.EmployeeHireHistoryId,
                    e.EmployeeName,
                    e.EmployeeSurname,
                    b.NoBadge,
                    h.HireDate,
                    h.HolidayPerYear,
                    CASE 
                        WHEN h.HireDate <= @DataRiferimento THEN
                            CASE 
                                WHEN MONTH(@DataRiferimento) > MONTH(h.HireDate) 
                                    OR (MONTH(@DataRiferimento) = MONTH(h.HireDate) AND DAY(@DataRiferimento) >= DAY(h.HireDate))
                                THEN DATEDIFF(YEAR, h.HireDate, @DataRiferimento)
                                ELSE DATEDIFF(YEAR, h.HireDate, @DataRiferimento) - 1
                            END
                        ELSE 0
                    END AS Anni
                FROM 
                    employee.dbo.employees E
                    INNER JOIN employee.dbo.EmployeeHireHistory H 
                        ON e.EmployeeId = h.EmployeeId 
                        AND h.EmployeerId = {EMPLOYER_ID} 
                        AND h.EndWorkDate IS NULL
                    INNER JOIN [Timeclocking].[dbo].[Employee] TE 
                        ON e.EmployeeNID COLLATE Latin1_General_CI_AI = te.UniqueID COLLATE Latin1_General_CI_AI
                        AND te.DataStop IS NULL
                    INNER JOIN employee.dbo.EmployeeBadgeHistory BH 
                        ON h.EmployeeHireHistoryId = bh.EmployeeHireHistoryId 
                        AND bh.DateOut IS NULL
                    INNER JOIN employee.dbo.Badges B 
                        ON bh.BadgeID = b.BadgeId
                WHERE 
                    b.NoBadge COLLATE Latin1_General_CI_AI = @NoBadge COLLATE Latin1_General_CI_AI
            ),
            FerieSpettantiCTE AS (
                SELECT 
                    C.*,
                    ISNULL((
                        SELECT TOP 1 GiorniBonus 
                        FROM BonusAnzianitaCTE 
                        WHERE noYears <= C.Anni
                        ORDER BY noYears DESC
                    ), 0) AS GiorniBonusAnzianita,
                    CASE 
                        WHEN YEAR(C.HireDate) = @Anno THEN 
                            CEILING(CAST(C.HolidayPerYear AS FLOAT) * 
                                   (DATEDIFF(DAY, C.HireDate, @DataRiferimento) + 1) / 
                                   (CASE WHEN (@Anno % 4 = 0 AND @Anno % 100 != 0) OR (@Anno % 400 = 0) 
                                         THEN 366 ELSE 365 END))
                        WHEN YEAR(C.HireDate) < @Anno THEN 
                            C.HolidayPerYear
                        ELSE 
                            0
                    END AS FerieAnnoCorrente
                FROM CalcoloAnzianitaCTE C
            ),
            FerieSpettantiPerAnnoCTE AS (
                SELECT 
                    F.IDEmployee,
                    YEAR(F.HireDate) + (N.n / 10) AS Anno,
                    CASE 
                        WHEN YEAR(F.HireDate) = YEAR(F.HireDate) + (N.n / 10) THEN 
                            CEILING(CAST(F.HolidayPerYear AS FLOAT) * 
                                   (DATEDIFF(DAY, F.HireDate, DATEFROMPARTS(YEAR(F.HireDate) + (N.n / 10), 12, 31)) + 1) / 
                                   (CASE WHEN ((YEAR(F.HireDate) + (N.n / 10)) % 4 = 0 AND (YEAR(F.HireDate) + (N.n / 10)) % 100 != 0) 
                                          OR ((YEAR(F.HireDate) + (N.n / 10)) % 400 = 0) 
                                         THEN 366 ELSE 365 END))
                        WHEN YEAR(F.HireDate) < YEAR(F.HireDate) + (N.n / 10) THEN 
                            F.HolidayPerYear
                        ELSE 
                            0
                    END AS FerieSpettanti
                FROM 
                    FerieSpettantiCTE F
                    CROSS JOIN Numbers N
                WHERE 
                    N.n % 10 = 0
                    AND (N.n / 10) <= 30
                    AND YEAR(F.HireDate) + (N.n / 10) < @Anno
            ),
            FerieSpettantiAnniPrecedentiCTE AS (
                SELECT 
                    IDEmployee,
                    SUM(FerieSpettanti) AS TotaleFerieSpettantiAnniPrecedenti
                FROM 
                    FerieSpettantiPerAnnoCTE
                GROUP BY 
                    IDEmployee
            ),
            GiorniAssenzeEspansi AS (
                SELECT 
                    D.IDEmployee,
                    D.IDRequestType,
                    DATEADD(DAY, N.n, D.DateFrom) AS DataCorrente,
                    CASE 
                        WHEN DATEADD(DAY, N.n, D.DateFrom) < @InizioAnno THEN 1
                        ELSE 0
                    END AS IsAnniPrecedenti,
                    CASE 
                        WHEN DATEADD(DAY, N.n, D.DateFrom) >= @InizioAnno 
                            AND DATEADD(DAY, N.n, D.DateFrom) <= @FineAnno THEN 1
                        ELSE 0
                    END AS IsAnnoCorrente,
                    CASE 
                        WHEN DATEPART(WEEKDAY, DATEADD(DAY, N.n, D.DateFrom)) IN (1, 7) THEN 0
                        WHEN EXISTS (
                            SELECT 1 
                            FROM FestiviCTE F 
                            WHERE F.DataFestivo = DATEADD(DAY, N.n, D.DateFrom)
                        ) THEN 0
                        ELSE 1
                    END AS IsGiornoLavorativo
                FROM 
                    [Timeclocking].[dbo].[EmployeeRequestEntireDay] D
                    INNER JOIN [Timeclocking].[dbo].[Employee] TE2 ON D.IDEmployee = TE2.IDEmployee AND TE2.DataStop IS NULL AND D.DateFrom >= TE2.DataStart
                    CROSS JOIN Numbers N
                WHERE 
                    DATEADD(DAY, N.n, D.DateFrom) <= D.DateTo
                    AND D.DateFrom <= DATEADD(YEAR, 1, @FineAnno)
            ),
            FerieUsateAnniPrecedentiCTE AS (
                SELECT 
                    IDEmployee,
                    SUM(IsGiornoLavorativo) AS FerieUsateAnniPrecedenti
                FROM 
                    GiorniAssenzeEspansi
                WHERE 
                    IDRequestType = 1
                    AND IsAnniPrecedenti = 1
                GROUP BY 
                    IDEmployee
            ),
            FerieUsateAnnoCorrenteCTE AS (
                SELECT 
                    IDEmployee,
                    SUM(IsGiornoLavorativo) AS FerieUsateAnnoCorrente
                FROM 
                    GiorniAssenzeEspansi
                WHERE 
                    IDRequestType = 1
                    AND IsAnnoCorrente = 1
                GROUP BY 
                    IDEmployee
            )
            SELECT 
                F.IDEmployee,
                F.EmployeeHireHistoryId,
                F.EmployeeName,
                F.EmployeeSurname,
                F.NoBadge,
                F.FerieAnnoCorrente + F.GiorniBonusAnzianita + 
                (ISNULL(FSAP.TotaleFerieSpettantiAnniPrecedenti, 0) - ISNULL(FUAP.FerieUsateAnniPrecedenti, 0)) - 
                ISNULL(FUAC.FerieUsateAnnoCorrente, 0) AS GiorniDisponibili
            FROM 
                FerieSpettantiCTE F
                LEFT JOIN FerieSpettantiAnniPrecedentiCTE FSAP ON F.IDEmployee = FSAP.IDEmployee
                LEFT JOIN FerieUsateAnniPrecedentiCTE FUAP ON F.IDEmployee = FUAP.IDEmployee
                LEFT JOIN FerieUsateAnnoCorrenteCTE FUAC ON F.IDEmployee = FUAC.IDEmployee
            """
            
            cursor.execute(query, (badge_number, year))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id_employee': row[0],
                    'hire_history_id': row[1],
                    'employee_name': row[2],
                    'employee_surname': row[3],
                    'badge_number': row[4],
                    'available_days': int(row[5]) if row[5] else 0
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Errore calcolo giorni disponibili: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def check_duplicate_request(self, hire_history_id, request_type_id, date_start, date_end):
        """Verifica se esiste già una richiesta uguale"""
        try:
            cursor = self.conn.cursor()
            
            query = """
            SELECT COUNT(*) AS NumDuplicates
            FROM [Employee].[dbo].[AbsenceRequestes]
            WHERE [EmployrrHireHistoryId] = ?
                AND [IDRequestType] = ?
                AND [DateStart] = ?
                AND [DateEnd] = ?
                AND [Approved] IS NOT NULL  -- Solo richieste già processate
            """
            
            cursor.execute(query, (hire_history_id, request_type_id, date_start, date_end))
            row = cursor.fetchone()
            
            num_duplicates = int(row[0]) if row else 0
            
            if num_duplicates > 0:
                logger.warning(f"Richiesta duplicata trovata: {num_duplicates} occorrenze")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Errore verifica duplicati: {str(e)}")
            # In caso di errore, permettiamo la richiesta (fail-safe)
            return False
    
    def validate_absence_date_rule(self, request_type_id, date_start):
        """
        Verifica se la data di inizio assenza rispetta le regole DayNoZone.
        
        Returns:
            dict: {
                'valid': bool,
                'message': str (messaggio errore in rumeno se non valido),
                'day_no_zone': int (numero di giorni di preavviso richiesti)
            }
        """
        try:
            cursor = self.conn.cursor()
            
            # Verifica se esiste una regola DayNoZone per questo tipo di richiesta
            query = """
            SELECT [DayNoZone]
            FROM [Employee].[dbo].[AbsenceRules]
            WHERE [IDRequestType] = ?
                AND [DayNoZone] IS NOT NULL
                AND [DateOut] IS NULL
            """
            
            cursor.execute(query, (request_type_id,))
            row = cursor.fetchone()
            
            # Se non c'è regola, la validazione passa
            if not row or row[0] is None:
                return {
                    'valid': True,
                    'message': '',
                    'day_no_zone': 0
                }
            
            day_no_zone = int(row[0])
            
            # Calcola la data minima consentita (oggi + DayNoZone giorni)
            today = datetime.now().date()
            min_allowed_date = today + timedelta(days=day_no_zone)
            
            # Converti date_start in date se è datetime
            if isinstance(date_start, datetime):
                date_start_check = date_start.date()
            else:
                date_start_check = date_start
            
            # Verifica se la data di inizio è valida
            if date_start_check < min_allowed_date:
                # Formatta la data massima per la richiesta in formato rumeno
                max_request_date_str = min_allowed_date.strftime('%d.%m.%Y')
                
                # Messaggio in rumeno
                message = (
                    f"ATENȚIE: Cererea nu poate fi înregistrată!\n\n"
                    f"Data maximă pentru înregistrarea acestei cereri este {max_request_date_str}.\n\n"
                    f"Conform regulilor companiei, această cerere trebuie înregistrată "
                    f"cu cel puțin {day_no_zone} zile înainte.\n\n"
                    f"Pentru cazuri speciale, vă rugăm să contactați responsabilul dumneavoastră direct."
                )
                
                logger.warning(
                    f"Validazione fallita: data {date_start_check} < data minima {min_allowed_date} "
                    f"(DayNoZone={day_no_zone})"
                )
                
                return {
                    'valid': False,
                    'message': message,
                    'day_no_zone': day_no_zone
                }
            
            # Validazione superata
            return {
                'valid': True,
                'message': '',
                'day_no_zone': day_no_zone
            }
            
        except Exception as e:
            logger.error(f"Errore validazione regole data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # In caso di errore, permettiamo la richiesta (fail-safe)
            return {
                'valid': True,
                'message': '',
                'day_no_zone': 0
            }
    
    def create_registry_entry(self, year, request_date, issued_by, employeer_id=2):
        """Crea entry nel registro tramite stored procedure"""
        try:
            cursor = self.conn.cursor()
            
            # Prepara parametri per SP
            registry_type_id = 1000
            
            # Con pyodbc, per recuperare OUTPUT parameter devo usare una query separata
            # Esegui stored procedure
            sql = """
            DECLARE @RegistroId INT
            
            EXEC [Employee].[dbo].[Registro]
                @RegistryTypeId = ?,
                @anno = ?,
                @DataDocumento = ?,
                @IussedBy = ?,
                @EmployeerId = ?,
                @RegistroId = @RegistroId OUTPUT
            
            SELECT @RegistroId AS RegistroId
            """
            
            cursor.execute(sql, (registry_type_id, year, request_date, issued_by, employeer_id))
            
            # Recupera ID generato
            row = cursor.fetchone()
            result_id = int(row[0]) if row and row[0] else None
            
            self.conn.commit()
            
            logger.info(f"Registry entry creato: RegistroId = {result_id}")
            
            return result_id
            
        except Exception as e:
            logger.error(f"Errore creazione registry: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.conn.rollback()
            return None
    
    def save_absence_request(self, registro_id, hire_history_id, request_type_id,
                            date_start, date_end, from_time=None, to_time=None,
                            username="Unknown", request_type_name="Richiesta Assenza",
                            urgent_recovery_period=None, special_reason=None,
                            special_reason_id=None):
        """Salva richiesta assenza nel database.

        Per le assenze urgenti (IDRequestType 18) `urgent_recovery_period` è la
        scelta del dipendente ('MONTH' = recupero nel mese della richiesta,
        'YEAR' = recupero entro l'anno lavorativo), salvata come parametro in
        AbsenceRequestes.UrgentRecoveryPeriod insieme alla scadenza calcolata.

        Per le assenze speciali (IDRequestType 19) `special_reason_id` è il
        MotiveId dall'anagrafica SpecialAbsenceMotives (limite giorni per
        evento) e `special_reason` il nome testuale del motivo; la scadenza
        per la presentazione della documentazione al dep. HR viene presa da
        SpecialAbsenceMotives.DocsDeadlineDays (fallback AbsenceRules).
        """
        try:
            cursor = self.conn.cursor()

            urgent_recovery_deadline = None
            documentation_deadline = None

            if request_type_id == URGENT_ABSENCE_TYPE_ID:
                if urgent_recovery_period not in URGENT_RECOVERY_PERIODS:
                    raise ValueError(
                        f"Periodo di recupero non valido: {urgent_recovery_period!r} "
                        f"(attesi: {', '.join(URGENT_RECOVERY_PERIODS)})"
                    )
                urgent_recovery_deadline = self.compute_urgent_recovery_deadline(
                    urgent_recovery_period, date_start
                )
            elif request_type_id == SPECIAL_ABSENCE_TYPE_ID:
                motive = self.get_special_motive(special_reason_id)
                if motive is not None:
                    # Motivo senza obbligo di documenti: nessuna scadenza (niente conversione)
                    docs_days = motive['docs_deadline_days'] if motive['requires_documentation'] else None
                else:
                    # Fallback: richieste legacy senza motivo anagrafico
                    docs_days = self.get_docs_deadline_days(request_type_id)
                if isinstance(date_start, datetime):
                    ds = date_start.date()
                else:
                    ds = date_start
                if docs_days is not None:
                    documentation_deadline = ds + timedelta(days=docs_days)
                if special_reason:
                    special_reason = str(special_reason).strip()[:200]

            # Con pyodbc, devo usare SET NOCOUNT ON per evitare problemi con INSERT + SELECT
            query = """
            SET NOCOUNT ON

            INSERT INTO [Employee].[dbo].[AbsenceRequestes]
                ([RegistroId], [EmployrrHireHistoryId], [IDRequestType],
                 [DateStart], [DateEnd], [FromTime], [ToTime],
                 [Approved], [ApprovedBy], [DateSys],
                 [UrgentRecoveryPeriod], [UrgentRecoveryDeadline],
                 [SpecialReason], [DocumentationDeadline])
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, GETDATE(), ?, ?, ?, ?)

            SELECT SCOPE_IDENTITY() AS AbsenceRequestId
            """

            cursor.execute(query, (registro_id, hire_history_id, request_type_id,
                                  date_start, date_end, from_time, to_time,
                                  urgent_recovery_period, urgent_recovery_deadline,
                                  special_reason, documentation_deadline))

            row = cursor.fetchone()
            absence_request_id = int(row[0]) if row and row[0] else None

            # Riferimento al motivo anagrafico: solo per le assenze speciali, nella
            # stessa transazione (le altre richieste non dipendono dalla colonna)
            if absence_request_id and special_reason_id is not None:
                cursor.execute("""
                    UPDATE [Employee].[dbo].[AbsenceRequestes]
                    SET [SpecialReasonId] = ?
                    WHERE [AbsenceRequestId] = ?
                """, (special_reason_id, absence_request_id))

            self.conn.commit()

            # Log dettagliato con orari se presenti
            time_info = ""
            if from_time and to_time:
                time_info = f", Orario: {from_time} - {to_time}"

            extra_info = ""
            if urgent_recovery_period:
                extra_info = f", Recupero: {urgent_recovery_period} entro {urgent_recovery_deadline}"
            elif special_reason:
                extra_info = f", Motivo speciale: {special_reason}, Documenti entro: {documentation_deadline}"

            logger.info(
                f"Richiesta assenza salvata: AbsenceRequestId = {absence_request_id}{time_info}{extra_info}"
            )

            # Log operazione riuscita
            log_service_operation(
                self.conn,
                username=username,
                service_name=f"Richiesta Assenza - {request_type_name}",
                success=True,
                additional_info=f"Periodo: {date_start} - {date_end}{time_info}{extra_info}, RequestId: {absence_request_id}"
            )

            return absence_request_id

        except Exception as e:
            logger.error(f"Errore salvataggio richiesta: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.conn.rollback()

            # Log operazione fallita
            log_service_operation(
                self.conn,
                username=username,
                service_name=f"Richiesta Assenza - {request_type_name}",
                success=False,
                error_message=str(e)
            )

            return None

    def get_request_type_name(self, request_type_id):
        """Nome del tipo di richiesta direttamente dal DB (fallback robusto per email/PDF)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT RequestName
                FROM [Timeclocking].[dbo].[RequestType]
                WHERE IDRequestType = ?
            """, (request_type_id,))
            row = cursor.fetchone()
            return str(row[0]) if row and row[0] else 'Tip necunoscut'
        except Exception as e:
            logger.error(f"Errore recupero nome tipo richiesta {request_type_id}: {e}")
            return 'Tip necunoscut'

    def mark_special_documentation_received(self, absence_request_id, received=True, received_date=None):
        """
        Registra la presentazione della documentazione per un'assenza speciale.
        Da usare dal dep. HR quando il dipendente consegna i documenti cartacei.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                UPDATE [Employee].[dbo].[AbsenceRequestes]
                SET [DocumentationReceived] = ?,
                    [DocumentationReceivedDate] = ?
                WHERE [AbsenceRequestId] = ?
                  AND [IDRequestType] = ?
            """, (1 if received else 0,
                  received_date if received else None,
                  absence_request_id,
                  SPECIAL_ABSENCE_TYPE_ID))
            updated = cursor.rowcount
            self.conn.commit()
            return updated > 0
        except Exception as e:
            logger.error(f"Errore registrazione documentazione richiesta {absence_request_id}: {e}")
            self.conn.rollback()
            return False

    def convert_expired_special_absences(self, employeer_id=2):
        """
        Annulla le assenze speciali per cui la documentazione non è stata
        presentata entro la scadenza (DocumentationDeadline) e le converte in
        giorni di congedo ordinario (Concediu odihna, IDRequestType 1), come da
        regola aziendale.

        Returns:
            list[dict]: conversioni effettuate in questa esecuzione.
        """
        conversions = []
        try:
            cursor = self.conn.cursor()

            # Regola di conversione (parametrica in AbsenceRules.ConvertToIDRequestType)
            cursor.execute("""
                SELECT ConvertToIDRequestType
                FROM [Employee].[dbo].[AbsenceRules]
                WHERE IDRequestType = ? AND DateOut IS NULL
            """, (SPECIAL_ABSENCE_TYPE_ID,))
            rule = cursor.fetchone()
            if not rule or rule[0] is None:
                logger.info("Nessuna regola di conversione per le assenze speciali: sweep saltato")
                return conversions
            convert_to_type = int(rule[0])

            # Richieste speciali scadute senza documenti, non ancora convertite né rifiutate
            cursor.execute("""
                SELECT ar.AbsenceRequestId,
                       ar.EmployrrHireHistoryId,
                       ar.DateStart,
                       ar.DateEnd,
                       ar.DocumentationDeadline,
                       ISNULL(ar.SpecialReason, ''),
                       UPPER(e.EmployeeSurname + ' ' + e.EmployeeName) AS EmployeeName
                FROM [Employee].[dbo].[AbsenceRequestes] ar
                INNER JOIN [Employee].[dbo].[EmployeeHireHistory] h
                    ON ar.EmployrrHireHistoryId = h.EmployeeHireHistoryId
                INNER JOIN [Employee].[dbo].[Employees] e
                    ON h.EmployeeId = e.EmployeeId
                WHERE ar.IDRequestType = ?
                  AND ISNULL(ar.DocumentationReceived, 0) = 0
                  AND ISNULL(ar.ConvertedToOrdinary, 0) = 0
                  AND (ar.Rejected IS NULL OR ar.Rejected = 0)
                  AND ar.DocumentationDeadline IS NOT NULL
                  AND CAST(GETDATE() AS date) > ar.DocumentationDeadline
            """, (SPECIAL_ABSENCE_TYPE_ID,))
            rows = cursor.fetchall()

            for row in rows:
                absence_request_id = row[0]
                hire_history_id = row[1]
                date_start = row[2]
                date_end = row[3]
                docs_deadline = row[4]
                special_reason = row[5]
                employee_name = row[6]

                try:
                    # 1. Crea entry registro per la nuova richiesta di congedo ordinario
                    registro_id = self.create_registry_entry(
                        year=datetime.now().year,
                        request_date=datetime.now(),
                        issued_by="Sistem HR - conversie automata",
                        employeer_id=employeer_id
                    )
                    if not registro_id:
                        raise Exception("creazione registro fallita")

                    # 2. Inserisce la richiesta di congedo ordinario equivalente
                    cursor.execute("""
                        SET NOCOUNT ON
                        INSERT INTO [Employee].[dbo].[AbsenceRequestes]
                            ([RegistroId], [EmployrrHireHistoryId], [IDRequestType],
                             [DateStart], [DateEnd], [Approved], [ApprovedBy], [DateSys])
                        VALUES (?, ?, ?, ?, ?, 0, NULL, GETDATE())
                        SELECT SCOPE_IDENTITY() AS NewRequestId
                    """, (registro_id, hire_history_id, convert_to_type, date_start, date_end))
                    new_row = cursor.fetchone()
                    new_request_id = int(new_row[0]) if new_row and new_row[0] else None

                    if not new_request_id:
                        raise Exception("inserimento richiesta di conversione fallito")

                    # 3. Annulla la richiesta speciale e collega la conversione
                    refuse_motive = (
                        f"Anulat\u0103: documenta\u021bia justificativ\u0103 nu a fost prezentat\u0103 "
                        f"\u00een termenul stabilit (p\u00e2n\u0103 la {docs_deadline.strftime('%d.%m.%Y') if docs_deadline else 'N/A'}). "
                        f"Transformat\u0103 automat \u00een zile de concediu odihn\u0103 (cererea nr. intern {new_request_id})."
                    )
                    cursor.execute("""
                        UPDATE [Employee].[dbo].[AbsenceRequestes]
                        SET [Rejected] = 1,
                            [RefuseMotive] = ?,
                            [ConvertedToOrdinary] = 1,
                            [ConvertedToOrdinaryDate] = GETDATE(),
                            [ConvertedAbsenceRequestId] = ?
                        WHERE [AbsenceRequestId] = ?
                          AND ISNULL([ConvertedToOrdinary], 0) = 0
                    """, (refuse_motive, new_request_id, absence_request_id))

                    self.conn.commit()

                    conversions.append({
                        'absence_request_id': absence_request_id,
                        'new_request_id': new_request_id,
                        'hire_history_id': hire_history_id,
                        'employee_name': employee_name,
                        'date_start': date_start,
                        'date_end': date_end,
                        'docs_deadline': docs_deadline,
                        'special_reason': special_reason
                    })
                    logger.info(
                        f"[SWEEP SPECIALI] Richiesta {absence_request_id} di {employee_name} "
                        f"annullata e convertita in congedo ordinario ({new_request_id})"
                    )
                except Exception as inner_e:
                    logger.error(
                        f"[SWEEP SPECIALI] Errore conversione richiesta {absence_request_id}: {inner_e}"
                    )
                    self.conn.rollback()
                    continue

        except Exception as e:
            logger.error(f"[SWEEP SPECIALI] Errore recupero richieste scadute: {e}")
            import traceback
            logger.error(traceback.format_exc())

        return conversions

    
    def get_manager_emails(self, employee_hire_history_id):
        """
        Recupera le email dei Manager del centro di costo del dipendente.

        Criteri (stesso MainCdcId, solo Manager, rapporto attivo):
          - EmployeeHireHistory.EndWorkDate IS NULL AND employeerid = {EMPLOYER_ID}
          - EmployeeCdcStories.DateOut IS NULL
          - Functions.FunctionCode >= MANAGER_FUNCTION_CODE (70 = MANAGER)
          - Functions.FunctionCode > FunctionCode del dipendente target
            (la richiesta di un Manager va solo a ruoli superiori, non ai pari)
          - CostCenters.CdcId = MainCdcId del dipendente target
          - EmployeeAddress.WorkEmail non vuoto (e DateOut IS NULL)
        """
        try:
            cursor = self.conn.cursor()
            logger.info(f"[GET_MANAGER_EMAILS] Ricerca superiori gerarchici per hire_history_id={employee_hire_history_id}")

            query = f"""
            DECLARE @EmployeeHireHistoryId INT = ?;
            DECLARE @FunctionCode INT;
            DECLARE @MainCdcId INT;

            SELECT @FunctionCode = f.FunctionCode,
                   @MainCdcId = c.CdcId
            FROM employee.dbo.EmployeeHireHistory h
            INNER JOIN employee.dbo.EmployeeCdcStories css ON h.EmployeeHireHistoryId = css.EmployeeHireHistoryId
                AND css.DateOut IS NULL
                AND h.EndWorkDate IS NULL
                AND h.employeerid = {EMPLOYER_ID}
            INNER JOIN employee.dbo.Functions f ON f.FunctionId = css.FunctionId
            INNER JOIN employee.dbo.CdcSub s ON s.SubCdcId = css.SubCdcId
            INNER JOIN employee.dbo.CostCenters c ON c.CdcId = s.CdcId
            WHERE h.EmployeeHireHistoryId = @EmployeeHireHistoryId;

            SELECT DISTINCT
                UPPER(e.EmployeeName + ' ' + e.EmployeeSurname) AS Employee,
                a.WorkEmail
            FROM employee.dbo.EmployeeCdcStories css
            INNER JOIN employee.dbo.EmployeeHireHistory h ON css.EmployeeHireHistoryId = h.EmployeeHireHistoryId
                AND h.EndWorkDate IS NULL
                AND h.employeerid = {EMPLOYER_ID}
                AND css.DateOut IS NULL
            INNER JOIN employee.dbo.Functions f ON f.FunctionId = css.FunctionId
            INNER JOIN employee.dbo.CdcSub s ON s.SubCdcId = css.SubCdcId
            INNER JOIN employee.dbo.CostCenters c ON c.CdcId = s.CdcId
            INNER JOIN employee.dbo.Employees e ON e.EmployeeId = h.EmployeeId
            INNER JOIN employee.dbo.EmployeeAddress a ON a.EmployeeId = e.EmployeeId AND a.DateOut IS NULL
            WHERE f.FunctionCode > @FunctionCode
              AND f.FunctionCode >= {MANAGER_FUNCTION_CODE}
              AND c.CdcId = @MainCdcId
              AND LEN(ISNULL(a.WorkEmail, '')) > 0
            ORDER BY UPPER(e.EmployeeName + ' ' + e.EmployeeSurname);
            """

            cursor.execute(query, (employee_hire_history_id,))

            # La query produce result-set multipli (DECLARE/SELECT @vars + SELECT finale).
            # Avanza fino al primo result-set con righe.
            rows = []
            while True:
                try:
                    fetched = cursor.fetchall()
                    if fetched:
                        rows = fetched
                        break
                except pyodbc.ProgrammingError:
                    pass
                if not cursor.nextset():
                    break

            logger.debug(f"[GET_MANAGER_EMAILS] Righe ritornate: {len(rows)}")

            emails = []
            for row in rows:
                # La query ritorna (Employee, WorkEmail): l'email è nell'ultimo campo
                work_email = row[-1]
                if work_email is None:
                    continue
                email = str(work_email).strip()
                if email and '@' in email and email not in emails:
                    emails.append(email)
                    logger.debug(f"[GET_MANAGER_EMAILS] Superiore: {row[0]} -> {email}")

            logger.info(f"[GET_MANAGER_EMAILS] Email superiori gerarchici trovate (TOTALE {len(emails)}): {emails}")
            if not emails:
                logger.warning(f"[GET_MANAGER_EMAILS] Nessun superiore con email trovato per hire_history_id {employee_hire_history_id}")

            return emails

        except Exception as e:
            logger.error(f"[GET_MANAGER_EMAILS] Errore recupero email superiori: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def authenticate_manager(self, user_id, password):
        """Autentica manager con user/password e recupera CDC di appartenenza."""
        try:
            cursor = self.conn.cursor()

            query = f"""
            WITH Manager (EmployeeHireHistoryId, SubCdcId, FunctionCode, MainCdcId, MainCdcDescription, WorkEmail, UserId, Pass, ManagerName)
            AS (
                SELECT
                    h.EmployeeHireHistoryId,
                    cs.SubCdcId,
                    f.FunctionCode,
                    c.CdcId,
                    c.CdcDescription,
                    a.WorkEmail,
                    k.nomeuser,
                    k.pass,
                    e.EmployeeName + ' ' + e.EmployeeSurname AS ManagerName
                FROM employee.dbo.EmployeeCdcStories cs
                INNER JOIN employee.dbo.CdcSub csub
                    ON csub.SubCdcId = cs.SubCdcId
                    AND cs.DateOut IS NULL
                INNER JOIN employee.dbo.CostCenters c
                    ON c.CdcId = csub.CdcId
                INNER JOIN employee.dbo.Functions f
                    ON cs.FunctionId = f.FunctionId
                    AND f.FunctionCode >= {MANAGER_FUNCTION_CODE}
                INNER JOIN employee.dbo.EmployeeHireHistory h
                    ON cs.EmployeeHireHistoryId = h.EmployeeHireHistoryId
                    AND h.EndWorkDate IS NULL
                    AND h.EmployeerId = {EMPLOYER_ID}
                INNER JOIN employee.dbo.EmployeeAddress a
                    ON a.EmployeeId = h.EmployeeId
                    AND a.DateOut IS NULL
                INNER JOIN employee.dbo.Employees e
                    ON e.EmployeeId = h.EmployeeId
                INNER JOIN ResetServices.dbo.tbuserkey k
                    ON k.idanga = e.EmployeeId
            )
            SELECT TOP 1
                m.UserId,
                m.Pass,
                m.ManagerName,
                m.WorkEmail,
                m.FunctionCode,
                m.MainCdcId,
                m.MainCdcDescription,
                m.EmployeeHireHistoryId
            FROM Manager m
            WHERE m.WorkEmail IS NOT NULL
              AND LTRIM(RTRIM(m.UserId)) = LTRIM(RTRIM(?))
              AND LTRIM(RTRIM(m.Pass)) = LTRIM(RTRIM(?))
            ORDER BY m.FunctionCode DESC;
            """

            cursor.execute(query, (user_id, password))
            row = cursor.fetchone()

            if not row:
                return None

            return {
                'user_id': row[0],
                'password': row[1],
                'manager_name': row[2],
                'manager_email': row[3],
                'function_code': int(row[4]) if row[4] is not None else None,
                'main_cdc_id': int(row[5]) if row[5] is not None else None,
                'main_cdc_description': row[6],
                'employee_hire_history_id': int(row[7]) if row[7] is not None else None
            }

        except Exception as e:
            logger.error(f"Errore autenticazione manager: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None

    def get_requests_for_manager(self, main_cdc_id, manager_function_code=None):
        """Recupera le richieste assenza dei subordinati del manager, ordinate alfabeticamente.

        Subordinati = dipendenti dello stesso CDC con FunctionCode inferiore a quello
        del manager (stessa regola usata per l'invio email in get_manager_emails).
        """
        if manager_function_code is None:
            manager_function_code = MANAGER_FUNCTION_CODE
        try:
            cursor = self.conn.cursor()

            query = f"""
            DECLARE @MainCdcId INT = ?;
            DECLARE @ManagerFunctionCode INT = ?;

            WITH AllowedEmployees AS (
                SELECT DISTINCT
                    h.EmployeeHireHistoryId,
                    UPPER(e.EmployeeName + ' ' + e.EmployeeSurname) AS Employee,
                    c.CdcId,
                    c.CdcDescription,
                    f.FunctionCode
                FROM employee.dbo.EmployeeHireHistory h
                INNER JOIN employee.dbo.EmployeeCdcStories ecs
                    ON h.EmployeeHireHistoryId = ecs.EmployeeHireHistoryId
                    AND ecs.DateOut IS NULL
                    AND h.EndWorkDate IS NULL
                    AND h.EmployeerId = {EMPLOYER_ID}
                INNER JOIN employee.dbo.Employees e
                    ON h.EmployeeId = e.EmployeeId
                INNER JOIN employee.dbo.CdcSub cs
                    ON cs.SubCdcId = ecs.SubCdcId
                INNER JOIN employee.dbo.CostCenters c
                    ON c.CdcId = cs.CdcId
                INNER JOIN employee.dbo.Functions f
                    ON f.FunctionId = ecs.FunctionId
                WHERE f.FunctionCode < @ManagerFunctionCode
                  AND c.CdcId = @MainCdcId
            )
            SELECT
                ar.AbsenceRequestId,
                r.DocName,
                ae.Employee,
                ISNULL(rt.RequestName, 'Sconosciuto') AS RequestType,
                ar.DateStart,
                ar.DateEnd,
                ar.FromTime,
                ar.ToTime,
                ar.DateSys,
                ar.Approved,
                ar.Rejected,
                ar.ApprovedBy,
                ar.RefuseMotive,
                ae.CdcId,
                ae.CdcDescription,
                ae.FunctionCode,
                ar.UrgentRecoveryPeriod,
                ar.UrgentRecoveryDeadline,
                ar.SpecialReason,
                ar.DocumentationDeadline,
                ISNULL(ar.DocumentationReceived, 0) AS DocumentationReceived,
                ISNULL(ar.ConvertedToOrdinary, 0) AS ConvertedToOrdinary
            FROM [Employee].[dbo].[AbsenceRequestes] ar
            INNER JOIN AllowedEmployees ae
                ON ae.EmployeeHireHistoryId = ar.EmployrrHireHistoryId
            LEFT JOIN [Employee].[dbo].[Registry] r
                ON r.RegistroId = ar.RegistroId
            LEFT JOIN [Timeclocking].[dbo].[RequestType] rt
                ON rt.IDRequestType = ar.IDRequestType
            WHERE (ar.Rejected IS NULL OR ar.Rejected = 0)
              AND (ar.ApprovedBy IS NULL OR LTRIM(RTRIM(ar.ApprovedBy)) = '')
              AND (ar.Approved IS NULL OR YEAR(ar.Approved) <= 1900)
            ORDER BY ae.Employee ASC, ar.DateStart ASC, ar.DateSys DESC;
            """

            cursor.execute(query, (main_cdc_id, int(manager_function_code)))
            rows = cursor.fetchall()

            requests = []
            for row in rows:
                approved_date = row[9]
                rejected_flag = row[10]
                approved_by = row[11]
                refuse_motive = row[12]

                is_approved = bool(approved_date and getattr(approved_date, 'year', 0) > 1900 and approved_by)
                is_rejected = bool(rejected_flag and rejected_flag != 0)

                if is_approved:
                    status = 'approved'
                    status_text = 'Aprobată'
                elif is_rejected:
                    status = 'rejected'
                    status_text = 'Respinsă'
                else:
                    status = 'pending'
                    status_text = 'În așteptare'

                requests.append({
                    'absence_request_id': row[0],
                    'request_number': row[1],
                    'employee': row[2],
                    'request_type': row[3],
                    'date_start': row[4].isoformat() if row[4] else None,
                    'date_end': row[5].isoformat() if row[5] else None,
                    'from_time': str(row[6]) if row[6] else None,
                    'to_time': str(row[7]) if row[7] else None,
                    'date_sys': row[8].isoformat() if row[8] else None,
                    'approved': approved_date.isoformat() if approved_date else None,
                    'rejected': rejected_flag,
                    'approved_by': approved_by,
                    'refuse_motive': refuse_motive,
                    'status': status,
                    'status_text': status_text,
                    'cdc_id': int(row[13]) if row[13] is not None else None,
                    'cdc_description': row[14],
                    'function_code': int(row[15]) if row[15] is not None else None,
                    'urgent_recovery_period': row[16],
                    'urgent_recovery_deadline': row[17].isoformat() if row[17] else None,
                    'special_reason': row[18],
                    'documentation_deadline': row[19].isoformat() if row[19] else None,
                    'documentation_received': bool(row[20]),
                    'converted_to_ordinary': bool(row[21]),
                    'can_take_action': status == 'pending'
                })

            return requests

        except Exception as e:
            logger.error(f"Errore recupero richieste manager per CDC: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def manager_can_access_request(self, main_cdc_id, absence_request_id, manager_function_code=None):
        """Verifica che la richiesta sia di un subordinato del manager corrente
        (stesso CDC e FunctionCode inferiore a quello del manager)."""
        if manager_function_code is None:
            manager_function_code = MANAGER_FUNCTION_CODE
        try:
            cursor = self.conn.cursor()

            query = f"""
            DECLARE @MainCdcId INT = ?;
            DECLARE @ManagerFunctionCode INT = ?;

            SELECT TOP 1 ar.AbsenceRequestId
            FROM [Employee].[dbo].[AbsenceRequestes] ar
            INNER JOIN employee.dbo.EmployeeHireHistory h
                ON h.EmployeeHireHistoryId = ar.EmployrrHireHistoryId
                AND h.EndWorkDate IS NULL
                AND h.EmployeerId = {EMPLOYER_ID}
            INNER JOIN employee.dbo.EmployeeCdcStories ecs
                ON ecs.EmployeeHireHistoryId = h.EmployeeHireHistoryId
                AND ecs.DateOut IS NULL
            INNER JOIN employee.dbo.CdcSub cs
                ON cs.SubCdcId = ecs.SubCdcId
            INNER JOIN employee.dbo.CostCenters c
                ON c.CdcId = cs.CdcId
            INNER JOIN employee.dbo.Functions f
                ON f.FunctionId = ecs.FunctionId
            WHERE ar.AbsenceRequestId = ?
              AND c.CdcId = @MainCdcId
              AND f.FunctionCode < @ManagerFunctionCode;
            """

            cursor.execute(query, (main_cdc_id, int(manager_function_code), absence_request_id))
            row = cursor.fetchone()
            return row is not None

        except Exception as e:
            logger.error(f"Errore verifica accesso manager a richiesta: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def approve_request(self, absence_request_id, manager_name):
        """Approva una richiesta assenza."""
        try:
            cursor = self.conn.cursor()

            query = """
            UPDATE [Employee].[dbo].[AbsenceRequestes]
            SET [Approved] = GETDATE(),
                [ApprovedBy] = ?,
                [Rejected] = 0,
                [RefuseMotive] = NULL
            WHERE [AbsenceRequestId] = ?
            """

            cursor.execute(query, (manager_name, absence_request_id))
            updated = cursor.rowcount
            self.conn.commit()

            return updated > 0

        except Exception as e:
            logger.error(f"Errore approvazione richiesta {absence_request_id}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.conn.rollback()
            return False

    def reject_request(self, absence_request_id, manager_name, refuse_motive):
        """Rifiuta una richiesta assenza."""
        try:
            cursor = self.conn.cursor()

            query = """
            UPDATE [Employee].[dbo].[AbsenceRequestes]
            SET [Approved] = NULL,
                [ApprovedBy] = ?,
                [Rejected] = 1,
                [RefuseMotive] = ?
            WHERE [AbsenceRequestId] = ?
            """

            cursor.execute(query, (manager_name, refuse_motive, absence_request_id))
            updated = cursor.rowcount
            self.conn.commit()

            return updated > 0

        except Exception as e:
            logger.error(f"Errore rifiuto richiesta {absence_request_id}: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            self.conn.rollback()
            return False
    
    def get_registry_info(self, registro_id):
        """Recupera informazioni registro"""
        try:
            cursor = self.conn.cursor()
            
            query = """
            SELECT DocName, DocDate
            FROM [Employee].[dbo].[Registry]
            WHERE RegistroId = ?
            """
            
            cursor.execute(query, (registro_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'doc_name': row[0],
                    'doc_date': row[1]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Errore recupero registry info: {str(e)}")
            return None
    
    def generate_confirmation_pdf(self, employee_data, request_data, registry_info):
        """Genera PDF di conferma richiesta"""
        try:
            # Crea cartella temp
            os.makedirs('temp', exist_ok=True)
            
            # Nome file
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            pdf_filename = f"Confirmare_Cerere_{registry_info['doc_name']}_{timestamp}.pdf"
            pdf_path = os.path.join('temp', pdf_filename)
            
            # Crea PDF
            c = canvas.Canvas(pdf_path, pagesize=A4)
            width, height = A4
            
            # Logo
            y = height - 60
            if os.path.exists(self.logo_path):
                try:
                    logo = ImageReader(self.logo_path)
                    c.drawImage(logo, 50, y, width=100, height=40, preserveAspectRatio=True)
                except:
                    pass
            
            # Titolo
            y = height - 120
            c.setFont(self.font_bold, 18)
            c.drawCentredString(width / 2, y, "CONFIRMARE CERERE ABSENȚĂ")
            
            # Numero richiesta
            y -= 40
            c.setFont(self.font_bold, 14)
            c.drawCentredString(width / 2, y, f"Nr. {registry_info['doc_name']}")
            
            y -= 20
            c.setFont(self.font_name, 10)
            c.drawCentredString(width / 2, y, 
                              f"Data: {registry_info['doc_date'].strftime('%d.%m.%Y')}")
            
            # Separatore
            y -= 30
            c.line(50, y, width - 50, y)
            
            # Dati dipendente
            y -= 40
            c.setFont(self.font_bold, 12)
            c.drawString(50, y, "DATE ANGAJAT")
            
            y -= 25
            c.setFont(self.font_name, 10)
            c.drawString(50, y, f"Nume: {employee_data['surname']} {employee_data['name']}")
            
            y -= 20
            c.drawString(50, y, f"Badge: {employee_data['badge']}")
            
            # Dati richiesta
            y -= 40
            c.setFont(self.font_bold, 12)
            c.drawString(50, y, "DETALII CERERE")
            
            y -= 25
            c.setFont(self.font_name, 10)
            c.drawString(50, y, f"Tip absență: {request_data['type_name']}")

            # Dettagli assenza urgente: periodo di recupero scelto dal dipendente
            if request_data.get('urgent_recovery_period'):
                y -= 20
                if request_data['urgent_recovery_period'] == URGENT_RECOVERY_MONTH:
                    recovery_text = "Recuperare: în luna solicitării"
                else:
                    recovery_text = "Recuperare: până la sfârșitul anului lucrător"
                if request_data.get('urgent_recovery_deadline'):
                    recovery_text += f" (până la {request_data['urgent_recovery_deadline'].strftime('%d.%m.%Y')})"
                c.drawString(50, y, recovery_text)

            # Dettagli assenza speciale: motivo e obbligo di documentazione
            if request_data.get('special_reason'):
                y -= 20
                c.drawString(50, y, f"Motiv special: {request_data['special_reason']}")

            y -= 20
            c.drawString(50, y, f"Perioada: {request_data['date_start'].strftime('%d.%m.%Y')} - {request_data['date_end'].strftime('%d.%m.%Y')}")
            
            # Aggiungi orari se presenti (per assenze parziali)
            if request_data.get('from_time') and request_data.get('to_time'):
                y -= 20
                c.setFont(self.font_bold, 10)
                c.drawString(50, y, f"Orario: Dalle ore {request_data['from_time']} - Fino alle ore {request_data['to_time']}")
            
            
            y -= 20
            # Solo per giornate intere
            if request_data.get('working_days') is not None:
                c.drawString(50, y, f"Zile lucrătoare: {request_data['working_days']}")
            
            # Messaggio conferma
            y -= 50
            c.setFont(self.font_bold, 11)
            c.drawString(50, y, "STARE CERERE:")
            
            y -= 25
            c.setFont(self.font_name, 10)
            
            # Testo conferma
            text_lines = [
                "Cererea dumneavoastră a fost înregistrată cu succes în sistem.",
                "",
                "⚠️ IMPORTANT:",
                "Această cerere este ÎN AȘTEPTARE de verificare și aprobare.",
                "",
                "Până când cererea nu va fi aprobată oficial, aceasta NU se consideră acceptată.",
                "Veți primi confirmarea scrisă din partea superiorului direct sau a",
                "departamentului de resurse umane.",
                "",
                "Puteți verifica starea cererii dumneavoastră oricând de la acest kiosk",
                f"introducând numărul cererii: {registry_info['doc_name']}"
            ]
            
            for line in text_lines:
                c.drawString(70, y, line)
                y -= 15

            # Avviso obbligatorio per assenze speciali: documentazione entro la scadenza
            if request_data.get('documentation_deadline'):
                y -= 15
                c.setFont(self.font_bold, 10)
                c.drawString(50, y, "DOCUMENTAȚIE OBLIGATORIE (motiv special):")
                y -= 15
                c.setFont(self.font_name, 10)
                dl = request_data['documentation_deadline']
                dl_str = dl.strftime('%d.%m.%Y') if hasattr(dl, 'strftime') else str(dl)
                docs_days = request_data.get('docs_deadline_days')
                docs_lines = [
                    f"Prezentați documentele justificative la departamentul HR până la {dl_str}",
                    f"(în termen de {docs_days} zile de la data cererii)." if docs_days
                    else "(în termenul stabilit pentru motivul selectat).",
                    "În lipsa documentației, cererea va fi anulată și transformată",
                    "automat în zile de concediu odihnă."
                ]
                for line in docs_lines:
                    c.drawString(70, y, line)
                    y -= 15

            # Footer
            y = 80
            c.setFont(self.font_name, 8)
            c.drawCentredString(width / 2, y, 
                              f"Document generat automat - {datetime.now().strftime('%d.%m.%Y %H:%M')}")
            
            y -= 15
            c.drawCentredString(width / 2, y, 
                              "Acest document este doar o confirmare de înregistrare, nu reprezintă aprobare.")
            
            c.save()
            
            logger.info(f"PDF conferma generato: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            logger.error(f"Errore generazione PDF: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
