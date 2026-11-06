/**
 * ABSENCE REQUEST - FRONTEND APPLICATION
 * Gestione cerere absență (richieste assenza)
 */

// ========================================
// STATE MANAGEMENT
// ========================================
const state = {
    selectedEmployee: null,
    requestTypes: [],
    selectedRequestType: null,
    availableDays: 0,
    quotaRemaining: null,   // quota annua residua (solo assenze urgenti, limite per legge)
    quotaMax: null,
    specialMotives: [],     // motivi speciali da SpecialAbsenceMotives (limite giorni PER EVENTO)
    selectedMotive: null,
    dateStart: null,
    dateEnd: null,
    workingDays: 0,
    currentPdfPath: null,
    currentPdfFilename: null,
    badgeReadTimeout: null,
    autoResetTimeout: null,
    printCountdownInterval: null,
    isProcessing: false,
    keypadMode: false  // true quando l'utente sta usando il tastierino manuale
};

// Rendi state globale per time-fields.js
window.state = state;

// ========================================
// CONFIGURATION
// ========================================
const config = {
    badgeReadDelay: 500,      // Delay per RFID (lettura rapida da scanner)
    badgeReadDelayKeypad: 2500, // Delay più lungo per inserimento manuale via tastierino
    autoResetDelay: 30000,
    vacationRequestTypeId: 1,   // IDRequestType per ferie
    urgentRequestTypeId: 18,    // IDRequestType per assenze urgenti (recuperabili)
    specialRequestTypeId: 19,   // IDRequestType per motivi speciali (deces, căsătorie)
    printButtonTimeout: 15000  // ms prima che il bottone stampa sparisca e il PDF venga eliminato
};

// ========================================
// DOM ELEMENTS
// ========================================
const elements = {
    badgeInput: document.getElementById('badgeInput'),
    badgeStatus: document.getElementById('badgeStatus'),
    numericKeypad: document.getElementById('numericKeypad'),
    employeeInfo: document.getElementById('employeeInfo'),
    employeeName: document.getElementById('employeeName'),
    availableDaysInfo: document.getElementById('availableDaysInfo'),
    availableDays: document.getElementById('availableDays'),
    requestType: document.getElementById('requestType'),
    dateStart: document.getElementById('dateStart'),
    dateEnd: document.getElementById('dateEnd'),
    workingDaysInfo: document.getElementById('workingDaysInfo'),
    workingDays: document.getElementById('workingDays'),
    workingDaysHelper: document.getElementById('workingDaysHelper'),
    submitBtn: document.getElementById('submitBtn'),
    resetBtn: document.getElementById('resetBtn'),
    requestForm: document.getElementById('requestForm'),
    resultSection: document.getElementById('resultSection'),
    resultRequestNumber: document.getElementById('resultRequestNumber'),
    resultEmployee: document.getElementById('resultEmployee'),
    resultType: document.getElementById('resultType'),
    resultPeriod: document.getElementById('resultPeriod'),
    resultDays: document.getElementById('resultDays'),
    printBtn: document.getElementById('printBtn'),
    newRequestBtn: document.getElementById('newRequestBtn'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    toastContainer: document.getElementById('toastContainer'),
    // Assenze urgenti / speciali
    urgentFieldsGroup: document.getElementById('urgentFieldsGroup'),
    urgentRecoveryPeriod: document.getElementById('urgentRecoveryPeriod'),
    urgentQuotaHelper: document.getElementById('urgentQuotaHelper'),
    specialFieldsGroup: document.getElementById('specialFieldsGroup'),
    specialReason: document.getElementById('specialReason'),
    specialMotiveHelper: document.getElementById('specialMotiveHelper'),
    specialDocsDays: document.getElementById('specialDocsDays'),
    specialDocsWarning: document.getElementById('specialDocsWarning'),
    quotaInfo: document.getElementById('quotaInfo'),
    quotaLabel: document.getElementById('quotaLabel'),
    quotaValue: document.getElementById('quotaValue')
};

// ========================================
// INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', function () {
    loadRequestTypes();
    loadSpecialMotives();
    attachEventListeners();
    setMinDate();
    elements.badgeInput.focus();
});

async function loadRequestTypes() {
    try {
        const response = await fetch('/api/request-types');
        const data = await response.json();

        if (data.success) {
            state.requestTypes = data.request_types;
            populateRequestTypes();
        } else {
            showToast('Errore caricamento tipi richiesta', 'error');
        }
    } catch (error) {
        console.error('Errore caricamento tipi richiesta:', error);
        showToast('Errore di connessione', 'error');
    }
}

function populateRequestTypes() {
    elements.requestType.innerHTML = '<option value="">Selectați...</option>';

    state.requestTypes.forEach(type => {
        const option = document.createElement('option');
        option.value = type.id;
        option.textContent = type.name;
        elements.requestType.appendChild(option);
    });
}

