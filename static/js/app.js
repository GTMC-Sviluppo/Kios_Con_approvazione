/**
 * CERTIFICATE GENERATOR - FRONTEND APPLICATION
 * Modern JavaScript with async/await and ES6+ features
 */

// ========================================
// STATE MANAGEMENT
// ========================================
const state = {
    employees: [],
    reasons: [],
    selectedEmployee: null,
    selectedReason: null,
    currentPdfPath: null,
    currentPdfFilename: null,
    badgeReadTimeout: null,
    autoResetTimeout: null,
    printCountdownInterval: null,
    printCountdownTimeout: null,
    isProcessing: false,
    lastKeyTime: null           // Timestamp ultimo carattere inserito (per rilevare digitazione manuale)
};

// ========================================
// CONFIGURATION  (valori di default; vengono sovrascritti da /api/badge-config)
// ========================================
const config = {
    badgeReadDelayRFID: 800,     // ms attesa dopo scansione RFID (burst veloce)
    badgeReadDelayManual: 3000,  // ms attesa dopo digitazione manuale (lenta)
    manualTypingThreshold: 150,  // ms tra caratteri: sopra = digitazione manuale
    autoResetDelay: 30000,       // ms prima di auto-reset dopo stampa (30 secondi)
    showResultDuration: 10000,   // ms per mostrare risultato prima di tornare a badge
    printButtonTimeout: 15000    // ms prima che il bottone stampa sparisca e il PDF venga eliminato
};

// ========================================
// SESSION STORAGE KEYS
// ========================================
const SESSION_KEYS = {
    employee: 'kiosk_badge_employee',
    badgeValue: 'kiosk_badge_value'
};

// ========================================
// DOM ELEMENTS
// ========================================
const elements = {
    badgeInput: document.getElementById('badgeInput'),
    badgeStatus: document.getElementById('badgeStatus'),
    employeeInfo: document.getElementById('employeeInfo'),
    employeeName: document.getElementById('employeeName'),
    reasonSelect: document.getElementById('reasonSelect'),
    customReasonGroup: document.getElementById('customReasonGroup'),
    customReason: document.getElementById('customReason'),
    generateBtn: document.getElementById('generateBtn'),
    resetBtn: document.getElementById('resetBtn'),
    certificateForm: document.getElementById('certificateForm'),
    resultSection: document.getElementById('resultSection'),
    loadingOverlay: document.getElementById('loadingOverlay'),
    addReasonBtn: document.getElementById('addReasonBtn'),
    addReasonModal: document.getElementById('addReasonModal'),
    closeModalBtn: document.getElementById('closeModalBtn'),
    saveReasonBtn: document.getElementById('saveReasonBtn'),
    cancelReasonBtn: document.getElementById('cancelReasonBtn'),
    newReasonText: document.getElementById('newReasonText'),
    requiresDetails: document.getElementById('requiresDetails'),
    printBtn: document.getElementById('printBtn'),
    newCertBtn: document.getElementById('newCertBtn'),
    docNumber: document.getElementById('docNumber'),
    docDate: document.getElementById('docDate'),
    toastContainer: document.getElementById('toastContainer')
};

// ========================================
// INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', async () => {
    console.log('🚀 Certificate Generator - KIOSK MODE initialized');

    // Carica configurazione badge dal server (reading_badge_time.json)
    await loadBadgeConfig();

    // Carica solo i motivi (non più i dipendenti)
    await loadReasons();

    // Setup event listeners
    setupEventListeners();

    // Ripristina badge dalla sessione (se presente e ancora valido)
    const restored = restoreBadgeFromSession();

    if (!restored) {
        // Focus automatico su badge input solo se non abbiamo ripristinato il badge
        focusBadgeInput();
        showToast('Sistem gata - Apropiați badge-ul RFID', 'success');
    }

    // Attiva auto-scroll per le istruzioni se necessario
    initializeInstructionsAutoScroll();
});

