-- =====================================================================
-- MIGRAZIONE: MOTIVI SPECIALI PARAMETRICI (v2.5.0)
-- ---------------------------------------------------------------------
-- Sostituisce la lista hardcoded dei motivi speciali (tipo 19, kiosk)
-- con una tabella: ogni motivo ha il proprio numero massimo di giorni
-- lavorativi PER EVENTO (nessun piu' tetto annuale condiviso di 5 gg).
--
--   1) Căsătorie salariat            -> 5 giorni lavorativi
--   2) Căsătorie copil               -> 3 giorni lavorativi
--   3) Deces soț/soție, copil,
--      părinți, socri                -> 3 giorni lavorativi
--   4) Deces bunic, frate, soră      -> 1 giorno lavorativo
--   5) Donare sânge                  -> 1 giorno (giorno della donazione)
--   6) Obligații civice              -> durata conform documentației
--                                       (MaxDays NULL, durata libera,
--                                        documentazione obbligatoria)
--
-- Altre modifiche:
--   - AbsenceRequestes.SpecialReasonId : riferimento al motivo scelto
--     (SpecialReason continua a memorizzare il nome testuale per
--      compatibilita' con approvazioni / PDF / email / monitor)
--   - AbsenceRules.MaxDaysPerYear = NULL per il tipo 19: il limite
--     non e' piu' annuale per tipo ma per evento (per motivo).
--     Il tipo 18 (assenze urgenti) RESTA a 10 giorni/anno.
--
-- Database coinvolti:
--   [Employee] -> SpecialAbsenceMotives (nuova tabella),
--                 AbsenceRequestes (nuova colonna),
--                 AbsenceRules (MaxDaysPerYear tipo 19 = NULL)
--
-- Script IDEMPOTENTE: puo' essere rieseguito senza errori.
-- I batch sono separati dal marcatore "-- >>> BATCH" per il runner Python.
-- In esecuzione manuale da SSMS: rimuovere i marcatori o eseguire a blocchi.
-- =====================================================================


-- >>> BATCH 1: [Employee].SpecialAbsenceMotives - catalogo motivi speciali per evento
IF OBJECT_ID('[Employee].[dbo].[SpecialAbsenceMotives]', 'U') IS NULL
BEGIN
    CREATE TABLE [Employee].[dbo].[SpecialAbsenceMotives] (
        MotiveId              INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_SpecialAbsenceMotives PRIMARY KEY,
        NameRo                NVARCHAR(100) NOT NULL,          -- nome mostrato nel kiosk (rumeno)
        NameIt                NVARCHAR(100) NOT NULL,          -- nome italiano (gestione)
        MaxDays               DECIMAL(4,1) NULL,               -- max giorni lavorativi per evento (NULL = durata da documentazione)
        DaysLabelRo           NVARCHAR(80) NULL,               -- etichetta giorni mostrata nel kiosk (es. N'5 zile lucratoare')
        RequiresDocumentation BIT NOT NULL
            CONSTRAINT DF_SpecialAbsenceMotives_ReqDocs DEFAULT (1),
        DocsDeadlineDays      TINYINT NOT NULL
            CONSTRAINT DF_SpecialAbsenceMotives_DocsDays DEFAULT (5),
        AllowCustomDuration   BIT NOT NULL
            CONSTRAINT DF_SpecialAbsenceMotives_CustomDur DEFAULT (0), -- 1 = durata libera in base alla documentazione
        IsActive              BIT NOT NULL
            CONSTRAINT DF_SpecialAbsenceMotives_IsActive DEFAULT (1),
        SortOrder             INT NOT NULL
            CONSTRAINT DF_SpecialAbsenceMotives_SortOrder DEFAULT (0),
        DateIn                DATETIME NOT NULL CONSTRAINT DF_SpecialAbsenceMotives_DateIn DEFAULT (GETDATE()),
        DateOut               DATETIME NULL
    );
    PRINT 'Tabella SpecialAbsenceMotives creata';
END
ELSE PRINT 'Tabella SpecialAbsenceMotives gia presente';


-- >>> BATCH 2: [Employee].SpecialAbsenceMotives - seed dei 6 motivi (idempotente su NameRo)
IF NOT EXISTS (SELECT 1 FROM [Employee].[dbo].[SpecialAbsenceMotives] WHERE NameRo = N'Căsătorie salariat')
BEGIN
    INSERT INTO [Employee].[dbo].[SpecialAbsenceMotives]
        (NameRo, NameIt, MaxDays, DaysLabelRo, RequiresDocumentation, DocsDeadlineDays, AllowCustomDuration, IsActive, SortOrder)
    VALUES
        (N'Căsătorie salariat',                       N'Matrimonio del dipendente',                    5.0,  N'5 zile lucrătoare',                    1, 5, 0, 1, 10),
        (N'Căsătorie copil',                          N'Matrimonio di un figlio/a',                    3.0,  N'3 zile lucrătoare',                    1, 5, 0, 1, 20),
        (N'Deces soț/soție, copil, părinți, socri',   N'Decesso coniuge, figlio, genitori o suoceri',  3.0,  N'3 zile lucrătoare',                    1, 5, 0, 1, 30),
        (N'Deces bunic, frate, soră',                 N'Decesso nonno, fratello o sorella',            1.0,  N'1 zi lucrătoare',                      1, 5, 0, 1, 40),
        (N'Donare sânge',                             N'Donazione di sangue',                          1.0,  N'1 zi de permis (în ziua donării)',     1, 5, 0, 1, 50),
        (N'Obligații civice',                         N'Obblighi civici',                              NULL, N'durată conform documentației',         1, 5, 1, 1, 60);
    PRINT 'Motivi speciali inseriti (6 righe)';
END
ELSE PRINT 'Motivi speciali gia presenti';


-- >>> BATCH 3: [Employee].AbsenceRequestes - colonna riferimento motivo
IF COL_LENGTH('[Employee].[dbo].[AbsenceRequestes]', 'SpecialReasonId') IS NULL
    ALTER TABLE [Employee].[dbo].[AbsenceRequestes] ADD SpecialReasonId INT NULL;
PRINT 'AbsenceRequestes: colonna SpecialReasonId aggiunta (se assente)';


-- >>> BATCH 4: [Employee].AbsenceRules - tipo 19 senza piu' tetto annuale (limite per evento per motivo)
UPDATE [Employee].[dbo].[AbsenceRules]
SET MaxDaysPerYear = NULL
WHERE IDRequestType = 19
  AND DateOut IS NULL
  AND MaxDaysPerYear IS NOT NULL;
PRINT 'AbsenceRules tipo 19: MaxDaysPerYear annullato (limite ora per evento/motivo)';
-- Il tipo 18 (Invoire urgenta) RESTA con MaxDaysPerYear = 10.


-- >>> BATCH 5: verifica finale
SELECT MotiveId, NameRo, NameIt, MaxDays, DaysLabelRo, RequiresDocumentation, DocsDeadlineDays, AllowCustomDuration, IsActive, SortOrder
FROM [Employee].[dbo].[SpecialAbsenceMotives]
WHERE DateOut IS NULL
ORDER BY SortOrder;

SELECT rt.IDRequestType, rt.RequestName, ar.MaxDaysPerYear, ar.DocsDeadlineDays
FROM [Timeclocking].[dbo].[RequestType] rt
LEFT JOIN [Employee].[dbo].[AbsenceRules] ar ON ar.IDRequestType = rt.IDRequestType AND ar.DateOut IS NULL
WHERE rt.IDRequestType IN (18, 19);