// ========================================
// MOTIVI SPECIALI (anagrafica SpecialAbsenceMotives: nome evento + giorni)
// ========================================
async function loadSpecialMotives() {
    try {
        const response = await fetch('/api/special-motives');
        const data = await response.json();

        if (data.success) {
            state.specialMotives = data.motives || [];
            populateSpecialMotives();
        } else {
            console.warn('Impossibile caricare i motivi speciali');
        }
    } catch (error) {
        console.error('Errore caricamento motivi speciali:', error);
    }
}

function formatMotiveDays(motive) {
    // Etichetta giorni dalla tabella (DaysLabelRo); fallback calcolato da MaxDays
    if (motive.days_label_ro) {
        return motive.days_label_ro;
    }
    if (motive.max_days === null || motive.max_days === undefined || motive.allow_custom_duration) {
        return 'durat\u0103 conform documenta\u021Biei';
    }
    const days = Number.isInteger(motive.max_days) ? motive.max_days : motive.max_days.toFixed(1);
    return motive.max_days === 1 ? `${days} zi lucr\u0103toare` : `${days} zile lucr\u0103toare`;
}

function populateSpecialMotives() {
    if (!elements.specialReason) return;

    elements.specialReason.innerHTML = '<option value="">Selecta\u021Bi...</option>';

    state.specialMotives.forEach(motive => {
        const option = document.createElement('option');
        option.value = motive.id;
        option.textContent = `${motive.name_ro} \u2013 ${formatMotiveDays(motive)}`;
        elements.specialReason.appendChild(option);
    });
}

function handleSpecialMotiveChange() {
    const motiveId = parseInt(elements.specialReason.value, 10);
    state.selectedMotive = state.specialMotives.find(m => m.id === motiveId) || null;
    updateSpecialMotiveUI();

    // Rivaluta il limite per evento se il periodo è già stato selezionato
    if (state.workingDays > 0) {
        evaluateSpecialMotiveDays();
    }
}

function updateSpecialMotiveUI() {
    const motive = state.selectedMotive;

    if (elements.specialMotiveHelper) {
        if (!state.specialMotives.length) {
            // Catalogo non disponibile (es. migrazione DB non applicata in questa sede)
            elements.specialMotiveHelper.textContent =
                'Lista motivelor nu este disponibil\u0103: contacta\u021Bi departamentul HR';
        } else if (!motive) {
            elements.specialMotiveHelper.textContent = 'Selecta\u021Bi situa\u021Bia pentru care solicita\u021Bi permisul';
        } else if (motive.max_days === null || motive.allow_custom_duration) {
            elements.specialMotiveHelper.textContent =
                'Durata se stabile\u0219te \u00een baza documenta\u021Biei justificative';
        } else {
            elements.specialMotiveHelper.textContent =
                `Pentru acest eveniment: ${formatMotiveDays(motive)}`;
        }
    }

    if (elements.specialDocsDays) {
        elements.specialDocsDays.textContent = motive ? motive.docs_deadline_days : 5;
    }
    // Avviso documenti solo se il motivo li richiede (RequiresDocumentation)
    if (elements.specialDocsWarning) {
        elements.specialDocsWarning.style.display =
            (motive && !motive.requires_documentation) ? 'none' : 'block';
    }
}

/**
 * Verifica il limite di giorni lavorativi PER EVENTO del motivo speciale.
 * Ritorna true se la richiesta rispetta il limite (o il motivo ha durata libera).
 */
function evaluateSpecialMotiveDays() {
    if (state.selectedRequestType !== config.specialRequestTypeId) return true;

    const motive = state.selectedMotive;
    const limited = motive && motive.max_days !== null && !motive.allow_custom_duration;

    if (limited && state.workingDays > motive.max_days) {
        elements.workingDaysHelper.textContent =
            `\u26A0\uFE0F Motivul selectat prevede maxim ${formatMotiveDays(motive)}!`;
        elements.workingDaysHelper.style.color = '#ef4444';
        elements.submitBtn.disabled = true;
        showToast(`Zile solicitate (${state.workingDays}) > maxim pentru motiv (${formatMotiveDays(motive)})`, 'error');
        return false;
    }

    if (limited) {
        elements.workingDaysHelper.textContent =
            `\u2713 \u00cen limita motivului: ${formatMotiveDays(motive)}`;
        elements.workingDaysHelper.style.color = '#10b981';
    } else {
        elements.workingDaysHelper.textContent = '';
    }
    elements.submitBtn.disabled = false;
    return true;
}