// ========================================
// BADGE CONFIG LOADER
// ========================================
async function loadBadgeConfig() {
    try {
        const response = await fetch('/api/badge-config');
        const data = await response.json();
        if (data.success) {
            config.badgeReadDelayRFID       = data.rfid_delay_ms;
            config.badgeReadDelayManual     = data.manual_typing_delay_ms;
            config.manualTypingThreshold    = data.manual_typing_threshold_ms;
            console.log(`⚙️ Badge config caricata: RFID=${data.rfid_delay_ms}ms, Manuale=${data.manual_typing_delay_ms}ms, Soglia=${data.manual_typing_threshold_ms}ms`);
        }
    } catch (e) {
        console.warn('⚠️ Impossibile caricare badge config dal server, uso valori di default:', e);
    }
}

// ========================================
// BADGE MANAGEMENT
// ========================================
function focusBadgeInput() {
    elements.badgeInput.focus();
    elements.badgeInput.select();
}

async function handleBadgeInput(e) {
    const badgeNumber = e.target.value.trim();
    const now = Date.now();

    // Clear previous timeout
    if (state.badgeReadTimeout) {
        clearTimeout(state.badgeReadTimeout);
    }

    // Se il campo è vuoto, reset status
    if (!badgeNumber) {
        state.lastKeyTime = null;
        updateBadgeStatus('waiting');
        return;
    }

    // Determina se è digitazione manuale o scansione RFID.
    // Se il tempo dall'ultimo carattere supera la soglia → l'utente sta digitando.
    const isManualTyping = state.lastKeyTime !== null &&
        (now - state.lastKeyTime) > config.manualTypingThreshold;
    state.lastKeyTime = now;

    const delay = isManualTyping ? config.badgeReadDelayManual : config.badgeReadDelayRFID;

    // Mostra status "lettura in corso"
    updateBadgeStatus('reading');

    // Debounce: attendi che l'utente finisca di digitare/lettore finisca
    state.badgeReadTimeout = setTimeout(async () => {
        await validateBadge(badgeNumber);
    }, delay);
}

async function validateBadge(badgeNumber) {
    if (state.isProcessing) return;

    try {
        state.isProcessing = true;

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
            showEmployeeInfo(data.employee);
            updateBadgeStatus('success');
            showToast(`Bun venit ${data.employee.name}!`, 'success');

            // Salva badge in sessionStorage per persistenza durante la sessione
            saveBadgeToSession(data.employee, elements.badgeInput.value.trim());

            // Disabilita input badge
            elements.badgeInput.disabled = true;
        } else {
            updateBadgeStatus('error');
            showToast(data.error || 'Badge nerecunoscut', 'error');
            clearBadgeSession();

            // Reset dopo 2 secondi
            setTimeout(() => {
                resetBadgeInput();
            }, 2000);
        }
    } catch (error) {
        console.error('Error validating badge:', error);
        updateBadgeStatus('error');
        showToast('Eroare de conexiune', 'error');
        clearBadgeSession();

        setTimeout(() => {
            resetBadgeInput();
        }, 2000);
    } finally {
        state.isProcessing = false;
    }
}

function updateBadgeStatus(status) {
    const statusIcon = elements.badgeStatus.querySelector('.status-icon');
    const statusText = elements.badgeStatus.querySelector('.status-text');

    // Remove all status classes
    elements.badgeStatus.classList.remove('reading', 'success', 'error');

    switch (status) {
        case 'waiting':
            statusIcon.textContent = '📱';
            statusText.textContent = 'În așteptare...';
            break;
        case 'reading':
            elements.badgeStatus.classList.add('reading');
            statusIcon.textContent = '🔄';
            statusText.textContent = 'Citire...';
            break;
        case 'success':
            elements.badgeStatus.classList.add('success');
            statusIcon.textContent = '✅';
            statusText.textContent = 'Recunoscut';
            break;
        case 'error':
            elements.badgeStatus.classList.add('error');
            statusIcon.textContent = '❌';
            statusText.textContent = 'Eroare';
            break;
    }
}

function showEmployeeInfo(employee) {
    elements.employeeName.textContent = employee.name;
    elements.employeeInfo.style.display = 'block';
    validateForm();
}

function resetBadgeInput() {
    elements.badgeInput.value = '';
    elements.badgeInput.disabled = false;
    state.lastKeyTime = null;
    updateBadgeStatus('waiting');
    focusBadgeInput();
}