function setMinDate(dayNoZone) {
    // Imposta data minima basata su DayNoZone (0 = oggi, 1 = domani, ecc.)
    if (dayNoZone === undefined || dayNoZone === null) {
        dayNoZone = 1; // default: domani
    }
    const minDateObj = new Date();
    minDateObj.setDate(minDateObj.getDate() + dayNoZone);
    // Usa formato locale YYYY-MM-DD per evitare problemi timezone con toISOString()
    const year = minDateObj.getFullYear();
    const month = String(minDateObj.getMonth() + 1).padStart(2, '0');
    const day = String(minDateObj.getDate()).padStart(2, '0');
    const minDate = `${year}-${month}-${day}`;

    elements.dateStart.min = minDate;
    elements.dateEnd.min = minDate;

    // Se le date già selezionate sono prima del nuovo minimo, resettale
    if (elements.dateStart.value && elements.dateStart.value < minDate) {
        elements.dateStart.value = '';
        state.dateStart = null;
    }
    if (elements.dateEnd.value && elements.dateEnd.value < minDate) {
        elements.dateEnd.value = '';
        state.dateEnd = null;
    }
}

// ========================================
// EVENT LISTENERS
// ========================================
function attachEventListeners() {
    // Badge input
    elements.badgeInput.addEventListener('input', handleBadgeInput);

    // Mostra tastierino quando il campo badge riceve focus
    elements.badgeInput.addEventListener('focus', showKeypad);

    // Tastierino numerico
    if (elements.numericKeypad) {
        elements.numericKeypad.addEventListener('click', handleKeypadClick);
        // Previeni la perdita di focus al click sul tastierino
        elements.numericKeypad.addEventListener('mousedown', (e) => e.preventDefault());
    }

    // Request type change
    elements.requestType.addEventListener('change', handleRequestTypeChange);

    // Motivo speciale: aggiorna limite giorni per evento e scadenza documenti
    if (elements.specialReason) {
        elements.specialReason.addEventListener('change', handleSpecialMotiveChange);
    }

    // Date changes
    elements.dateStart.addEventListener('change', handleDateChange);
    elements.dateEnd.addEventListener('change', handleDateChange);

    // Form submit
    elements.requestForm.addEventListener('submit', handleFormSubmit);

    // Reset button
    elements.resetBtn.addEventListener('click', resetForm);

    // Print button
    elements.printBtn.addEventListener('click', handlePrint);

    // New request button
    elements.newRequestBtn.addEventListener('click', resetToKioskMode);
}

// ========================================
// BADGE HANDLING
// ========================================
function handleBadgeInput(e) {
    clearTimeout(state.badgeReadTimeout);

    const badgeNumber = e.target.value.trim();

    if (badgeNumber.length === 0) {
        updateBadgeStatus('waiting');
        elements.employeeInfo.style.display = 'none';
        state.selectedEmployee = null;
        disableForm();
        return;
    }

    updateBadgeStatus('reading');

    // Usa delay più lungo se l'utente sta inserendo manualmente col tastierino
    const delay = state.keypadMode ? config.badgeReadDelayKeypad : config.badgeReadDelay;

    state.badgeReadTimeout = setTimeout(() => {
        validateBadge(badgeNumber);
    }, delay);
}

// ========================================
// TASTIERINO NUMERICO
// ========================================
function showKeypad() {
    if (elements.numericKeypad) {
        elements.numericKeypad.style.display = 'block';
    }
}

function hideKeypad() {
    if (elements.numericKeypad) {
        elements.numericKeypad.style.display = 'none';
    }
    state.keypadMode = false;
}

function handleKeypadClick(e) {
    const btn = e.target.closest('.keypad-btn');
    if (!btn) return;

    const key = btn.dataset.key;
    // Attiva modalità tastierino: delay più lungo per dare tempo di inserire le cifre
    state.keypadMode = true;

    if (key === 'clear') {
        elements.badgeInput.value = '';
    } else if (key === 'back') {
        elements.badgeInput.value = elements.badgeInput.value.slice(0, -1);
    } else {
        elements.badgeInput.value += key;
    }

    // Dispatcha evento input per riusare la logica di handleBadgeInput
    elements.badgeInput.dispatchEvent(new Event('input', { bubbles: true }));
    elements.badgeInput.focus();
}

async function validateBadge(badgeNumber) {
    try {
        updateBadgeStatus('reading');

        const response = await fetch('/api/validate-badge', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ badgeNumber })
        });

        const data = await response.json();

        if (data.success) {
            state.selectedEmployee = data.employee;
            updateBadgeStatus('success');
            showEmployeeInfo(data.employee);
            enableForm();
            hideKeypad();
            showToast(`Bun venit, ${data.employee.name}!`, 'success');

            // Carica giorni disponibili per anno corrente
            await loadAvailableDays(badgeNumber);
        } else {
            updateBadgeStatus('error');
            elements.employeeInfo.style.display = 'none';
            state.selectedEmployee = null;
            disableForm();
            showToast(data.error || 'Badge invalid', 'error');

            setTimeout(() => {
                resetBadgeInput();
            }, 2000);
        }
    } catch (error) {
        console.error('Errore validazione badge:', error);
        updateBadgeStatus('error');
        showToast('Errore di connessione', 'error');
    }
}

async function loadAvailableDays(badgeNumber) {
    try {
        const currentYear = new Date().getFullYear();

        const response = await fetch('/api/available-vacation-days', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                badgeNumber: badgeNumber,
                year: currentYear
            })
        });

        const data = await response.json();

        if (data.success) {
            state.availableDays = data.available_days;
            // Non mostrare subito, solo quando si seleziona tipo ferie
        } else {
            console.warn('Impossibile caricare giorni disponibili');
        }
    } catch (error) {
        console.error('Errore caricamento giorni disponibili:', error);
    }
}

function showEmployeeInfo(employee) {
    elements.employeeName.textContent = employee.name;
    elements.employeeInfo.style.display = 'block';
}

function updateBadgeStatus(status) {
    const statusIcon = elements.badgeStatus.querySelector('.status-icon');
    const statusText = elements.badgeStatus.querySelector('.status-text');

    elements.badgeStatus.className = 'badge-status ' + status;

    switch (status) {
        case 'waiting':
            statusIcon.textContent = '\uD83D\uDCF1';
            statusText.textContent = '\u00CEn a\u0219teptare...';
            break;
        case 'reading':
            statusIcon.textContent = '\uD83D\uDD04';
            statusText.textContent = 'Citire...';
            break;
        case 'success':
            statusIcon.textContent = '\u2705';
            statusText.textContent = 'Valid';
            break;
        case 'error':
            statusIcon.textContent = '\u274C';
            statusText.textContent = 'Invalid';
            break;
    }
}

// ========================================
// FORM HANDLING
// ========================================
function enableForm() {
    elements.requestType.disabled = false;
    elements.dateStart.disabled = false;
    elements.dateEnd.disabled = false;
}

function disableForm() {
    elements.requestType.disabled = true;
    elements.dateStart.disabled = true;
    elements.dateEnd.disabled = true;
    elements.submitBtn.disabled = true;
}

function handleRequestTypeChange(e) {
    const requestTypeId = parseInt(e.target.value);

    if (!requestTypeId) {
        state.selectedRequestType = null;
        elements.availableDaysInfo.style.display = 'none';
        hideUrgentFields();
        hideSpecialFields();
        hideQuotaInfo();
        return;
    }

    state.selectedRequestType = requestTypeId;

    // Aggiorna data minima in base a DayNoZone del tipo selezionato
    const selectedType = state.requestTypes.find(t => t.id === requestTypeId);
    if (selectedType) {
        // Resetta le date quando cambia il tipo di richiesta
        // in modo che il calendario rifletta il nuovo minimo
        elements.dateStart.value = '';
        elements.dateEnd.value = '';
        state.dateStart = null;
        state.dateEnd = null;
        state.workingDays = 0;
        elements.workingDaysInfo.style.display = 'none';
        elements.submitBtn.disabled = true;

        setMinDate(selectedType.day_no_zone);
    }

    // Mostra giorni disponibili solo per ferie (IDRequestType = 1)
    if (requestTypeId === config.vacationRequestTypeId) {
        elements.availableDays.textContent = state.availableDays;
        elements.availableDaysInfo.style.display = 'block';

        if (state.availableDays <= 0) {
            showToast('Nu ave\u021Bi zile de concediu disponibile!', 'warning');
        }
    } else {
        elements.availableDaysInfo.style.display = 'none';
    }

    // Assenze urgenti: mostra la scelta del periodo di recupero
    if (requestTypeId === config.urgentRequestTypeId) {
        showUrgentFields(selectedType);
    } else {
        hideUrgentFields();
    }

    // Assenze speciali: mostra la scelta del motivo + avviso documentazione
    if (requestTypeId === config.specialRequestTypeId) {
        showSpecialFields();
    } else {
        hideSpecialFields();
    }

    // Quota annua residua: solo assenze urgenti (le speciali hanno limite per evento)
    if (requestTypeId === config.urgentRequestTypeId) {
        loadQuota(requestTypeId, selectedType);
    } else {
        hideQuotaInfo();
    }

    // Gestisci visibilità campi orari
    if (window.timeFieldsManagement) {
        window.timeFieldsManagement.handleTimeFieldsVisibility(requestTypeId);
    }

    // Ricalcola giorni lavorativi se date già selezionate
    if (state.dateStart && state.dateEnd) {
        calculateWorkingDays();
    }
}