// ========================================
// SESSION PERSISTENCE (badge)
// ========================================
function saveBadgeToSession(employee, badgeValue) {
    try {
        sessionStorage.setItem(SESSION_KEYS.employee, JSON.stringify(employee));
        sessionStorage.setItem(SESSION_KEYS.badgeValue, badgeValue || '');
        console.log('💾 Badge salvato in sessione:', employee.name);
    } catch (e) {
        console.warn('sessionStorage non disponibile:', e);
    }
}

function clearBadgeSession() {
    try {
        sessionStorage.removeItem(SESSION_KEYS.employee);
        sessionStorage.removeItem(SESSION_KEYS.badgeValue);
        console.log('🗑️ Sessione badge cancellata');
    } catch (e) {
        // Ignora errori
    }
}

function restoreBadgeFromSession() {
    try {
        const employeeJson = sessionStorage.getItem(SESSION_KEYS.employee);
        const badgeValue   = sessionStorage.getItem(SESSION_KEYS.badgeValue);
        if (!employeeJson) return false;

        const employee = JSON.parse(employeeJson);
        state.selectedEmployee = employee;

        // Ripristina valore nel campo badge (mascherato)
        if (badgeValue) {
            elements.badgeInput.value = badgeValue;
        }
        elements.badgeInput.disabled = true;

        showEmployeeInfo(employee);
        updateBadgeStatus('success');
        showToast(`Bun venit ${employee.name}!`, 'success');
        console.log('✅ Badge ripristinato dalla sessione:', employee.name);
        return true;
    } catch (e) {
        console.warn('Errore ripristino badge da sessione:', e);
        clearBadgeSession();
        return false;
    }
}

// ========================================
// DATA LOADING
// ========================================
async function loadReasons() {
    try {
        const response = await fetch('/api/certificate-reasons');
        const data = await response.json();

        if (data.success) {
            state.reasons = data.reasons;
            populateReasonSelect();
        } else {
            throw new Error(data.error || 'Eroare la încărcarea motivelor');
        }
    } catch (error) {
        console.error('Error loading reasons:', error);
        showToast('Eroare la încărcarea motivelor: ' + error.message, 'error');
        elements.reasonSelect.innerHTML = '<option value="">Eroare la încărcare</option>';
    }
}

// ========================================
// UI POPULATION
// ========================================
function populateReasonSelect() {
    elements.reasonSelect.innerHTML = '<option value="">Selectează motivul...</option>';

    state.reasons.forEach(reason => {
        const option = document.createElement('option');
        option.value = reason.id;
        option.textContent = reason.reason;
        option.dataset.canTypeSpecial = reason.canTypeSpecial;
        option.dataset.groupId = reason.groupId;
        elements.reasonSelect.appendChild(option);
    });
}

// ========================================
// EVENT LISTENERS
// ========================================
function setupEventListeners() {
    // Badge input
    elements.badgeInput.addEventListener('input', handleBadgeInput);

    // Reason selection
    elements.reasonSelect.addEventListener('change', handleReasonChange);

    // Form submission
    elements.certificateForm.addEventListener('submit', handleFormSubmit);

    // Reset button (reset completo: cancella badge e torna alla home)
    elements.resetBtn.addEventListener('click', () => resetToKioskMode(true));

    // Add reason modal
    elements.addReasonBtn.addEventListener('click', openAddReasonModal);
    elements.closeModalBtn.addEventListener('click', closeAddReasonModal);
    elements.cancelReasonBtn.addEventListener('click', closeAddReasonModal);
    elements.saveReasonBtn.addEventListener('click', saveNewReason);

    // Result actions — bottone stampa: stampa client-side (kiosk silenzioso, remoto con dialog)
    elements.printBtn.addEventListener('click', printCertificate);
    // "Generează altă adeverință": mantiene il badge, torna al form
    elements.newCertBtn.addEventListener('click', () => resetToKioskMode(false));

    // Auto-focus badge quando perde focus
    elements.badgeInput.addEventListener('blur', () => {
        if (!state.selectedEmployee && !state.isProcessing) {
            setTimeout(() => focusBadgeInput(), 100);
        }
    });
}