// ========================================
// ASSENZE URGENTI / SPECIALI
// ========================================
function showUrgentFields(selectedType) {
    if (elements.urgentFieldsGroup) {
        elements.urgentFieldsGroup.style.display = 'block';
    }
    // Limite annuo per legge dalla tabella AbsenceRules.MaxDaysPerYear (niente valori fissi)
    if (elements.urgentQuotaHelper) {
        const maxDays = selectedType ? selectedType.max_days_per_year : null;
        elements.urgentQuotaHelper.textContent = maxDays
            ? `Zilele de absen\u021B\u0103 urgent\u0103 trebuie recuperate (max. ${maxDays} zile/an)`
            : 'Zilele de absen\u021B\u0103 urgent\u0103 trebuie recuperate';
    }
}

function hideUrgentFields() {
    if (elements.urgentFieldsGroup) {
        elements.urgentFieldsGroup.style.display = 'none';
    }
    if (elements.urgentRecoveryPeriod) {
        elements.urgentRecoveryPeriod.value = '';
    }
}

function showSpecialFields() {
    if (elements.specialFieldsGroup) {
        elements.specialFieldsGroup.style.display = 'block';
    }
    updateSpecialMotiveUI();
}

function hideSpecialFields() {
    if (elements.specialFieldsGroup) {
        elements.specialFieldsGroup.style.display = 'none';
    }
    if (elements.specialReason) {
        elements.specialReason.value = '';
    }
    state.selectedMotive = null;
    updateSpecialMotiveUI();
}

function hideQuotaInfo() {
    state.quotaRemaining = null;
    state.quotaMax = null;
    if (elements.quotaInfo) {
        elements.quotaInfo.style.display = 'none';
    }
}

async function loadQuota(requestTypeId, selectedType) {
    try {
        const response = await fetch('/api/absence-quota', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                badgeNumber: elements.badgeInput.value.trim(),
                requestTypeId: requestTypeId
            })
        });

        const data = await response.json();

        if (data.success && elements.quotaInfo) {
            state.quotaRemaining = data.remaining;
            state.quotaMax = data.max_days;

            const typeName = selectedType ? selectedType.name : 'absen\u021B\u0103';
            elements.quotaLabel.textContent = `Zile r\u0103mase: ${typeName}`;
            elements.quotaValue.textContent = `${data.remaining} din ${data.max_days} (utilizate: ${data.used})`;
            elements.quotaInfo.style.display = 'block';

            if (data.remaining <= 0) {
                showToast('Nu mai ave\u021Bi zile disponibile pentru acest tip de absen\u021B\u0103!', 'warning');
            }
        } else {
            hideQuotaInfo();
        }
    } catch (error) {
        console.error('Errore caricamento quota:', error);
        hideQuotaInfo();
    }
}

async function handleDateChange() {
    const startDate = elements.dateStart.value;
    const endDate = elements.dateEnd.value;

    if (!startDate || !endDate) {
        elements.workingDaysInfo.style.display = 'none';
        elements.submitBtn.disabled = true;
        return;
    }

    // Verifica che data fine >= data inizio
    if (new Date(endDate) < new Date(startDate)) {
        showToast('Data sf\u00e2r\u0219it trebuie s\u0103 fie dup\u0103 data \u00eenceput', 'warning');
        elements.dateEnd.value = '';
        elements.workingDaysInfo.style.display = 'none';
        elements.submitBtn.disabled = true;
        return;
    }

    state.dateStart = new Date(startDate);
    state.dateEnd = new Date(endDate);

    await calculateWorkingDays();
}

async function calculateWorkingDays() {
    // Salta calcolo per assenze parziali
    if (window.timeFieldsManagement && window.timeFieldsManagement.isPartialAbsence()) {
        elements.workingDaysInfo.style.display = 'none';
        elements.submitBtn.disabled = false;
        return;
    }

    if (!state.dateStart || !state.dateEnd || !state.selectedRequestType) {
        return;
    }

    try {
        showLoading('Calcul zile lucr\u0103toare...');

        const response = await fetch('/api/calculate-working-days', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                dateStart: state.dateStart.toISOString().split('T')[0],
                dateEnd: state.dateEnd.toISOString().split('T')[0],
                requestTypeId: state.selectedRequestType
            })
        });

        const data = await response.json();

        hideLoading();

        if (data.success) {
            state.workingDays = data.working_days;
            elements.workingDays.textContent = data.working_days;

            // Mostra info giorni lavorativi
            elements.workingDaysInfo.style.display = 'block';

            // Verifica disponibilità per ferie
            if (state.selectedRequestType === config.vacationRequestTypeId) {
                if (state.workingDays > state.availableDays) {
                    elements.workingDaysHelper.textContent =
                        `\u26A0\uFE0F Ave\u021Bi doar ${state.availableDays} zile disponibile!`;
                    elements.workingDaysHelper.style.color = '#ef4444';
                    elements.submitBtn.disabled = true;
                    showToast(`Zile solicitate (${state.workingDays}) > Zile disponibile (${state.availableDays})`, 'error');
                } else {
                    elements.workingDaysHelper.textContent =
                        `\u2713 Zile disponibile dup\u0103 cerere: ${state.availableDays - state.workingDays}`;
                    elements.workingDaysHelper.style.color = '#10b981';
                    elements.submitBtn.disabled = false;
                }
            } else if (state.quotaRemaining !== null && state.selectedRequestType !== null) {
                // Tipi con quota annua (assenze urgenti)
                if (state.workingDays > state.quotaRemaining) {
                    elements.workingDaysHelper.textContent =
                        `\u26A0\uFE0F Ave\u021Bi doar ${state.quotaRemaining} zile disponibile pentru acest tip!`;
                    elements.workingDaysHelper.style.color = '#ef4444';
                    elements.submitBtn.disabled = true;
                    showToast(`Zile solicitate (${state.workingDays}) > Zile disponibile (${state.quotaRemaining})`, 'error');
                } else {
                    elements.workingDaysHelper.textContent =
                        `\u2713 Zile r\u0103mase dup\u0103 cerere: ${state.quotaRemaining - state.workingDays}`;
                    elements.workingDaysHelper.style.color = '#10b981';
                    elements.submitBtn.disabled = false;
                }
            } else if (state.selectedRequestType === config.specialRequestTypeId) {
                // Motivi speciali: limite di giorni lavorativi PER EVENTO (SpecialAbsenceMotives)
                evaluateSpecialMotiveDays();
            } else {
                elements.workingDaysHelper.textContent = '';
                elements.submitBtn.disabled = false;
            }
        } else {
            showToast(data.error || 'Errore calcolo giorni', 'error');
        }
    } catch (error) {
        hideLoading();
        console.error('Errore calcolo giorni lavorativi:', error);
        showToast('Errore di connessione', 'error');
    }
}

async function handleFormSubmit(e) {
    e.preventDefault();

    if (state.isProcessing) return;

    // SKIP COMPLETO VALIDAZIONI PER ASSENZE PARZIALI
    if (window.timeFieldsManagement && window.timeFieldsManagement.isPartialAbsence()) {
        // Validazioni minime per assenze orarie
        if (!state.selectedEmployee) {
            showToast('Scana\u021bi badge-ul', 'warning');
            return;
        }
        if (!state.selectedRequestType) {
            showToast('Selecta\u021bi tipul de absen\u021b\u0103', 'warning');
            return;
        }
        
        // Valida orari
        const {fromTime, toTime} = window.timeFieldsManagement.getTimeValues();
        if (!fromTime || !toTime) {
            showToast('Inserire orario inizio e fine', 'warning');
            return;
        }
        if (!window.timeFieldsManagement.validateTimeRange()) {
            return;
        }
        
        // Se state \u00e8 popolato, vai direttamente a submit
        if (window.state && window.state.dateStart && window.state.dateEnd) {
            console.log(' Assenza parziale validata - submit diretto');
            await submitRequest();
            return;
        }
    }

    // Validazioni finali
    if (!state.selectedEmployee) {
        showToast('Scana\u021bi badge-ul', 'warning');
        return;
    }

    if (!state.selectedRequestType) {
        showToast('Selecta\u021bi tipul de absen\u021b\u0103', 'warning');
        return;
    }

    if (!state.dateStart || !state.dateEnd) {
        showToast('Selecta\u021bi perioada', 'warning');
        return;
    }

    if (state.workingDays <= 0) {
        showToast('Perioada selectat\u0103 nu con\u021bine zile lucr\u0103toare', 'warning');
        return;
    }

    // Verifica giorni disponibili per ferie
    if (state.selectedRequestType === config.vacationRequestTypeId) {
        if (state.workingDays > state.availableDays) {
            showToast('Nu ave\u021Bi suficiente zile de concediu disponibile', 'error');
            return;
        }
    }

    // Verifica quota annua per assenze urgenti
    if (state.quotaRemaining !== null && state.selectedRequestType !== null) {
        if (state.workingDays > state.quotaRemaining) {
            showToast(`Zile solicitate (${state.workingDays}) > Zile disponibile (${state.quotaRemaining})`, 'error');
            return;
        }
    }

    // Assenza urgente: periodo di recupero obbligatorio (mese o anno lavorativo)
    if (state.selectedRequestType === config.urgentRequestTypeId) {
        if (!elements.urgentRecoveryPeriod || !elements.urgentRecoveryPeriod.value) {
            showToast('Selecta\u021Bi perioada de recuperare a zilelor de absen\u021B\u0103 urgent\u0103!', 'warning');
            return;
        }
    }

    // Assenza speciale: motivo obbligatorio + limite di giorni per evento
    if (state.selectedRequestType === config.specialRequestTypeId) {
        if (!elements.specialReason || !elements.specialReason.value || !state.selectedMotive) {
            showToast('Selecta\u021Bi motivul special (deces, c\u0103s\u0103torie etc.)!', 'warning');
            return;
        }
        if (!evaluateSpecialMotiveDays()) {
            return;
        }
    }

    await submitRequest();
}