// ========================================
// EVENT HANDLERS
// ========================================
function handleReasonChange(e) {
    const selectedOption = e.target.options[e.target.selectedIndex];

    if (selectedOption.value) {
        state.selectedReason = {
            id: selectedOption.value,
            reason: selectedOption.textContent,
            canTypeSpecial: selectedOption.dataset.canTypeSpecial === 'true',
            groupId: parseInt(selectedOption.dataset.groupId)
        };

        // Show/hide custom reason field
        if (state.selectedReason.canTypeSpecial) {
            elements.customReasonGroup.style.display = 'flex';
            elements.customReason.required = true;
        } else {
            elements.customReasonGroup.style.display = 'none';
            elements.customReason.required = false;
            elements.customReason.value = '';
        }

        console.log('Selected reason:', state.selectedReason);
        validateForm();
    } else {
        state.selectedReason = null;
        elements.customReasonGroup.style.display = 'none';
        elements.customReason.required = false;
        validateForm();
    }
}

async function handleFormSubmit(e) {
    e.preventDefault();

    if (!validateForm()) {
        showToast('Completați toate câmpurile obligatorii', 'warning');
        return;
    }

    // Check custom reason if required
    if (state.selectedReason.canTypeSpecial && !elements.customReason.value.trim()) {
        showToast('Completați detaliile suplimentare', 'warning');
        elements.customReason.focus();
        return;
    }

    // Genera direttamente senza conferma (stampa automatica)
    await generateCertificate();
}

// ========================================
// CERTIFICATE GENERATION
// ========================================
async function generateCertificate() {
    try {
        showLoading('Se generează adeverința...');

        const payload = {
            employeeId: state.selectedEmployee.id,
            badgeNumber: state.selectedEmployee.badgeNumber || elements.badgeInput.value.trim(),
            reason: state.selectedReason.reason,
            typedReason: elements.customReason.value.trim(),
            groupId: state.selectedReason.groupId
        };

        console.log('Generating certificate with payload:', payload);

        const response = await fetch('/api/generate-certificate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.success) {
            state.currentPdfPath = data.pdfPath;
            state.currentPdfFilename = extractFilename(data.pdfPath);
            showResult(data);
            showToast('Adeverință generată cu succes! Se trimite la imprimantă...', 'success');

            // AUTO-STAMPA: avvia la stampa automaticamente dopo un breve delay
            // (il bottone rimane visibile come fallback se la stampa fallisce)
            setTimeout(() => {
                printCertificate();
            }, 800);
        } else {
            throw new Error(data.error || 'Eroare la generarea adeverinței');
        }
    } catch (error) {
        console.error('Error generating certificate:', error);
        showToast('Eroare: ' + error.message, 'error');
    } finally {
        hideLoading();
    }
}

// ========================================
// ADD NEW REASON
// ========================================
function openAddReasonModal() {
    elements.addReasonModal.style.display = 'flex';
    elements.newReasonText.value = '';
    elements.requiresDetails.checked = false;
    elements.newReasonText.focus();
}

function closeAddReasonModal() {
    elements.addReasonModal.style.display = 'none';
}

async function saveNewReason() {
    const reasonText = elements.newReasonText.value.trim();

    if (!reasonText) {
        showToast('Introduceți descrierea motivului', 'warning');
        elements.newReasonText.focus();
        return;
    }

    try {
        showLoading('Salvare motiv...');

        const response = await fetch('/api/add-reason', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                reason: reasonText,
                canTypeSpecial: elements.requiresDetails.checked
            })
        });

        const data = await response.json();

        if (data.success) {
            showToast('Motiv adăugat cu succes!', 'success');
            closeAddReasonModal();
            await loadReasons();
        } else {
            throw new Error(data.error || 'Eroare la salvarea motivului');
        }
    } catch (error) {
        console.error('Error saving reason:', error);
        showToast('Eroare: ' + error.message, 'error');
    } finally {
        hideLoading();
    }
}

// ========================================
// RESULT DISPLAY
// ========================================
function showResult(data) {
    elements.docNumber.textContent = data.documentNumber;
    elements.docDate.textContent = data.documentDate;

    elements.certificateForm.style.display = 'none';
    elements.resultSection.style.display = 'block';

    // Avvia countdown 15s sul bottone stampa
    startPrintCountdown();

    // Auto-reset dopo configurato delay (default 30 secondi)
    state.autoResetTimeout = setTimeout(() => {
        showToast('Revenire automată la ecranul inițial...', 'warning');
        setTimeout(() => {
            resetToKioskMode();
        }, 3000);
    }, config.autoResetDelay);
}