async function submitRequest() {
    try {
        state.isProcessing = true;
        showLoading('Se trimite cererea...');

        const response = await fetch('/api/submit-absence-request', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                badgeNumber: elements.badgeInput.value.trim(),
                requestTypeId: state.selectedRequestType,
                dateStart: state.dateStart.toISOString().split('T')[0],
                dateEnd: state.dateEnd.toISOString().split('T')[0],
                fromTime: window.timeFieldsManagement?.getTimeValues().fromTime || null,
                toTime: window.timeFieldsManagement?.getTimeValues().toTime || null,
                // Assenze urgenti: scelta recupero ('MONTH' | 'YEAR')
                urgentRecoveryPeriod: state.selectedRequestType === config.urgentRequestTypeId
                    ? (elements.urgentRecoveryPeriod?.value || null)
                    : null,
                // Assenze speciali: motivo dall'anagrafica (SpecialReasonId = MotiveId)
                specialReasonId: state.selectedRequestType === config.specialRequestTypeId && state.selectedMotive
                    ? state.selectedMotive.id
                    : null
            })
        });

        const data = await response.json();

        hideLoading();

        if (data.success) {
            state.currentPdfPath = data.pdf_path;
            state.currentPdfFilename = data.pdf_filename || extractFilename(data.pdf_path);
            showResult(data);
            showToast('Cerere \u00eenregistrat\u0103 cu succes!', 'success');

            // Countdown 15s sul bottone stampa + auto-reset 30s
            startPrintCountdown();
            startAutoReset();
        } else {
            showToast(data.error || 'Errore invio richiesta', 'error');
            state.isProcessing = false;
        }

    } catch (error) {
        hideLoading();
        console.error('Errore invio richiesta:', error);
        showToast('Errore di connessione', 'error');
        state.isProcessing = false;
    }
}

function showResult(data) {
    const requestTypeName = state.requestTypes.find(t => t.id === state.selectedRequestType)?.name || '';

    elements.resultRequestNumber.textContent = data.request_number;
    elements.resultEmployee.textContent = state.selectedEmployee.name;
    elements.resultType.textContent = requestTypeName;
    elements.resultPeriod.textContent =
        `${state.dateStart.toLocaleDateString('ro-RO')} - ${state.dateEnd.toLocaleDateString('ro-RO')}`;
    elements.resultDays.textContent = state.workingDays;

    elements.requestForm.style.display = 'none';
    elements.resultSection.style.display = 'block';

    // Promemoria scadenze per i nuovi tipi di assenza
    if (data.urgent_recovery_deadline) {
        const dl = new Date(data.urgent_recovery_deadline).toLocaleDateString('ro-RO');
        showToast(`Zilele trebuie recuperate p\u00e2n\u0103 la ${dl} (perioada selectat\u0103).`, 'info');
    }
    if (data.documentation_deadline) {
        const dl = new Date(data.documentation_deadline).toLocaleDateString('ro-RO');
        showToast(`DOCUMENTA\u021aIE OBLIGATORIE: prezenta\u021bi documentele la HR p\u00e2n\u0103 la ${dl}!`, 'warning');
    }
}

// ========================================
// PRINT HANDLING (client-side: kiosk silenzioso via --kiosk-printing,
// remoto con dialog standard del browser)
// ========================================
function extractFilename(path) {
    if (!path) return null;
    return path.replace(/\\/g, '/').split('/').pop();
}

function startPrintCountdown() {
    const btn = elements.printBtn;
    if (!btn) return;

    const totalSeconds = Math.floor(config.printButtonTimeout / 1000);
    let secondsLeft = totalSeconds;

    btn.disabled = false;
    btn.style.display = '';
    renderPrintBtnLabel(secondsLeft);

    clearPrintCountdown();
    state.printCountdownInterval = setInterval(() => {
        secondsLeft -= 1;
        if (secondsLeft <= 0) {
            clearPrintCountdown();
            hidePrintBtn();
            deleteCurrentPdf();
        } else {
            renderPrintBtnLabel(secondsLeft);
        }
    }, 1000);
}

function renderPrintBtnLabel(secondsLeft) {
    elements.printBtn.innerHTML =
        `<span class="btn-icon">\uD83D\uDDA8\uFE0F</span> Printeaz\u0103 Confirmare (${secondsLeft})`;
}

function clearPrintCountdown() {
    if (state.printCountdownInterval) {
        clearInterval(state.printCountdownInterval);
        state.printCountdownInterval = null;
    }
}

function hidePrintBtn() {
    if (elements.printBtn) {
        elements.printBtn.style.display = 'none';
    }
}

function deleteCurrentPdf() {
    if (!state.currentPdfFilename) return;
    const filename = state.currentPdfFilename;
    state.currentPdfFilename = null;
    state.currentPdfPath = null;
    fetch(`/api/delete-pdf/${encodeURIComponent(filename)}`, { method: 'POST' })
        .catch(err => console.warn('Errore eliminazione PDF temp:', err));
}

function handlePrint() {
    if (!state.currentPdfFilename) {
        showToast('Nessun PDF da stampare', 'error');
        return;
    }

    clearPrintCountdown();
    const filename = state.currentPdfFilename;

    const oldIframe = document.getElementById('pdfPrintFrame');
    if (oldIframe) oldIframe.remove();

    const iframe = document.createElement('iframe');
    iframe.id = 'pdfPrintFrame';
    iframe.style.position = 'fixed';
    iframe.style.right = '0';
    iframe.style.bottom = '0';
    iframe.style.width = '0';
    iframe.style.height = '0';
    iframe.style.border = '0';
    iframe.src = `/api/print-pdf/${encodeURIComponent(filename)}`;

    iframe.onload = () => {
        setTimeout(() => {
            try {
                iframe.contentWindow.focus();
                iframe.contentWindow.print();
            } catch (e) {
                console.error('Errore stampa iframe, fallback a nuova finestra:', e);
                window.open(`/api/print-pdf/${encodeURIComponent(filename)}`, '_blank');
            }
        }, 500);
    };

    document.body.appendChild(iframe);
    showToast('Trimis la imprimant\u0103...', 'success');

    hidePrintBtn();
    setTimeout(() => deleteCurrentPdf(), 20000);
}

// ========================================
// RESET FUNCTIONS
// ========================================
function resetForm() {
    elements.badgeInput.value = '';
    elements.requestType.value = '';
    elements.dateStart.value = '';
    elements.dateEnd.value = '';
    elements.employeeInfo.style.display = 'none';
    elements.availableDaysInfo.style.display = 'none';
    elements.workingDaysInfo.style.display = 'none';

    // Reset campi assenze urgenti / speciali
    hideUrgentFields();
    hideSpecialFields();
    hideQuotaInfo();

    state.selectedEmployee = null;
    state.selectedRequestType = null;
    state.availableDays = 0;
    state.dateStart = null;
    state.dateEnd = null;
    state.workingDays = 0;
    state.currentPdfPath = null;
    state.currentPdfFilename = null;
    clearPrintCountdown();

    updateBadgeStatus('waiting');
    disableForm();

    state.keypadMode = false;
    showKeypad();
    elements.badgeInput.focus();
}

function resetBadgeInput() {
    elements.badgeInput.value = '';
    elements.badgeInput.disabled = false;
    state.keypadMode = false;
    showKeypad();
    elements.badgeInput.focus();
    updateBadgeStatus('waiting');
}

function startAutoReset() {
    if (state.autoResetTimeout) {
        clearTimeout(state.autoResetTimeout);
    }

    state.autoResetTimeout = setTimeout(() => {
        showToast('Revenire automat\u0103 la ecranul ini\u021bial...', 'warning');
        setTimeout(() => {
            resetToKioskMode();
        }, 3000);
    }, config.autoResetDelay);
}

function resetToKioskMode() {
    if (state.autoResetTimeout) {
        clearTimeout(state.autoResetTimeout);
        state.autoResetTimeout = null;
    }
    clearPrintCountdown();

    // Redirect alla home launcher
    window.location.href = '/';
}

// ========================================
// UI HELPERS
// ========================================
function showLoading(message = '\u00CEnc\u0103rcare...') {
    elements.loadingOverlay.querySelector('.loading-text').textContent = message;
    elements.loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    elements.loadingOverlay.style.display = 'none';
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = type === 'success' ? '\u2705' : type === 'error' ? '\u274C' : type === 'warning' ? '\u26A0\uFE0F' : '\u2139\uFE0F';

    const messageSpan = document.createElement('span');
    messageSpan.className = 'toast-message';
    messageSpan.textContent = message;

    // Per messaggi lunghi, permetti al testo di andare su pi\u00f9 righe
    if (message.length > 100) {
        messageSpan.style.whiteSpace = 'pre-wrap';
        messageSpan.style.maxWidth = '500px';
        messageSpan.style.lineHeight = '1.5';
        toast.style.maxWidth = '600px';
    }

    toast.appendChild(icon);
    toast.appendChild(messageSpan);

    elements.toastContainer.appendChild(toast);

    // Timeout pi\u00f9 lungo per messaggi di errore lunghi
    let timeout = 4000; // 4 secondi di default
    if (type === 'error' && message.length > 100) {
        timeout = 10000; // 10 secondi per errori lunghi
    }

    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, timeout);
}