// ========================================
// PRINT CERTIFICATE (countdown + stampa client-side)
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
        `<span class="btn-icon">🖨️</span> Printează (${secondsLeft})`;
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

function printCertificate() {
    if (!state.currentPdfFilename) {
        showToast('Niciun PDF disponibil', 'error');
        return;
    }

    clearPrintCountdown();
    const filename = state.currentPdfFilename;

    // Stampa via iframe nascosto:
    // - su kiosk Chrome con --kiosk-printing → stampa silenziosa
    // - su browser normale → dialog di stampa standard
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
    showToast('Trimis la imprimantă...', 'success');

    hidePrintBtn();
    // Elimina PDF temp dopo un margine di tempo per dare alla stampante tempo di leggere
    setTimeout(() => deleteCurrentPdf(), 20000);
}

// ========================================
// FORM VALIDATION
// ========================================
function validateForm() {
    const isValid = state.selectedEmployee && state.selectedReason;
    elements.generateBtn.disabled = !isValid;
    return isValid;
}

function resetToKioskMode(clearBadge = false) {
    // Clear any auto-reset timers
    if (state.autoResetTimeout) {
        clearTimeout(state.autoResetTimeout);
        state.autoResetTimeout = null;
    }
    clearPrintCountdown();

    if (clearBadge) {
        // Reset completo: cancella badge e torna alla home (es. pulsante Resetează o inattività)
        clearBadgeSession();
        window.location.href = '/';
    } else {
        // Reset parziale: mantiene il badge e torna al form per una nuova adeverinta
        state.selectedReason = null;
        elements.reasonSelect.value = '';
        elements.customReasonGroup.style.display = 'none';
        elements.customReason.value = '';
        elements.resultSection.style.display = 'none';
        elements.certificateForm.style.display = '';
        validateForm();
        // Scorri in cima
        window.scrollTo({ top: 0, behavior: 'smooth' });
        showToast('Selectați un nou tip de adeverință', 'success');
    }
}

// ========================================
// UI HELPERS
// ========================================
function showLoading(message = 'Încărcare...') {
    elements.loadingOverlay.querySelector('.loading-text').textContent = message;
    elements.loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    elements.loadingOverlay.style.display = 'none';
}

function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️'
    };

    // textContent al posto di innerHTML: nomi e messaggi arrivano dal DB
    // e non devono poter iniettare markup (stored XSS)
    const iconSpan = document.createElement('span');
    iconSpan.className = 'toast-icon';
    iconSpan.textContent = icons[type] || 'ℹ️';

    const messageSpan = document.createElement('span');
    messageSpan.className = 'toast-message';
    messageSpan.textContent = message;

    toast.appendChild(iconSpan);
    toast.appendChild(messageSpan);

    elements.toastContainer.appendChild(toast);

    // Auto remove after 5 seconds
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ========================================
// UTILITY FUNCTIONS
// ========================================
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ========================================
// ERROR HANDLING
// ========================================
window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
    showToast('A apărut o eroare neașteptată', 'error');
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    showToast('Eroare de conexiune la server', 'error');
});

// ========================================
// AUTO-SCROLL FOR INSTRUCTIONS
// ========================================
function initializeInstructionsAutoScroll() {
    const instructionsList = document.querySelector('.instructions-list');

    if (!instructionsList) {
        return; // Non siamo nella pagina con le istruzioni
    }

    // Controlla se il contenuto eccede l'altezza del container
    const containerHeight = 350; // Max height definito nel CSS
    const contentHeight = instructionsList.scrollHeight;

    console.log(`Instructions height check: container=${containerHeight}px, content=${contentHeight}px`);

    if (contentHeight > containerHeight) {
        // Attiva l'animazione di scorrimento
        instructionsList.classList.add('auto-scroll');
        console.log('✅ Auto-scroll attivato per le istruzioni');

        // Calcola la durata dell'animazione in base all'altezza del contenuto
        // Più contenuto = animazione più lenta per leggibilità
        const scrollDuration = Math.max(20, (contentHeight / containerHeight) * 15);
        instructionsList.style.animationDuration = `${scrollDuration}s`;

        console.log(`Animation duration set to: ${scrollDuration}s`);
    } else {
        console.log('ℹ️ Contenuto istruzioni non richiede auto-scroll');
    }
}

console.log('✅ App.js loaded successfully');

